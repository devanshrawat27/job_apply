# JobPilot frontend watchdog.
# Runs the production Next.js server in a loop so the UI comes back automatically.
# Started detached (via WMI) so it is not tied to any terminal or editor session.

$ErrorActionPreference = "SilentlyContinue"
$frontend = "D:\CODING\twitterJobAppyly\job_apply\frontend"
$node = "C:\Program Files\nodejs\node.exe"
$next = Join-Path $frontend "node_modules\next\dist\bin\next"
$log = Join-Path $frontend "frontend.log"
$errlog = Join-Path $frontend "frontend.log.err"

Set-Location $frontend

while ($true) {
    "[$(Get-Date -Format o)] watchdog: starting frontend" | Out-File -FilePath $errlog -Append -Encoding utf8
    & $node $next start -p 3000 1>> $log 2>> $errlog
    "[$(Get-Date -Format o)] watchdog: frontend exited ($LASTEXITCODE), restarting in 5s" | Out-File -FilePath $errlog -Append -Encoding utf8
    Start-Sleep -Seconds 5
}
