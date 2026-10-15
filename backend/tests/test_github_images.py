import asyncio
import importlib
import io
import json
import time
import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.config import Settings
from app.github_images import GitHubImages
from app.glb import make_test_glb
from app.hunyuan_provider import HunyuanProvider
from app.main import create_app

VIEWS=['front','back','left','right','top','bottom']
URLS=[f'https://photos-example.github.io/craft/images/{view}.png' for view in VIEWS]
ASSET='https://hunyuan-prod-1258344699.cos.ap-guangzhou.tencentcos.cn/test.glb'


def photo():
    output=io.BytesIO(); Image.new('RGB',(256,256),'tan').save(output,format='PNG'); return output.getvalue()


def app_for(tmp_path,handler,key='fake-test-key'):
    config=Settings(_env_file=None,provider='hunyuan',hunyuan_api_key=key,data_dir=tmp_path,poll_interval_seconds=.05)
    app=create_app(config)
    app.state.github_images=GitHubImages(transport=httpx.MockTransport(handler))
    return config,app


def good_image(request):
    assert request.method=='GET' and request.url.host=='photos-example.github.io'
    assert 'authorization' not in request.headers
    return httpx.Response(200,content=photo(),headers={'Content-Type':'image/png'})


def test_check_six_links_without_key_or_cloud_submission(tmp_path):
    _,app=app_for(tmp_path,good_image,key='')
    client=TestClient(app)
    result=client.post('/api/v1/image-links/check',json={'image_urls':URLS,'views':VIEWS})
    assert result.status_code==200 and result.json()['image_count']==6
    assert result.json()['valid'] and not app.state.store.pending()
    assert not list(tmp_path.glob('*/image*'))
    assert client.post('/api/v1/reconstructions/from-urls',json={'image_urls':URLS}).status_code==503


@pytest.mark.parametrize('bad_url',[
    'http://photos-example.github.io/a.png','https://127.0.0.1/a.png',
    'https://photos-example.github.io.evil.test/a.png','https://github.com/user/repo/blob/main/a.png',
    'https://user:password@photos-example.github.io/a.png','https://photos-example.github.io:444/a.png',
    'https://photos-example.github.io/index.html','https://photos-example.github.io/a.png#fragment',
])
def test_invalid_link_never_fetched_or_enqueued(tmp_path,bad_url):
    calls=[]
    def handler(request): calls.append(request); return good_image(request)
    _,app=app_for(tmp_path,handler)
    response=TestClient(app).post('/api/v1/reconstructions/from-urls',json={'image_urls':[URLS[0],bad_url]})
    assert response.status_code==422 and not calls and not app.state.store.pending()


@pytest.mark.parametrize('mode',['redirect','not-found','html','damaged','large','timeout'])
def test_unusable_link_does_not_create_paid_task(tmp_path,mode):
    calls=[]
    def handler(request):
        calls.append(request)
        if mode=='redirect':return httpx.Response(302,headers={'Location':'http://127.0.0.1/private'})
        if mode=='not-found':return httpx.Response(404)
        if mode=='html':return httpx.Response(200,text='<html>not a photo</html>',headers={'Content-Type':'text/html'})
        if mode=='damaged':return httpx.Response(200,content=b'invalid',headers={'Content-Type':'image/png'})
        if mode=='large':return httpx.Response(200,content=b'x'*(4*1024*1024+1),headers={'Content-Type':'image/png'})
        raise httpx.ReadTimeout('test',request=request)
    _,app=app_for(tmp_path,handler)
    response=TestClient(app).post('/api/v1/reconstructions/from-urls',json={'image_urls':URLS[:1]})
    assert response.status_code==422 and not app.state.store.pending()
    assert len(calls)==1


def test_invalid_view_labels_and_count_before_fetch(tmp_path):
    calls=[]
    _,app=app_for(tmp_path,lambda request:calls.append(request))
    client=TestClient(app)
    for body in ({'image_urls':URLS,'views':['front']*6},
                 {'image_urls':URLS,'views':VIEWS[:5]},
                 {'image_urls':URLS*2},{'image_urls':[]}):
        assert client.post('/api/v1/reconstructions/from-urls',json=body).status_code==422
    assert not calls and not app.state.store.pending()


@pytest.mark.parametrize('count',[1,6])
def test_public_url_task_pipeline_and_restart_manifest(tmp_path,monkeypatch,count):
    config,app=app_for(tmp_path,good_image)
    urls=URLS[:count]; views=VIEWS[:count]; submit=[]
    def cloud(request):
        if request.url.host.endswith('tencentcos.cn'):
            assert 'authorization' not in request.headers
            return httpx.Response(200,content=make_test_glb())
        assert request.headers['authorization']=='Bearer fake-test-key'
        data=json.loads(request.content)
        if request.url.path.endswith('/submit'):
            submit.append(data)
            assert data['image_url']==urls[0] and 'image_base64' not in data
            assert data.get('multi_view_images',[])==[{'view_type':view,'view_image_url':url} for view,url in zip(views[1:],urls[1:])]
            return httpx.Response(200,json={'id':'github-job','status':'queued'})
        return httpx.Response(200,json={'status':'completed','data':[{'type':'glb','url':ASSET}]})
    monkeypatch.setattr(importlib.import_module('app.main'),'make_provider',
                        lambda _:HunyuanProvider(config,transport=httpx.MockTransport(cloud)))
    with TestClient(app) as client:
        assert client.get('/health').json()['public_images_configured'] is False
        result=client.post('/api/v1/reconstructions/from-urls',json={'image_urls':urls,'views':views})
        assert result.status_code==202
        task=result.json()
        for _ in range(100):
            task=client.get(task['status_url']).json()
            if task['status'] in ('succeeded','failed'):break
            time.sleep(.02)
        assert task['status']=='succeeded' and len(submit)==1
        folder=tmp_path/task['task_id']
        assert json.loads((folder/'public-images.json').read_text())==urls
        assert not (folder/'.image-access.json').exists()
        assert client.get(task['model_url']).content==make_test_glb()
    # A new adapter reads the saved public URLs without depending on in-memory state.
    async def replay():
        provider=HunyuanProvider(config,transport=httpx.MockTransport(cloud))
        try: await provider.create([folder/f'image_{i}.png' for i in range(count)])
        finally:await provider.close()
    asyncio.run(replay())
    assert len(submit)==2  # Only the fake transport receives these test submissions.


def test_meshy_does_not_accept_public_link_mode(tmp_path):
    app=create_app(Settings(_env_file=None,provider='meshy',meshy_api_key='fake',data_dir=tmp_path))
    assert TestClient(app).post('/api/v1/image-links/check',json={'image_urls':URLS[:1]}).status_code==409
