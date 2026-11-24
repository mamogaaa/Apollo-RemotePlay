"""Build an unmodified headless Chiaki engine, its test driver, and protobuf bindings."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('chiaki',type=Path)
p.add_argument('--prefix',type=Path,help='Optional dependency prefix, e.g. extracted Debian /usr')
a = p.parse_args()
root = a.chiaki.resolve()
here = Path(__file__).resolve().parent
out = here/'build'
build = root/'build-session'
subprocess.run([sys.executable,str(here/'build.py'),str(root)],check=True)
env = os.environ.copy()
libs = []
cmake = []
if a.prefix:
    prefix = a.prefix.resolve()
    libdir = prefix/'lib/x86_64-linux-gnu'
    for key,value in [('PATH',str(prefix/'bin')),('LD_LIBRARY_PATH',str(libdir)),('PKG_CONFIG_PATH',str(libdir/'pkgconfig'))]:
        env[key] = value + os.pathsep + env.get(key,'')
    libs = ['-L'+str(libdir),'-Wl,-rpath,'+str(libdir)]
    cmake.append('-DCMAKE_PREFIX_PATH='+str(prefix))
options = {'GUI':'OFF','TESTS':'OFF','CLI':'ON','STEAM_SHORTCUT':'OFF','STEAMDECK_NATIVE':'OFF','FFMPEG_DECODER':'OFF','PI_DECODER':'OFF'}
subprocess.run(['cmake','-S',str(root),'-B',str(build),
                *[f'-DCHIAKI_ENABLE_{k}={v}' for k,v in options.items()],
                '-DCHIAKI_LIB_ENABLE_OPUS=OFF','-DCHIAKI_USE_SYSTEM_CURL=ON',
                '-DPYTHON_EXECUTABLE='+sys.executable,*cmake],env=env,check=True)
subprocess.run(['cmake','--build',str(build),'-j4'],env=env,check=True)
subprocess.run(['cc','-O2','-I'+str(root/'lib/include'),'-I'+str(build/'lib/include'),
                str(here/'tests/session_client.c'),str(build/'lib/libchiaki.a'),
                str(build/'third-party/nanopb/libprotobuf-nanopb.a'),
                str(build/'third-party/libjerasure.a'),str(build/'third-party/libgf_complete.a'),
                *libs,'-ljson-c','-lminiupnpc','-levent','-lcurl','-lcrypto','-lpthread','-lm',
                '-o',str(out/'session-client')],env=env,check=True)
protoc = shutil.which('protoc',path=env['PATH'])
if not protoc: p.error('protoc missing from PATH')
subprocess.run([protoc,'-I'+str(root/'lib/protobuf'),'--python_out='+str(out),str(root/'lib/protobuf/takion.proto')],env=env,check=True)
