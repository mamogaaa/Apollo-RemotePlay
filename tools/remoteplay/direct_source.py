"""Control-only bindings to native media inside Apollo. No Python video/audio loop."""

import asyncio
import ctypes as c
from controller_mapping import map_controller


class DirectSource:
    native = True

    def __init__(self, appid):
        self.appid = appid
        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.GetModuleHandleW.restype = c.c_void_p
        self.lib = c.CDLL("", handle=kernel.GetModuleHandleW(None))
        self.lib.rp_direct_configure.argtypes = [
            c.c_uint64,
            c.c_char_p,
            c.c_int,
            c.c_int,
            c.c_void_p,
            c.c_void_p,
            c.c_uint64,
        ]
        self.lib.rp_direct_reserve.argtypes = [c.c_uint]
        self.lib.rp_direct_reserve.restype = c.c_uint64
        self.lib.rp_direct_header.argtypes = [c.c_void_p, c.c_int]
        self.lib.rp_direct_input.argtypes = [c.c_int] * 7
        self.lib.rp_direct_begin.argtypes = [c.c_int]
        for name in ("stream", "idr", "input", "end"):
            getattr(self.lib, "rp_direct_" + name).restype = None
        self.closing = None
        self.owner = None

    async def begin_connection(self, conn):
        if self.closing:
            await self.closing
        socket = conn.server.transport.get_extra_info("socket").fileno()
        result = self.lib.rp_direct_configure(
            socket,
            conn.addr[0].encode(),
            conn.addr[1],
            conn.active.pending.profile.name == "PS5",
            conn.handshake,
            conn.shared_secret,
            conn.position,
        )
        if result:
            raise RuntimeError(f"Native Remote Play configure failed ({result})")
        self.owner = conn
        conn.native_keys = True
        try:
            start = asyncio.create_task(
                asyncio.to_thread(self.lib.rp_direct_begin, self.appid)
            )
            try:
                result = await asyncio.shield(start)
            except asyncio.CancelledError:
                await start
                raise
            if result:
                raise RuntimeError(f"Apollo capture failed ({result})")
            header = c.create_string_buffer(65536)
            async with asyncio.timeout(15):
                while True:
                    size = self.lib.rp_direct_header(header, len(header))
                    if size < 0:
                        raise RuntimeError("Oversized stream header")
                    if size:
                        return header.raw[:size]
                    await asyncio.sleep(0.01)
        except BaseException:
            self.end()
            raise

    def reserve(self, size):
        pos = self.lib.rp_direct_reserve(size)
        if pos > 0xFFFFF000:
            raise ValueError("Rekey required before key-position wrap")
        return pos

    def stream(self):
        self.lib.rp_direct_stream()

    def idr(self):
        self.lib.rp_direct_idr()

    def input(self, controller):
        if self.owner:
            self.lib.rp_direct_input(*map_controller(controller))

    def end(self):
        if self.owner:
            self.owner = None
            self.closing = asyncio.create_task(
                asyncio.to_thread(self.lib.rp_direct_end)
            )

    async def close(self):
        self.end()
        if self.closing:
            await self.closing
