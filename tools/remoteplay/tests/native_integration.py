"""Exercise an already running native Apollo with the unchanged Chiaki engine.

No server fixture is created. Credentials stay on stdin and are not logged.
Run the real desktop probe separately for audible sound and XInput observation.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(Path(__file__).parent)]
from validate_live import validate_live

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--state', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--frames', type=int, default=300)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
state = json.loads(a.state.read_text(encoding='utf-8'))
env = os.environ.copy()
if env.get('REMOTEPLAY_NATIVE_BIN'):
    env['PATH'] = env['REMOTEPLAY_NATIVE_BIN'] + os.pathsep + env['PATH']
for profile in ('ps4', 'ps5'):
    for attempt in range(2):
        credential, client = next(iter(state[profile]['clients'].items()))
        media = a.output / f'{profile}-{attempt}.h264'
        result = subprocess.run(
            [str(root/'build/session-client.exe'), profile, 'stream', str(media), str(a.frames)],
            input=(credential+' '+client['key']+'\n').encode(), capture_output=True,
            env=env, timeout=30+a.frames/60)
        (a.output/f'{profile}-{attempt}.log').write_bytes(result.stdout+result.stderr)
        print(profile, attempt, result.stdout.decode(errors='replace').strip(), flush=True)
        if result.returncode:
            raise RuntimeError(f'{profile} session failed ({result.returncode}); inspect local log')
        validate_live(media)
        time.sleep(2)
print('PASS: native Apollo media and reconnect for both profiles. GUI, input and playback require separate observation.')
