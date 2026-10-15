import asyncio
import httpx
import pytest
from app.config import Settings
from app.providers import MeshyProvider
from app.glb import make_test_glb


def test_meshy_contract_and_no_key_on_download(tmp_path):
    calls=[]
    def handle(request):
        calls.append(request)
        if request.method=='POST':
            import json
            data=json.loads(request.content)
            assert data['image_urls'][0].startswith('data:image/png;base64,')
            assert data['target_formats']==['glb'] and data['should_texture']
            return httpx.Response(200,json={'result':'remote-123'})
        if request.url.host=='assets.meshy.ai':
            assert 'authorization' not in request.headers
            return httpx.Response(200,content=make_test_glb())
        return httpx.Response(200,json={'status':'SUCCEEDED','progress':100,'model_urls':{'glb':'https://assets.meshy.ai/model.glb'}})
    async def run():
        settings=Settings(meshy_api_key='fake-test-only')
        provider=MeshyProvider(settings,transport=httpx.MockTransport(handle))
        image=tmp_path/'a.png'; image.write_bytes(b'test')
        remote=await provider.create([image])
        result=await provider.poll(remote)
        assert result.status=='succeeded'
        await provider.download(result.model_url,tmp_path/'model.glb')
        with pytest.raises(ValueError,match='白名单'):
            await provider.download('http://127.0.0.1/secret',tmp_path/'bad.glb')
        await provider.close()
    asyncio.run(run())
    assert len(calls)==3


@pytest.mark.parametrize('status,message',[(400,'无效'),(401,'Key'),(402,'额度'),(429,'限流'),(500,'500')])
def test_remote_errors(status,message):
    async def run():
        provider=MeshyProvider(Settings(meshy_api_key='fake-test-only'),
             transport=httpx.MockTransport(lambda _:httpx.Response(status)))
        with pytest.raises(ValueError,match=message): await provider.poll('test')
        await provider.close()
    asyncio.run(run())


def test_missing_key():
    async def run():
        provider=MeshyProvider(Settings(meshy_api_key=''))
        with pytest.raises(ValueError,match='未配置'): await provider.poll('test')
        await provider.close()
    asyncio.run(run())
