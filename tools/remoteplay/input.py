"""Normalize authenticated Remote Play feedback; OS injection is a separate adapter."""
import struct

class Controller:
    def __init__(self):
        self.axes = (0,0,0,0)
        self.buttons = {}
        self.sequence = {}
        self.observed = set()

    def reset(self):
        self.axes = (0,0,0,0)
        self.buttons.clear()

    def receive(self, kind, seq, data):
        previous = self.sequence.get(kind)
        if previous is not None and not 0 < ((seq-previous)&0xffff) < 0x8000:
            return
        if kind == 6:
            if len(data) not in (25,28) or data[0] != 0xa0: return
            self.axes = struct.unpack_from('!hhhh',data,17)
            if self.axes[0] == 12345: self.observed.add('left_x')
        elif kind == 1:
            offset = 0
            newest = {}
            while offset < len(data):
                if data[offset] in (0xc0,0xd0):
                    if offset+5 > len(data): return
                    offset += 5  # Touch contacts are not yet mapped to a PC action.
                    continue
                if data[offset] != 0x80 or offset+2 > len(data): return
                code = data[offset+1]
                size = 3 if 0x80 <= code <= 0x8b else 2
                if offset+size > len(data): return
                if size == 3:
                    button,value = code,data[offset+2]
                else:
                    button,value = (code-0x20,255) if 0xac <= code <= 0xb1 else (code,0)
                newest.setdefault(button,value)
                offset += size
            self.buttons.update(newest)
            if 0x88 in newest:
                self.observed.add('cross_down' if newest[0x88] else 'cross_up')
        else:
            return
        self.sequence[kind] = seq
