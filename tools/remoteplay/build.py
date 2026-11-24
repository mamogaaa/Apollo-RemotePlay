"""Build the research crypto shim against a pinned, external Chiaki checkout."""
import argparse
from pathlib import Path
import subprocess

PIN = '43728af2e639fecb8a7af1cd68c29820a40de973'
p = argparse.ArgumentParser()
p.add_argument('chiaki', type=Path)
a = p.parse_args()
root = a.chiaki.resolve()
if subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip() != PIN:
    p.error('Chiaki checkout must be at ' + PIN)
out = Path(__file__).resolve().parent / 'build'
out.mkdir(exist_ok=True)
subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-I'+str(root/'lib/include'),
                *[str(root/'lib/src'/f'{name}.c') for name in ('rpcrypt', 'gkcrypt', 'log', 'thread', 'time')],
                str(out.parent/'gkbridge.c'), '-lcrypto', '-lpthread', '-o', str(out/'librpcrypt.so')], check=True)
print(out/'librpcrypt.so')
sources = ['regist', 'rpcrypt', 'base64', 'common', 'session', 'http', 'log', 'sock', 'thread', 'stoppipe', 'random', 'time', 'remote/rudp', 'remote/rudpsendbuffer']
subprocess.run(['cc', '-O2', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections',
                '-I'+str(root/'lib/include'), '-I'+str(root/'third-party/jerasure/include'),
                '-I'+str(root/'third-party/gf-complete/include'),
                str(out.parent/'tests/registration_client.c'),
                *[str(root/'lib/src'/f'{name}.c') for name in sources],
                '-lcrypto', '-lpthread', '-lm', '-o', str(out/'registration-client')], check=True)
print(out/'registration-client')
