[CmdletBinding()]
param(
    [string]$OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $projectRoot 'dist'
}

$python = Join-Path $projectRoot '.venv_m3\Scripts\python.exe'
$entry = Join-Path $projectRoot 'deskpet2d.py'
$exePath = Join-Path $OutputDirectory '线条小狗桌宠.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw "未找到打包环境：$python"
}
if (Get-Process -Name '线条小狗桌宠' -ErrorAction SilentlyContinue) {
    throw '请先退出正在运行的桌宠，再生成正式 EXE。'
}

$pythonBase = (& $python -c 'import sys; print(sys.base_prefix)').Trim()
$tclLibrary = Join-Path $pythonBase 'tcl\tcl8.6'
$tkLibrary = Join-Path (Split-Path $tclLibrary -Parent) 'tk8.6'
if (-not (Test-Path -LiteralPath $tclLibrary) -or -not (Test-Path -LiteralPath $tkLibrary)) {
    throw '未找到 Python 自带的 Tcl/Tk 运行库。'
}

$temporary = Join-Path ([IO.Path]::GetTempPath()) ("LineDogDeskPetBuild-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temporary | Out-Null
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

try {
    $arguments = @(
        '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
        '--name', '线条小狗桌宠',
        '--runtime-hook', (Join-Path $projectRoot 'tools\pyinstaller_tk_runtime.py'),
        '--add-data', ((Join-Path $projectRoot 'action_manifest.json') + ';.'),
        '--add-data', ((Join-Path $projectRoot 'assets\runtime') + ';assets\runtime'),
        '--add-data', ($tclLibrary + ';tcl_runtime\tcl8.6'),
        '--add-data', ($tkLibrary + ';tcl_runtime\tk8.6'),
        '--exclude-module', 'pkg_resources', '--exclude-module', 'setuptools',
        '--exclude-module', 'OpenGL', '--exclude-module', 'numpy',
        '--distpath', $OutputDirectory, '--workpath', $temporary,
        '--specpath', $temporary, $entry
    )
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 打包失败，退出码：$LASTEXITCODE"
    }
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw '打包完成但未找到 EXE。'
    }
    Get-Item -LiteralPath $exePath | Select-Object FullName, Length, LastWriteTime
}
finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
}
