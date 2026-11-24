"""Exercise actual, unmodified Chiaki registration over UDP + TCP loopback."""
import asyncio
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from host import Host, Store, Datagram

async def main():
    with tempfile.TemporaryDirectory() as tmp:
        host = Host(Store(Path(tmp)/'state.json'), 12345678)
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(lambda: Datagram(host), local_addr=('127.0.0.1', 9295))
        server = await asyncio.start_server(host.client, '127.0.0.1', 9295)
        try:
            for profile in ('ps4', 'ps5'):
                for pin, expected in (('12345678', 0), ('87654321', 1)):
                    process = await asyncio.create_subprocess_exec(str(Path(__file__).resolve().parents[1]/'build/registration-client'), profile, '127.0.0.1', pin, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    try:
                        out, err = await asyncio.wait_for(process.communicate(), 15)
                    except TimeoutError:
                        process.kill()
                        await process.wait()
                        raise
                    assert process.returncode == expected, (profile, process.returncode, out, err)
                    print(f'{profile}: {"correct" if expected == 0 else "incorrect"} PIN -> expected result', out.decode().strip())
            state = Store(host.store.path).data
            assert all(len(x['clients']) == 1 for x in state.values())
            print('PASS: both profiles registered by real Chiaki code; wrong PIN rejected; credentials persisted.')
        finally:
            server.close()
            await server.wait_closed()
            transport.close()

asyncio.run(main())
