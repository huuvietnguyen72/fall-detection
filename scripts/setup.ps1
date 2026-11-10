# Cài đặt một lệnh cho Windows (PowerShell):   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# Tạo .venv, cài thư viện Python, tạo .env từ mẫu, tải sẵn model MediaPipe, kiểm tra Mosquitto.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$env:PYTHONUTF8 = "1"

# Dùng "py -3" (Python Launcher) nếu có, không thì "python"
function Invoke-BasePython { if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 @args } else { & python @args } }
Invoke-BasePython -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { Write-Host "Can Python >= 3.10: https://www.python.org/downloads/ (tick 'Add python.exe to PATH')"; exit 1 }

Write-Host "==> Tao moi truong ao .venv"
if (-not (Test-Path .venv)) { Invoke-BasePython -m venv .venv }
$vpy = ".venv\Scripts\python.exe"
& $vpy -m pip install -q --upgrade pip
Write-Host "==> Cai thu vien (lan dau mat vai phut)"
& $vpy -m pip install -q -r requirements.txt

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "==> Da tao .env tu .env.example (mo ra dien Telegram, camera neu can)"
}

Write-Host "==> Tai model MediaPipe Pose"
& $vpy -c "from vision.backends import MediaPipeBackend; MediaPipeBackend()" | Out-Null

if ((Get-Command mosquitto -ErrorAction SilentlyContinue) -or (Test-Path "C:\Program Files\mosquitto\mosquitto.exe")) {
    Write-Host "==> Mosquitto: OK"
} else {
    Write-Host "!!  Chua co Mosquitto: tai ban Windows tai https://mosquitto.org/download/ va cai mac dinh"
}

Write-Host "==> Chay kiem thu"
& $vpy -m pytest -q 2>&1 | Select-Object -Last 1

Write-Host ""
Write-Host "Xong. Chay he thong:"
Write-Host "    .venv\Scripts\python run.py                 # broker + server + camera + dashboard"
Write-Host "    .venv\Scripts\python run.py --camera-sim    # chua co webcam: camera gia lap"
