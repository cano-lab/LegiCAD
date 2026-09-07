# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_all

datas = [('render_ui.html', '.'), ('postprocessor.py', '.'), ('upscaler.py', '.'), ('ai_enhancer.py', '.'), ('ai_segmentation.py', '.'), ('image_channels.py', '.'), ('gpu_memory.py', '.'), ('channel_extractor_warp.py', '.'), ('progress_state.py', '.'), ('render/enhance/inpainting.py', 'render/enhance'), ('render/enhance/style_harmonizer.py', 'render/enhance')]
binaries = []
hiddenimports = ['torch', 'torchvision', 'diffusers', 'transformers', 'controlnet_aux', 'xformers', 'flask', 'flask_cors', 'PIL', 'cv2', 'numpy', 'scipy', 'huggingface_hub', 'safetensors', 'accelerate', 'warp', 'trimesh', 'spandrel', 'skimage']
datas += collect_data_files('torch')
tmp_ret = collect_all('diffusers')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('transformers')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('controlnet_aux')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('warp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('scipy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('skimage')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('trimesh')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['render_server.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['./hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['channel_extractor_warp'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='enhancer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='enhancer',
)
