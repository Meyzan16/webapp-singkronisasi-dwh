# check-night.ps1 - apakah START-NIGHT semalam benar-benar TUNTAS?
#
# Latar: 5 & 6 Agu 2026 night-runner.log mencatat "START-NIGHT dipicu" lalu
# senyap. Backend tak pernah menyala dari scheduler dua malam berturut-turut, dan
# tak ada satu pun baris yang menjelaskan kenapa. Sejak itu start-night.ps1 selalu
# menutup dengan penanda SELESAI (atau GAGAL + nomor baris). Skrip ini membaca
# penanda itu supaya pertanyaan "jadwal jalan tidak semalam?" bisa dijawab dalam
# satu perintah, bukan dengan menyisir log.
#
# CATATAN ENCODING: night-runner.log ditulis Tee-Object sebagai UTF-16LE. Membaca
# apa adanya membuat setiap huruf terpisah spasi sehingga pencarian teks GAGAL
# tanpa error — persis jebakan yang sempat membuat verifikasi salah lapor.

param([int]$Hari = 1)

$Log = Join-Path $PSScriptRoot 'logs\night-runner.log'
if (-not (Test-Path $Log)) { Write-Host "night-runner.log tidak ada"; exit 1 }

$bytes = [System.IO.File]::ReadAllBytes($Log)
$text  = [System.Text.Encoding]::UTF8.GetString(($bytes | Where-Object { $_ -ne 0 }))
$lines = $text -split "`r?`n" | Where-Object { $_.Trim() }

$batas = (Get-Date).AddDays(-$Hari)
$recent = $lines | Where-Object {
    if ($_ -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})') { [datetime]$matches[1] -ge $batas } else { $false }
}

$dipicu  = @($recent | Where-Object { $_ -match 'START-NIGHT dipicu' })
$selesai = @($recent | Where-Object { $_ -match 'START-NIGHT SELESAI' })
$gagal   = @($recent | Where-Object { $_ -match 'GAGAL di baris|BERHENTI \(tidak tuntas\)' })

Write-Host "=== START-NIGHT, $Hari hari terakhir ==="
Write-Host ("  dipicu  : {0}" -f $dipicu.Count)
Write-Host ("  SELESAI : {0}" -f $selesai.Count)
Write-Host ("  GAGAL   : {0}" -f $gagal.Count)
foreach ($g in $gagal) { Write-Host "    ! $g" }

if ($dipicu.Count -eq 0) {
    Write-Host "`nHASIL: tidak ada pemicu sama sekali - cek Task Scheduler."
    exit 2
}
# Setiap pemicu WAJIB punya penanda penutup. Selisihnya = jalan yang menggantung.
$menggantung = $dipicu.Count - $selesai.Count - $gagal.Count
if ($menggantung -gt 0) {
    Write-Host "`nHASIL: $menggantung jalan TIDAK menutup - skrip mati tanpa sempat melapor."
    exit 3
}
if ($gagal.Count -gt 0) {
    Write-Host "`nHASIL: ada kegagalan, tapi TERCATAT - lihat baris '!' di atas."
    exit 4
}
Write-Host "`nHASIL: semua pemicu tuntas."
exit 0
