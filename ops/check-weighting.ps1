# check-weighting.ps1 - apakah adaptive weighting benar-benar BEKERJA, bukan sekadar
# tersimpan? Satu perintah, jawaban berbasis bukti.
#
# Latar (audit 8 Agu 2026): "bobot tersimpan di DB" TIDAK sama dengan "bobot
# mempengaruhi keputusan". Riwayat proyek ini penuh kasus di mana keduanya
# terputus tanpa satu pun error muncul:
#   - 49/49 bobot canonical futures terkunci 1.0 karena namespace kunci tak
#     beririsan antara penulis dan pembaca (29 Jul)
#   - monitor_config.refresh() dipanggil tiap siklus tapi nilainya tak pernah
#     dibaca monitor (M2, 1 Agu)
#   - baris bobot dua lane saling menimpa karena dikunci hanya oleh signal_key
#     (8 Agu)
#
# Skrip ini memeriksa RANTAI PENUHNYA: cache terisi -> bobot bergerak dari 1.0 ->
# skor kandidat benar-benar bergeser.

param([switch]$Diam)

$Base = 'http://localhost:8000'
function Say($m) { if (-not $Diam) { Write-Host $m } }

$masalah = @()

# 1) Cache di memori terisi? Kosong = scoring berjalan tanpa bobot sama sekali.
try {
    $st = Invoke-RestMethod "$Base/api/v1/signals/updater/state" -TimeoutSec 30
    $fk = [int]$st.futures.cached_keys
    $sk = [int]$st.spot.cached_keys
    $ck = [int]$st.cross.cached_keys
    Say "cache  : futures=$fk spot=$sk cross=$ck kunci"
    if ($fk -eq 0) { $masalah += 'cache futures KOSONG' }
    if ($sk -eq 0) { $masalah += 'cache spot KOSONG' }
    if ($st.futures.last_error) { $masalah += "updater futures: $($st.futures.last_error)" }
    if ($st.spot.last_error)    { $masalah += "updater spot: $($st.spot.last_error)" }
} catch { $masalah += "state updater tak terbaca: $($_.Exception.Message)" }

# 2) Bobot BERGERAK dari 1.0? Semua tepat 1.0 = tersimpan tapi tanpa efek apa pun.
try {
    # limit dibatasi 100 oleh API (le=100); meminta lebih menghasilkan 422.
    $sig = Invoke-RestMethod "$Base/api/v1/signals/performance?min_trades=2&limit=100" -TimeoutSec 60
    $bergerak = 0; $total = 0
    foreach ($row in $sig.signals) {
        foreach ($a in $row.agents.PSObject.Properties) {
            $total++
            if ([math]::Abs([double]$a.Value.weight - 1.0) -gt 1e-9) { $bergerak++ }
        }
    }
    Say "bobot  : $bergerak dari $total baris bergerak dari 1.0"
    if ($total -gt 0 -and $bergerak -eq 0) { $masalah += 'SEMUA bobot tepat 1.0 - tersimpan tapi nol efek' }
} catch { $masalah += "performa sinyal tak terbaca: $($_.Exception.Message)" }

# 3) Skor kandidat benar-benar bergeser? Ini bukti terakhir bahwa bobot sampai ke
#    keputusan, bukan berhenti di lapisan penyimpanan.
try {
    $scan = Invoke-RestMethod "$Base/api/v1/opportunity/scan" -TimeoutSec 90
    $n = 0; $geser = 0
    foreach ($r in $scan.results) {
        if ($null -ne $r.adaptive_score -and $null -ne $r.raw_score) {
            $n++
            if ([math]::Abs([double]$r.raw_score - [double]$r.adaptive_score) -gt 0.05) { $geser++ }
        }
    }
    Say "skor   : $geser dari $n kandidat SPOT skornya bergeser"
    if ($n -gt 0 -and $geser -eq 0) { $masalah += 'skor SPOT tak bergeser sama sekali' }
} catch { Say "skor   : scan SPOT tak terbaca (mungkin sedang sibuk) - dilewati" }

if ($masalah.Count -eq 0) { Say "`nHASIL: adaptive weighting sampai ke keputusan."; exit 0 }
Say "`nHASIL: ADA MASALAH"
foreach ($m in $masalah) { Say "  ! $m" }
exit 1
