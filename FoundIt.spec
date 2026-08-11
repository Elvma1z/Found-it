# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['found_it\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('found_it\\resources\\app_icon.ico', 'found_it\\resources')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyinstaller_rthook_torch.py'],
    excludes=['matplotlib', 'tensorflow', 'sklearn', 'timm'],
    noarchive=False,
    optimize=0,
)
# One of the bundled wheels ships an older vcruntime140/vcruntime140_1
# (14.42) than msvcp140 (14.51) and the system's own copies. Mixed-version
# CRT DLLs in the same process break torch's c10.dll init (WinError 1114:
# "DLL initialization routine failed") because it ends up loading the stale
# bundled vcruntime instead of the matching system one. Drop the bundled
# copies so everything resolves against the system-installed VC++
# Redistributable uniformly, same as when running unfrozen.
_crt_dll_excludes = {
    'vcruntime140.dll', 'vcruntime140_1.dll',
    'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
    'msvcp140_atomic_wait.dll', 'concrt140.dll',
}
a.binaries = [b for b in a.binaries if b[0].lower() not in _crt_dll_excludes]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='FoundIt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-compressing torch's native DLLs (c10.dll etc.) causes
    # "DLL initialization routine failed" (WinError 1114) at import time,
    # since UPX corrupts DllMain-time CPU feature detection in those libs.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='found_it\\resources\\app_icon.ico',
)
