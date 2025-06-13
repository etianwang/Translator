# -*- mode: python ; coding: utf-8 -*-


block_cipher = None


a = Analysis(
    ['Toolbox_GUI.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('CAD_translator', 'CAD_translator'), ('EXCEL_translator', 'EXCEL_translator'), ('PDF_translator', 'PDF_translator'), ('PPT_translator', 'PPT_translator'), ('C:\\Users\\etn\\AppData\\Local\\Programs\\Python\\Python37\\Lib\\site-packages\\PyQt5\\Qt5\\plugins\\platforms', 'plugins\\platforms'), ('C:\\Users\\etn\\AppData\\Local\\Programs\\Python\\Python37\\Lib\\site-packages\\PyQt5\\Qt5\\plugins\\imageformats', 'plugins\\imageformats'), ('C:\\Users\\etn\\AppData\\Local\\Programs\\Python\\Python37\\Lib\\site-packages\\PyQt5\\Qt5\\plugins\\styles', 'plugins\\styles')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Toolbox_GUI',
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
    icon=['assets\\icon.ico'],
)
