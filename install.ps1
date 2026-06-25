$ErrorActionPreference = "Stop"

function Write-Info {
  param([string]$Message)
  Write-Host "[INFO] $Message"
}

function Write-Fail {
  param([string]$Message)
  Write-Error "[ERR] $Message"
}

$installerUrl = "https://raw.githubusercontent.com/umutkeltek/healthsave-observatory/main/install.sh"

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
  Write-Fail "HealthSave Observatory supports Windows through WSL2 today. Run 'wsl --install -d Ubuntu', install Docker Desktop, enable WSL integration, then rerun this installer."
  exit 1
}

$wslStatus = & wsl.exe --status 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Fail "WSL is installed but not ready. Run 'wsl --install -d Ubuntu', reboot if requested, then rerun this installer."
  exit 1
}

Write-Info "HealthSave Observatory uses WSL2 + Docker Desktop WSL integration on Windows."
Write-Info "Launching the Linux installer inside your default WSL distro."

$wslCommand = @"
set -eu
if ! command -v curl >/dev/null 2>&1; then
  echo '[ERR] curl is required inside WSL. Install it with your distro package manager, then rerun the installer.' >&2
  exit 1
fi
curl -fsSL '$installerUrl' | bash
"@

& wsl.exe sh -lc $wslCommand
exit $LASTEXITCODE
