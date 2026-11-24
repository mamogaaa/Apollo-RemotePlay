"""Build native Windows DLLs using MSYS2 UCRT64; run with Windows Python."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('chiaki', type=Path)
p.add_argument('--prefix', type=Path, default=Path('C:/msys64/ucrt64'))
p.add_argument('--clients', action='store_true', help='Also build unmodified Chiaki engine and test drivers')
a = p.parse_args()
here = Path(__file__).resolve().parent
chiaki = a.chiaki.resolve()
for source, pin in ((chiaki, '43728af2e639fecb8a7af1cd68c29820a40de973'),
                    (here.parent.parent/'third-party/moonlight-common-c', 'c999436858471dfefa7617af3b7dc03ec1644ce4')):
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != pin:
        p.error(f'Unexpected source revision: {source}')
env = os.environ.copy()
env['PATH'] = str(a.prefix/'bin') + os.pathsep + env['PATH']
cmake = str(a.prefix/'bin/cmake.exe')
build = here/'build/windows'
subprocess.run([cmake, '-S', str(here/'windows'), '-B', str(build), '-G', 'Ninja',
    '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_COMPILER='+str(a.prefix/'bin/gcc.exe'),
    '-DCMAKE_PREFIX_PATH='+str(a.prefix), '-DCHIAKI_SOURCE='+str(chiaki)], env=env, check=True)
subprocess.run([cmake, '--build', str(build), '-j4'], env=env, check=True)
subprocess.run([str(a.prefix/'bin/protoc.exe'), '-I'+str(chiaki/'lib/protobuf'),
    '--python_out='+str(here/'build'), str(chiaki/'lib/protobuf/takion.proto')], env=env, check=True)
if a.clients:
    client_build = chiaki/'build-session-win'
    options = {'GUI':'OFF', 'TESTS':'OFF', 'CLI':'OFF', 'STEAM_SHORTCUT':'OFF',
               'STEAMDECK_NATIVE':'OFF', 'FFMPEG_DECODER':'OFF', 'PI_DECODER':'OFF'}
    subprocess.run([cmake, '-S', str(chiaki), '-B', str(client_build), '-G', 'Ninja',
        '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_POLICY_VERSION_MINIMUM=3.5',
        '-DCMAKE_PREFIX_PATH='+str(a.prefix), '-DCHIAKI_LIB_ENABLE_OPUS=OFF',
        '-DCHIAKI_USE_SYSTEM_CURL=ON', '-DPYTHON_EXECUTABLE='+sys.executable,
        *[f'-DCHIAKI_ENABLE_{k}={v}' for k,v in options.items()]], env=env, check=True)
    subprocess.run([cmake, '--build', str(client_build), '-j4'], env=env, check=True)
    archives = [client_build/path for path in ('lib/libchiaki.a',
        'third-party/nanopb/libprotobuf-nanopb.a', 'third-party/libjerasure.a', 'third-party/libgf_complete.a')]
    for name in ('registration', 'session'):
        subprocess.run([str(a.prefix/'bin/gcc.exe'), '-O2', '-I'+str(chiaki/'lib/include'),
            '-I'+str(client_build/'lib/include'), str(here/'tests'/f'{name}_client.c'),
            *map(str, archives), '-ljson-c', '-lminiupnpc', '-levent', '-lcurl', '-lssl',
            '-lcrypto', '-lws2_32', '-lcrypt32', '-liphlpapi', '-lbcrypt', '-lm',
            '-o', str(here/'build'/f'{name}-client.exe')], env=env, check=True)
