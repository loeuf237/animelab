# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path
import shutil
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

project = Path(SPECPATH)
sys.path.insert(0, str(project))
from animan import __version__
frontend = project / 'frontend' / 'dist'
if not (frontend / 'index.html').is_file():
    raise RuntimeError('Build the Vue frontend before packaging AnimeLab')
datas = [(str(project / 'animan' / 'templates'), 'animan/templates'),
         (str(project / 'animan' / 'static'), 'animan/static'),
         (str(frontend), 'frontend/dist'),
         (str(project / 'LICENSE'), '.'),
         (str(project / 'NOTICE'), '.'),
         (str(project / 'docs/branding/animelab.ico'), 'desktop-assets'),
         (str(project / 'animan/desktop/panel.html'), 'animan/desktop'),
         (str(project / 'animan/desktop/panel.js'), 'animan/desktop'),
         (str(project / 'animan/desktop/panel.css'), 'animan/desktop'),
         (str(project / 'docs' / 'desktop-distribution.md'), '.')]
datas += collect_data_files('webview') + collect_data_files('curl_cffi')
metadata = project / 'build' / 'release-metadata'
if metadata.exists(): datas.append((str(metadata), 'release-metadata'))
binaries = collect_dynamic_libs('curl_cffi')
for name in ('ffmpeg', 'ffprobe'):
    source = os.getenv('ANIMAN_' + name.upper() + '_BINARY') or shutil.which(name)
    if not source: raise RuntimeError(f'{name} must be available at build time')
    binaries.append((str(Path(source).resolve()), 'bin'))
hiddenimports = ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio',
    'uvicorn.protocols.http.h11_impl', 'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.lifespan.on', 'sqlalchemy.dialects.sqlite', 'yt_dlp', '__cffi_backend']
hiddenimports += collect_submodules('animan.services.extractors')
hiddenimports += ['animan.services.recipe_runtime', 'animan.services.recipe_plans']
if sys.platform == 'win32':
    hiddenimports += ['webview.platforms.edgechromium', 'webview.platforms.winforms']
elif sys.platform == 'darwin':
    hiddenimports += ['webview.platforms.cocoa']
else:
    hiddenimports += ['webview.platforms.gtk']
a = Analysis([str(project / 'desktop.py')], pathex=[str(project)], binaries=binaries,
    datas=datas, hiddenimports=hiddenimports,
    excludes=['pytest', 'tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy',
              'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'cefpython3'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AnimeLab',
    icon=str(project / 'docs/branding/animelab.ico') if sys.platform == 'win32' else None,
    console=sys.platform not in ('win32', 'darwin'), upx=False,
    target_arch=None, codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, name='AnimeLab', strip=False, upx=False)
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='AnimeLab.app', icon=str(project / 'docs/branding/animelab.icns'), bundle_identifier='com.animan.desktop',
        info_plist={'CFBundleShortVersionString':__version__, 'CFBundleVersion':__version__,
                    'NSHighResolutionCapable':True})
