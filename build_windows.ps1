$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$sitePackages = Join-Path $PSScriptRoot ".venv\Lib\site-packages"
$vipsDll = Get-ChildItem -LiteralPath $sitePackages -File -Filter "libvips-42-*.dll" | Select-Object -First 1
if (-not $vipsDll) { throw "libvips DLL not found. Install requirements-dev.txt first." }

Push-Location $PSScriptRoot
try {
    $env:FLOWER_SEARCH_VIPS_DLL = $vipsDll.FullName
    & $python -m PyInstaller --noconfirm --clean FlowerSearch.spec
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Remove-Item Env:\FLOWER_SEARCH_VIPS_DLL -ErrorAction SilentlyContinue
    Pop-Location
}
