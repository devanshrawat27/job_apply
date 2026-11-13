# JobPilot backend watchdog.
# Runs uvicorn in a loop so the API comes back automatically if it ever exits.
# Started detached (via WMI) so it is not tied to any terminal or editor session.

$ErrorActionPreference = "SilentlyContinue"
$backend = "D:\CODING\twitterJobAppyly\job_apply\backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"
$log = Join-Path $backend "uvicorn.log"
$errlog = Join-Path $backend "uvicorn.log.err"

Set-Location $backend

while ($true) {
    "[$(Get-Date -Format o)] watchdog: starting backend" | Out-File -FilePath $errlog -Append -Encoding utf8
    & $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 1>> $log 2>> $errlog
    "[$(Get-Date -Format o)] watchdog: backend exited ($LASTEXITCODE), restarting in 5s" | Out-File -FilePath $errlog -Append -Encoding utf8
    Start-Sleep -Seconds 5
}
