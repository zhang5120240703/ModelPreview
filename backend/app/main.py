import asyncio
import io
import json
import shutil
import warnings
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal
from uuid import uuid4
from PIL import Image, UnidentifiedImageError
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.datastructures import UploadFile
from .config import Settings
from .providers import make_provider
from .service import ReconstructionWorker
from .store import TaskStore
from .image_sources import ImageSources, VIEW_ORDER, VIEW_LABELS, validate_views
from .github_images import GitHubImages


class PublicImagesRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    image_urls: list[str] = Field(min_length=1,max_length=6,title='GitHub Pages 图片直链')
    views: list[Literal['front','back','left','right','top','bottom']] | None = Field(default=None,title='对应视角')


class TaskResponse(BaseModel):
    task_id: str = Field(title='任务编号')
    status: Literal['queued','processing','succeeded','failed'] = Field(title='任务状态',description='queued 排队中；processing 生成中；succeeded 已完成；failed 失败')
    progress: float | None = Field(default=None,title='任务进度',description='无真实进度时为空')
    model_url: str | None = Field(default=None,title='模型下载地址')
    error: str | None = Field(default=None,title='失败原因')
    provider: str = Field(title='建模服务')
    is_mock: bool = Field(title='是否为模拟测试结果')
    status_url: str = Field(title='任务查询地址')


class BodyLimit:
    """Bound multipart bytes even for chunked requests before parsing/spooling."""
    def __init__(self, app, limit): self.app, self.limit = app, limit
    async def __call__(self, scope, receive, send):
        if scope['type']!='http' or scope['method']!='POST':
            return await self.app(scope,receive,send)
        length = dict(scope['headers']).get(b'content-length',b'0')
        try: too_large = int(length) > self.limit
        except ValueError: too_large = True
        body = bytearray()
        if not too_large:
            while True:
                event = await receive()
                if event['type']=='http.disconnect': return
                body.extend(event.get('body',b''))
                if len(body)>self.limit:
                    too_large=True
                    break
                if not event.get('more_body'): break
        if too_large:
            return await JSONResponse({'detail':'上传请求超过总大小限制'},status_code=413)(scope,receive,send)
        delivered=False
        async def replay():
            nonlocal delivered
            if delivered: return await receive()
            delivered=True
            return {'type':'http.request','body':bytes(body),'more_body':False}
        await self.app(scope,replay,send)


def inspect_image(data, suffix, hunyuan=False):
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as image:
            if image.format != ('PNG' if suffix=='.png' else 'JPEG'):
                raise ValueError('文件扩展名与实际图片内容不一致')
            if image.width*image.height > 24_000_000: raise ValueError('图片不得超过 2400 万像素')
            if hunyuan and not all(128 < size < 5000 for size in image.size):
                raise ValueError('混元图片宽和高均须大于 128 且小于 5000 像素')
            image.verify()
        with Image.open(io.BytesIO(data)) as image: image.load()


def create_app(settings=None):
    settings = settings or Settings()
    settings.data_dir = settings.data_dir.resolve()
    store = TaskStore(settings.data_dir)
    image_sources = ImageSources(settings)

    @asynccontextmanager
    async def lifespan(app):
        provider = make_provider(settings)
        worker = asyncio.create_task(ReconstructionWorker(settings,store,provider).run())
        yield
        worker.cancel()
        with suppress(asyncio.CancelledError): await worker
        await provider.close()

    app = FastAPI(title='草编工艺品三维重建接口',version='1.0.0',lifespan=lifespan,
                  description='上传多角度照片、查询任务进度并下载 GLB 模型。默认使用免费模拟测试模式。',
                  docs_url='/docs/swagger',redoc_url=None)
    app.add_middleware(BodyLimit,limit=(settings.max_images*settings.effective_image_mb+1)*1024*1024)
    app.add_middleware(CORSMiddleware,allow_origins=[s.strip() for s in settings.cors_origins.split(',') if s.strip()],
                       allow_methods=['GET','POST'],allow_headers=['Content-Type'])
    app.state.store = store
    app.state.github_images = GitHubImages()

    @app.exception_handler(StarletteHTTPException)
    async def chinese_http_error(request, exc):
        detail = exc.detail
        if isinstance(detail,str):
            if detail.startswith('Too many files'):
                detail = f'最多只能上传 {settings.max_images} 张图片'
            elif detail.startswith('Too many fields'):
                detail = '只允许 images 文件字段和对应的 views 视角字段，不接受额外表单字段或本地路径'
            elif detail.startswith('Part exceeded'):
                detail = '上传内容超过单个表单项大小限制'
            elif detail == 'Not Found': detail = '接口地址不存在'
            elif detail == 'Method Not Allowed': detail = '该接口不支持此请求方式'
        return JSONResponse({'detail':detail},status_code=exc.status_code,headers=exc.headers)

    @app.get('/docs',include_in_schema=False,response_class=HTMLResponse)
    async def chinese_test_page():
        page = (Path(__file__).parent/'test_page.html').read_text(encoding='utf-8')
        return HTMLResponse(page.replace('__MAX_IMAGE_MB__',str(settings.effective_image_mb))
                            .replace('__MAX_IMAGES__',str(settings.max_images)))

    def get_task(task_id):
        row = store.get(task_id)
        if not row: raise HTTPException(404,'任务不存在')
        return row

    def serialize(row):
        task_id = row['task_id']
        return TaskResponse(task_id=task_id,status=row['status'],progress=row['progress'],error=row['error'],
            provider=row['provider'],is_mock=row['provider']=='mock',
            status_url=f'/api/v1/reconstructions/{task_id}',
            model_url=f'{settings.base_url}/api/v1/models/{task_id}/file' if row['status']=='succeeded' else None)

    @app.get('/health',summary='检查服务状态',tags=['服务检查'])
    async def health():
        return {'status':'ok','provider':settings.provider,'provider_ready':settings.provider_ready,
                'min_images':settings.min_images,'max_images':settings.max_images,
                'max_image_mb':settings.effective_image_mb,
                'image_order':['正面','左侧','背面','右侧'] if settings.provider=='fal_tripo' else [VIEW_LABELS[v] for v in VIEW_ORDER[:settings.max_images]],
                'public_images_configured':image_sources.configured if settings.provider=='hunyuan' else None,
                'public_image_links_supported':settings.provider=='hunyuan',
                'model':settings.hunyuan_model if settings.provider=='hunyuan' else None,
                'enable_pbr':settings.hunyuan_enable_pbr if settings.provider=='hunyuan' else None,
                'face_count':settings.hunyuan_face_count if settings.provider=='hunyuan' else None}

    @app.post('/api/v1/reconstructions',status_code=202,response_model=TaskResponse,
              summary='上传图片并创建建模任务',tags=['模型生成'],
              description=f'通过重复的 images 文件字段上传 {settings.min_images}–{settings.max_images} 张 JPG、JPEG 或 PNG 图片。立即返回任务编号。',
              response_description='任务已接收，可使用任务编号查询进度',
              openapi_extra={'requestBody':{'required':True,'content':{'multipart/form-data':{'schema':{
                  'type':'object','required':['images'],'properties':{'images':{'type':'array','minItems':settings.min_images,
                  'maxItems':settings.max_images,'items':{'type':'string','format':'binary'}},
                  'views':{'type':'array','maxItems':settings.max_images,
                           'description':'混元可选：与图片一一对应，不重复且包含 front；省略时按 front/back/left/right/top/bottom',
                           'items':{'type':'string','enum':VIEW_ORDER[:settings.max_images]}}}}}}}})
    async def upload(request: Request):
        if settings.provider == 'fal_tripo' and not settings.provider_ready:
            raise HTTPException(503,'请先在 backend/.env 填写 FAL_KEY 并重启后端；本次未创建付费任务')
        if settings.provider == 'hunyuan' and not settings.provider_ready:
            raise HTTPException(503,'请先在 backend/.env 填写 HUNYUAN_API_KEY 并重启后端；本次未创建付费任务')
        task_id = uuid4().hex
        folder = settings.data_dir / task_id
        try:
            async with request.form(max_files=settings.max_images,max_fields=settings.max_images,
                                    max_part_size=settings.effective_image_mb*1024*1024) as form:
                files = form.getlist('images')
                if any(name not in ('images','views') for name, _ in form.multi_items()):
                    raise HTTPException(400,'不接受额外表单字段或本地路径，只允许 images 和可选 views 字段')
                if not 1<=len(files)<=settings.max_images:
                    raise HTTPException(422,f'images 字段须包含 1–{settings.max_images} 张图片')
                if len(files) < settings.min_images:
                    raise HTTPException(422,'Tripo H3.1 多视图需要 2–4 张图片，按正面、左侧、背面、右侧排序')
                views = form.getlist('views') or VIEW_ORDER[:len(files)]
                if any(not isinstance(view,str) for view in views): raise HTTPException(422,'views 必须是视角名称')
                try: validate_views(views,len(files))
                except ValueError as exc: raise HTTPException(422,str(exc))
                if any(view not in VIEW_ORDER[:settings.max_images] for view in views):
                    raise HTTPException(422,'当前建模服务仅支持正面、背面、左侧、右侧视角')
                if settings.provider == 'hunyuan' and len(files)>1:
                    try: image_sources.require_public_url()
                    except ValueError as exc: raise HTTPException(422,str(exc))
                folder.mkdir()
                paths=[]
                for index, file in enumerate(files):
                    if not isinstance(file,UploadFile): raise HTTPException(422,'images 必须是文件')
                    suffix = '.'+(file.filename or '').rsplit('.',1)[-1].lower()
                    mime = 'image/png' if suffix=='.png' else 'image/jpeg'
                    if suffix not in ('.jpg','.jpeg','.png') or file.content_type != mime:
                        raise HTTPException(415,'只允许 JPG、JPEG、PNG，且 MIME 类型必须匹配')
                    data = await file.read(settings.effective_image_mb*1024*1024+1)
                    if len(data)>settings.effective_image_mb*1024*1024: raise HTTPException(413,f'单张图片超过 {settings.effective_image_mb} MB 限制')
                    try: await asyncio.to_thread(inspect_image,data,suffix,settings.provider=='hunyuan')
                    except (ValueError,OSError,UnidentifiedImageError,Image.DecompressionBombError,Image.DecompressionBombWarning):
                        raise HTTPException(415,'图片内容无效、损坏或尺寸不符；混元要求宽高为 129–4999 像素' if settings.provider=='hunyuan' else '图片内容无效、损坏或像素过大')
                    name = f'image_{index}{suffix}'
                    await asyncio.to_thread((folder/name).write_bytes,data)
                    paths.append(name)
                (folder/'views.json').write_text(json.dumps(views),encoding='utf-8')
                store.create(task_id,settings.provider,paths)
        except BaseException:
            if folder.exists(): shutil.rmtree(folder)
            raise
        return serialize(store.get(task_id))

    async def prepare_public_images(body):
        if settings.provider!='hunyuan': raise HTTPException(409,'GitHub Pages 图片链接模式仅用于腾讯混元')
        views=body.views if body.views is not None else VIEW_ORDER[:len(body.image_urls)]
        try:
            validate_views(views,len(body.image_urls))
            images=await app.state.github_images.fetch(body.image_urls,settings.effective_image_mb)
            for data,suffix in images:
                await asyncio.to_thread(inspect_image,data,suffix,True)
        except (ValueError,OSError,UnidentifiedImageError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:
            message=str(exc) if isinstance(exc,ValueError) else '图片内容无效或损坏，请确认为 JPG/PNG，宽高为 129–4999 像素'
            raise HTTPException(422,message) from None
        return views,images

    @app.post('/api/v1/image-links/check',summary='检查 GitHub Pages 图片链接（不生成、不计费）',tags=['服务检查'])
    async def check_public_images(body: PublicImagesRequest):
        views,images=await prepare_public_images(body)
        return {'valid':True,'image_count':len(images),'views':views,
                'message':'本机读取与图片校验通过；未创建建模任务。腾讯实际可达性仍以提交结果为准。'}

    @app.post('/api/v1/reconstructions/from-urls',status_code=202,response_model=TaskResponse,
              summary='使用 GitHub Pages 图片直链创建混元任务',tags=['模型生成'])
    async def create_from_urls(body: PublicImagesRequest):
        if settings.provider=='hunyuan' and not settings.provider_ready:
            raise HTTPException(503,'请先配置 HUNYUAN_API_KEY 并重启后端；本次未创建任务')
        views,images=await prepare_public_images(body)
        task_id=uuid4().hex
        folder=settings.data_dir/task_id
        try:
            folder.mkdir()
            paths=[]
            for index,(data,suffix) in enumerate(images):
                name=f'image_{index}{suffix}'
                await asyncio.to_thread((folder/name).write_bytes,data)
                paths.append(name)
            (folder/'views.json').write_text(json.dumps(views),encoding='utf-8')
            (folder/'public-images.json').write_text(json.dumps(body.image_urls),encoding='utf-8')
            store.create(task_id,settings.provider,paths)
        except BaseException:
            if folder.exists(): shutil.rmtree(folder)
            raise
        return serialize(store.get(task_id))

    @app.get('/api/v1/reconstructions/{task_id}',response_model=TaskResponse,summary='查询建模任务',tags=['模型生成'],response_description='当前任务状态与模型地址')
    async def status(task_id: str): return serialize(get_task(task_id))

    @app.get('/api/v1/reconstructions/{task_id}/images/{image_index}',include_in_schema=False)
    async def source_image(task_id: str, image_index: int, token: str = ''):
        row = get_task(task_id)
        if row['provider']!='hunyuan' or row['status'] not in ('queued','processing') or not image_sources.verify(task_id,token):
            raise HTTPException(403,'图片访问凭据无效或已失效')
        images = json.loads(row['images'])
        if image_index<0 or image_index>=len(images): raise HTTPException(404,'图片不存在')
        path = settings.data_dir/row['task_id']/images[image_index]
        if not path.is_file(): raise HTTPException(404,'图片不存在')
        return FileResponse(path,media_type='image/png' if path.suffix=='.png' else 'image/jpeg',
                            headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})

    @app.get('/api/v1/models/{task_id}/file',summary='下载 GLB 模型',tags=['模型下载'],responses={200:{'description':'模型下载成功','content':{'model/gltf-binary':{}}}})
    async def model(task_id: str):
        row = get_task(task_id)
        if row['status']!='succeeded': raise HTTPException(409,'模型尚未生成成功')
        path = settings.data_dir / row['task_id'] / 'model.glb'
        if not path.is_file(): raise HTTPException(404,'模型文件不存在')
        return FileResponse(path,media_type='model/gltf-binary',filename=f'{task_id}.glb')

    return app


app = create_app()
