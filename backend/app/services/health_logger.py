"""
System Health Event Logger — in-memory circular buffer.

Tracks:
  - Binance API up/down events
  - Agent start/stop/error events
  - Database connectivity changes

Events survive as long as the backend process runs.
Max 500 events (FIFO).
"""

import time
from typing import Optional

_events: list[dict] = []
MAX_EVENTS = 500

# Previous known states — detect changes
_state: dict = {
    "spot_ok":     None,
    "futures_ok":  None,
    "spot_banned": None,
    "fut_banned":  None,
    "db_ok":       None,
    "agents": {},   # agent_name → running bool
}

_event_id = 0


# ── Core log function ──────────────────────────────────────────────────────────

def _log(category: str, level: str, message: str, detail: dict | None = None) -> None:
    """
    level: "up" | "down" | "error" | "warn" | "info" | "ban"
    category: "api_spot" | "api_futures" | "agent" | "database" | "system"
    """
    global _event_id, _events
    _event_id += 1
    _events.append({
        "id":       _event_id,
        "ts":       time.time(),
        "category": category,
        "level":    level,
        "message":  message,
        "detail":   detail or {},
    })
    # Trim to MAX_EVENTS
    if len(_events) > MAX_EVENTS:
        _events = _events[-MAX_EVENTS:]


# ── API status recording ───────────────────────────────────────────────────────

def record_api_status(
    api: str,                         # "spot" | "futures"
    ok: bool,
    latency_ms: Optional[int],
    error: Optional[str],
    banned_until: Optional[int],
) -> None:
    """Called by binance_status.py every 30s. Logs changes only."""
    state_key_ok   = f"{api}_ok"
    state_key_ban  = f"{'spot' if api == 'spot' else 'fut'}_banned"
    prev_ok        = _state.get(state_key_ok)
    prev_banned    = _state.get(state_key_ban)

    api_label = "Spot" if api == "spot" else "Futures"

    # First time → log initial state
    if prev_ok is None:
        if ok:
            _log(f"api_{api}", "up",
                 f"✅ Binance {api_label} API Online — {latency_ms}ms",
                 {"latency_ms": latency_ms})
        else:
            _log(f"api_{api}", "down",
                 f"🔴 Binance {api_label} API Tidak Terjangkau",
                 {"error": error})
        _state[state_key_ok]  = ok
        _state[state_key_ban] = banned_until
        return

    # Status change: up → down
    if prev_ok and not ok:
        _log(f"api_{api}", "down",
             f"🔴 Binance {api_label} API MATI",
             {"error": error or "Connection failed"})

    # Status change: down → up
    elif not prev_ok and ok:
        _log(f"api_{api}", "up",
             f"✅ Binance {api_label} API PULIH — {latency_ms}ms",
             {"latency_ms": latency_ms})

    # Banned state change
    if banned_until and not prev_banned:
        import datetime
        dt = datetime.datetime.fromtimestamp(banned_until).strftime("%H:%M:%S")
        _log(f"api_{api}", "ban",
             f"⛔ Binance {api_label} IP BANNED — sampai {dt}",
             {"banned_until": banned_until})

    elif not banned_until and prev_banned:
        _log(f"api_{api}", "up",
             f"✅ Binance {api_label} IP Ban BERAKHIR — API kembali normal",
             {"latency_ms": latency_ms})

    _state[state_key_ok]  = ok
    _state[state_key_ban] = banned_until


# ── Agent status recording ─────────────────────────────────────────────────────

AGENT_LABELS = {
    "spot_scanner":    "🚀 Spot Opp Scanner",
    "spot_monitor":    "👁 Spot Position Monitor",
    "futures_scanner": "⚡ Futures Scanner (A1+A2)",
    "futures_monitor": "🔍 Futures Risk Monitor",
    "weight_updater":  "🧠 Weight Updater",
}

def record_agent_status(agent: str, running: bool, error: Optional[str] = None) -> None:
    """Called by health endpoint. Logs changes only."""
    prev = _state["agents"].get(agent)
    label = AGENT_LABELS.get(agent, agent)

    # First time
    if prev is None:
        _log("agent", "info" if running else "warn",
             f"{label} — {'Running' if running else 'Stopped'}",
             {"agent": agent, "running": running})
        _state["agents"][agent] = running
        return

    # Agent stopped
    if prev and not running:
        _log("agent", "down",
             f"🔴 {label} BERHENTI",
             {"agent": agent, "error": error})

    # Agent restarted
    elif not prev and running:
        _log("agent", "up",
             f"✅ {label} AKTIF KEMBALI",
             {"agent": agent})

    _state["agents"][agent] = running


# ── Database recording ─────────────────────────────────────────────────────────

def record_db_status(ok: bool, error: Optional[str] = None) -> None:
    """Log database connectivity changes."""
    prev = _state.get("db_ok")
    if prev is None:
        _log("database", "info" if ok else "down",
             f"🗄 Database {'Connected' if ok else 'Unavailable'}",
             {"error": error})
        _state["db_ok"] = ok
        return
    if prev and not ok:
        _log("database", "down",
             f"🔴 Database TERPUTUS — {error or 'connection lost'}",
             {"error": error})
    elif not prev and ok:
        _log("database", "up",
             "✅ Database TERHUBUNG KEMBALI")
    _state["db_ok"] = ok


# ── System startup ─────────────────────────────────────────────────────────────

def log_startup() -> None:
    """Call once on backend startup."""
    _log("system", "info",
         "🚀 Backend dimulai — semua agents diinisialisasi",
         {"ts": time.time()})


# ── Read functions ─────────────────────────────────────────────────────────────

def get_log(limit: int = 100) -> list[dict]:
    """Return most recent events, newest first."""
    return list(reversed(_events[-limit:]))


def get_stats() -> dict:
    return {
        "total_events": len(_events),
        "max_events":   MAX_EVENTS,
        "uptime_since": _events[0]["ts"] if _events else None,
    }
