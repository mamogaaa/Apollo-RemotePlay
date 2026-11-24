"""LAN research host: PS4/PS5 registration and an encrypted test AV stream."""
import argparse
import asyncio
import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import time
from crypto import Crypto
from private_files import protect
from network import configure_udp
from session import Sessions, Rejected

@dataclass(frozen=True)
class Profile:
    name: str
    target: int
    discovery_port: int
    discovery_version: str
    system_version: str
    rp_version: str
    search: bytes
    response: bytes

PROFILES = {
    'ps4': Profile('PS4', 1000, 987, '00020020', '08000000', '10.0', b'SRC2\0', b'RES2\0'),
    'ps5': Profile('PS5', 1000100, 9302, '00030010', '08050001', '1.0', b'SRC3\0', b'RES3\0'),
}

def headers(data):
    result = {}
    for line in data.decode('ascii').splitlines():
        if not line:
            continue
        key, sep, value = line.partition(':')
        if not sep or key.lower() in result:
            raise ValueError('malformed or duplicate header')
        result[key.lower()] = value.strip()
    return result

class Store:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
        else:
            self.data = {name: {'id': '02' + secrets.token_hex(5), 'clients': {}} for name in PROFILES}
            self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + '.' + secrets.token_hex(6) + '.tmp')
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f:
                protect(temp)
                json.dump(self.data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)

class Host:
    def __init__(self, store, pin, pairing_seconds=300):
        self.store, self.pin = store, pin
        self.deadline = time.monotonic() + pairing_seconds
        self.crypto = Crypto()
        self.failures = {}
        self.sessions = Sessions(self)

    def pairing(self):
        return time.monotonic() < self.deadline

    def discovery(self, profile, data):
        if len(data) > 2048:
            return None
        lines = data.split(b'\n', 1)
        if lines[0].strip() != b'SRCH * HTTP/1.1' or len(lines) != 2:
            return None
        try:
            h = headers(lines[1])
        except (ValueError, UnicodeError):
            return None
        if h.get('device-discovery-protocol-version') != profile.discovery_version:
            return None
        identity = self.store.data[profile.name.lower()]['id']
        return (f'HTTP/1.1 200 Ok\r\nhost-id:{identity}\r\nhost-type:{profile.name}\r\n'
                f'host-name:Apollo-RP-{profile.name}\r\nhost-request-port:9295\r\n'
                f'system-version:{profile.system_version}\r\n'
                f'device-discovery-protocol-version:{profile.discovery_version}\r\n\r\n').encode()

    def register(self, profile, payload):
        ctx, plaintext = self.crypto.registration(profile.target, self.pin, payload)
        h = headers(plaintext)
        if set(h) != {'client-type', 'np-accountid'} or not h['client-type']:
            raise ValueError('registration credentials invalid')
        account = base64.b64decode(h['np-accountid'], validate=True)
        if len(account) != 8:
            raise ValueError('account ID must contain eight bytes')
        state = self.store.data[profile.name.lower()]
        # RegistKey is eight ASCII hex characters, hex-encoded in the response.
        credential = secrets.token_hex(4)
        key = secrets.token_hex(16)
        fields = {f'{profile.name}-Nickname': f'Apollo-RP-{profile.name}',
                  f'{profile.name}-Mac': state['id'],
                  f'{profile.name}-RegistKey': credential.encode().hex(),
                  'RP-KeyType': '2', 'RP-Key': key}
        response = ''.join(f'{k}: {v}\r\n' for k, v in fields.items()).encode()
        encrypted = self.crypto.transform(ctx, response)
        state['clients'][credential] = {'account_id': account.hex(), 'key': key}
        self.store.save()
        return encrypted

    async def client(self, reader, writer):
        peer = writer.get_extra_info('peername')[0]
        status, body = 400, b''
        response_headers = {}
        control = None
        upgraded = False
        try:
            async with asyncio.timeout(5):
                raw = await reader.readuntil(b'\r\n\r\n')
                if len(raw) > 8192:
                    raise ValueError('header too large')
                line, rest = raw.split(b'\r\n', 1)
                method, path, version = line.decode('ascii').split()
                # Chiaki's registration formatter emits this extra line verbatim.
                if rest.startswith(b' HTTP/1.1\r\n'):
                    rest = rest[len(b' HTTP/1.1\r\n'):]
                h = headers(rest)
                if version != 'HTTP/1.1' or 'transfer-encoding' in h:
                    raise ValueError('unsupported framing')
                size = int(h.get('content-length', '0'))
                if not 0 <= size <= 4096:
                    raise ValueError('body too large')
                payload = await reader.readexactly(size)
                profile = next((p for p in PROFILES.values()
                                if path in (f'/sie/{p.name.lower()}/rp/sess/{a}' for a in ('rgst','init','ctrl'))), None)
                action = path.rsplit('/', 1)[-1]
                if profile and method == 'GET' and action in ('init', 'ctrl'):
                    if payload:
                        raise ValueError('session GET must have empty body')
                    if h.get('rp-version') != profile.rp_version:
                        response_headers['RP-Version'] = profile.rp_version
                        raise Rejected(400, '80108b11')
                    if action == 'init':
                        response_headers.update(self.sessions.init(profile, peer, h))
                        status = 200
                    else:
                        control = self.sessions.authorize(profile, peer, h, writer)
                elif not profile or method != 'POST' or action != 'rgst':
                    status = 501
                elif not self.pairing() or self.failures.get(peer, 0) >= 5:
                    status = 403
                elif h.get('rp-version') != profile.rp_version:
                    status = 400
                else:
                    try:
                        body = self.register(profile, payload)
                        status = 200
                    except (ValueError, UnicodeError):
                        self.failures[peer] = self.failures.get(peer, 0) + 1
                        status = 403
                    print(json.dumps({'event': 'registration', 'profile': profile.name, 'status': status}), flush=True)
            if control:
                upgraded = True
                await self.sessions.control(control, reader)
        except Rejected as exc:
            status = exc.status
            response_headers['RP-Application-Reason'] = exc.reason
        except (ValueError, UnicodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            status = 400
        except OSError:
            status = 500
        finally:
            reason = {200: 'OK', 400: 'Bad Request', 403: 'Forbidden', 500: 'Internal Server Error', 503: 'Service Unavailable', 501: 'Not Implemented'}[status]
            try:
                if not upgraded:
                    extra = ''.join(f'{k}: {v}\r\n' for k, v in response_headers.items())
                    writer.write(f'HTTP/1.1 {status} {reason}\r\n{extra}Content-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode() + body)
                    await writer.drain()
            except (OSError, ConnectionError):
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, ConnectionError):
                pass

class Datagram(asyncio.DatagramProtocol):
    def __init__(self, host, profile=None):
        self.host, self.profile = host, profile

    def connection_made(self, transport):
        configure_udp(transport)
        self.transport = transport

    def datagram_received(self, data, addr):
        if self.profile:
            reply = self.host.discovery(self.profile, data)
        else:
            reply = next((p.response for p in PROFILES.values() if data == p.search), None) if self.host.pairing() else None
        if reply:
            self.transport.sendto(reply, addr)

async def serve(args):
    host = Host(Store(args.state), secrets.randbelow(100000000), args.pairing_seconds)
    transports = []
    server = None
    source = None
    try:
        if args.apollo_state:
            from apollo_source import ApolloSource
            source = ApolloSource(args.apollo_state,args.apollo_app)
            await source.start()
        loop = asyncio.get_running_loop()
        for profile in PROFILES.values():
            transport, _ = await loop.create_datagram_endpoint(lambda p=profile: Datagram(host, p), local_addr=(args.bind, profile.discovery_port))
            transports.append(transport)
        transport, _ = await loop.create_datagram_endpoint(lambda: Datagram(host), local_addr=(args.bind, 9295))
        transports.append(transport)
        from takion import TakionServer
        for port in (9296,9297):
            transport, _ = await loop.create_datagram_endpoint(lambda p=port: TakionServer(host,probe=p==9297,source=source if p==9296 else None), local_addr=(args.bind,port))
            transports.append(transport)
        server = await asyncio.start_server(host.client, args.bind, 9295, limit=8192)
        source_name = 'Apollo live H.264 720p60 + Opus stereo' if source else 'test H.264 720p60 + Opus stereo'
        print(f'Pairing PIN: {host.pin:08d} (valid {args.pairing_seconds}s). Source: {source_name}.', flush=True)
        async with server:
            await server.serve_forever()
    finally:
        for transport in transports:
            transport.close()
        if server:
            server.close()
            await server.wait_closed()
        if source: await source.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='127.0.0.1', help='Set to PC LAN IPv4 address for real client testing')
    parser.add_argument('--state', type=Path, default=Path(__file__).parent/'state.json')
    parser.add_argument('--pairing-seconds', type=int, default=300)
    parser.add_argument('--apollo-state', type=Path, help='Directory created by apollo_control.py pair')
    parser.add_argument('--apollo-app', type=int, help='Apollo application ID from apollo_control.py apps')
    args = parser.parse_args()
    if bool(args.apollo_state) != (args.apollo_app is not None):
        parser.error('--apollo-state and --apollo-app must be provided together')
    if not 1 <= args.pairing_seconds <= 3600:
        parser.error('pairing-seconds must be 1..3600')
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass
