import io
import json
import struct
import time
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


def photo():
    output=io.BytesIO()
    Image.new('RGB',(32,32),'tan').save(output,format='PNG')
    return output.getvalue()


def client_for(tmp_path, **kwargs):
    return TestClient(create_app(Settings(_env_file=None,provider='mock',meshy_api_key='',data_dir=tmp_path,mock_delay_seconds=0.02,
                        public_base_url='http://192.168.1.20:8000',**kwargs)))


def wait(client, task):
    for _ in range(100):
        result=client.get(task['status_url']).json()
        if result['status'] in ('succeeded','failed'): return result
        time.sleep(.02)
    raise AssertionError('worker did not finish')


@pytest.mark.parametrize('image_count',[4,6])
def test_full_mock_pipeline(tmp_path,image_count):
    with client_for(tmp_path) as client:
        response=client.post('/api/v1/reconstructions',files=[('images',('front.png',photo(),'image/png'))]*image_count)
        assert response.status_code==202
        task=response.json()
        assert task['status']=='queued' and task['is_mock']
        pending=client.get(f"/api/v1/models/{task['task_id']}/file")
        assert pending.status_code==409
        result=wait(client,task)
        assert result['status']=='succeeded' and result['progress']==100
        assert result['model_url'].startswith('http://192.168.1.20:8000/')
        download=client.get(result['model_url'])
        assert download.status_code==200 and download.headers['content-type']=='model/gltf-binary'
        magic,version,size=struct.unpack('<4sII',download.content[:12])
        assert (magic,version,size)==(b'glTF',2,len(download.content))
        json_size=struct.unpack('<I',download.content[12:16])[0]
        gltf=json.loads(download.content[20:20+json_size])
        assert gltf['images'][0]['mimeType']=='image/png'
        assert len(list((tmp_path/task['task_id']).glob('image*')))==image_count


def test_upload_validation(tmp_path):
    with client_for(tmp_path,max_image_mb=1) as client:
        path='/api/v1/reconstructions'
        assert client.post(path).status_code==422
        assert client.post(path,files=[('images',('x.png',photo(),'image/png'))]*7).status_code==400
        assert client.post(path,files={'images':('x.png',b'fake','image/png')}).status_code==415
        assert client.post(path,files={'images':('x.jpg',photo(),'image/jpeg')}).status_code==415
        assert client.post(path,files={'images':('x.exe',photo(),'image/png')}).status_code==415
        assert client.post(path,files={'images':('x.png',photo(),'text/plain')}).status_code==415
        assert client.post(path,files={'images':('x.png',b'x'*(1024*1024+1),'image/png')}).status_code==413
        assert client.post(path,content=b'x'*(7*1024*1024+1)).status_code==413
        assert client.post(path,data={'local_path':'C:/secret.png'}).status_code==400
        assert not list(tmp_path.glob('*/image*'))


def test_unknown_and_path_traversal(tmp_path):
    with client_for(tmp_path) as client:
        assert client.get('/api/v1/reconstructions/unknown').status_code==404
        assert client.get('/api/v1/models/unknown/file').status_code==404
        task=client.post('/api/v1/reconstructions',files={'images':('../../outside.png',photo(),'image/png')}).json()
        assert wait(client,task)['status']=='succeeded'
        assert (tmp_path/task['task_id']/'image_0.png').exists()
        assert not (tmp_path/'outside.png').exists()


def test_restart_recovers_queued_and_marks_ambiguous_failed(tmp_path):
    app=create_app(Settings(_env_file=None,provider='mock',meshy_api_key='',data_dir=tmp_path,mock_delay_seconds=0))
    folder=tmp_path/'queued'; folder.mkdir()
    (folder/'image_0.png').write_bytes(photo())
    app.state.store.create('queued','mock',['image_0.png'])
    (tmp_path/'ambiguous').mkdir()
    app.state.store.create('ambiguous','meshy',[])
    app.state.store.update('ambiguous',status='processing')
    with TestClient(app) as client:
        assert wait(client,{'status_url':'/api/v1/reconstructions/queued'})['status']=='succeeded'
        assert wait(client,{'status_url':'/api/v1/reconstructions/ambiguous'})['status']=='failed'
