"""Store a TokenHub key locally without echoing it or placing it in shell history."""
import getpass
import json
import re
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    path = root / '.env'
    text = path.read_text(encoding='utf-8-sig') if path.exists() else (root/'.env.hunyuan.example').read_text(encoding='utf-8')
    key = getpass.getpass('粘贴腾讯 TokenHub API Key（输入不显示，回车保存）：').strip()
    if not key or '\n' in key or '\r' in key:
        raise SystemExit('未填写有效密钥，配置未修改。')
    changes = {'PROVIDER':'hunyuan', 'HUNYUAN_API_KEY':json.dumps(key), 'HUNYUAN_MODEL':'hy-3d-3.1'}
    for name, value in changes.items():
        pattern = rf'(?m)^\s*{name}\s*=.*$'
        line = name + '=' + value
        if re.search(pattern,text): text = re.sub(pattern,lambda _:line,text)
        else: text = text.rstrip() + '\n' + line + '\n'
    path.write_text(text,encoding='utf-8')
    print('混元配置已保存到 backend/.env，密钥未显示。重启后端后即可手动上传测试。')


if __name__ == '__main__':
    main()
