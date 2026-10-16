"""Configure GitHub publishing locally; never upload photos or print a token."""
import getpass
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.github_publisher import validate_target


def main():
    path=ROOT/'.env'
    text=path.read_text(encoding='utf-8-sig') if path.exists() else (ROOT/'.env.example').read_text(encoding='utf-8')
    current=Settings(_env_file=path if path.exists() else None)
    repo=current.github_repository
    if not repo:
        result=subprocess.run(['git','config','--get','remote.origin.url'],cwd=ROOT.parent,capture_output=True,text=True)
        match=re.search(r'github\.com[/:]([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?$',result.stdout.strip())
        if match:repo=match.group(1)+'/'+match.group(2)
    repo=input(f'公开照片仓库（用户名/仓库名）[{repo}]：').strip() or repo
    if not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+',repo):raise SystemExit('仓库名称无效，配置未修改。')
    owner,name=repo.split('/')
    default_base=current.github_pages_base_url or f'https://{owner.lower()}.github.io'+('' if name.lower()==owner.lower()+'.github.io' else '/'+name)
    base=input(f'Pages 网站根地址 [{default_base}]：').strip() or default_base
    branch=input(f'Pages 发布分支 [{current.github_branch}]：').strip() or current.github_branch
    prefix=input(f'仓库内图片目录 [{current.github_upload_path}]：').strip() or current.github_upload_path
    try:validate_target({'repository':repo,'pages_base_url':base,'branch':branch,'upload_path':prefix})
    except ValueError as exc:raise SystemExit(str(exc)+'，配置未修改。') from None
    token=getpass.getpass('粘贴 GitHub Token（仅所选仓库 Contents 读写权限；输入不显示）：').strip()
    if not token or any(c.isspace() for c in token):raise SystemExit('未填写有效 Token，配置未修改。')
    changes={'GITHUB_UPLOAD_ENABLED':'true','GITHUB_TOKEN':json.dumps(token),'GITHUB_REPOSITORY':json.dumps(repo),
             'GITHUB_BRANCH':json.dumps(branch),'GITHUB_PAGES_BASE_URL':json.dumps(base.rstrip('/')),
             'GITHUB_UPLOAD_PATH':json.dumps(prefix.strip('/'))}
    for name,value in changes.items():
        pattern=rf'(?m)^[ \t]*{name}[ \t]*=.*$'
        line=name+'='+value
        if re.search(pattern,text):text=re.sub(pattern,lambda _:line,text)
        else:text=text.rstrip()+'\n'+line+'\n'
    path.write_text(text,encoding='utf-8')
    print('GitHub 自动上传配置已保存，原混元 Key 保留，Token 未显示。')
    print('重启后端后，从电脑选图并开始任务即可。照片会公开发布到所选仓库；本次配置没有上传或生成。')


if __name__=='__main__':main()
