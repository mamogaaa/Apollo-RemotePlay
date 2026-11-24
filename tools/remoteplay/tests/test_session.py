import base64
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from host import Host, Store, PROFILES
from session import Rejected
from input import Controller

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.host = Host(Store(Path(self.tmp.name)/'state.json'),12345678)
        self.p = PROFILES['ps4']
        self.credential = '1234abcd'
        self.key = bytes(range(16))
        self.host.store.data['ps4']['clients'][self.credential] = {'key':self.key.hex(),'account_id':'42'*8}

    def tearDown(self): self.tmp.cleanup()

    def init(self):
        return self.host.sessions.init(self.p,'127.0.0.1',{'rp-registkey':self.credential.encode().hex()})

    def encrypted_headers(self, nonce, key=None):
        crypto = self.host.crypto
        ctx = crypto.auth(self.p.target,base64.b64decode(nonce),key or self.key)
        values = [self.credential.encode().ljust(16,b'\0'),bytes(32),b'Windows\0',bytes(4)]
        return {name:base64.b64encode(crypto.transform(ctx,value,counter=i)).decode()
                for i,(name,value) in enumerate(zip(('rp-auth','rp-did','rp-ostype','rp-startbitrate'),values))}

    def test_unregistered_key_rejected(self):
        with self.assertRaises(Rejected): self.host.sessions.init(self.p,'127.0.0.1',{'rp-registkey':'deadbeef'})
        self.assertFalse(self.host.sessions.pending)

    def test_old_nonce_and_wrong_key_rejected(self):
        first = self.init()['RP-Nonce']
        second = self.init()['RP-Nonce']
        self.assertNotEqual(first,second)
        for h in (self.encrypted_headers(first),self.encrypted_headers(second,bytes(16))):
            with self.assertRaises(Rejected): self.host.sessions.authorize(self.p,'127.0.0.1',h,None)
        self.assertFalse(self.host.sessions.active)
        self.host.sessions.authorize(self.p,'127.0.0.1',self.encrypted_headers(second),None)
        self.assertTrue(self.host.sessions.active)

    def test_expiry_and_wrong_peer_rejected(self):
        nonce = self.init()['RP-Nonce']
        h = self.encrypted_headers(nonce)
        with self.assertRaises(Rejected): self.host.sessions.authorize(self.p,'127.0.0.2',h,None)
        self.host.sessions.pending['127.0.0.1','PS4'].deadline = 0
        with self.assertRaises(Rejected): self.host.sessions.authorize(self.p,'127.0.0.1',h,None)

    def test_authorization_consumes_nonce_and_busy_is_explicit(self):
        nonce = self.init()['RP-Nonce']
        h = self.encrypted_headers(nonce)
        self.host.sessions.authorize(self.p,'127.0.0.1',h,None)
        with self.assertRaises(Rejected): self.host.sessions.authorize(self.p,'127.0.0.1',h,None)
        with self.assertRaises(Rejected) as ctx: self.init()
        self.assertEqual(ctx.exception.reason,'80108b10')

    def test_input_history_newest_wins_and_replay_ignored(self):
        c = Controller()
        c.receive(1,65535,b'\x80\x88\xff')
        self.assertEqual(c.buttons[0x88],255)
        c.receive(1,0,b'\x80\x88\0\x80\x88\xff')
        self.assertEqual(c.buttons[0x88],0)
        c.receive(1,65535,b'\x80\x88\xff')
        self.assertEqual(c.buttons[0x88],0)
        c.reset()
        self.assertFalse(c.buttons)
        self.assertEqual(c.axes,(0,0,0,0))
