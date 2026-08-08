# diag-spot.ps1 - pengawas harian agents SPOT (fokus: agents/opportunity + model spot).
# DETEKSI bug/anomali/kesalahan posisi -> lapor Telegram HANYA bila ada masalah
# (senyap saat sehat). Guarded backend.pid (jalan hanya saat agents aktif).
# Perbaikan kode/logika trading TIDAK otomatis - ini surfacing untuk sesi terawasi.

$ErrorActionPreference = 'Stop'
$Repo    = 'D:\kerja\Apps\workspace\agents-trading'
$PidFile = Join-Path $Repo 'ops\backend.pid'
$Notify  = Join-Path $Repo 'ops\send-telegram.ps1'
$Log     = Join-Path $Repo 'ops\logs\diag-spot.log'
if (-not (Test-Path $PidFile)) { return }   # agents tak aktif -> keluar diam

function Api($p) { try { Invoke-RestMethod "http://localhost:8000$p" -TimeoutSec 12 } catch { $null } }
function LogLine($m) { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Out-File $Log -Append -Encoding utf8 }
$issues = @()

$h = Api '/health'
if ($h) {
    if (-not $h.spot_scanner.running) { $issues += 'spot_scanner MATI' }
    if (-not $h.spot_monitor.running) { $issues += 'spot_monitor MATI' }
    if ($h.db -ne 'ok')               { $issues += 'DB tak tersedia' }
} else { $issues += '/health tak merespon' }

$ae = Api '/api/v1/signals/adaptive-engine'
if ($ae) {
    if ($ae.engine_status -eq 'degraded') { $issues += 'engine SPOT degraded' }
    $q = $ae.decision_ledger.quality
    foreach ($k in 'duplicate_keys','missing_snapshots','future_events','invalid_closes') {
        if ($q.$k -and [int]$q.$k -gt 0) { $issues += "ledger.$k = $($q.$k)" }
    }
    $oc = $ae.decision_ledger.outcome_completeness_pct
    if ($oc -ne $null -and [double]$oc -lt 50) { $issues += "outcome_completeness rendah $oc%" }
}

# Kesalahan posisi SPOT (long-only): valid = SL < entry < TP1, dan wajib ada SL.
$pos = Api '/api/v1/opportunity/positions'
if ($pos -and $pos.positions) {
    $open = @($pos.positions | Where-Object { -not $_.closed_at -and $_.status -notin @('sl','tp','tp1','tp2','tp3','closed') })
    foreach ($p in $open) {
        if ($p.entry) {
            if ($p.sl -and [double]$p.sl -ge [double]$p.entry)  { $issues += "posisi $($p.symbol): SL>=entry (broken)" }
            if ($p.tp1 -and [double]$p.tp1 -le [double]$p.entry){ $issues += "posisi $($p.symbol): TP1<=entry (broken)" }
            if (-not $p.sl)                                     { $issues += "posisi $($p.symbol): TANPA SL" }
        }
    }
}

if ($issues.Count) {
    $ico = [char]::ConvertFromUtf32(0x1F9EA)
    & $Notify ("$ico DIAG SPOT - $($issues.Count) masalah:`n- " + ($issues -join "`n- "))
    LogLine ("ISSUES: " + ($issues -join ' | '))
} else { LogLine 'OK' }
