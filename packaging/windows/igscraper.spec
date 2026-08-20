# -*- mode: python ; coding: utf-8 -*-
# Spec do PyInstaller pro build desktop do IG-Scraper Pro (Windows).
# Rode via build_windows.bat, ou manualmente:
#   pyinstaller packaging\windows\igscraper.spec --noconfirm
#
# IMPORTANTE: rode a partir da RAIZ do repositorio (onde ficam app.py,
# desktop.py, templates\, etc), nao de dentro de packaging\windows\.

import os

ROOT = os.path.abspath(os.getcwd())

a = Analysis(
    [os.path.join(ROOT, 'desktop.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'templates'), 'templates'),
    ],
    hiddenimports=[
        'instagrapi',
        'pydantic',
        'pydantic_core',
        'PIL',
        'PIL._imaging',
        'engineio.async_drivers.threading',
        'instaloader',
        'instaloader.exceptions',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='IGScraperPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # sem janela de terminal preta atras do app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'packaging', 'windows', 'icon.ico'),
)
