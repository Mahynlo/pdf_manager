# ============================================================
#  installer\web\build.ps1  —  Empaqueta la versión web y genera su instalador
#  Uso (desde la raíz del proyecto):  .\installer\web\build.ps1 [-SkipInstaller] [-Version x.y.z-web]
#  La versión es APP_VERSION de app\__init__.py (pyproject.toml lleva la de Flet).
#
#  1. pnpm compila la interfaz (app\ui → app\ui\dist). Hace falta Node.js y pnpm.
#  2. PyInstaller (sin añadirlo al proyecto: uv run --with pyinstaller) genera
#     dist\web\ExtraerPDFs\ con ExtraerPDFs.exe y sus recursos.
#  3. Inno Setup compila installer\web\setup.iss → dist\ExtraerPDFs_Web_Setup_<versión>.exe
#
#  No hace falta el launcher de «Abrir con» de la versión Flet: el exe acepta las
#  rutas como argumentos y, si ya hay una ventana abierta, se las pasa (app/single_instance.py).
# ============================================================
param([switch]$SkipInstaller, [string]$Version = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root    = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Name    = "ExtraerPDFs"
$DistDir = Join-Path $Root "dist\web"
$WorkDir = Join-Path $Root "build\pyinstaller-web"
if (-not $Version) {
    $Version = (Select-String -Path (Join-Path $Root "app\__init__.py") -Pattern '^APP_VERSION\s*=\s*"(.+)"').Matches[0].Groups[1].Value
}

Set-Location $Root

# Recursos que se leen en tiempo de ejecución, con la ruta que esperan dentro del paquete
# (app.PROJECT_ROOT es la carpeta _internal del exe; ver docs\web\instalador.md).
# Origen absoluto: PyInstaller resuelve las rutas relativas desde --specpath.
$Data = @(
    "app\ui\dist;app\ui\dist",
    "src\assets\ayuda;src\assets\ayuda",
    "src\assets\ayuda_img;src\assets\ayuda_img",
    "src\assets\ayuda_svg;src\assets\ayuda_svg",
    "src\assets\ocr_models;assets\ocr_models"
)
$DataArgs = $Data | ForEach-Object { "--add-data"; "$Root\$_" }

Write-Host ""
Write-Host "==> [1/3] Interfaz (pnpm build en app\ui) ..." -ForegroundColor Cyan
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: falta pnpm (https://pnpm.io/installation); hace falta para compilar la interfaz." -ForegroundColor Red
    exit 1
}
Push-Location (Join-Path $Root "app\ui")
try {
    pnpm install --frozen-lockfile
    if ($LASTEXITCODE -eq 0) { pnpm build }
} finally {
    Pop-Location
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: no se pudo compilar la interfaz (código $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "==> [2/3] PyInstaller ($Name $Version) ..." -ForegroundColor Cyan
uv run --with pyinstaller pyinstaller `
    --noconfirm --clean --windowed `
    --name $Name `
    --icon "$Root\launcher\app.ico" `
    --paths "$Root" --paths "$Root\src" `
    --distpath $DistDir --workpath $WorkDir --specpath $WorkDir `
    --collect-submodules pdf_core `
    --collect-data markdown_it `
    @DataArgs `
    "$Root\app\main.py"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: PyInstaller falló (código $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}
$AppDir = Join-Path $DistDir $Name
if (-not (Test-Path (Join-Path $AppDir "$Name.exe"))) {
    Write-Host "ERROR: no se generó $Name.exe" -ForegroundColor Red
    exit 1
}
Write-Host "Ejecutable: $AppDir\$Name.exe" -ForegroundColor Green
if ($SkipInstaller) { exit 0 }

Write-Host ""
Write-Host "==> [3/3] Inno Setup ..." -ForegroundColor Cyan
$ISCC = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $ISCC) {
    Write-Host "AVISO: Inno Setup 6 no está instalado (https://jrsoftware.org/isinfo.php)." -ForegroundColor Yellow
    Write-Host "  Después ejecuta: ISCC.exe /DMyAppVersion=$Version /DMyAppSourceDir=`"$AppDir`" installer\web\setup.iss" -ForegroundColor White
    exit 0
}
& $ISCC "/DMyAppVersion=$Version" "/DMyAppSourceDir=$AppDir" (Join-Path $PSScriptRoot "setup.iss")
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: ISCC falló (código $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}
Write-Host "Instalador generado en dist\" -ForegroundColor Green
