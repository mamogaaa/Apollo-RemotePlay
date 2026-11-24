"""Build the Apollo adapter against Apollo's pinned Moonlight submodule."""
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent.parent/'third-party'/'moonlight-common-c'
BUILD = ROOT/'build'/'moonlight'
EXPECTED = 'c999436858471dfefa7617af3b7dc03ec1644ce4'
if subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip() != EXPECTED:
    raise SystemExit('Unexpected Moonlight revision')
subprocess.run(['cmake','-S',str(SOURCE),'-B',str(BUILD),'-DCMAKE_BUILD_TYPE=Release',
                '-DBUILD_SHARED_LIBS=OFF','-DCMAKE_POSITION_INDEPENDENT_CODE=ON'],check=True)
subprocess.run(['cmake','--build',str(BUILD),'-j4'],check=True)
subprocess.run(['cc','-shared','-fPIC','-Wall','-Wextra','-Wno-unused-parameter','-Werror',
    '-I'+str(SOURCE/'src'),str(ROOT/'moonbridge.c'),str(BUILD/'libmoonlight-common-c.a'),
    str(BUILD/'enet'/'libenet.a'),'-lcrypto','-lpthread','-o',str(ROOT/'build'/'libmoonbridge.so')],check=True)
