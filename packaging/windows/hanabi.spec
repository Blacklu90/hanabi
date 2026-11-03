# PyInstaller recipe: builds dist/Hanabi/Hanabi(.exe) — a folder with Python and everything Hanabi needs.
# Build:  pyinstaller packaging/windows/hanabi.spec --noconfirm
import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
R = lambda *p: os.path.join(ROOT, *p)
ICON = R("packaging", "windows", "hanabi.ico")

a = Analysis(
    [R("app", "desktop.py")],
    pathex=[ROOT],
    datas=[(R("templates"), "templates"), (R("static"), "static"), (R("packaging"), "packaging"),
           (R("data", "content.db"), "data"), (R("data", "content_report.json"), "data"), (R("data", "strokes"), os.path.join("data", "strokes")),
           (R("README.md"), "."), (R("DATA_SOURCES.md"), "."), (R("LICENSE"), ".")],
    hiddenimports=collect_submodules("uvicorn") + collect_submodules("app") + ["zstandard", "multipart", "python_multipart"],
    excludes=["tkinter", "pytest", "unittest", "pydoc_data", "test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Hanabi", console=False, upx=False,
          icon=ICON if os.path.exists(ICON) else None, version=None)
coll = COLLECT(exe, a.binaries, a.datas, name="Hanabi", upx=False)
