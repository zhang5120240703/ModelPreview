import asyncio
import base64
import mimetypes
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, quote
import httpx
from .glb import make_test_glb


@dataclass
class ProviderResult:
    status: str
    progress: float | None = None
    model_url: str | None = None
    error: str | None = None


class Base3DProvider(ABC):
    @abstractmethod
    async def create(self, images: list[Path]) -> str: ...
    @abstractmethod
    async def poll(self, remote_id: str) -> ProviderResult: ...
    @abstractmethod
    async def download(self, url: str, destination: Path): ...
    async def close(self): pass


class MockProvider(Base3DProvider):
    def __init__(self, settings): self.delay = settings.mock_delay_seconds
    async def create(self, images): return 'mock-test-geometry'
    async def poll(self, remote_id):
        await asyncio.sleep(self.delay)
        return ProviderResult('succeeded',100,'mock://test-cube')
    async def download(self, url, destination):
        await asyncio.to_thread(destination.write_bytes, make_test_glb())


class MeshyProvider(Base3DProvider):
    """Official Multi-Image to 3D API. Never retry paid POST automatically."""
    endpoint = 'https://api.meshy.ai/openapi/v1/multi-image-to-3d'
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=60, transport=transport)

    @property
    def headers(self):
        key = self.settings.meshy_api_key.get_secret_value()
        if not key: raise ValueError('服务器未配置 MESHY_API_KEY')
        return {'Authorization':f'Bearer {key}'}

    def check(self, response):
        errors = {400:'图片或建模参数无效',401:'API Key 无效',402:'建模额度不足',
                  403:'API 访问被拒绝',429:'第三方限流，请稍后创建新任务'}
        if not response.is_success:
            raise ValueError('Meshy: '+errors.get(response.status_code, f'服务错误 HTTP {response.status_code}'))

    async def create(self, images):
        def encode():
            return ['data:'+mimetypes.guess_type(p.name)[0]+';base64,'+
                    base64.b64encode(p.read_bytes()).decode('ascii') for p in images]
        response = await self.client.post(self.endpoint, headers=self.headers, json={
            'image_urls':await asyncio.to_thread(encode), 'ai_model':self.settings.meshy_ai_model,
            'should_texture':True,'enable_pbr':True,'target_formats':['glb'],
            'should_remesh':True,'topology':'triangle','target_polycount':30000,
            'texture_resolution':'2k'})
        self.check(response)
        remote_id = response.json().get('result')
        if not isinstance(remote_id,str) or not remote_id: raise ValueError('Meshy 未返回任务 ID')
        return remote_id

    async def poll(self, remote_id):
        response = await self.client.get(self.endpoint+'/'+quote(remote_id,safe=''),headers=self.headers)
        self.check(response)
        data = response.json()
        state = data.get('status')
        if state in ('FAILED','CANCELED','EXPIRED'):
            return ProviderResult('failed', error='Meshy 建模失败: '+str(data.get('task_error',{}).get('message','远程任务终止'))[:500])
        if state not in ('PENDING','IN_PROGRESS','SUCCEEDED'):
            raise ValueError('Meshy 返回未知任务状态')
        progress = data.get('progress')
        if not isinstance(progress,(float,int)): progress = None
        elif not 0 <= progress <= 100: progress = None
        return ProviderResult('succeeded' if state=='SUCCEEDED' else 'processing', progress,
                              data.get('model_urls',{}).get('glb'))

    async def download(self, url, destination):
        parsed = urlparse(url)
        allowed = [h.strip().lower() for h in self.settings.model_download_hosts.split(',') if h.strip()]
        if parsed.scheme != 'https' or parsed.hostname not in allowed or parsed.username or parsed.port not in (None,443):
            raise ValueError('模型下载地址不在服务器 HTTPS 白名单中')
        # Separate unauthenticated request: never forward the API key to asset hosts.
        async with self.client.stream('GET', url, follow_redirects=False) as response:
            self.check(response)
            length = 0
            with destination.open('wb') as output:
                async for chunk in response.aiter_bytes():
                    length += len(chunk)
                    if length > self.settings.max_model_mb*1024*1024:
                        raise ValueError('模型文件超出大小限制')
                    output.write(chunk)

    async def close(self): await self.client.aclose()


class TripoProvider(Base3DProvider):
    async def create(self, images): raise NotImplementedError('Tripo 尚未接入，请使用 mock 或 meshy')
    async def poll(self, remote_id): raise NotImplementedError('Tripo 尚未接入')
    async def download(self, url, destination): raise NotImplementedError('Tripo 尚未接入')


def make_provider(settings):
    from .fal_provider import FalTripoProvider
    from .hunyuan_provider import HunyuanProvider
    factories = {'mock':MockProvider,'meshy':MeshyProvider,'hunyuan':HunyuanProvider,'fal_tripo':FalTripoProvider,'tripo':lambda _:TripoProvider()}
    if settings.provider not in factories: raise ValueError('PROVIDER 必须是 mock、meshy、hunyuan、fal_tripo 或 tripo')
    return factories[settings.provider](settings)
