"""Cetak distribusi bobot FUTURES: "n|jumlah>1.0|max".

Dipakai ops/b1-watch.ps1 untuk membuktikan apakah Fase B1
(expectancy_aware_weights) benar membuat bobot menyimpang ke atas.
Jalankan dari folder backend/ (butuh `app.*` importable).
"""

import asyncio
import os
import sys

# Script ini tinggal di ops/ tapi mengimpor `app.*` milik backend/. Menjalankan
# file di luar backend/ TIDAK menaruh backend/ di sys.path (beda dgn `python -c`
# yang memakai cwd), jadi daftarkan eksplisit.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import truststore

truststore.inject_into_ssl()

from sqlalchemy import text  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402

SQL = (
    "SELECT COUNT(*), "
    "COALESCE(SUM(CASE WHEN weight > 1.0 THEN 1 ELSE 0 END), 0), "
    "ROUND(MAX(weight)::numeric, 3) "
    "FROM agent_signal_weights WHERE agent LIKE 'futures%'"
)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        row = (await session.execute(text(SQL))).first()
        print("%s|%s|%s" % (row[0], row[1], row[2]))


asyncio.run(main())
