"""Jaring pengaman endpoint `/agent/config` — jendela satu-satunya ke tala runtime.

Penyakit yang dijaga di sini nyata dan sudah pernah terjadi: M2 dan M7 memindahkan
konstanta keputusan dari `monitor.py` ke `monitor_config.py`, tapi `agent_config.py`
masih membacanya dari modul lama. Tak satu pun test gagal, tak satu pun impor
pecah — kesalahannya baru muncul saat request datang, sebagai `AttributeError`
yang ditangkap `try/except` per-seksi lalu berubah menjadi **grup kosong**.

Akibatnya seluruh UI tala buta: `{"spot":{},"futures":{},"learning":{}}`. Ironisnya
M2 justru bertujuan menyambungkan tala UI — kabelnya tersambung di sisi agen, tapi
jendelanya pecah tanpa suara.

Dua hal yang dijaga:
  1. **Setiap** atribut modul yang dirujuk `agent_config.py` benar-benar ada —
     diperiksa dengan membaca sumbernya, bukan daftar nama yang harus diingat
     manusia untuk diperbarui.
  2. Pemuat tiap seksi tidak menaikkan exception, sehingga tak ada grup yang
     diam-diam menjadi kosong.
"""

import importlib
import re
from pathlib import Path

import pytest

CONFIG_SRC = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "agent_config.py"


def _referenced_attributes() -> dict[str, set[str]]:
    """Petakan `alias.ATTR` di agent_config.py → {modul: {atribut}}.

    Dibaca dari sumbernya supaya test ini ikut menjaga rujukan yang DITAMBAHKAN
    nanti, tanpa perlu ada yang ingat memperbarui daftar di sini.
    """
    src = CONFIG_SRC.read_text(encoding="utf-8")

    aliases: dict[str, str] = {}
    for mod, sub, alias in re.findall(
            r"from (agents[\w.]*) import (\w+) as (\w+)", src):
        aliases[alias] = f"{mod}.{sub}"
    # Bentuk tanpa `as`: `from agents.futures import agent1, agent2`
    for mod, names in re.findall(r"from (agents[\w.]*) import ([\w, ]+)$", src, re.M):
        for name in (n.strip() for n in names.split(",")):
            if name and " as " not in name:
                aliases.setdefault(name, f"{mod}.{name}")

    refs: dict[str, set[str]] = {}
    for alias, modpath in aliases.items():
        for attr in re.findall(rf"\b{alias}\.([A-Za-z_][A-Za-z0-9_]*)", src):
            refs.setdefault(modpath, set()).add(attr)
    return refs


def test_peta_rujukan_tidak_kosong():
    """Kalau parsingnya berhenti menemukan apa pun, test di bawah lulus palsu."""
    refs = _referenced_attributes()
    assert refs, "tak satu pun rujukan `alias.ATTR` terbaca — parser test ini rusak"
    assert sum(len(v) for v in refs.values()) > 50


def _resolve(dotted: str):
    """Kembalikan modul, atau objek bila yang diimpor bukan submodul.

    `from agents.shared.config_reader import cfg` mengimpor sebuah OBJEK, bukan
    modul — dan atributnya (`cfg.get`) tetap layak dijaga, jadi objeknya ikut
    diperiksa, bukan dilewati.
    """
    try:
        return importlib.import_module(dotted)
    except ModuleNotFoundError:
        parent, _, name = dotted.rpartition(".")
        return getattr(importlib.import_module(parent), name)


@pytest.mark.parametrize("modpath", sorted(_referenced_attributes()))
def test_atribut_yang_dirujuk_benar_benar_ada(modpath: str):
    """Konstanta yang pindah modul harus menggagalkan test, bukan mengosongkan grup."""
    attrs = _referenced_attributes()[modpath]
    target = _resolve(modpath)
    hilang = sorted(a for a in attrs if not hasattr(target, a))
    assert not hilang, (
        f"{modpath} tak lagi punya: {hilang}. "
        f"Konstanta yang dipindah (mis. ke monitor_config.py) harus diikuti di "
        f"agent_config.py — satu atribut hilang mengosongkan SELURUH grupnya "
        f"di /agent/config, dan seluruh UI tala ikut buta.")


@pytest.mark.asyncio
@pytest.mark.parametrize("nama", ["spot", "futures", "learning"])
async def test_pemuat_seksi_tidak_melempar(nama: str):
    """Tanpa ini, kegagalan hanya terlihat sebagai grup kosong saat runtime.

    `cfg.get()` mundur ke default saat DB tak tersedia, jadi test ini tetap sah
    dijalankan tanpa database.
    """
    from app.api.v1 import agent_config as ac

    loader = {"spot": ac._spot_config,
              "futures": ac._futures_config,
              "learning": ac._learning_config}[nama]
    hasil = await loader()
    assert isinstance(hasil, dict) and hasil, f"seksi {nama} kosong"
