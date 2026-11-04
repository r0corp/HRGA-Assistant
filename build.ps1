# Build HRGA WA Report.exe (satu file, tanpa jendela console) dan installer-nya ke folder dist\.
# Browser tidak ikut dibundel: app memakai Microsoft Edge bawaan Windows.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

.\venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Test gagal, build dibatalkan." }

.\venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed `
    --name "HRGA WA Report" `
    --collect-data playwright `
    --collect-data sv_ttk `
    --collect-data holidays `
    --collect-submodules holidays `
    --add-data "assets;assets" `
    --icon "assets\icon.ico" `
    app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller gagal." }

# Installer dibuat kalau Inno Setup 6 terpasang.
$version = (.\venv\Scripts\python.exe -c "from core.updater import VERSION; print(VERSION)").Trim()
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($iscc) {
    .\venv\Scripts\python.exe installer\make_images.py
    & $iscc "/DAppVersion=$version" installer\setup.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup gagal." }
} else {
    Write-Warning "Inno Setup 6 tidak ditemukan; installer tidak dibuat."
}

Write-Host "Selesai versi $version di $PSScriptRoot\dist"
