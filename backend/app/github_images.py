"""Read public GitHub Pages photos without forwarding service credentials."""
import asyncio
import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse
import httpx


def validate_github_image_url(url):
    if not isinstance(url,str) or len(url)>2048 or any(c.isspace() for c in url):
        raise ValueError('图片链接无效，请填写完整的 GitHub Pages HTTPS 图片地址')
    try:
        parsed=urlparse(url)
        valid=(parsed.scheme=='https' and
               re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.github\.io',parsed.hostname or '') and
               not parsed.username and not parsed.password and parsed.port in (None,443) and
               not parsed.fragment and '\\' not in url)
    except ValueError:
        valid=False
    if not valid:
        raise ValueError('请使用 https://用户名.github.io/... 的图片直链，不接受仓库网页、本地地址或自定义域名')
    suffix=PurePosixPath(unquote(parsed.path)).suffix.lower()
    if suffix not in ('.jpg','.jpeg','.png'):
        raise ValueError('图片直链必须指向 JPG、JPEG 或 PNG 文件，不能填写网站首页')
    return suffix


class GitHubImages:
    def __init__(self,transport=None):
        self.transport=transport

    async def fetch(self,urls,max_image_mb):
        suffixes=[validate_github_image_url(url) for url in urls]
        async with httpx.AsyncClient(timeout=15,follow_redirects=False,transport=self.transport) as client:
            async def read(url,suffix):
                async with client.stream('GET',url) as response:
                    if response.status_code!=200:
                        raise ValueError(f'GitHub Pages 图片读取失败（HTTP {response.status_code}），请确认已发布且链接直接打开图片；本次未创建任务')
                    mime=response.headers.get('content-type','').split(';',1)[0].strip().lower()
                    if mime!=('image/png' if suffix=='.png' else 'image/jpeg'):
                        raise ValueError('图片链接返回的不是对应图片格式，可能是网页、404 页面或未发布的文件')
                    data=bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data)>max_image_mb*1024*1024:
                            raise ValueError(f'GitHub Pages 单张图片超过 {max_image_mb} MB，请压缩后重新发布')
                    if data.startswith(b'version https://git-lfs.github.com/spec/v1'):
                        raise ValueError('图片链接返回的是 Git LFS 指针，无法用于 GitHub Pages。请取消该照片目录的 LFS 管理，重新提交真正的图片并等待发布；本次未创建任务')
                    return bytes(data),suffix
            try:
                async with asyncio.timeout(25):
                    results=await asyncio.gather(*(read(url,suffix) for url,suffix in zip(urls,suffixes)),return_exceptions=True)
                for result in results:
                    if isinstance(result,Exception): raise result
                return results
            except (httpx.HTTPError,TimeoutError):
                raise ValueError('无法连接 GitHub Pages 图片，请检查网络和发布状态；本次未创建任务') from None
