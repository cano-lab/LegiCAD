# hook-warp.py
# Custom PyInstaller hook for NVIDIA Warp
# Warp uses inspect.getsourcelines() for JIT compilation, so we need to include source files

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# Collect all warp submodules
hiddenimports = collect_submodules('warp')

# Collect all data files including Python source files (critical for JIT)
datas = collect_data_files('warp', include_py_files=True)

# Also collect from warp._src specifically
try:
    datas += collect_data_files('warp._src', include_py_files=True)
except Exception:
    pass

# Collect any binaries (CUDA kernels, DLLs)
_, binaries, _ = collect_all('warp')
