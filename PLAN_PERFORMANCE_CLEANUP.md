# PLAN — Signal Performance: Clean Bug + Susunan Naratif (awam)

Tanggal: 2026-07-18 · Status: **DRAFT — analisa selesai, implementasi belum**
Basis: commit `709b8f7` (dashboard perbaikan SPOT↔FUTURES) + `e868a28` (takeout plan).
Guardrail tetap: **nol file engine SPOT disentuh**; semua perubahan di
`frontend/src/features/signals/page.tsx` (+ endpoint read-only bila perlu).

## 1. Analisa — kondisi sekarang

Halaman sudah punya semua DATA yang benar (repair ledger 2 scope, funnel, saran
actionable). Masalahnya tinggal 2: **sisa bug** dan **susunan cerita** yang tidak
mengalir untuk orang awam.

### 1a. Bug yang terkonfirmasi (bukan dugaan)

| # | Bug | Bukti | Dampak |
|---|-----|-------|--------|
| **B1** | `weightPerf` di-fetch & disimpan tapi **tidak pernah dirender** | declare 2280 · set 2345 · dipakai hanya sbg gate 2419/2426; `ImprovementsTab` (572) tak menerima prop ini | Query `/signals/performance?limit=100` sia-sia tiap buka Perbaikan Live |
| **B2** | Filter agent **diabaikan** di Perbaikan Live | 2788 `onNavigate` set `progressAgentFilter` lalu `setSubTab("improvements")`, tapi `ImprovementsTab` (572) tak punya prop `agentFilter` | Tombol "Lihat aktivitas perbaikan agent ini →" bohong: tetap tampil semua agent. Filter juga **bocor** ke tab Progress berikutnya |
| **B3** | `Date.now()` dipanggil di dalam `useMemo` (impure) | eslint `react-hooks/purity` 594, 1032 | Hitungan "24 jam terakhir" tidak stabil antar-render |
| **B4** | Mutasi nilai turunan props di `useMemo` | eslint `react-hooks/immutability` 614, 615 | Melanggar rules-of-react; rawan bug halus saat re-render |
| **B5** | Komponen `MoverList` tak terpakai | eslint no-unused-vars 538 | Dead code |
| **B6** | Tanda kutip tak di-escape di JSX | eslint `react/no-unescaped-entities` 708, 1186 | `npm run lint` gagal |
| **B7** | Label agent **tidak konsisten** antar tab | `_agentShort` (802) tak memetakan `opportunity_spot`; padahal `AGENT_LABEL` (533) sudah benar. Plus hardcode `🎯 opportunity_spot` di 1175 | Awam lihat ID mentah `opportunity_spot` di tab repair, tapi "SPOT" di tab lain — terasa beda sistem |
| **B8** | Refetch berulang saat endpoint SPOT gagal | gate 2419 `(!weightPerf \|\| !repairsData \|\| !spotRepairsData)` + deps 2426 | Bila `/spot-repair/repairs` timeout, state tetap null → effect nembak ulang tiap deps berubah, tanpa backoff |

### 1b. Masalah susunan (kenapa awam bingung)

- **Overview nol menyebut perbaikan.** Blok 2545–2627 tak punya satu pun kata
  perbaikan/repair/progress/verifikasi. Kapabilitas paling penting sistem tidak
  punya benang merah dari halaman pembuka.
- **Urutan seksi bukan alur sebab-akibat.** Sekarang Overview → **Engine** →
  Signals → Analysis → Improve. Engine adalah yang PALING teknis (ledger, model,
  canary, drift) tapi ditaruh ke-2 → menakutkan. Improve (hasil/payoff) malah paling akhir.
- **Subtab Improve terbalik.** Default mendarat di **Progress** (akhir cerita).
  Padahal alur yang diiklankan UI sendiri: Terapkan → Progress → Verifier.
- **Tak ada jalur balik.** Signals (bobot) dan Improve (aksi atas bobot itu)
  bicara objek yang sama tapi tak saling menaut; Analysis→Predictive menampilkan
  hit-rate yang persis jadi pemicu agen repair, juga tanpa tautan.

## 2. Susunan yang diusulkan (jawaban "harusnya seperti apa")

Satu alur pertanyaan awam, tiap seksi menjawab satu pertanyaan:

| Urutan | Seksi | Menjawab |
|--------|-------|----------|
| 1 | 📊 **Overview** | "Sistem sehat tidak, dan apa yang perlu saya perhatikan?" |
| 2 | 🎯 **Signals** | "Apa yang sudah dipelajari agent?" (bobot per market) |
| 3 | 🔬 **Analysis** | "Di mana letak salahnya?" (regime · formulas · rejections · predictive) |
| 4 | 🔧 **Improve** | "Apa yang sedang diperbaiki, dan terbukti membaik tidak?" |
| 5 | 🧠 **Engine** | "Mesin di baliknya" — lanjutan/teknis, sengaja paling akhir |

Sub-tab **Improve** diurutkan mengikuti alurnya sendiri:
**💡 Saran (temuan) → 🔧 Perbaikan Live (sedang berjalan per agent) → 📈 Progress (hasil terverifikasi)**,
default mendarat di **Saran**, bukan Progress.

## 3. Fase implementasi

### P1 — Clean bug (tanpa ubah tampilan)
- B1: buang `weightPerf` + `setWeightPerf` + fetch-nya dari `fetchImprovements`
  (sisakan `reviewData` yang memang dipakai); bersihkan gate 2419 & deps 2426.
- B2: tambah prop `agentFilter` ke `ImprovementsTab`, filter kartu per agent +
  chip "Agent: X ✕"; **reset filter saat pindah seksi** supaya tidak bocor.
- B3: angkat `Date.now()` keluar dari `useMemo` → `useState`/prop `nowTs` yang
  di-refresh berkala (atau kirim dari parent sekali per fetch).
- B4: bangun objek baru (spread) alih-alih mem-`push` nilai turunan props.
- B5/B6: hapus `MoverList`; escape kutip di 708 & 1186.
- B7: **satukan label** — pakai satu helper (`AGENT_LABEL`) di semua tab, hapus
  `_agentShort` atau jadikan pembungkus tipis di atasnya; hapus hardcode 1175.
- B8: gate cukup `!repairsData` saja + tandai kegagalan (`spotRepairsError`)
  supaya tidak nembak ulang tanpa henti; tampilkan strip "SPOT tak terjangkau".
- **Exit**: `npx tsc --noEmit` exit 0 **dan** `npx eslint src/features/signals/page.tsx` bersih.

### P2 — Susunan naratif
- Urutkan `SECTIONS` sesuai tabel §2 (Engine dipindah ke posisi 5).
- `SECTION_DEFAULT.improve` → `"suggestions"`; urutkan `SUBTABS_OF.improve`
  menjadi Saran → Perbaikan Live → Progress.
- Perbarui modal tutorial "Panduan 5 Seksi" agar cocok urutan baru + kalimat
  alur satu baris: *temuan → perbaikan → bukti*.
- Beri tiap seksi satu kalimat pertanyaan (bukan jargon) di kartu level-1.

### P3 — Integrasi antar tab (hilangkan rasa "terpisah")
- **Overview** dapat kartu ringkas **"Perbaikan hari ini"**: X aksi 24j ·
  Y terbukti membaik · Z di-revert (SPOT+FUTURES digabung), dengan tombol
  "Lihat detail →" ke Improve. Ini benang merah yang sekarang hilang.
- **Signals → Improve**: baris sinyal yang punya aksi repair diberi badge
  🔧 kecil + klik → Improve ter-filter sinyal/agent tsb.
- **Analysis→Predictive → Improve**: baris hit-rate rendah diberi tautan
  "sinyal ini sedang diperbaiki →".
- Aturan anti-duplikat: **angka mentah hidup di satu tab saja**; tab lain hanya
  merujuk + menaut, tidak menyalin tabel.

## 4. Guardrails
- Murni presentasi/observability — **tidak menyentuh logika keputusan trading**,
  ambang, bobot, maupun file engine SPOT.
- Tidak menambah npm package.
- Endpoint yang dipakai sudah ada; bila Overview butuh agregat, hitung di
  frontend dari `/signals/repairs` + `/spot-repair/repairs` (jangan tambah beban BE).

## 5. Verifikasi
- `tsc --noEmit` exit 0 + `eslint` bersih (gate P1).
- `curl` 2 endpoint repair → funnel tampil benar di Overview.
- Telusuri alur klik: Saran → "Lihat aktivitas" → Perbaikan Live **ter-filter**
  → "Lihat semua aksi" → Progress ter-filter → ganti seksi → filter **ter-reset**.
- Catatan: preview browser in-app tidak bisa hydrate Next 16 (RSC `__next_f`
  kosong, terjadi juga di route yang tak disentuh) → verifikasi lewat
  tsc/eslint/curl + review, atau di browser asli owner.

## 6. Urutan kerja
**P1 (bug) → P2 (urutan) → P3 (tautan)**. P1 berdiri sendiri dan aman di-commit
duluan; P2 murni konfigurasi urutan; P3 yang paling terasa untuk awam.
