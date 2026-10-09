# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

root = Path(SPECPATH)
entry = os.environ.get("FLOWER_SEARCH_ENTRY", "main.py")
app_name = os.environ.get("FLOWER_SEARCH_NAME", "FlowerSearch")
console = os.environ.get("FLOWER_SEARCH_CONSOLE", "0") == "1"
a = Analysis(
    [str(root / entry)],
    pathex=[str(root)],
    binaries=[(os.environ["FLOWER_SEARCH_VIPS_DLL"], ".")],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Let Windows resolve API sets and avoid Poppler's ICU DLL, which conflicts with Qt.
a.binaries = [
    binary
    for binary in a.binaries
    if not Path(binary[0]).name.lower().startswith("api-ms-win-")
    and not (
        Path(binary[0]).name.lower() == "icuuc.dll"
        and "poppler" in str(binary[1]).lower()
    )
]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=console,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
