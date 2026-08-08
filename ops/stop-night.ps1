# stop-night.ps1 - matikan backend dengan rapi (agent ikut berhenti via lifespan).
# Dipanggil Windows Task Scheduler tiap Sel-Jum + Sen 07:00 WIB.
# Docker (postgres/redis) dibiarkan hidup - data aman, murah, restart otomatis.

$ErrorActionPreference = 'Stop'
$Repo    = 'D:\kerja\Apps\workspace\agents-trading'
$PidFile = Join-Path $Repo 'ops\backend.pid'
$RunLog  = Join-Path $Repo 'ops\logs\night-runner.log'

function Log($m) { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Tee-Object -FilePath $RunLog -Append }

Log "=== STOP-NIGHT dipicu ==="

if (-not (Test-Path $PidFile)) { Log "tidak ada backend.pid - mungkin sudah mati"; return }

# Kirim ringkasan pagi SELAGI backend masih hidup (endpoint masih bisa diquery)
try { & (Join-Path $Repo 'ops\report-telegram.ps1') 'Ringkasan Pagi' | Out-Null; Log "laporan pagi dikirim" }
catch { Log "laporan pagi gagal: $($_.Exception.Message)" }

$procId = Get-Content $PidFile -ErrorAction SilentlyContinue
if ($procId -and (Get-Process -Id $procId -ErrorAction SilentlyContinue)) {
    Stop-Process -Id $procId -Force
    Log "backend STOP (PID $procId)"
} else {
    Log "PID $procId sudah tidak aktif"
}
Remove-Item $PidFile -ErrorAction SilentlyContinue
