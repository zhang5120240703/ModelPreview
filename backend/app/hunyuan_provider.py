"""Tencent TokenHub HY-3D-3.1 REST adapter, not the retired TencentCloud 2.5 API."""
import asyncio
import base64
import json
import re
from pathlib import Path
from urllib.parse import urlparse
import httpx
from PIL import Image
from .image_sources import ImageSources, read_views
from .github_images import validate_github_image_url
from .providers import Base3DProvider, ProviderResult


class HunyuanProvider(Base3DProvider):
    endpoint = 'https://tokenhub.tencentmaas.com/v1/api/3d'

    def __init__(self, settings, transport=None):
        self.settings = settings
        if settings.hunyuan_model not in ('hy-3d-3.0', 'hy-3d-3.1'):
            raise ValueError('HUNYUAN_MODEL 必须是 hy-3d-3.0 或 hy-3d-3.1')
        self.client = httpx.AsyncClient(timeout=90, transport=transport, follow_redirects=False)
        self.sources = ImageSources(settings)
        self.query_failures = {}

    @property
    def headers(self):
        key = self.settings.hunyuan_api_key.get_secret_value().strip()
        if not key:
            raise ValueError('未配置 HUNYUAN_API_KEY，请在 backend/.env 填写 TokenHub API Key 后重启')
        return {'Authorization': f'Bearer {key}'}

    @staticmethod
    def check(response):
        if response.is_success: return
        errors = {400: '提交参数或图片无效', 401: 'API Key 无效或已禁用',
                  402: '账户余额或额度不足', 403: '访问被拒绝，请检查模型授权、IP 白名单及账户状态',
                  404: '远程任务不存在或已过期', 422: '图片或建模参数校验失败',
                  429: '并发额度或请求频率超限，请勿重复提交付费任务'}
        raise ValueError('腾讯混元：' + errors.get(response.status_code, f'服务异常（HTTP {response.status_code}）'))

    @staticmethod
    def parse(response):
        try:
            data = response.json()
        except ValueError:
            raise ValueError('腾讯混元返回的数据不是有效 JSON') from None
        if not isinstance(data, dict): raise ValueError('腾讯混元返回的数据格式无效')
        if data.get('error'):
            raise ValueError('腾讯混元返回错误，请在 TokenHub 控制台核实模型授权、额度和请求记录')
        return data

    @staticmethod
    def validate_images(images):
        if not 1 <= len(images) <= 6: raise ValueError('混元预览原型支持 1–6 张图片，分别为前、后、左、右、上、下')
        for image in images:
            if image.stat().st_size > 4 * 1024 * 1024:
                raise ValueError('混元接入中单张图片最多 4 MB，以保证 Base64 编码后不超限')
            with Image.open(image) as decoded:
                if decoded.format not in ('JPEG', 'PNG') or not all(128 < size < 5000 for size in decoded.size):
                    raise ValueError('混元图片须为 JPG/PNG，宽和高均须大于 128 且小于 5000 像素')

    async def create(self, images: list[Path]) -> str:
        headers = self.headers
        await asyncio.to_thread(self.validate_images, images)
        folder = images[0].parent
        views = read_views(folder, len(images))
        front = views.index('front')
        arguments = {'model': self.settings.hunyuan_model, 'generate_type': 'Normal',
                     'enable_pbr': self.settings.hunyuan_enable_pbr}
        if self.settings.hunyuan_face_count is not None:
            arguments['face_count'] = self.settings.hunyuan_face_count
        public_path=folder/'public-images.json'
        if public_path.exists():
            urls=json.loads(public_path.read_text(encoding='utf-8'))
            if not isinstance(urls,list) or len(urls)!=len(images):
                raise ValueError('已保存的公网图片链接与照片数量不匹配')
            for url in urls: validate_github_image_url(url)
            arguments['image_url']=urls[front]
            if len(images)>1:
                arguments['multi_view_images']=[{'view_type':view,'view_image_url':urls[i]}
                                               for i,view in enumerate(views) if view!='front']
        elif len(images) == 1:
            data = await asyncio.to_thread(images[front].read_bytes)
            # Official API expects raw base64, not a data:image/... prefix.
            arguments['image_base64'] = base64.b64encode(data).decode('ascii')
        else:
            urls = self.sources.urls(folder.name, len(images))
            arguments['image_url'] = urls[front]
            arguments['multi_view_images'] = [
                {'view_type': view, 'view_image_url': urls[i]}
                for i, view in enumerate(views) if view != 'front']
        # Omit result_format: the documented default includes GLB and OBJ.
        # Never retry this paid creation POST automatically.
        response = await self.client.post(self.endpoint + '/submit', headers=headers, json=arguments)
        self.check(response)
        result = self.parse(response)
        job_id = result.get('id')
        if not isinstance(job_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,200}', job_id):
            raise ValueError('腾讯混元未返回有效任务编号；请先在平台核实，避免重复付费')
        if result.get('status') == 'failed':
            raise ValueError(f'腾讯混元提交后返回失败，请查看平台任务 {job_id}')
        # Persist model alongside the task ID so config changes never query the wrong model.
        return json.dumps({'id': job_id, 'model': self.settings.hunyuan_model}, separators=(',', ':'))

    async def poll(self, remote_id: str) -> ProviderResult:
        try:
            handle = json.loads(remote_id)
            valid = (isinstance(handle, dict) and handle.get('model') in ('hy-3d-3.0','hy-3d-3.1') and
                     isinstance(handle.get('id'), str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,200}', handle['id']))
        except (ValueError, TypeError):
            valid = False
        if not valid: raise ValueError('腾讯混元任务凭据无效')
        try:
            response = await self.client.post(self.endpoint + '/query', headers=self.headers, json=handle)
            transient = response.status_code in (429, 500, 502, 503, 504)
        except httpx.TransportError:
            response = None
            transient = True
        if transient:
            failures = self.query_failures.get(remote_id, 0) + 1
            self.query_failures[remote_id] = failures
            if failures <= 3: return ProviderResult('processing')
            raise ValueError('腾讯混元查询连续异常，请在 TokenHub 核实原任务，避免重新提交扣费')
        self.query_failures.pop(remote_id, None)
        self.check(response)
        result = self.parse(response)
        state = result.get('status')
        if state in ('queued', 'in_progress'):
            return ProviderResult('processing')  # No documented numeric progress; never fabricate it.
        if state == 'failed':
            return ProviderResult('failed', error=f"腾讯混元建模失败，请在 TokenHub 查看任务 {handle['id']} 的原因")
        if state != 'completed': raise ValueError('腾讯混元返回未知任务状态')
        files = result.get('data')
        if isinstance(files, list):
            for file in files:
                if isinstance(file, dict) and str(file.get('type','')).lower() == 'glb' and isinstance(file.get('url'), str) and file['url']:
                    return ProviderResult('succeeded', model_url=file['url'])
        raise ValueError('腾讯混元任务已完成但没有返回 GLB，请在平台核实模型文件')

    async def download(self, url: str, destination: Path):
        parsed = urlparse(url)
        hosts = [host.strip().lower() for host in self.settings.hunyuan_model_download_hosts.split(',') if host.strip()]
        if (parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or
            parsed.password or parsed.port not in (None,443)):
            raise ValueError('混元模型下载地址不在 HTTPS 白名单中，请核实官方素材域名')
        # The API key is sent only to the fixed TokenHub submit/query endpoints.
        async with self.client.stream('GET', url) as response:
            self.check(response)
            size = 0
            with destination.open('wb') as output:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.settings.max_model_mb * 1024 * 1024:
                        raise ValueError('混元模型超过 MAX_MODEL_MB 下载限制，可调整上限后下载原任务文件')
                    output.write(chunk)

    async def close(self):
        await self.client.aclose()
