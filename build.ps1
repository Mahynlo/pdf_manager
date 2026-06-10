# ============================================================
#  build.ps1  —  Compila Extraer PDFs y genera el instalador
#  Uso:  .\build.ps1
# ============================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$IssScript   = Join-Path $ProjectRoot "installer\setup.iss"
$DistDir     = Join-Path $ProjectRoot "dist"

# Rutas candidatas para el compilador de InnoSetup
$ISSCCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    "C:\Program Files\Inno Setup 6\ISCC.exe"
    "C:\Program Files (x86)\Inno Setup 5\ISCC.exe"
    "C:\Program Files\Inno Setup 5\ISCC.exe"
)

# ── 1. Compilar la app con Flet ───────────────────────────────────────────────
Write-Host ""
Write-Host "==> [1/2] Compilando con flet build windows ..." -ForegroundColor Cyan

Set-Location $ProjectRoot
uv run flet build windows -v
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: flet build windows fallo (codigo $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

# Verificar que el exe existe (ajustar ruta si el build la cambia)
$BuildOutput = Join-Path $ProjectRoot "build\windows\x64\runner\Release"
$ExePath     = Join-Path $BuildOutput "extraer_pdfs.exe"

if (-not (Test-Path $ExePath)) {
    # Busqueda de fallback en caso de nombre diferente
    $found = Get-ChildItem -Path (Join-Path $ProjectRoot "build\windows") -Filter "*.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) {
        Write-Host "Aviso: exe encontrado en $($found.FullName) (no en la ruta esperada)" -ForegroundColor Yellow
        $BuildOutput = $found.DirectoryName
        # Actualizar la definicion en el .iss temporalmente
        Write-Host "Usando ruta de build: $BuildOutput" -ForegroundColor Yellow
    } else {
        Write-Host "ERROR: no se encontro el exe en build\windows" -ForegroundColor Red
        exit 1
    }
}

Write-Host "Build OK: $BuildOutput" -ForegroundColor Green

# ── 1b. Compilar el launcher de "Abrir con" ───────────────────────────────────
# El exe de Flet no arranca si recibe argumentos (se queda en blanco); Windows
# invoca este launcher, que entrega la ruta por env var / socket IPC. Se compila
# dentro de $BuildOutput para que el [Files] del .iss lo copie al instalador.
Write-Host ""
Write-Host "==> [1b/2] Compilando launcher.exe (puente 'Abrir con') ..." -ForegroundColor Cyan

$LauncherSrc = Join-Path $ProjectRoot "launcher\launcher.c"
$LauncherRc  = Join-Path $ProjectRoot "launcher\launcher.rc"
$LauncherDir = Join-Path $ProjectRoot "launcher"
$LauncherOut = Join-Path $BuildOutput "launcher.exe"
$LauncherResObj = Join-Path $BuildOutput "launcher_res.o"

$gcc = (Get-Command gcc -ErrorAction SilentlyContinue).Source
if (-not $gcc -and (Test-Path "C:\TDM-GCC-64\bin\gcc.exe")) {
    $gcc = "C:\TDM-GCC-64\bin\gcc.exe"
}

if (-not $gcc) {
    Write-Host "ERROR: no se encontro gcc (mingw/TDM-GCC) para compilar el launcher." -ForegroundColor Red
    Write-Host "  Instala TDM-GCC o MinGW-w64 y vuelve a ejecutar, o compila a mano:" -ForegroundColor Yellow
    Write-Host "    gcc `"$LauncherSrc`" -o `"$LauncherOut`" -municode -static -mwindows -O2 -s -lws2_32 -lshell32" -ForegroundColor White
    exit 1
}

# Compilar el recurso de ícono (launcher.rc -> .o) con windres y enlazarlo, para
# que launcher.exe lleve el ícono de la app embebido y "Abrir con" no muestre el
# genérico. windres viene junto a gcc en MinGW/TDM-GCC; si por algún motivo no
# está, se compila SIN ícono (no se aborta el build por algo cosmético).
$windres = (Get-Command windres -ErrorAction SilentlyContinue).Source
if (-not $windres) {
    $windres = Join-Path (Split-Path $gcc) "windres.exe"
    if (-not (Test-Path $windres)) { $windres = $null }
}

$LauncherResArg = @()
if ($windres) {
    & $windres $LauncherRc -O coff --include-dir $LauncherDir -o $LauncherResObj
    if ($LASTEXITCODE -eq 0 -and (Test-Path $LauncherResObj)) {
        $LauncherResArg = @($LauncherResObj)
        Write-Host "Recurso de icono compilado: launcher_res.o" -ForegroundColor DarkGray
    } else {
        Write-Host "AVISO: windres fallo; launcher.exe se compilara sin icono." -ForegroundColor Yellow
    }
} else {
    Write-Host "AVISO: windres no encontrado; launcher.exe se compilara sin icono." -ForegroundColor Yellow
}

& $gcc $LauncherSrc @LauncherResArg -o $LauncherOut -municode -static -mwindows -O2 -s -lws2_32 -lshell32
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $LauncherOut)) {
    Write-Host "ERROR: fallo la compilacion del launcher (codigo $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

Write-Host "Launcher OK: $LauncherOut" -ForegroundColor Green

# ── 2. Generar el instalador con InnoSetup ────────────────────────────────────
Write-Host ""
Write-Host "==> [2/2] Generando instalador con InnoSetup ..." -ForegroundColor Cyan

$ISCC = $null
foreach ($candidate in $ISSCCandidates) {
    if (Test-Path $candidate) {
        $ISCC = $candidate
        break
    }
}

if (-not $ISCC) {
    Write-Host ""
    Write-Host "AVISO: InnoSetup no encontrado en rutas estandar." -ForegroundColor Yellow
    Write-Host "  Instala InnoSetup 6 desde https://jrsoftware.org/isinfo.php" -ForegroundColor Yellow
    Write-Host "  Luego ejecuta manualmente:" -ForegroundColor Yellow
    Write-Host "    ISCC.exe `"$IssScript`"" -ForegroundColor White
    exit 0
}

# Crear carpeta de salida si no existe
if (-not (Test-Path $DistDir)) {
    New-Item -ItemType Directory -Path $DistDir | Out-Null
}

& $ISCC "/DMyAppSourceDir=$BuildOutput" $IssScript
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: ISCC fallo (codigo $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Instalador generado en: $DistDir" -ForegroundColor Green
Get-ChildItem $DistDir -Filter "*.exe" | ForEach-Object {
    Write-Host "  $($_.Name)  ($([math]::Round($_.Length / 1MB, 1)) MB)" -ForegroundColor White
}
Write-Host ""
