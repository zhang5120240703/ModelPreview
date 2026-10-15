"""Short-lived, task-scoped photo URLs for cloud multiview generation."""
import ipaddress
import json
import secrets
import time
from urllib.parse import urlparse, quote

# Preserve the original four-view order for existing clients and saved tasks.
VIEW_ORDER = ['front', 'back', 'left', 'right', 'top', 'bottom']
VIEW_LABELS = {'front': '正面', 'back': '背面', 'left': '左侧', 'right': '右侧', 'top': '顶面', 'bottom': '底面'}


class ImageSources:
    def __init__(self, settings):
        self.settings = settings

    @property
    def base_url(self):
        return (self.settings.hunyuan_image_base_url or self.settings.base_url).rstrip('/')

    def require_public_url(self):
        parsed = urlparse(self.base_url)
        host = parsed.hostname or ''
        invalid = parsed.scheme != 'https' or not host or parsed.username or parsed.password or parsed.query or parsed.fragment
        if host.lower() == 'localhost' or host.lower().endswith(('.localhost', '.local')) or '.' not in host:
            invalid = True
        try:
            if not ipaddress.ip_address(host).is_global: invalid = True
        except ValueError:
            pass
        if invalid:
            raise ValueError('混元多视图需要公网 HTTPS 图片地址。请配置 HUNYUAN_IMAGE_BASE_URL；本机可先上传一张正面图测试')

    @property
    def configured(self):
        try:
            self.require_public_url()
            return True
        except ValueError:
            return False

    def urls(self, task_id, count):
        self.require_public_url()
        folder = self.settings.data_dir / task_id
        access = {'token': secrets.token_urlsafe(32),
                  'expires': time.time() + self.settings.task_timeout_seconds + 600}
        (folder / '.image-access.json').write_text(json.dumps(access), encoding='utf-8')
        return [f'{self.base_url}/api/v1/reconstructions/{quote(task_id,safe="")}/images/{i}?token={access["token"]}'
                for i in range(count)]

    def verify(self, task_id, token):
        try:
            access = json.loads((self.settings.data_dir / task_id / '.image-access.json').read_text(encoding='utf-8'))
            return time.time() < access['expires'] and secrets.compare_digest(token, access['token'])
        except (OSError, ValueError, KeyError, TypeError):
            return False


def read_views(folder, count):
    path = folder / 'views.json'
    views = json.loads(path.read_text(encoding='utf-8')) if path.exists() else VIEW_ORDER[:count]
    validate_views(views, count)
    return views


def validate_views(views, count):
    if (len(views) != count or any(v not in VIEW_ORDER for v in views) or
        len(set(views)) != count or 'front' not in views):
        raise ValueError('每张照片必须对应不同视角，且包含一张正面图；可选 front、back、left、right、top、bottom')
