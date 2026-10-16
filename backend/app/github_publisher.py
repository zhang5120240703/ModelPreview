"""Publish one task's photos in one Git commit, then wait before any paid AI call."""
import asyncio
import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote, urlparse
import httpx
from .github_images import GitHubImages, ImageLinkNotReady, validate_github_image_url

MANIFEST='github-upload.json'
ATTRIBUTES=b'*.jpg -filter -diff -merge -text\n*.jpeg -filter -diff -merge -text\n*.png -filter -diff -merge -text\n'


def save_json(path,data):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    temporary.replace(path)


def validate_target(target):
    if not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+',target['repository']):
        raise ValueError('GITHUB_REPOSITORY 须填写 用户名/仓库名')
    branch=target['branch']
    if not re.fullmatch(r'[A-Za-z0-9_/-]+',branch) or branch.startswith('/') or '//' in branch:
        raise ValueError('GitHub 分支名称无效')
    prefix=target['upload_path']
    if not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*',prefix):
        raise ValueError('GitHub 图片发布目录无效，只允许目录名、短横线、下划线和斜杠')
    base=target['pages_base_url'].rstrip('/')
    validate_github_image_url(base+'/validation.jpg')
    parsed=urlparse(base)
    if parsed.query or parsed.fragment or parsed.hostname!=target['repository'].split('/')[0].lower()+'.github.io':
        raise ValueError('GITHUB_PAGES_BASE_URL 须为仓库所有者的 GitHub Pages 地址，不带查询参数')


def make_manifest(settings,task_id,paths,views):
    target={'repository':settings.github_repository,'branch':settings.github_branch,
            'pages_base_url':settings.github_pages_base_url.rstrip('/'),
            'upload_path':settings.github_upload_path.strip('/')}
    validate_target(target)
    target.update(task_id=task_id,files=[{'local':path,'remote':f'{target["upload_path"]}/{task_id}/{view}{Path(path).suffix}'}
                                       for path,view in zip(paths,views)],blobs={},published=False)
    return target


class GitHubPublisher:
    def __init__(self,settings,transport=None,images_transport=None):
        self.settings=settings
        # Credentials exist only on the client for the fixed api.github.com endpoint.
        self.client=httpx.AsyncClient(timeout=45,transport=transport,follow_redirects=False)
        self.images=GitHubImages(transport=images_transport)

    @staticmethod
    def checked(response):
        if response.is_success:return
        reasons={401:'GitHub Token 无效或过期',403:'GitHub 权限、分支保护或请求频率限制，请检查该仓库 Contents 写入权限',
                 404:'GitHub 仓库或分支不存在，或 Token 未获该仓库授权',409:'GitHub 仓库为空或分支冲突',
                 422:'GitHub 参数或分支更新被拒绝',429:'GitHub 请求频率受限'}
        raise ValueError(reasons.get(response.status_code,f'GitHub 服务异常（HTTP {response.status_code}）')+'；尚未提交混元')

    async def request(self,method,repo,path='',body=None,conflict=False):
        key=self.settings.github_token.get_secret_value().strip()
        if not key:raise ValueError('缺少 GITHUB_TOKEN，请运行 scripts/configure-github.ps1；尚未提交混元')
        headers={'Authorization':'Bearer '+key,'Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2026-03-10','User-Agent':'GrassCraft-Photo-Uploader'}
        try:
            response=await self.client.request(method,'https://api.github.com/repos/'+repo+path,headers=headers,json=body)
        except httpx.HTTPError:
            raise ValueError('GitHub 网络异常，尚未提交混元；照片发布状态会在重启后按原任务检查') from None
        if conflict and response.status_code in (409,422):return None
        self.checked(response)
        try:data=response.json()
        except ValueError:raise ValueError('GitHub 返回的数据格式无效；尚未提交混元') from None
        if not isinstance(data,dict):raise ValueError('GitHub 返回的数据格式无效；尚未提交混元')
        return data

    @staticmethod
    def sha(value):
        if not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{40}',value):
            raise ValueError('GitHub 未返回有效提交或文件编号；尚未提交混元')
        return value

    async def publish(self,folder,changed):
        path=folder/MANIFEST
        state=json.loads(path.read_text(encoding='utf-8'))
        validate_target(state)
        if state.get('published'):return state
        repo=state['repository']
        info=await self.request('GET',repo)
        if info.get('private') is not False:
            raise ValueError('自动照片上传需要公开照片仓库；当前仓库不是公开仓库，尚未上传照片或提交混元')
        contents=[(entry['remote'],await asyncio.to_thread((folder/entry['local']).read_bytes)) for entry in state['files']]
        parent=contents[0][0].rsplit('/',1)[0]
        contents.append((parent+'/.gitattributes',ATTRIBUTES))
        for index,(remote,content) in enumerate(contents):
            if remote not in state['blobs']:
                result=await self.request('POST',repo,'/git/blobs',{'content':base64.b64encode(content).decode('ascii'),'encoding':'base64'})
                state['blobs'][remote]=self.sha(result.get('sha'))
                save_json(path,state)
            if index<len(state['files']):changed(f'正在上传照片到 GitHub：{index+1}/{len(state["files"])}；尚未提交混元')
        ref=quote(state['branch'],safe='/')
        for _ in range(3):
            head=await self.request('GET',repo,'/git/ref/heads/'+ref)
            base=self.sha(head.get('object',{}).get('sha'))
            # Recover a successful ref update even if its response was lost on shutdown.
            if base==state.get('pending_commit'):
                state['published']=True;save_json(path,state);return state
            commit=await self.request('GET',repo,'/git/commits/'+base)
            base_tree=self.sha(commit.get('tree',{}).get('sha'))
            tree=await self.request('POST',repo,'/git/trees',{'base_tree':base_tree,'tree':[
                {'path':remote,'mode':'100644','type':'blob','sha':sha} for remote,sha in state['blobs'].items()]})
            result=await self.request('POST',repo,'/git/commits',{
                'message':f'Publish photo views for task {state["task_id"]}',
                'tree':self.sha(tree.get('sha')),'parents':[base]})
            state['pending_commit']=self.sha(result.get('sha'));save_json(path,state)
            try:
                updated=await self.request('PATCH',repo,'/git/refs/heads/'+ref,
                                           {'sha':state['pending_commit'],'force':False},conflict=True)
            except ValueError as exc:
                if '网络异常' in str(exc):continue
                raise
            if updated is not None:
                state['published']=True;save_json(path,state);return state
        raise ValueError('GitHub 分支连续变化或发布结果未确认；尚未提交混元，请保留原任务记录并核实 GitHub')

    async def prepare(self,folder,changed):
        try:
            async with asyncio.timeout(self.settings.github_publish_timeout_seconds):
                state=await self.publish(folder,lambda message:changed('uploading_images',message))
                urls=[state['pages_base_url']+'/'+entry['remote'] for entry in state['files']]
                changed('waiting_images','照片已上传，等待 GitHub Pages 发布；尚未提交混元，暂未产生混元建模费用')
                while True:
                    try:
                        files=await self.images.fetch(urls,self.settings.effective_image_mb)
                    except ImageLinkNotReady:
                        await asyncio.sleep(self.settings.github_publish_poll_seconds)
                        continue
                    for (data,_),entry in zip(files,state['files']):
                        local=await asyncio.to_thread((folder/entry['local']).read_bytes)
                        if hashlib.sha256(data).digest()!=hashlib.sha256(local).digest():
                            raise ValueError('Pages 图片内容与本次上传不一致，尚未提交混元；请核实 Pages 发布目录')
                    save_json(folder/'public-images.json',urls)
                    return
        except TimeoutError:
            raise ValueError('GitHub 图片发布等待超时，尚未提交混元；请检查 Pages 发布分支、目录和 Actions 状态，照片已上传的部分会保留') from None

    async def close(self):
        await self.client.aclose()
