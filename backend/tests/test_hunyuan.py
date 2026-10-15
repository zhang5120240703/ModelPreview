import asyncio
import base64
import importlib
import io
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.config import Settings
from app.glb import make_test_glb
from app.hunyuan_provider import HunyuanProvider
from app.image_sources import ImageSources
from app.main import create_app

ASSET = 'https://hunyuan-prod-1258344699.cos.ap-guangzhou.tencentcos.cn/model.glb'
KEY = 'fake-local-test-key'


def settings_for(tmp_path, **kwargs):
    return Settings(_env_file=None,provider='hunyuan',hunyuan_api_key=KEY,data_dir=tmp_path,**kwargs)


def photo(size=256):
    output=io.BytesIO()
    Image.new('RGB',(size,size),'tan').save(output,format='PNG')
    return output.getvalue()


def images_for(tmp_path,count=1,views=None):
    folder=tmp_path/'task-source'; folder.mkdir(exist_ok=True)
    images=[]
    for i in range(count):
        path=folder/f'image_{i}.png'; path.write_bytes(photo()); images.append(path)
    if views: (folder/'views.json').write_text(json.dumps(views),encoding='utf-8')
    return images


def test_single_image_submit_query_and_download(tmp_path):
    calls=[]
    states=iter(['queued','in_progress','completed'])
    def handle(request):
        calls.append(request)
        if request.url.host.endswith('tencentcos.cn'):
            assert 'authorization' not in request.headers, '下载模型不得携带 API Key'
            return httpx.Response(200,content=make_test_glb())
        assert request.headers['authorization']==f'Bearer {KEY}'
        assert request.method=='POST'
        data=json.loads(request.content)
        if request.url.path.endswith('/submit'):
            assert data['model']=='hy-3d-3.1' and data['generate_type']=='Normal'
            assert data['enable_pbr'] is False
            assert 'result_format' not in data and 'face_count' not in data
            assert 'image_url' not in data and 'multi_view_images' not in data
            assert base64.b64decode(data['image_base64'])==photo()
            return httpx.Response(200,json={'id':'remote-1','status':'queued'})
        assert request.url.path.endswith('/query') and data=={'id':'remote-1','model':'hy-3d-3.1'}
        state=next(states)
        return httpx.Response(200,json={'status':state,'data':[{'type':'obj','url':'https://invalid/mesh.obj'}, {'type':'glb','url':ASSET}]})
    async def run():
        provider=HunyuanProvider(settings_for(tmp_path),transport=httpx.MockTransport(handle))
        remote=await provider.create(images_for(tmp_path))
        assert KEY not in remote
        assert (await provider.poll(remote)).progress is None
        assert (await provider.poll(remote)).status=='processing'
        result=await provider.poll(remote)
        assert result.status=='succeeded' and result.model_url==ASSET and result.progress is None
        await provider.download(result.model_url,tmp_path/'model.glb')
        assert (tmp_path/'model.glb').read_bytes()==make_test_glb()
        await provider.close()
    asyncio.run(run())
    assert len(calls)==5


@pytest.mark.parametrize('views',[
    ['back','front','right','left'],
    ['top','back','front','bottom','right','left'],
])
def test_multiview_mapping_signed_urls_and_restart_model(tmp_path,views):
    calls=[]
    def handle(request):
        data=json.loads(request.content); calls.append(data)
        if request.url.path.endswith('/submit'):
            assert data['enable_pbr'] is True and data['face_count']==30000
            assert f'/images/{views.index("front")}?' in data['image_url']
            assert [(v['view_type'],urlparse(v['view_image_url']).path.rsplit('/',1)[-1])
                    for v in data['multi_view_images']]==[(v,str(i)) for i,v in enumerate(views) if v!='front']
            for url in [data['image_url']]+[v['view_image_url'] for v in data['multi_view_images']]:
                assert url.startswith('https://images.example.com/')
                assert ImageSources(settings_for(tmp_path)).verify('task-source',parse_qs(urlparse(url).query)['token'][0])
            assert 'image_base64' not in data
            return httpx.Response(200,json={'id':'remote-2'})
        assert data['model']=='hy-3d-3.1', '重启后必须按原任务模型查询'
        return httpx.Response(200,json={'status':'completed','data':[{'type':'glb','url':ASSET}]})
    async def run():
        provider=HunyuanProvider(settings_for(tmp_path,hunyuan_image_base_url='https://images.example.com',
                  hunyuan_enable_pbr=True,hunyuan_face_count=30000),transport=httpx.MockTransport(handle))
        remote=await provider.create(images_for(tmp_path,len(views),views))
        await provider.close()
        resumed=HunyuanProvider(settings_for(tmp_path,hunyuan_model='hy-3d-3.0'),transport=httpx.MockTransport(handle))
        assert (await resumed.poll(remote)).status=='succeeded'
        await resumed.close()
    asyncio.run(run())
    assert len(calls)==2


@pytest.mark.parametrize('url',['http://images.example.com','https://127.0.0.1','https://192.168.1.3',
                              'https://localhost','https://machine.local','https://user:pass@example.com'])
def test_public_image_address_validation(tmp_path,url):
    source=ImageSources(settings_for(tmp_path,hunyuan_image_base_url=url))
    assert source.configured is False
    with pytest.raises(ValueError,match='公网 HTTPS'): source.require_public_url()


@pytest.mark.parametrize('status,message',[(400,'无效'),(401,'Key'),(402,'额度'),(403,'授权'),(429,'超限'),(500,'500')])
def test_submission_errors_are_not_retried(tmp_path,status,message):
    requests=[]
    def handle(request):
        requests.append(request)
        return httpx.Response(status)
    async def run():
        provider=HunyuanProvider(settings_for(tmp_path),transport=httpx.MockTransport(handle))
        with pytest.raises(ValueError,match=message): await provider.create(images_for(tmp_path))
        await provider.close()
    asyncio.run(run())
    assert len(requests)==1


def test_poll_transient_errors_do_not_resubmit(tmp_path):
    requests=[]
    def handle(request):
        requests.append(request)
        assert request.url.path.endswith('/query')
        return httpx.Response(503)
    async def run():
        provider=HunyuanProvider(settings_for(tmp_path),transport=httpx.MockTransport(handle))
        remote=json.dumps({'id':'job','model':'hy-3d-3.1'})
        for _ in range(3): assert (await provider.poll(remote)).status=='processing'
        with pytest.raises(ValueError,match='连续异常'): await provider.poll(remote)
        await provider.close()
    asyncio.run(run())
    assert len(requests)==4


@pytest.mark.parametrize('result,expected',[({'status':'failed'},'建模失败'),
    ({'status':'completed','data':[{'type':'obj','url':'https://example.com/a.obj'}]},'GLB'),
    ({'status':'unknown'},'未知'),({'error':{'message':'secret-signed-url'}},'返回错误')])
def test_invalid_remote_results(tmp_path,result,expected):
    async def run():
        provider=HunyuanProvider(settings_for(tmp_path),transport=httpx.MockTransport(lambda _:httpx.Response(200,json=result)))
        try:
            value=await provider.poll(json.dumps({'id':'job','model':'hy-3d-3.1'}))
            assert value.status=='failed' and expected in value.error
        except ValueError as exc:
            assert expected in str(exc) and 'secret-signed-url' not in str(exc)
        finally: await provider.close()
    asyncio.run(run())


def test_download_limits_hosts_and_redirects(tmp_path):
    calls=[]
    def handle(request):
        calls.append(request)
        assert 'authorization' not in request.headers
        if request.url.path=='/large.glb': return httpx.Response(200,content=b'x'*(1024*1024+1))
        return httpx.Response(302,headers={'Location':'http://127.0.0.1/secret'})
    async def run():
        provider=HunyuanProvider(settings_for(tmp_path,max_model_mb=1),transport=httpx.MockTransport(handle))
        for url in ('http://127.0.0.1/a.glb','https://example.com/a.glb','https://user:pass@hunyuan-prod-1258344699.cos.ap-guangzhou.tencentcos.cn/a.glb'):
            with pytest.raises(ValueError,match='白名单'): await provider.download(url,tmp_path/'blocked')
        with pytest.raises(ValueError,match='下载限制'):
            await provider.download(ASSET.replace('model.glb','large.glb'),tmp_path/'large')
        with pytest.raises(ValueError,match='302'): await provider.download(ASSET,tmp_path/'redirect')
        await provider.close()
    asyncio.run(run())
    assert len(calls)==2


def test_missing_key_rejected_without_task_or_secret_leak(tmp_path):
    app=create_app(Settings(_env_file=None,provider='hunyuan',hunyuan_api_key='',data_dir=tmp_path))
    with TestClient(app) as client:
        health=client.get('/health').json()
        assert health['provider_ready'] is False and health['model']=='hy-3d-3.1'
        result=client.post('/api/v1/reconstructions',files={'images':('front.png',photo(),'image/png')})
        assert result.status_code==503 and 'HUNYUAN_API_KEY' in result.json()['detail']
        assert not app.state.store.pending()


def test_preflight_multiview_and_dimensions_and_views(tmp_path):
    app=create_app(settings_for(tmp_path))
    # No lifespan: these cases must fail before any worker/provider/network call.
    client=TestClient(app)
    path='/api/v1/reconstructions'
    assert client.post(path,files=[('images',('a.png',photo(),'image/png'))]*2).status_code==422
    assert client.post(path,files={'images':('a.png',photo(128),'image/png')}).status_code==415
    assert client.post(path,files=[('images',('a.png',photo(),'image/png')),('views',(None,'left'))]).status_code==422
    assert client.post(path,files={'images':('a.png',b'x'*(4*1024*1024+1),'image/png')}).status_code==413
    assert not app.state.store.pending()


def test_source_image_route_tokens_expiration_and_finished_task(tmp_path):
    config=settings_for(tmp_path,hunyuan_image_base_url='https://images.example.com')
    app=create_app(config)
    images=images_for(tmp_path,6)
    app.state.store.create('task-source','hunyuan',[p.name for p in images])
    source=ImageSources(config)
    url=source.urls('task-source',6)[5]
    client=TestClient(app)
    relative=urlparse(url).path+'?'+urlparse(url).query
    assert client.get(urlparse(url).path).status_code==403
    assert client.get(relative).status_code==200
    assert client.get(relative).headers['cache-control']=='no-store'
    assert client.get(relative.replace('/images/5?','/images/9?')).status_code==404
    app.state.store.update('task-source',status='succeeded')
    assert client.get(relative).status_code==403
    app.state.store.update('task-source',status='processing')
    access=tmp_path/'task-source'/'.image-access.json'
    data=json.loads(access.read_text()); data['expires']=0; access.write_text(json.dumps(data))
    assert client.get(relative).status_code==403


@pytest.mark.parametrize('image_count',[1,6])
def test_hunyuan_http_pipeline_with_fake_cloud(tmp_path,monkeypatch,image_count):
    count={'submit':0,'query':0}
    def handle(request):
        if request.url.host.endswith('tencentcos.cn'): return httpx.Response(200,content=make_test_glb())
        if request.url.path.endswith('/submit'):
            count['submit']+=1
            data=json.loads(request.content)
            if image_count==6:
                assert '/images/0?' in data['image_url']
                assert [v['view_type'] for v in data['multi_view_images']]==['back','left','right','top','bottom']
                assert 'image_base64' not in data
            else:
                assert base64.b64decode(data['image_base64'])==photo()
            return httpx.Response(200,json={'id':'job-local-test','status':'queued'})
        count['query']+=1
        return httpx.Response(200,json={'status':'completed','data':[{'type':'glb','url':ASSET}]})
    config=settings_for(tmp_path,poll_interval_seconds=.05,hunyuan_image_base_url='https://images.example.com')
    monkeypatch.setattr(importlib.import_module('app.main'),'make_provider',
        lambda _:HunyuanProvider(config,transport=httpx.MockTransport(handle)))
    app=create_app(config)
    with TestClient(app) as client:
        response=client.post('/api/v1/reconstructions',files=[('images',(f'view-{i}.png',photo(),'image/png')) for i in range(image_count)])
        assert response.status_code==202
        task=response.json()
        import time
        for _ in range(100):
            task=client.get(task['status_url']).json()
            if task['status'] in ('succeeded','failed'): break
            time.sleep(.02)
        assert task['status']=='succeeded' and task['is_mock'] is False
        assert KEY not in json.dumps(task) and KEY not in client.get('/health').text
        assert client.get(task['model_url']).content==make_test_glb()
        row=app.state.store.get(task['task_id'])
        assert json.loads(row['remote_id'])=={'id':'job-local-test','model':'hy-3d-3.1'}
        assert len(json.loads(row['images']))==image_count
    assert count=={'submit':1,'query':1}


@pytest.mark.parametrize('views',[
    ['front','back','left','right','top','top'],
    ['front','back','left','right','top','underside'],
    ['front','back','left','right','top'],
])
def test_six_view_upload_rejects_invalid_labels_before_submission(tmp_path,views):
    app=create_app(settings_for(tmp_path,hunyuan_image_base_url='https://images.example.com'))
    client=TestClient(app)  # No worker: validation must not call a cloud provider.
    files=[('images',(f'view-{i}.png',photo(),'image/png')) for i in range(6)]
    files += [('views',(None,view)) for view in views]
    response=client.post('/api/v1/reconstructions',files=files)
    assert response.status_code==422
    assert not app.state.store.pending()


def test_hunyuan_seventh_image_is_rejected(tmp_path):
    app=create_app(settings_for(tmp_path,hunyuan_image_base_url='https://images.example.com'))
    response=TestClient(app).post('/api/v1/reconstructions',
        files=[('images',('view.png',photo(),'image/png'))]*7)
    assert response.status_code==400 and '6' in response.json()['detail']
    assert not app.state.store.pending()
