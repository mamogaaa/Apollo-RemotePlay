"""Control plane embedded in Apollo; all media capture/encoding/UDP output is C++."""

import asyncio
import ctypes
from pathlib import Path
import installed_runtime as runtime
from private_files import protect


def main():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetModuleHandleW.restype = ctypes.c_void_p
    native = ctypes.CDLL("", handle=kernel.GetModuleHandleW(None))
    native.rp_direct_data_path.restype = ctypes.c_char_p
    directory = Path(native.rp_direct_data_path().decode())
    directory.mkdir(exist_ok=True)
    protect(directory)
    runtime.DATA = directory
    runtime.setup_logging()
    if not (directory / "config.json").exists():
        runtime.write_json(
            directory / "config.json",
            dict(bind="127.0.0.1", appid=native.rp_direct_default_app()),
        )

    class Stop:
        def is_set(self):
            return native.rp_direct_stopping() != 0

    asyncio.run(runtime.run_managed(Stop(), directory))
