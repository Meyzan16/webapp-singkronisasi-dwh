# report-telegram.ps1 - laporan kesehatan sistem MENYELURUH ke Telegram.
# Kumpulkan status dari banyak endpoint /api/v1, rangkum jadi 1 pesan.
# Dipakai: saat start (19:00), saat stop (07:00), atau manual.
#   & .\report-telegram.ps1            -> judul default "Laporan Sistem"
#   & .\report-telegram.ps1 "Startup"  -> judul kustom

param([string]$Title = 'Laporan Sistem')

$ErrorActionPreference = 'Continue'
$Repo   = 'D:\kerja\Apps\workspace\agents-trading'
$Base   = 'http://localhost:8000'
$Notify = Join-Path $Repo 'ops\send-telegram.ps1'

function Get-Api($p) { try { Invoke-RestMethod "$Base$p" -TimeoutSec 20 } catch { $null } }
function E($cp)      { [char]::ConvertFromUtf32($cp) }        # emoji dari codepoint (file tetap ASCII)
function Dot($ok)    { if ($ok) { E 0x1F7E2 } else { E 0x1F534 } }   # hijau / merah
function N($v,$d=2)  { if ($null -eq $v) { '-' } else { [math]::Round([double]$v,$d) } }

$OK=E 0x2705; $BAD=E 0x274C; $WARN=E 0x26A0
$L = New-Object System.Collections.Generic.List[string]
$stamp = (Get-Date).ToString('ddd dd MMM HH:mm')

$L.Add("$(E 0x1F4CA) AGENTS-TRADING - $Title")
$L.Add("$stamp WIB")
$L.Add('')

# 1) SYSTEM HEALTH
$h = Get-Api '/health'
if ($h) {
    $L.Add("$(E 0x1F5A5) SISTEM")
    $L.Add("  $(Dot ($h.db -eq 'ok')) Database")
    $L.Add("  $(Dot $h.spot_scanner.running) Spot Scanner   $(Dot $h.spot_monitor.running) Spot Monitor")
    $L.Add("  $(Dot $h.futures_scanner.running) Futures Scanner $(Dot $h.futures_monitor.running) Futures Monitor")
} else {
    $L.Add("$BAD SISTEM: /health tidak merespon")
}
$L.Add('')

# 2) BINANCE
$b = Get-Api '/api/v1/market/binance-status'
if ($b) {
    $L.Add("$(E 0x1F4E1) BINANCE")
    $L.Add("  $(Dot $b.spot_ok) Spot  $(N $b.spot_latency_ms 0)ms  wt $(N $b.spot_weight_pct 0)%")
    $L.Add("  $(Dot $b.futures_ok) Futures  $(N $b.futures_latency_ms 0)ms  wt $(N $b.futures_weight_pct 0)%")
    if ($b.spot_banned_until -or $b.futures_banned_until) { $L.Add("  $WARN ADA BAN AKTIF - cek rate limit") }
}
$L.Add('')

# 2b) MARKET REGIME / KONDISI PASAR
$mc = Get-Api '/api/v1/market/context'
if ($mc) {
    $L.Add("$(E 0x1F310) MARKET")
    $L.Add("  Sentimen: $($mc.sentiment)   BTC $(N $mc.btc_price 0)`$ ($(N $mc.btc_change_24h 1)%)")
    $L.Add("  Breadth: $(N $mc.pct_green 0)% hijau / $(N $mc.pct_red 0)% merah   top50 avg $(N $mc.avg_change_top50 1)%")
    $L.Add("  Ekstrem 24j: $(N $mc.coins_up_10pct 0) naik>10% / $(N $mc.coins_down_10pct 0) turun>10%")
    $L.Add("  Funding BTC $(N $mc.btc_funding 3)% ($($mc.fr_sentiment))")
    $L.Add('')
}

# 3) SCANNER
$opp = Get-Api '/api/v1/opportunity/status'
$fut = Get-Api '/api/v1/futures/status'
$L.Add("$(E 0x1F50D) SCANNER")
if ($opp) { $L.Add("  Spot: siklus $($opp.cycle_count), scan berikut ~$(N $opp.next_scan_in_min 1)m") }
if ($fut) { $L.Add("  Futures: siklus $($fut.cycle_count), hasil a1/a2/a3 = $($fut.agent1_results)/$($fut.agent2_results)/$($fut.agent3_results)") }
$L.Add('')

# 4) AUTO-TRADER (futures)
$auto = Get-Api '/api/v1/futures/auto/status'
if ($auto) {
    $L.Add("$(E 0x1F916) AUTO-TRADER FUTURES")
    $L.Add("  $(Dot $auto.enabled) $(if($auto.enabled){'AKTIF'}else{'MATI'})  ambang $($auto.threshold)  maks posisi $($auto.max_positions)")
    $L.Add('')
}

# 5) POSISI TERBUKA + RISK
$risk = Get-Api '/api/v1/futures/monitor/risk'
$balS = Get-Api '/api/v1/balance/opportunity_spot'
$spotOpen = if ($balS) { $balS.open_positions } else { '?' }
$futOpen  = if ($risk) { $risk.portfolio.open_count } else { '?' }
$L.Add("$(E 0x1F4C8) POSISI TERBUKA")
$L.Add("  Spot: $spotOpen   Futures: $futOpen")
if ($risk -and $risk.positions) {
    foreach ($p in $risk.positions) {
        $L.Add("   - $($p.symbol) $($p.direction) [$($p.agent)] uPnL $(N $p.upnl_dollar)$ ($(N $p.roi_pct 1)%)")
    }
}
$L.Add('')

# 6) RISK GATE
if ($risk -and $risk.gate) {
    $g = $risk.gate
    $L.Add("$(E 0x1F6E1) RISK")
    $L.Add("  $(Dot (-not $g.active)) Gate: $(if($g.active){"AKTIF ($($g.gate_type)) - $($g.reason)"}else{'normal'})")
    $L.Add("  Drawdown $(N $g.drawdown_pct 1)%  PnL harian $(N $g.daily_gates.day_pnl)$")
    $flags = @()
    if ($g.daily_gates.loss_breaker) { $flags += 'LOSS-BREAKER' }
    if ($g.daily_gates.profit_lock)  { $flags += 'PROFIT-LOCK' }
    if ($g.daily_gates.giveback_stop){ $flags += 'GIVEBACK-STOP' }
    if ($flags.Count) { $L.Add("  $WARN Rem harian: $($flags -join ', ')") }
    $paused = @()
    if ($g.lane_pauses) { foreach ($ln in $g.lane_pauses.PSObject.Properties) { if ($ln.Value.paused) { $paused += $ln.Name } } }
    if ($paused.Count) { $L.Add("  $WARN Lane paused: $($paused -join ', ')") }
    $L.Add('')
}

# 7) PERFORMA
$st = Get-Api '/api/v1/history/stats'
if ($st -and $st.overall) {
    $o = $st.overall
    $L.Add("$(E 0x1F3AF) PERFORMA (semua waktu)")
    $L.Add("  Win rate $(N $o.win_rate 1)%  ($($o.wins)W/$($o.losses)L dari $($o.closed) closed)")
    $L.Add("  Terbuka $($o.open)  avg PnL $(N $o.avg_pnl)%")
}
$daily = Get-Api '/api/v1/history/daily-pnl'
if ($daily -and $daily.daily) {
    $today = (Get-Date).ToString('yyyy-MM-dd')
    $td = $daily.daily | Where-Object { $_.date -eq $today }
    if ($td) { $L.Add("  Hari ini: PnL $(N $td.pnl)$  ($($td.wins)W/$($td.losses)L, $($td.trades) trade)") }
}
$L.Add('')

# 8) BALANCE
$L.Add("$(E 0x1F4B0) BALANCE")
if ($balS) { $L.Add("  Spot: $(N $balS.balance)$  (realized $(N $balS.realized_pnl)$)") }
if ($risk -and $risk.portfolio) {
    $pf = $risk.portfolio
    $L.Add("  Futures: $(N $pf.current_balance)$  (closed $(N $pf.total_closed_pnl)$)")
}

# 9) ADAPTIVE ENGINE (learning yang mengangkat scanner)
function GatesPassed($g) {
    if (-not $g) { return '?/?' }
    $p = 0; $n = 0
    foreach ($k in $g.PSObject.Properties) { $n++; if ($k.Value) { $p++ } }
    "$p/$n"
}
$ae  = Get-Api '/api/v1/signals/adaptive-engine'
$aef = Get-Api '/api/v1/signals/adaptive-engine/futures'
$L.Add('')
$L.Add("$(E 0x1F9E0) ADAPTIVE ENGINE")
if ($ae) {
    $L.Add("  SPOT: $($ae.engine_status)  train $(N $ae.training.progress_pct 0)%  outcome $(N $ae.decision_ledger.outcome_completeness_pct 0)%  gates $(GatesPassed $ae.gates)")
} else { $L.Add("  SPOT: (tak terbaca)") }
if ($aef) {
    $L.Add("  FUTURES: $($aef.engine_status)/$($aef.learning_status)  train $(N $aef.training.progress_pct 0)%  outcome $(N $aef.decision_ledger.outcome_completeness_pct 0)%  gates $(GatesPassed $aef.gates)")
    # Fase 1 shadow-compare @thr72: apakah adaptive_score membaik vs raw (read-only)
    $sc = $aef.shadow_compare
    if ($sc -and $sc.status -eq 'ok') {
        $t = $sc.by_threshold | Where-Object { $_.threshold -eq 72 } | Select-Object -First 1
        if ($t) { $L.Add("   shadow@72: lift $(N $t.expectancy_lift_pct 3)% | veto-slice exp $(N $t.vetoed_slice.expectancy_pct 2)% (n$($t.vetoed_slice.n)) | data n$($sc.n)") }
        $bd = $sc.by_direction_eligible
        if ($bd) { $L.Add("   arah(70-80): LONG exp $(N $bd.LONG.expectancy_pct 2)% (n$($bd.LONG.n)) | SHORT exp $(N $bd.SHORT.expectancy_pct 2)% (n$($bd.SHORT.n))") }
    } elseif ($sc) { $L.Add("   shadow: $($sc.status)") }
} else { $L.Add("  FUTURES: (tak terbaca)") }

# 10) BOBOT ADAPTIF (weight_updater — tuning bobot sinyal per-agent per-regime)
$us = Get-Api '/api/v1/signals/updater/state'
if ($us) {
    $L.Add('')
    $L.Add("$(E 0x2696) BOBOT ADAPTIF")
    foreach ($scope in 'spot','futures') {
        $u = $us.$scope
        if ($u -and ($u.cached_keys -or $u.cached_agents)) {
            $nAgents = if ($u.cached_agents) { @($u.cached_agents).Count } else { 0 }
            $nBlack  = if ($u.blacklisted_coins) { @($u.blacklisted_coins).Count } else { 0 }
            $blackTxt = if ($nBlack -gt 0) { "  $WARN blacklist $nBlack ($($u.blacklisted_coins -join ', '))" } else { '' }
            $errTxt   = if ($u.last_error) { "  $BAD $($u.last_error)" } else { '' }
            $name = if ($scope -eq 'spot') { 'SPOT' } else { 'FUTURES' }
            # SPOT memuat bobot langsung dari DB tiap scan (tak ada cache per-agen),
            # jadi "/ N agen" hanya bermakna untuk FUTURES.
            $agentTxt = if ($nAgents -gt 0) { " / $nAgents agen" } else { '' }
            $L.Add("  ${name}: $(N $u.cached_keys 0) bobot$agentTxt$blackTxt$errTxt")
        }
    }
    if ($us.cross -and $us.cross.pairs) {
        $L.Add("  Cross-agent: $(N $us.cross.pairs 0) pasangan blended")
    }
}

# --- Kirim ---
$msg = ($L -join "`n")
& $Notify $msg
Write-Output $msg
