"""Visible Windows application for end-to-end capture/audio/XInput verification.

This is a real desktop window and system audio playback, not an adapter media source.
Input is read only from Windows XInput; there is no connection to host internals.
"""
import ctypes as c
import json
import math
from pathlib import Path
import struct
import time
import tkinter as tk
import wave
import winsound

ROOT = Path(__file__).resolve().parents[1] / 'build'
ROOT.mkdir(exist_ok=True)
class Pad(c.Structure):
    _fields_ = [('buttons', c.c_ushort), ('lt', c.c_ubyte), ('rt', c.c_ubyte),
                ('lx', c.c_short), ('ly', c.c_short), ('rx', c.c_short), ('ry', c.c_short)]
class State(c.Structure):
    _fields_ = [('packet', c.c_ulong), ('pad', Pad)]
xinput = c.WinDLL('xinput1_4')
xinput.XInputGetState.argtypes = [c.c_ulong, c.POINTER(State)]
tone = ROOT / 'desktop-probe-tone.wav'
with wave.open(str(tone), 'wb') as wav:
    wav.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
    wav.writeframes(b''.join(struct.pack('<hh', *(2*[int(2800*math.sin(2*math.pi*(440 if i<48000 else 660)*i/48000))])) for i in range(96000)))
winsound.PlaySound(str(tone), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
window = tk.Tk()
window.title('Apollo Desktop Input Probe')
window.geometry('580x400+10+35')
window.attributes('-topmost', True)
canvas = tk.Canvas(window, bg='#122235', highlightthickness=0)
canvas.pack(fill='both', expand=True)
started = time.monotonic()
position, jumps, previous = 280.0, 0, 0
events = open(ROOT/'desktop-probe-events.jsonl', 'a', buffering=1)
events.write(json.dumps({'event':'start','time':time.time()})+'\n')
last = None
last_audio = 0.0

def update():
    global position, jumps, previous, last, last_audio
    # Apollo may switch the Windows default sink when a session starts.
    if time.monotonic() - last_audio > 2:
        winsound.PlaySound(str(tone), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
        last_audio = time.monotonic()
    pad = Pad()
    connected = False
    for index in range(4):
        state = State()
        if xinput.XInputGetState(index, c.byref(state)) == 0:
            pad, connected = state.pad, True
            break
    if pad.buttons & 0x1000 and not previous & 0x1000:
        jumps += 1
    previous = pad.buttons
    position = max(25, min(550, position + pad.lx/32768*7 + (bool(pad.buttons&8)-bool(pad.buttons&4))*7))
    current = (connected, pad.buttons, pad.lx, pad.ly, jumps)
    if current != last:
        events.write(json.dumps({'event':'xinput','time':time.time(),'connected':connected,
                                'buttons':pad.buttons,'lx':pad.lx,'ly':pad.ly,'jumps':jumps,'x':position})+'\n')
        last = current
    canvas.delete('all')
    canvas.create_text(290, 32, text='REAL WINDOWS DESKTOP', fill='white', font=('Segoe UI',20,'bold'))
    canvas.create_text(290, 78, text=f'Live clock: {time.monotonic()-started:07.2f} s', fill='#69d8ff',font=('Consolas',22))
    canvas.create_text(290, 124, text=f'XInput: {"connected" if connected else "waiting"} | A presses: {jumps}', fill='white',font=('Segoe UI',16))
    canvas.create_text(290, 165, text=f'Buttons {pad.buttons:04x}    Stick {pad.lx}, {pad.ly}',fill='white',font=('Consolas',15))
    canvas.create_oval(position-22,230,position+22,274,fill='#f6bd60' if pad.buttons&0x1000 else '#60d6a0')
    canvas.create_text(290, 320, text='D-pad / left stick moves the ball; Cross changes colour.\n440 / 660 Hz sound plays through Windows.',fill='white',font=('Segoe UI',13))
    window.after(16, update)

def close():
    winsound.PlaySound(None, 0)
    events.close()
    window.destroy()
window.protocol('WM_DELETE_WINDOW', close)
update()
window.mainloop()
