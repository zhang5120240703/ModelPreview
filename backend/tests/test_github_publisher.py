import asyncio
import base64
import importlib
import io
import json
import sqlite3
import time
from pathlib import Path
import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.config import Settings
from app.github_publisher import GitHubPublisher,MANIFEST,make_manifest,save_json,validate_target
from app.glb import make_test_glb
from app.hunyuan_provider import HunyuanProvider
from app.main import create_app
from app.service import ReconstructionWorker
from app.store import TaskStore

VIEWS=['front','back','left','right','top','bottom']


def photo(color='tan'):
    data=io.BytesIO();Image.new('RGB',(256,256),color).save(data,format='PNG');return data.getvalue()


def settings(tmp_path,**changes):
    options=dict(_env_file=None,provider='hunyuan',hunyuan_api_key='fake-hunyuan-key',data_dir=tmp_path,
                 github_upload_enabled=True,github_token='fake-github-token',github_repository='tester/photos',
                 github_pages_base_url='https://tester.github.io/photos',github_publish_poll_seconds=.05,
                 poll_interval_seconds=.05)
    options.update(changes);return Settings(**options)


class GitHub:
    def __init__(self,private=False,conflict=False,lost_patch=False):
        self.head='a'*40;self.private=private;self.conflict=conflict;self.lost_patch=lost_patch
        self.calls=[];self.blobs={};self.trees=[];self.commits=[];self.patches=0
    def __call__(self,request):
        assert request.url.host=='api.github.com'
        assert request.headers['authorization']=='Bearer fake-github-token'
        path=request.url.path;body=json.loads(request.content) if request.content else None
        self.calls.append((request.method,path,body))
        if path=='/repos/tester/photos':return httpx.Response(200,json={'private':self.private})
        if path.endswith('/git/blobs'):
            data=base64.b64decode(body['content']);sha=f'{len(self.blobs)+1:040x}'
            self.blobs[sha]=data;return httpx.Response(201,json={'sha':sha})
        if '/git/ref/heads/' in path:return httpx.Response(200,json={'object':{'sha':self.head}})
        if request.method=='GET' and '/git/commits/' in path:return httpx.Response(200,json={'tree':{'sha':'b'*40}})
        if path.endswith('/git/trees'):
            assert body['base_tree']=='b'*40
            self.trees.append(body);return httpx.Response(201,json={'sha':'c'*40})
        if path.endswith('/git/commits'):
            self.commits.append(body);return httpx.Response(201,json={'sha':f'{100+len(self.commits):040x}'})
        if '/git/refs/heads/' in path:
            self.patches+=1;assert body['force'] is False
            if self.conflict:
                self.conflict=False;self.head='e'*40;return httpx.Response(422,json={})
            self.head=body['sha']
            if self.lost_patch:
                self.lost_patch=False;raise httpx.ReadTimeout('lost response',request=request)
            return httpx.Response(200,json={'object':{'sha':self.head}})
        raise AssertionError(path)


def folder_for(tmp_path,config,views=VIEWS):
    folder=tmp_path/'job';folder.mkdir()
    names=[]
    for index,view in enumerate(views):
        name=f'image_{index}.png';(folder/name).write_bytes(photo());names.append(name)
    (folder/'views.json').write_text(json.dumps(views))
    save_json(folder/MANIFEST,make_manifest(config,'job',names,views))
    return folder,names


@pytest.mark.parametrize('case',['normal','conflict','lost-patch'])
def test_single_commit_publish_preserves_tree_and_recovers_ref_update(tmp_path,case):
    config=settings(tmp_path);folder,_=folder_for(tmp_path,config)
    github=GitHub(conflict=case=='conflict',lost_patch=case=='lost-patch')
    async def run():
        publisher=GitHubPublisher(config,transport=httpx.MockTransport(github))
        try:
            state=await publisher.publish(folder,lambda _:None)
            assert state['published'] and 'fake-github-token' not in (folder/MANIFEST).read_text()
            before=len(github.calls)
            await publisher.publish(folder,lambda _:None)
            assert len(github.calls)==before
        finally:await publisher.close()
    asyncio.run(run())
    assert len(github.blobs)==7
    assert len(github.commits)==(2 if case=='conflict' else 1)
    entries=github.trees[-1]['tree'];assert len(entries)==7
    assert all(entry['path'].startswith('github-pages-images/uploads/job/') for entry in entries)
    assert set(entry['mode'] for entry in entries)=={'100644'}
    assert any(b'-filter' in data for data in github.blobs.values())
    assert sum(data==photo() for data in github.blobs.values())==6


def test_private_repository_rejected_before_any_blob_upload(tmp_path):
    config=settings(tmp_path);folder,_=folder_for(tmp_path,config);github=GitHub(private=True)
    async def run():
        publisher=GitHubPublisher(config,transport=httpx.MockTransport(github))
        try:
            with pytest.raises(ValueError,match='公开'):await publisher.publish(folder,lambda _:None)
        finally:await publisher.close()
    asyncio.run(run());assert len(github.calls)==1 and not github.blobs


@pytest.mark.parametrize('field,value',[
    ('repository','tester/photos/extra'),('branch','../../main'),('upload_path','../Assets'),
    ('pages_base_url','http://tester.github.io/photos'),('pages_base_url','https://evil.github.io/photos'),
    ('pages_base_url','https://tester.github.io/photos?secret=bad'),
])
def test_unsafe_publish_target_rejected(tmp_path,field,value):
    state=make_manifest(settings(tmp_path),'job',['image.png'],['front']);state[field]=value
    with pytest.raises(ValueError):validate_target(state)


@pytest.mark.parametrize('status',[401,403,404,429,500])
def test_api_errors_do_not_expose_response_secrets(tmp_path,status):
    config=settings(tmp_path);folder,_=folder_for(tmp_path,config)
    async def run():
        publisher=GitHubPublisher(config,transport=httpx.MockTransport(lambda _:httpx.Response(status,json={'message':'DO-NOT-LEAK-KEY'})))
        try:
            with pytest.raises(ValueError) as error:await publisher.publish(folder,lambda _:None)
            assert 'DO-NOT-LEAK' not in str(error.value) and '尚未提交混元' in str(error.value)
        finally:await publisher.close()
    asyncio.run(run())


def test_waits_for_pages_before_one_paid_submission(tmp_path,monkeypatch):
    config=settings(tmp_path);github=GitHub();reads=[];paid=[];stages=[]
    def assets(request):
        assert request.url.host=='tester.github.io' and 'authorization' not in request.headers
        reads.append(str(request.url))
        if len(reads)<=6:return httpx.Response(404)
        return httpx.Response(200,content=photo(),headers={'Content-Type':'image/png'})
    def cloud(request):
        if request.url.host.endswith('tencentcos.cn'):
            assert 'authorization' not in request.headers
            return httpx.Response(200,content=make_test_glb())
        assert request.headers['authorization']=='Bearer fake-hunyuan-key'
        if request.url.path.endswith('/submit'):
            assert len(reads)>=12
            data=json.loads(request.content);paid.append(data)
            assert data['image_url'].endswith('/front.png')
            assert {item['view_type'] for item in data['multi_view_images']}==set(VIEWS)-{'front'}
            return httpx.Response(200,json={'id':'one-paid-task'})
        return httpx.Response(200,json={'status':'completed','data':[{'type':'glb','url':'https://hunyuan-prod-1258344699.cos.ap-guangzhou.tencentcos.cn/test.glb'}]})
    main=importlib.import_module('app.main')
    monkeypatch.setattr(main,'GitHubPublisher',lambda _:GitHubPublisher(config,transport=httpx.MockTransport(github),images_transport=httpx.MockTransport(assets)))
    monkeypatch.setattr(main,'make_provider',lambda _:HunyuanProvider(config,transport=httpx.MockTransport(cloud)))
    app=create_app(config);original=app.state.store.update
    def record(task_id,**fields):
        if 'stage' in fields:stages.append(fields['stage'])
        return original(task_id,**fields)
    app.state.store.update=record
    with TestClient(app) as client:
        response=client.post('/api/v1/reconstructions',files=[('images',(f'private-name-{i}.png',photo(),'image/png')) for i in range(6)]+[('views',(None,view)) for view in VIEWS])
        assert response.status_code==202;task=response.json()
        for _ in range(150):
            task=client.get(task['status_url']).json()
            if task['status'] in ('succeeded','failed'):break
            time.sleep(.02)
        assert task['status']=='succeeded' and task['stage']=='completed'
        assert task['progress']==100 and len(paid)==1 and len(github.commits)==1
        assert set(['uploading_images','waiting_images','submitting','generating','downloading','completed'])<=set(stages)
        assert 'fake-github-token' not in client.get('/health').text+json.dumps(task)
        assert client.get(task['model_url']).content==make_test_glb()


@pytest.mark.parametrize('condition',['timeout','different-image','lfs'])
def test_image_publication_failure_never_creates_ai_task(tmp_path,condition):
    config=settings(tmp_path,github_publish_timeout_seconds=1)
    folder,names=folder_for(tmp_path,config);store=TaskStore(tmp_path);store.create('job','hunyuan',names)
    def assets(_):
        if condition=='timeout':return httpx.Response(404)
        data=photo('red') if condition=='different-image' else b'version https://git-lfs.github.com/spec/v1\noid sha256:a\nsize 50\n'
        return httpx.Response(200,content=data,headers={'Content-Type':'image/png'})
    class NoPaidCall:
        async def create(self,images):raise AssertionError('未发布图片时不得提交付费任务')
    async def run():
        publisher=GitHubPublisher(config,transport=httpx.MockTransport(GitHub()),images_transport=httpx.MockTransport(assets))
        try:await ReconstructionWorker(config,store,NoPaidCall(),publisher).process('job')
        finally:await publisher.close()
    asyncio.run(run());row=store.get('job')
    assert row['status']=='failed' and row['remote_id'] is None
    assert '尚未提交混元' in row['error'] or 'LFS' in row['error']


def test_waiting_stage_resumes_after_restart_without_republishing(tmp_path):
    config=settings(tmp_path);folder,names=folder_for(tmp_path,config);store=TaskStore(tmp_path);store.create('job','hunyuan',names)
    github=GitHub();waiting=asyncio.Event();paid=[]
    def not_ready(_):waiting.set();return httpx.Response(404)
    class Provider:
        async def create(self,images):
            assert (folder/'public-images.json').exists();paid.append(True);return 'remote'
        async def poll(self,remote):
            from app.providers import ProviderResult
            return ProviderResult('succeeded',model_url='mock://file')
        async def download(self,url,path):path.write_bytes(make_test_glb())
    async def run():
        first=GitHubPublisher(config,transport=httpx.MockTransport(github),images_transport=httpx.MockTransport(not_ready))
        task=asyncio.create_task(ReconstructionWorker(config,store,Provider(),first).process('job'))
        await asyncio.wait_for(waiting.wait(),3);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        await first.close()
        assert store.get('job')['stage']=='waiting_images' and not paid
        count=len(github.calls)
        resumed=GitHubPublisher(config,transport=httpx.MockTransport(github),images_transport=httpx.MockTransport(lambda _:httpx.Response(200,content=photo(),headers={'Content-Type':'image/png'})))
        try:await ReconstructionWorker(config,store,Provider(),resumed).process('job')
        finally:await resumed.close()
        assert len(github.calls)==count
    asyncio.run(run());assert store.get('job')['status']=='succeeded' and len(paid)==1


def test_missing_github_token_rejected_before_task_or_upload(tmp_path):
    config=settings(tmp_path,github_token='');app=create_app(config);client=TestClient(app)
    response=client.post('/api/v1/reconstructions',files=[('images',('photo.png',photo(),'image/png'))]*6)
    assert response.status_code==503 and not app.state.store.pending()
    assert client.get('/health').json()['github_upload_ready'] is False


def test_legacy_database_migration_preserves_existing_tasks(tmp_path):
    conn=sqlite3.connect(tmp_path/'tasks.sqlite3')
    conn.execute('CREATE TABLE tasks (task_id TEXT PRIMARY KEY,status TEXT,progress REAL,provider TEXT,remote_id TEXT,images TEXT,error TEXT,created_at TEXT)')
    conn.execute("INSERT INTO tasks VALUES ('old','succeeded',100,'hunyuan','remote','[]',NULL,'2026-01-01')")
    conn.commit();conn.close()
    store=TaskStore(tmp_path);row=store.get('old')
    assert row['stage']=='completed' and row['remote_id']=='remote' and row['status_message'] is None
    store.create('new','mock',[]);assert store.get('new')['stage']=='queued'


def test_configuration_helper_preserves_hunyuan_key_and_hides_github_token(tmp_path,monkeypatch,capsys):
    import importlib.util
    from dotenv import dotenv_values
    source=Path(__file__).resolve().parents[1]/'scripts/configure_github.py'
    spec=importlib.util.spec_from_file_location('configure_github_test',source)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    helper.ROOT=tmp_path
    (tmp_path/'.env').write_text('PROVIDER=hunyuan\nHUNYUAN_API_KEY=keep-this-test-key\nGITHUB_REPOSITORY=tester/photos\n',encoding='utf-8')
    monkeypatch.setattr('builtins.input',lambda _: '')
    monkeypatch.setattr(helper.getpass,'getpass',lambda _: 'new-test-github-token')
    helper.main()
    values=dotenv_values(tmp_path/'.env')
    assert values['HUNYUAN_API_KEY']=='keep-this-test-key'
    assert values['GITHUB_TOKEN']=='new-test-github-token' and values['GITHUB_UPLOAD_ENABLED']=='true'
    assert 'new-test-github-token' not in capsys.readouterr().out
