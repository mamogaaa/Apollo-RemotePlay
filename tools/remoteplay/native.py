"""Load native dependencies explicitly on Windows (Python 3.8+ DLL rules)."""
import ctypes
import ctypes.util
import os
from pathlib import Path

BUILD = Path(__file__).resolve().parent / 'build'
_directories = []
if os.name == 'nt':
    for directory in (BUILD, Path(os.environ['REMOTEPLAY_NATIVE_BIN']) if os.environ.get('REMOTEPLAY_NATIVE_BIN') else BUILD):
        if directory.is_dir():
            _directories.append(os.add_dll_directory(str(directory)))


def library(name):
    if name in ('rpcrypt', 'moonbridge'):
        path = BUILD / (f'{name}.dll' if os.name == 'nt' else f'lib{name}.so')
        return ctypes.CDLL(str(path))
    path = 'libopus-0.dll' if os.name == 'nt' and name == 'opus' else ctypes.util.find_library(name)
    if not path:
        raise RuntimeError(f'Native library missing: {name}')
    return ctypes.CDLL(path)
