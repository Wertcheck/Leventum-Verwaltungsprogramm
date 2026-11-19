# PyInstaller-Spec (onedir). Zwei Programme im selben Ordner:
#   Leventum.exe        – Fenster (pywebview/WebView2), keine Konsole; Logdatei im Datenordner
#   LeventumServer.exe  – Konsole, Browser-Modus (Diagnose/Fallback ohne WebView2)
# Aufruf (aus dem Repo-Wurzelordner, nach `cd frontend && npm ci && npm run build`):  pyinstaller packaging/leventum.spec --noconfirm
# STATUS: unter Linux gebaut und gestartet (Bündelung, Alembic-Daten, Frontend); unter Windows NICHT gebaut/getestet.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 – von PyInstaller bereitgestellt
BACKEND = ROOT / "backend"
DIST = ROOT / "frontend" / "dist"
assert (DIST / "index.html").exists(), "frontend/dist fehlt: zuerst `npm ci && npm run build` im Ordner frontend ausführen"

datas = [(str(BACKEND / "alembic.ini"), "."), (str(BACKEND / "alembic"), "alembic"), (str(DIST), "frontend_dist")]
hidden = (collect_submodules("leventum") + collect_submodules("alembic") + collect_submodules("uvicorn") + collect_submodules("argon2")
          + ["sqlalchemy.dialects.sqlite", "python_multipart", "multipart", "httpx", "email.mime.multipart"])
if sys.platform == "win32":
    hidden += ["webview.platforms.edgechromium", "webview.platforms.winforms", "clr"]

a = Analysis([str(ROOT / "packaging" / "entry.py")], pathex=[str(BACKEND)], datas=datas, hiddenimports=hidden,  # noqa: F821
             excludes=["tkinter", "pytest", "IPython"], noarchive=False)
pyz = PYZ(a.pure)  # noqa: F821
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Leventum", console=False, upx=False)  # noqa: F821
srv = EXE(pyz, a.scripts, [], exclude_binaries=True, name="LeventumServer", console=True, upx=False)  # noqa: F821
coll = COLLECT(gui, srv, a.binaries, a.datas, name="Leventum", upx=False)  # noqa: F821
