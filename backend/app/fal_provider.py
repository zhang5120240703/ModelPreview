"""Tripo H3.1 via fal queue REST API. No SDK or automatic paid POST retry."""
import asyncio
import base64
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse
import httpx
from .providers import Base3DProvider, ProviderResult


class FalTripoProvider(Base3DProvider):
    model = 'tripo3d/h3.1/multiview-to-3d'
    endpoint = f'https://queue.fal.run/{model}'

    def __init__(self, settings, transport=None):
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=90, transport=transport, follow_redirects=False)
        self.read_failures = 0

    @property
    def headers(self):
        key = self.settings.fal_key.get_secret_value().strip()
        if not key: raise ValueError('服务器未配置 FAL_KEY，请填写 backend/.env 后重启服务')
        return {'Authorization': f'Key {key}'}

    @staticmethod
    def check(response):
        if response.is_success: return
        messages = {
            400: '图片或建模参数无效', 401: 'FAL_KEY 无效',
            402: '账户余额或额度不足', 403: '访问被拒绝，请检查密钥权限和账户余额',
            404: '远程任务或模型接口不存在', 422: '图片内容、数量或建模参数未通过校验',
            429: '请求限流，请稍后使用原任务查询，勿重复提交',
        }
        raise ValueError('fal：' + messages.get(response.status_code, f'服务异常（HTTP {response.status_code}）'))

    @classmethod
    def validate_handle(cls, handle):
        if not isinstance(handle, dict): raise ValueError('fal 任务凭据无效')
        request_id = handle.get('request_id', '')
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,200}', request_id):
            raise ValueError('fal 未返回有效请求编号')
        for field in ('status_url', 'response_url'):
            url = handle.get(field)
            if not isinstance(url, str): raise ValueError('fal 未返回完整队列查询地址')
            parsed = urlparse(url)
            tail = f'/requests/{request_id}' + ('/status' if field == 'status_url' else '')
            valid_path = parsed.path.endswith(tail) or (
                field == 'response_url' and parsed.path.endswith(tail + '/response'))
            if (parsed.scheme != 'https' or parsed.hostname != 'queue.fal.run' or
                parsed.username or parsed.port not in (None, 443) or parsed.fragment or
                not parsed.path.startswith('/tripo3d/h3.1/') or not valid_path):
                raise ValueError('fal 返回的队列地址不符合当前模型的 HTTPS 地址要求')
        return handle

    async def create(self, images: list[Path]) -> str:
        if not 2 <= len(images) <= 4:
            raise ValueError('Tripo H3.1 多视图需要 2–4 张图片，按正面、左侧、背面、右侧排序')
        headers = self.headers  # Reject missing credentials before reading/encoding files.

        def encode():
            return ['data:' + (mimetypes.guess_type(path.name)[0] or 'image/png') +
                    ';base64,' + base64.b64encode(path.read_bytes()).decode('ascii') for path in images]

        response = await self.client.post(self.endpoint, headers=headers, json={
            'image_urls': await asyncio.to_thread(encode),
            'texture': True, 'pbr': True,
            'texture_quality': 'standard', 'geometry_quality': 'standard',
            'texture_alignment': 'original_image', 'orientation': 'default',
            'quad': False, 'face_limit': 30000,
        })
        self.check(response)
        data = response.json()
        handle = {key: data.get(key) for key in ('request_id', 'status_url', 'response_url')}
        # Queue result/status paths can omit the endpoint suffix. Use returned URLs, not guessed paths.
        self.validate_handle(handle)
        return json.dumps(handle, separators=(',', ':'))

    async def read(self, url):
        try:
            response = await self.client.get(url, headers=self.headers)
        except httpx.TransportError:
            self.read_failures += 1
            if self.read_failures <= 3: return None
            raise ValueError('fal 查询连续网络异常，请在平台核实原任务，避免重复提交')
        if response.status_code in (429, 500, 502, 503, 504):
            self.read_failures += 1
            if self.read_failures <= 3: return None
        self.check(response)
        self.read_failures = 0
        return response.json()

    async def poll(self, remote_id: str) -> ProviderResult:
        handle = self.validate_handle(json.loads(remote_id))
        status = await self.read(handle['status_url'])
        if status is None: return ProviderResult('processing')
        state = status.get('status')
        if state in ('IN_QUEUE', 'IN_PROGRESS'):
            return ProviderResult('processing')  # The queue does not expose a genuine percentage.
        if state != 'COMPLETED': raise ValueError('fal 返回未知队列状态')
        if status.get('error') or status.get('error_type'):
            return ProviderResult('failed', error=f"fal 建模失败，请在平台查看请求 {handle['request_id']} 的原因")
        result = await self.read(handle['response_url'])
        if result is None: return ProviderResult('processing')
        if result.get('error') or result.get('detail'):
            return ProviderResult('failed', error=f"fal 模型生成失败，请在平台查看请求 {handle['request_id']} 的原因")
        models = result.get('model_urls') or {}
        model = models.get('glb') or result.get('model_mesh') or {}
        url = model.get('url') if isinstance(model, dict) else None
        if not isinstance(url, str) or not url:
            raise ValueError('fal 任务已完成但没有返回可下载的模型；请在平台核实原任务')
        filename = str(model.get('file_name', '')).lower()
        if filename.endswith('.fbx') or urlparse(url).path.lower().endswith('.fbx'):
            raise ValueError('fal 返回了 FBX，本预览器需要 GLB；请保持 quad=false')
        return ProviderResult('succeeded', model_url=url)

    async def download(self, url: str, destination: Path):
        parsed = urlparse(url)
        allowed = [host.strip().lower() for host in self.settings.fal_model_download_hosts.split(',') if host.strip()]
        # fal's own media subdomains are trusted. Additional hosts must be explicitly configured.
        trusted = parsed.hostname in allowed or (parsed.hostname or '').endswith('.fal.media')
        if (parsed.scheme != 'https' or not trusted or parsed.username or parsed.port not in (None,443)):
            raise ValueError('fal 模型下载地址不在 HTTPS 白名单中')
        async with self.client.stream('GET', url) as response:
            self.check(response)
            size = 0
            with destination.open('wb') as output:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.settings.max_model_mb * 1024 * 1024:
                        raise ValueError('模型文件超出大小限制，请提高 MAX_MODEL_MB 或减少模型细节')
                    output.write(chunk)

    async def close(self):
        await self.client.aclose()
