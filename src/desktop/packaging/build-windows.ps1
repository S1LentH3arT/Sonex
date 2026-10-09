param([Parameter(Mandatory = $true)][string]$PlayerDirectory)
$ErrorActionPreference = 'Stop'
$DesktopRoot = Split-Path $PSScriptRoot -Parent
$RepositoryRoot = (Resolve-Path (Join-Path $DesktopRoot '../..')).Path
$Python = Join-Path $RepositoryRoot '.venv/Scripts/python.exe'
$Resources = Join-Path $DesktopRoot 'src-tauri/resources'
if (!(Test-Path (Join-Path $PlayerDirectory 'mpv.exe'))) { throw 'PlayerDirectory must contain mpv.exe and its accompanying DLLs and license notices.' }
Push-Location $RepositoryRoot
try {
    & $Python -m PyInstaller --noconfirm --clean --onedir --name sonex-runtime --paths $RepositoryRoot --collect-submodules src.tools --collect-data src.tools.bead_catalog_data --collect-all yt_dlp --collect-submodules yt_dlp_plugins --distpath "$DesktopRoot/runtime-build/dist" --workpath "$DesktopRoot/runtime-build/work" --specpath "$DesktopRoot/runtime-build" "$PSScriptRoot/runtime_entry.py"
    if ($LASTEXITCODE -ne 0) { throw 'Runtime bundle failed.' }
    New-Item -ItemType Directory -Force "$Resources/runtime", "$Resources/player" | Out-Null
    Copy-Item "$DesktopRoot/runtime-build/dist/sonex-runtime/*" "$Resources/runtime/" -Recurse -Force
    Copy-Item "$PlayerDirectory/*" "$Resources/player/" -Recurse -Force
    Push-Location $DesktopRoot
    try {
        npm run tauri -- build --config src-tauri/tauri.release.conf.json
        if ($LASTEXITCODE -ne 0) { throw 'Desktop bundle failed.' }
    } finally { Pop-Location }
} finally { Pop-Location }
