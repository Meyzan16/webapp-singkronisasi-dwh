"""Setup import untuk seluruh test suite.

`pytest.ini` hanya menaruh `backend/` di `sys.path`, sedangkan paket `agents/`
ada di akar repo. Selama ini delapan file tes menambal itu sendiri-sendiri dengan
potongan `sys.path.insert` yang identik — dan file yang tidak menambal hanya
lulus bila kebetulan dijalankan SESUDAH salah satu dari delapan itu.

Akibatnya `pytest tests/` lulus tapi `pytest tests/test_satu_file.py` gagal
dengan `ModuleNotFoundError: No module named 'agents'` — kegagalan yang muncul
hanya saat seseorang menjalankan satu berkas, biasanya justru saat sedang
men-debug berkas itu.

conftest.py dimuat pytest sebelum modul tes mana pun, jadi menaruhnya di sini
membuat urutan tak lagi berpengaruh.
"""

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
