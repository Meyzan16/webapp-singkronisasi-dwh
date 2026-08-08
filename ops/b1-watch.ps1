# b1-watch.ps1 - pantau efek Fase B1 (expectancy_aware_weights) beberapa hari.
# Ukur 2 hal tiap hari lalu kirim ke Telegram:
#   1) apakah bobot FUTURES benar-benar MENYIMPANG (>1.0) setelah flag ON
#   2) apakah shadow@72 lift membaik vs baseline saat flag dinyalakan
# Baseline disimpan sekali di ops/b1-baseline.json (dibuat saat run pertama).
# Guarded backend.pid - diam saja kalau backend memang sedang tidak jalan.

$ErrorActionPreference = 'Continue'
$Repo     = 'D:\kerja\Apps\workspace\agents-trading'
$Base     = 'http://localhost:8000'
$Notify   = Join-Path $Repo 'ops\send-telegram.ps1'
$Baseline = Join-Path $Repo 'ops\b1-baseline.json'
$LogFile  = Join-Path $Repo 'ops\logs\b1-watch.log'
$PidFile  = Join-Path $Repo 'ops\backend.pid'

function Log($m) { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Out-File -FilePath $LogFile -Append -Encoding utf8 }
function Get-Api($p) { try { Invoke-RestMethod "$Base$p" -TimeoutSec 25 } catch { $null } }
function N($v,$d=3) { if ($null -eq $v) { '-' } else { [math]::Round([double]$v,$d) } }

# Backend harus hidup (jam agent aktif); kalau tidak, keluar diam-diam.
if (-not (Test-Path $PidFile)) { return }
$curPid = (Get-Content $PidFile -ErrorAction SilentlyContinue)
if (-not $curPid -or -not (Get-Process -Id $curPid -ErrorAction SilentlyContinue)) { return }

# --- Ambil metrik ---
$fut = Get-Api '/api/v1/signals/adaptive-engine/futures'
if (-not $fut) { Log 'endpoint futures tak merespon - skip'; return }

$sc   = $fut.shadow_compare
if (-not $sc -or $sc.status -ne 'ok') { Log "shadow_compare belum siap ($($sc.status)) - skip"; return }
$t72  = $sc.by_threshold | Where-Object { $_.threshold -eq 72 } | Select-Object -First 1
$lift = if ($t72) { [double]$t72.expectancy_lift_pct } else { $null }
$n    = [int]$sc.n

# Bobot: apakah sudah menyimpang ke atas? (bukti utama B1 bekerja).
# Tak ada endpoint distribusi bobot -> query DB langsung lewat venv backend.
$w = Get-Api '/api/v1/signals/updater/state'
$keys = if ($w -and $w.futures) { $w.futures.cached_keys } else { $null }
$maxW = $null; $above = $null
try {
    $py     = Join-Path $Repo 'backend\.venv\Scripts\python.exe'
    $script = Join-Path $Repo 'ops\b1_weight_stats.py'
    Push-Location (Join-Path $Repo 'backend')   # app.* hanya importable dari sini
    $out = & $py $script 2>$null | Select-String -Pattern '^\d+\|' | Select-Object -First 1
    Pop-Location
    if ($out) {
        $parts = "$out".ToString().Split('|')
        $above = $parts[1]; $maxW = $parts[2]
    } else { Log 'query bobot: output kosong' }
} catch { Log "query bobot gagal: $($_.Exception.Message)" }

# --- Baseline sekali ---
if (-not (Test-Path $Baseline)) {
    @{ created = (Get-Date).ToString('s'); lift = $lift; n = $n } |
        ConvertTo-Json | Out-File $Baseline -Encoding utf8
    Log "baseline dibuat: lift=$lift n=$n"
    & $Notify "$([char]::ConvertFromUtf32(0x1F9EA)) B1 WATCH dimulai`nBaseline shadow@72 lift = $(N $lift 4) (n=$n)`nFlag expectancy_aware_weights = ON`nLaporan harian menyusul."
    return
}

$b = Get-Content $Baseline -Raw | ConvertFrom-Json
$delta = if ($null -ne $lift -and $null -ne $b.lift) { $lift - [double]$b.lift } else { $null }
$days  = [math]::Round(((Get-Date) - [datetime]$b.created).TotalDays, 1)

# --- Vonis ---
$verdict = if ($null -eq $delta) { 'DATA BELUM CUKUP' }
           elseif ($delta -gt 0.05) { "MEMBAIK (+$(N $delta 4))" }
           elseif ($delta -lt -0.05) { "MEMBURUK ($(N $delta 4))" }
           else { "DATAR ($(N $delta 4))" }

$L = New-Object System.Collections.Generic.List[string]
$L.Add("$([char]::ConvertFromUtf32(0x1F9EA)) B1 WATCH - hari $days")
$L.Add("shadow@72 lift: $(N $lift 4)  (baseline $(N $b.lift 4))")
$L.Add("Vonis: $verdict")
$L.Add("sampel n=$n  |  bobot cached=$keys")
if ($null -ne $maxW) { $L.Add("bobot futures max=$(N $maxW 3)  >1.0: $above") }
$L.Add('')
$L.Add("Kalau MEMBURUK berhari-hari: matikan flag (value 0).")

$msg = ($L -join "`n")
& $Notify $msg
Log "lift=$lift baseline=$($b.lift) delta=$delta vonis=$verdict n=$n"
Write-Output $msg
