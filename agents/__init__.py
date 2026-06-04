"""
Agents package — autonomous trading agents.

Each agent runs as an independent asyncio loop and can be developed,
deployed, and scaled independently from the FastAPI backend.

Agents:
  scanner/      — Scans 100 USDT pairs every 15 min, caches results
  paper_trader/ — Monitors open paper trades, closes on TP/SL
  learning/     — (future) Strategy optimizer, ML signal improver

Entry point:
  python -m agents          ← start all agents (standalone)
  or imported by backend    ← agents run inside FastAPI lifespan

Communication:
  - Shared PostgreSQL DB (same DATABASE_URL as backend)
  - scan_store (in-memory, shared when running inside backend)
"""
