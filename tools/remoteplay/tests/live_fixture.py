"""Paced fixture for adapter callbacks; does NOT simulate Apollo's network protocol."""
import asyncio
import ctypes as c
import queue
import threading
from apollo_source import ApolloSource, AudioConverter, map_controller
from media import prepare, prepare_audio

class Fixture(ApolloSource):
    def __init__(self):
        self.lock=threading.Lock()
        self.active=False; self.wait_idr=True; self.header=b''; self.error=None
        self.started=False
        self.video_queue=queue.Queue(3); self.audio_queue=queue.Queue(10)
        self.converter=AudioConverter()
        self.frames=prepare()[1]; self.audio_frames=prepare_audio()
        self.input_events=[]; self.tasks=[]; self.accepted=[]
        self.request_idr=False
        self.lib=self

    def callback(self,kind,pointer,size,metadata):
        active=self.active
        result=super().callback(kind,pointer,size,metadata)
        if active and kind==1 and result==0:
            self.accepted.append(c.string_at(pointer,size))
        return result

    async def begin(self):
        self.accepted.clear()
        return await super().begin()

    def rp_moon_idr(self): self.request_idr=True

    async def start(self):
        self.tasks=[asyncio.create_task(self.feed(1)),asyncio.create_task(self.feed(2))]

    async def feed(self,kind):
        index=0
        try:
            while True:
                frames=self.frames if kind==1 else self.audio_frames
                if kind==1 and self.request_idr:
                    index=0; self.request_idr=False
                data=frames[index%len(frames)]
                buffer=c.create_string_buffer(data)
                result=self.callback(kind,c.addressof(buffer),len(data),int(kind==1 and index%60==0))
                if kind==1 and result: self.request_idr=True
                index+=1
                await asyncio.sleep(1/60 if kind==1 else .01)
        except asyncio.CancelledError: pass

    def input(self,controller): self.input_events.append(map_controller(controller))

    def end(self):
        super().end()
        self.input_events.append((0,0,0,0,0,0,0))

    async def close(self):
        self.end()
        for task in self.tasks: task.cancel()
        await asyncio.gather(*self.tasks)
        self.converter.close()
