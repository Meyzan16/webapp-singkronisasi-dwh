# stop-night.ps1 - matikan backend dengan rapi (agent ikut berhenti via lifespan).
# Dipanggil Windows Task Scheduler tiap Sel-Jum + Sen 07:00 WIB.
# Docker (postgres/redis) dibiarkan hidup - data aman, murah, restart otomatis.

$ErrorActionPreference = 'Stop'
$Repo    = 'D:\kerja\Apps\workspace\agents-trading'
$PidFile = Join-Path $Repo 'ops\backend.pid'
$LearnPidFile = Join-Path $Repo 'ops\learning.pid'
$FePidFile = Join-Path (Join-Path $Repo 'ops') 'frontend.pid'
$RunLog  = Join-Path $Repo 'ops\logs\night-runner.log'

function Log($m) { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Tee-Object -FilePath $RunLog -Append }

Log "=== STOP-NIGHT dipicu ==="

# Proses pembelajaran dimatikan LEBIH DULU dan TANPA bergantung pada backend.pid:
# ia proses terpisah, jadi keluar-awal di bawah tak boleh meninggalkannya hidup
# sendirian tanpa backend.
if (Test-Path $LearnPidFile) {
    $lpid = Get-Content $LearnPidFile -ErrorAction SilentlyContinue
    if ($lpid -and (Get-Process -Id $lpid -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $lpid -Force
        Log "learning STOP (PID $lpid)"
    } else {
        Log "learning PID $lpid sudah tidak aktif"
    }
    Remove-Item $LearnPidFile -ErrorAction SilentlyContinue
}

# Frontend (cmd -> node): bunuh pohon prosesnya, bukan hanya cmd induknya.
if (Test-Path $FePidFile) {
    $fpid = Get-Content $FePidFile -ErrorAction SilentlyContinue
    if ($fpid -and (Get-Process -Id $fpid -ErrorAction SilentlyContinue)) {
        try { Start-Process taskkill -ArgumentList '/PID', $fpid, '/T', '/F' -WindowStyle Hidden -Wait } catch {}
        Log "frontend STOP (PID $fpid)"
    } else {
        Log "frontend PID $fpid sudah tidak aktif"
    }
    Remove-Item $FePidFile -Force -ErrorAction SilentlyContinue
}

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
