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

& $ISCC $IssScript
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
