# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_all

# Auto-detect icon.ico next to this spec file
_here = os.path.dirname(os.path.abspath(SPEC))
_icon_path = os.path.join(_here, 'icon.ico')
_icon = _icon_path if os.path.exists(_icon_path) else None

# Collect customtkinter assets (themes, images)
ctk_datas, ctk_binaries, ctk_hiddenimports = collect_all('customtkinter')

# Bundle icon.ico into the exe if it exists
_extra_datas = [(_icon_path, '.')] if _icon else []

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=ctk_binaries,
    datas=ctk_datas + _extra_datas,
    hiddenimports=ctk_hiddenimports + [
        'minecraft_launcher_lib',
        'requests',
        'packaging',
        'tkinter',
        'tkinter.ttk',
        '_tkinter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'PIL', 'scipy'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NovaLauncher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
    version=None,
)
