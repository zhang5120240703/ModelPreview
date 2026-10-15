param([string]$BindAddress = '127.0.0.1', [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..\backend')
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '需要 Python 3.12，请先安装或手动创建 backend/.venv 虚拟环境。' }
    & .venv\Scripts\python.exe -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络后重试。' }
}
& .venv\Scripts\python.exe -m uvicorn app.main:app --host $BindAddress --port $Port --workers 1
