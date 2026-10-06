param([switch]$Dev)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Run-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Falló la instalación; revisa el mensaje anterior." }
}

$CounterPython = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $CounterPython)) {
    if (Test-Path ".venv") { throw "El entorno .venv está incompleto. Renómbralo y vuelve a ejecutar el instalador." }
    Run-Checked -Program "py" -Arguments @("-3.11", "-I", "-m", "venv", ".venv")
}
Run-Checked -Program $CounterPython -Arguments @("-I", "-c", "import sys, encodings; assert sys.version_info >= (3, 11), 'Se requiere Python 3.11 o superior'")
Run-Checked -Program $CounterPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
Run-Checked -Program $CounterPython -Arguments @("-m", "pip", "install", "torch", "torchvision", "--index-url", "https://download.pytorch.org/whl/cpu")
Run-Checked -Program $CounterPython -Arguments @("-m", "pip", "install", "-r", "requirements-windows.txt")
if ($Dev) { Run-Checked -Program $CounterPython -Arguments @("-m", "pip", "install", "-r", "requirements-dev.txt") }
if (-not (Test-Path "config.yaml")) { Copy-Item "config.example.yaml" "config.yaml" }
Run-Checked -Program $CounterPython -Arguments @("scripts/download_face_models.py")
Run-Checked -Program $CounterPython -Arguments @("scripts/check_body_model.py")
Write-Host "Listo. Prueba sin cámara: .\.venv\Scripts\python.exe main.py --simulate"
Write-Host "Para usar YOLO con cámara real: .\.venv\Scripts\python.exe scripts\download_model.py"
