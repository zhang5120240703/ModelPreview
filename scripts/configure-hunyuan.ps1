$ErrorActionPreference = 'Stop'
$backendFolder = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\backend'))
$pythonPath = Join-Path $backendFolder '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw '请先运行 scripts/start-backend.ps1 安装后端环境。'
}
& $pythonPath (Join-Path $backendFolder 'scripts\configure_hunyuan.py')
if ($LASTEXITCODE -ne 0) { throw '配置未完成。' }
