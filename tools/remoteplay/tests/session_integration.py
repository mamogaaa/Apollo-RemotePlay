"""Real Chiaki session engine against the host over loopback."""
import asyncio
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from host import Host, Store

async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'control'
    target_frames = 3600 if '--soak' in sys.argv else 120
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp)/'state.json')
        root = Path(__file__).resolve().parents[1]
        host = Host(store, 12345678)
        from host import Datagram
        registration_udp, _ = await asyncio.get_running_loop().create_datagram_endpoint(lambda: Datagram(host), local_addr=('127.0.0.1',9295))
        server = await asyncio.start_server(host.client, '127.0.0.1',9295)
        try:
            for profile in ('ps4','ps5'):
                proc = await asyncio.create_subprocess_exec(str(root/'build/registration-client'),profile,'127.0.0.1','12345678',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                try:
                    out,err = await asyncio.wait_for(proc.communicate(),10)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
                    raise
                assert proc.returncode == 0, (out,err)
        finally:
            registration_udp.close()
            server.close()
            await server.wait_closed()
        # Restart the host and close pairing; clients must use credentials from registration.
        host = Host(Store(store.path),0)
        host.deadline = 0
        server = await asyncio.start_server(host.client,'127.0.0.1',9295)
        from takion import TakionServer
        probe, _ = await asyncio.get_running_loop().create_datagram_endpoint(lambda: TakionServer(host,probe=True), local_addr=('127.0.0.1',9297))
        udp = None
        source = None
        if "--live-fixture" in sys.argv:
            from live_fixture import Fixture
            source = Fixture()
            await source.start()
        if mode == 'stream':
            from takion import TakionServer
            udp, protocol = await asyncio.get_running_loop().create_datagram_endpoint(lambda: TakionServer(host,drop_test='--loss' in sys.argv,source=source), local_addr=('127.0.0.1',9296))
        try:
            for profile in ('ps4','ps5'):
                for attempt in range(1 if '--soak' in sys.argv else 2):
                    root = Path(__file__).resolve().parents[1]
                    p = await asyncio.create_subprocess_exec(str(root/'build/session-client'),profile,mode,str(root/'build'/f'{profile}-received.h264'),str(target_frames),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                    try:
                        credential, client = next(iter(host.store.data[profile]['clients'].items()))
                        secret_input = (credential+' '+client['key']+'\n').encode()
                        out, err = await asyncio.wait_for(p.communicate(secret_input),25+target_frames/60)
                    except TimeoutError:
                        p.kill()
                        await p.wait()
                        raise
                    print(out.decode(),err.decode())
                    assert p.returncode == 0, (profile,p.returncode)
                    if mode == 'stream':
                        assert {'left_x','cross_down','cross_up'} <= protocol.input_observed, protocol.input_observed
                        protocol.input_observed.clear()
                        if '--loss' in sys.argv:
                            assert protocol.dropped_packets > 0
                        from validate_media import validate
                        validate(root/'build'/f'{profile}-received.h264',source.accepted if source else protocol.frames)
                        if source:
                            assert any(event[3] == 12345 for event in source.input_events)
                            assert any(event[0] & 0x1000 for event in source.input_events)
                            assert source.input_events[-1] == (0,0,0,0,0,0,0)
                            source.input_events.clear()
                    await asyncio.sleep(1.1)
                    assert not host.sessions.active, 'control session leaked'
            print(f'PASS: real Chiaki {mode} and reconnect for both profiles')
        finally:
            server.close()
            await server.wait_closed()
            probe.close()
            if udp: udp.close()
            await asyncio.sleep(0)
            if source: await source.close()

asyncio.run(main())
