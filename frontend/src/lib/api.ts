/**
 * apiFetch — satu-satunya pintu FE menuju backend.
 *
 * Dibuat setelah sesi "socket hang up" (ECONNRESET) 4 Sep 2026. Dua sebab yang
 * ditangani di sini:
 *
 * 1. SOKET MATI DIPAKAI ULANG. Next dev mem-proxy `/api/v1/*` ke uvicorn lewat
 *    koneksi keep-alive. Uvicorn default menutup koneksi menganggur setelah 5
 *    detik, sementara poller FE berjeda 30-60 detik — jadi soket di pool sudah
 *    mati saat dipakai lagi dan Node melaporkannya sebagai ECONNRESET. Sisi
 *    server sudah dinaikkan (lihat ops/start-night.ps1 & backend/Dockerfile);
 *    di sisi sini SATU kali ulang untuk GET menutup sisa balapannya, karena
 *    kegagalan jenis ini terjadi SEBELUM request sempat sampai ke backend
 *    (aman diulang — backend tak pernah melihatnya).
 *
 * 2. REQUEST YANG TAK PERNAH SELESAI. Sebelumnya 92 pemanggilan fetch tanpa
 *    satu pun timeout: satu request menggantung berarti `await` tak pernah
 *    kembali, flag loading tak pernah turun, dan poller menumpuk batch baru
 *    tiap siklus sampai soket habis. Timeout membuat setiap panggilan PASTI
 *    berakhir, sehingga layar selalu pulih sendiri.
 *
 * POST/PATCH/DELETE TIDAK PERNAH diulang otomatis — membuka posisi dua kali
 * jauh lebih mahal daripada satu error yang terlihat di layar.
 */

/** Batas tunggu bawaan. Endpoint berat (scan, backtest) mengirim `timeoutMs` sendiri. */
export const DEFAULT_TIMEOUT_MS = 20_000;

/**
 * Untuk pekerjaan yang memang lama: scan seluruh pasar, backtest, analisa satu
 * koin, dan muat blob adaptive-engine. Tetap ADA batasnya — tanpa batas berarti
 * kembali ke perilaku menggantung yang jadi sebab masalah ini.
 */
export const HEAVY_TIMEOUT_MS = 120_000;

export interface ApiFetchInit extends RequestInit {
  /** Batas tunggu per percobaan, ms. Default {@link DEFAULT_TIMEOUT_MS}. */
  timeoutMs?: number;
}

/** Kegagalan transport (soket mati / DNS / server menutup) — request tak pernah sampai. */
function isTransportError(err: unknown): boolean {
  // Timeout dari AbortSignal.timeout() datang sebagai TimeoutError; itu BUKAN
  // soket mati — backend mungkin sedang mengerjakannya, jadi jangan diulang.
  if (err instanceof DOMException) return false;
  return err instanceof TypeError; // fetch melempar TypeError untuk gagal jaringan
}

function isRetryable(method: string | undefined): boolean {
  const m = (method ?? "GET").toUpperCase();
  return m === "GET" || m === "HEAD";
}

/**
 * fetch dengan timeout wajib + satu kali ulang untuk GET yang mati di transport.
 *
 * Tanda tangannya sengaja sama persis dengan `fetch`, jadi semua pemanggil lama
 * bekerja tanpa perubahan lain. `signal` milik pemanggil tetap dihormati:
 * membatalkan dari luar membatalkan percobaan yang sedang jalan DAN mencegah
 * percobaan ulang.
 */
export async function apiFetch(input: RequestInfo | URL, init?: ApiFetchInit): Promise<Response> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal: callerSignal, ...rest } = init ?? {};
  const attempts = isRetryable(rest.method) ? 2 : 1;

  let lastErr: unknown;
  for (let attempt = 0; attempt < attempts; attempt++) {
    // Timeout per percobaan, digabung dengan signal pemanggil bila ada.
    // AbortSignal.any baru ada di browser yang relatif baru; kalau tak tersedia,
    // timeout tetap jalan dan signal pemanggil ditangani lewat pemeriksaan
    // `callerSignal.aborted` di bawah — jangan sampai seluruh fetch mati hanya
    // karena satu API pembantu tak ada.
    const timeout = AbortSignal.timeout(timeoutMs);
    const signal =
      callerSignal && typeof AbortSignal.any === "function"
        ? AbortSignal.any([callerSignal, timeout])
        : timeout;

    try {
      return await fetch(input, { ...rest, signal });
    } catch (err) {
      lastErr = err;
      // Pemanggil yang membatalkan (unmount, ganti filter) tak boleh diulang.
      if (callerSignal?.aborted) throw err;
      if (attempt === attempts - 1 || !isTransportError(err)) throw err;
      // Jeda singkat: beri pool waktu membuang soket mati sebelum coba lagi.
      await new Promise((r) => setTimeout(r, 250));
    }
  }
  throw lastErr;
}
