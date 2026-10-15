import asyncio
import io
from PIL import Image
from app.config import Settings
from app.providers import Base3DProvider, ProviderResult
from app.service import ReconstructionWorker
from app.store import TaskStore
from app.main import inspect_image
import pytest


class BrokenDownload(Base3DProvider):
    async def create(self, images): return 'remote-saved'
    async def poll(self, remote_id): return ProviderResult('succeeded',100,'mock://bad')
    async def download(self,url,destination): destination.write_bytes(b'not-a-glb')


def test_bad_download_is_failed_and_not_published(tmp_path):
    store=TaskStore(tmp_path)
    folder=tmp_path/'bad'; folder.mkdir()
    store.create('bad','mock',[])
    asyncio.run(ReconstructionWorker(Settings(_env_file=None,provider='mock',data_dir=tmp_path),store,BrokenDownload()).process('bad'))
    assert store.get('bad')['status']=='failed'
    assert store.get('bad')['remote_id']=='remote-saved'
    assert not (folder/'model.part').exists() and not (folder/'model.glb').exists()


def test_ambiguous_submission_does_not_resubmit(tmp_path):
    store=TaskStore(tmp_path)
    (tmp_path/'interrupted').mkdir()
    store.create('interrupted','mock',[])
    store.update('interrupted',status='processing')
    asyncio.run(ReconstructionWorker(Settings(_env_file=None,provider='mock',data_dir=tmp_path),store,BrokenDownload()).process('interrupted'))
    row=store.get('interrupted')
    assert row['status']=='failed' and '重复付费' in row['error']
    assert row['remote_id'] is None


def test_jpeg_decode_and_pixel_limit():
    output=io.BytesIO()
    Image.new('RGB',(16,16)).save(output,format='JPEG')
    inspect_image(output.getvalue(),'.jpeg')
    with pytest.raises(ValueError): inspect_image(output.getvalue(),'.png')


def test_chunked_request_total_body_limit(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app(Settings(_env_file=None,provider='mock',meshy_api_key='',data_dir=tmp_path,max_image_mb=1))) as client:
        def chunks():
            for _ in range(8): yield b'x'*1024*1024
        response=client.post('/api/v1/reconstructions',content=chunks())
        assert response.status_code==413
