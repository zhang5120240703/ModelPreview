from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


def test_chinese_test_page_and_protocol(tmp_path):
    settings = Settings(_env_file=None, provider='mock', meshy_api_key='',
                        data_dir=tmp_path, max_image_mb=3)
    with TestClient(create_app(settings)) as client:
        response = client.get('/docs')
        assert response.status_code == 200
        assert 'text/html' in response.headers['content-type']
        assert 'lang="zh-CN"' in response.text
        assert '上传并开始生成' in response.text
        assert '每张最多 3 MB' in response.text
        assert '__MAX_IMAGE_MB__' not in response.text
        assert '__MAX_IMAGES__' not in response.text
        assert '选择 1–6 张照片' in response.text
        schema = client.get('/openapi.json').json()
        assert schema['info']['title'] == '草编工艺品三维重建接口'
        operation = schema['paths']['/api/v1/reconstructions']['post']
        assert operation['summary'] == '上传图片并创建建模任务'
        assert 'images' in operation['requestBody']['content']['multipart/form-data']['schema']['properties']
        properties=operation['requestBody']['content']['multipart/form-data']['schema']['properties']
        assert properties['images']['maxItems']==6
        assert properties['views']['items']['enum']==['front','back','left','right','top','bottom']
        assert client.get('/health').json()['image_order']==['正面','背面','左侧','右侧','顶面','底面']
        assert client.get('/docs/swagger').status_code == 200
        rejected = client.post('/api/v1/reconstructions', data={'local_path': 'C:/photo.png'})
        assert rejected.status_code == 400
        assert '不接受额外表单字段' in rejected.json()['detail']


def test_meshy_keeps_its_four_image_limit(tmp_path):
    settings=Settings(_env_file=None,provider='meshy',meshy_api_key='fake',data_dir=tmp_path)
    client=TestClient(create_app(settings))
    assert client.get('/health').json()['max_images']==4
    assert '选择 1–4 张照片' in client.get('/docs').text
    assert client.post('/api/v1/reconstructions',
        files=[('images',('photo.png',b'not-decoded','image/png'))]*5).status_code==400
