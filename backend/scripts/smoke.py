"""Exercise a running Mock server, produce a sample upload and a downloaded GLB."""
import argparse
import io
import json
import time
from pathlib import Path
import httpx
from PIL import Image

parser=argparse.ArgumentParser(description='上传测试图片，等待模拟任务完成并下载 GLB 模型。')
parser.add_argument('--base-url',default='http://127.0.0.1:8000',help='后端服务地址')
parser.add_argument('--output',type=Path,default=Path('data/smoke'),help='测试图片、任务记录和模型的保存目录')
args=parser.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
with httpx.Client(base_url=args.base_url,timeout=30) as client:
    health=client.get('/health'); health.raise_for_status()
    if health.json()['provider']!='mock': raise SystemExit('请先设置 PROVIDER=mock 再运行联调测试；本次未提交任何付费任务。')
    image=io.BytesIO()
    Image.new('RGB',(256,256),(194,154,91)).save(image,format='PNG')
    (args.output/'test-photo.png').write_bytes(image.getvalue())
    response=client.post('/api/v1/reconstructions',files={'images':('test-photo.png',image.getvalue(),'image/png')})
    response.raise_for_status()
    task=response.json()
    for _ in range(60):
        response=client.get(task['status_url']); response.raise_for_status()
        task=response.json()
        if task['status'] in ('succeeded','failed'): break
        time.sleep(1)
    if task['status']!='succeeded': raise SystemExit(json.dumps(task,ensure_ascii=False))
    model=client.get(task['model_url']); model.raise_for_status()
    assert model.content[:4]==b'glTF'
    (args.output/'mock-textured-cube.glb').write_bytes(model.content)
    (args.output/'task.json').write_text(json.dumps(task,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(task,ensure_ascii=False,indent=2))
    print(f'模拟测试模型下载成功：{len(model.content)} 字节。此模型不是实际 AI 重建结果。')
