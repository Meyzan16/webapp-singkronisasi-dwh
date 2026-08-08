# diag-futures.ps1 - pengawas harian agents FUTURES (fokus: agents/futures + risk).
# DETEKSI bug/anomali/kesalahan posisi + rem risiko -> lapor Telegram bila ada masalah.
# Guarded backend.pid. Perbaikan kode/logika trading TIDAK otomatis (sesi terawasi).

$ErrorActionPreference = 'Stop'
$Repo    = 'D:\kerja\Apps\workspace\agents-trading'
$PidFile = Join-Path $Repo 'ops\backend.pid'
$Notify  = Join-Path $Repo 'ops\send-telegram.ps1'
$Log     = Join-Path $Repo 'ops\logs\diag-futures.log'
if (-not (Test-Path $PidFile)) { return }

function Api($p) { try { Invoke-RestMethod "http://localhost:8000$p" -TimeoutSec 12 } catch { $null } }
function LogLine($m) { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Out-File $Log -Append -Encoding utf8 }
$issues = @()

$h = Api '/health'
if ($h) {
    if (-not $h.futures_scanner.running) { $issues += 'futures_scanner MATI' }
    if (-not $h.futures_monitor.running) { $issues += 'futures_monitor MATI' }
} else { $issues += '/health tak merespon' }

$ae = Api '/api/v1/signals/adaptive-engine/futures'
if ($ae) {
    if ($ae.engine_status -eq 'degraded') { $issues += 'engine FUTURES degraded' }
    $q = $ae.decision_ledger.quality
    foreach ($k in 'duplicate_keys','missing_snapshots','future_events','invalid_closes') {
        if ($q.$k -and [int]$q.$k -gt 0) { $issues += "ledger.$k = $($q.$k)" }
    }
}

# Rem risiko + kesalahan posisi (LONG: SL<entry; SHORT: SL>entry).
$risk = Api '/api/v1/futures/monitor/risk'
if ($risk) {
    $g = $risk.gate
    if ($g) {
        if ($g.active)                     { $issues += "risk-gate AKTIF ($($g.gate_type)): $($g.reason)" }
        if ($g.daily_gates.loss_breaker)   { $issues += 'daily LOSS-BREAKER aktif' }
        if ($g.daily_gates.giveback_stop)  { $issues += 'daily GIVEBACK-STOP aktif' }
    }
    if ($risk.portfolio -and [int]$risk.portfolio.at_risk_count -gt 0) {
        $issues += "$($risk.portfolio.at_risk_count) posisi AT-RISK"
    }
    foreach ($p in @($risk.positions)) {
        if ($p.entry -and $p.sl) {
            $e = [double]$p.entry; $s = [double]$p.sl
            if ($p.direction -eq 'LONG'  -and $s -ge $e) { $issues += "posisi $($p.symbol) LONG: SL>=entry (broken)" }
            if ($p.direction -eq 'SHORT' -and $s -le $e) { $issues += "posisi $($p.symbol) SHORT: SL<=entry (broken)" }
        }
        if ($p.liq_dist_pct -ne $null -and [double]$p.liq_dist_pct -lt 15) {
            $issues += "posisi $($p.symbol): dekat likuidasi ($([math]::Round([double]$p.liq_dist_pct,1))%)"
        }
    }
}

if ($issues.Count) {
    $ico = [char]::ConvertFromUtf32(0x1F9EA)
    & $Notify ("$ico DIAG FUTURES - $($issues.Count) masalah:`n- " + ($issues -join "`n- "))
    LogLine ("ISSUES: " + ($issues -join ' | '))
} else { LogLine 'OK' }
