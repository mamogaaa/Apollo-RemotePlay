"""Keep Windows UDP listeners alive when a previous client closes its port."""
import os
import ctypes as c


def configure_udp(transport):
    if os.name == 'nt':
        # ICMP port-unreachable must not stop asyncio's receive loop after disconnect.
        ws = c.WinDLL('ws2_32')
        ws.WSAIoctl.argtypes = [c.c_size_t, c.c_ulong, c.c_void_p, c.c_ulong,
                               c.c_void_p, c.c_ulong, c.c_void_p, c.c_void_p, c.c_void_p]
        disabled, returned = c.c_ulong(0), c.c_ulong()
        if ws.WSAIoctl(transport.get_extra_info('socket').fileno(), 0x9800000C,
                       c.byref(disabled), c.sizeof(disabled), None, 0,
                       c.byref(returned), None, None):
            raise OSError(ws.WSAGetLastError(), 'SIO_UDP_CONNRESET failed')
