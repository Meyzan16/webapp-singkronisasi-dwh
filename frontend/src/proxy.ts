import { NextResponse, type NextRequest } from "next/server";

/**
 * Penjaga akses dashboard (Next 16 "proxy", dulu middleware).
 *
 * Setiap halaman dan setiap /api/*, /health, /ws/* wajib cookie sesi `at_session`
 * yang ditandatangani backend (app/services/auth.py, format `<payload>.<hmac>`).
 * Backend hanya mendengar di 127.0.0.1, jadi dari jaringan pintunya hanya lewat sini.
 * Tanpa AUTH_SECRET (belum menjalankan ops/set-password.py) semua ditolak — gagal tertutup.
 */

const COOKIE = "at_session";
const PUBLIC_PATHS = ["/sign-in", "/api/v1/auth/login", "/api/v1/auth/logout"];

function b64urlToBytes(s: string): Uint8Array {
  const pad = s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4);
  const bin = atob(pad);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function bytesToB64url(b: ArrayBuffer): string {
  let bin = "";
  new Uint8Array(b).forEach(x => { bin += String.fromCharCode(x); });
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function validSession(token: string | undefined, secret: string): Promise<boolean> {
  if (!token || !secret) return false;
  const parts = token.split(".");
  if (parts.length !== 2) return false;
  const [payload, sig] = parts;
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const expected = bytesToB64url(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload)));
  if (!safeEqual(sig, expected)) return false;
  try {
    const data = JSON.parse(new TextDecoder().decode(b64urlToBytes(payload))) as { exp?: number };
    return typeof data.exp === "number" && data.exp > Date.now() / 1000;
  } catch {
    return false;
  }
}

export async function proxy(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  if (PUBLIC_PATHS.some(p => pathname === p || pathname.startsWith(`${p}/`))) {
    return NextResponse.next();
  }
  const ok = await validSession(req.cookies.get(COOKIE)?.value, process.env.AUTH_SECRET ?? "");
  if (ok) return NextResponse.next();

  const isApi = pathname.startsWith("/api/") || pathname.startsWith("/health") || pathname.startsWith("/ws/");
  if (isApi) {
    return NextResponse.json({ detail: "Belum login." }, { status: 401 });
  }
  const url = req.nextUrl.clone();
  url.pathname = "/sign-in";
  url.search = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname + search)}`;
  return NextResponse.redirect(url);
}

export const config = {
  // Semua kecuali aset statis Next & berkas publik.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|svg|gif|webp|ico|txt)$).*)"],
};
