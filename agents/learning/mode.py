"""Saklar satu-tempat: apakah pembelajaran berat jalan di proses terpisah?

Dibuat 4 Sep 2026 setelah terukur bahwa `train_and_register()` — melatih model
atas SELURUH ledger (387.390 baris saat itu) — MENAHAN event loop 94-129 detik
tiap kali jalan. Selama itu backend tak menjawab apa pun: `/balance/futures`
sampai 119 detik, dan FE melihatnya sebagai layar menggantung lalu
"socket hang up" (ECONNRESET).

Tiga upaya di dalam satu proses sudah dicoba dan TERUKUR TIDAK CUKUP:
`asyncio.to_thread`, select kolom seperlunya, dan streaming `.partitions()`.
Sebabnya GIL — kerja Python murni tak pernah benar-benar paralel dengan event
loop di proses yang sama. Satu-satunya pemisah yang nyata adalah PROSES lain.

Yang dipindah HANYA langkah berat murni-DB (latih model, drift, lifecycle).
Scanner, monitor, weight updater, dan outcome tracker tetap di proses backend,
karena API membaca status hidup mereka dari memori (scanner store, risk gate,
cache bobot) — memindahkan itu akan membuat API kehilangan status tersebut.
"""

import os

# Set LEARNING_STANDALONE=true di proses backend, lalu jalankan
# `python -m agents.learning` sebagai proses terpisah.
LEARNING_STANDALONE: bool = os.getenv("LEARNING_STANDALONE", "false").lower() == "true"
