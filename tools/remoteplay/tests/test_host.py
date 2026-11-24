import asyncio
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from host import Host, Store, PROFILES, Datagram, headers

class Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.host = Host(Store(Path(self.tmp.name)/'state.json'), 12345678)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_discovery_udp_both_profiles(self):
        loop = asyncio.get_running_loop()
        for p in PROFILES.values():
            transport, _ = await loop.create_datagram_endpoint(lambda: Datagram(self.host, p), local_addr=('127.0.0.1', 0))
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            try:
                await loop.sock_sendto(sock, f'SRCH * HTTP/1.1\ndevice-discovery-protocol-version:{p.discovery_version}\n'.encode(), transport.get_extra_info('sockname'))
                packet = await asyncio.wait_for(loop.sock_recv(sock, 2048), 1)
                h = headers(packet.split(b'\r\n', 1)[1])
                self.assertEqual(h['host-type'], p.name)
                self.assertEqual(h['device-discovery-protocol-version'], p.discovery_version)
            finally:
                sock.close()
                transport.close()

    def test_malformed_discovery_ignored(self):
        p = PROFILES['ps4']
        for data in (b'garbage', b'WAKEUP * HTTP/1.1\n', b'SRCH * HTTP/1.1\n\xff', b'x'*4096,
                     b'SRCH * HTTP/1.1\ndevice-discovery-protocol-version:00030010\n'):
            self.assertIsNone(self.host.discovery(p, data))

    def test_identity_persisted(self):
        self.assertEqual(self.host.store.data, Store(self.host.store.path).data)
        self.assertEqual(self.host.store.path.stat().st_mode & 0o777, 0o600)

    async def request(self, data):
        server = await asyncio.start_server(self.host.client, '127.0.0.1', 0, limit=8192)
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', server.sockets[0].getsockname()[1])
            writer.write(data)
            await writer.drain()
            response = await asyncio.wait_for(reader.read(), 2)
            writer.close()
            await writer.wait_closed()
            return response
        finally:
            server.close()
            await server.wait_closed()

    async def test_streaming_explicitly_unimplemented(self):
        response = await self.request(b'GET /sie/ps4/rp/sess/init HTTP/1.1\r\nContent-Length: 0\r\n\r\n')
        self.assertTrue(response.startswith(b'HTTP/1.1 501'))

    async def test_reject_bad_framing(self):
        for extra in (b'Content-Length: 5000', b'Content-Length: -1', b'Content-Length: 0\r\nContent-Length: 0', b'Transfer-Encoding: chunked'):
            response = await self.request(b'POST /sie/ps4/rp/sess/rgst HTTP/1.1\r\n'+extra+b'\r\n\r\n')
            self.assertTrue(response.startswith(b'HTTP/1.1 400'))

    async def test_pairing_expired(self):
        self.host.deadline = 0
        response = await self.request(b'POST /sie/ps4/rp/sess/rgst HTTP/1.1\r\nContent-Length: 0\r\nRP-Version: 10.0\r\n\r\n')
        self.assertTrue(response.startswith(b'HTTP/1.1 403'))

if __name__ == '__main__':
    unittest.main()
