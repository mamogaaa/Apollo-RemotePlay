"""Adapter boundaries: authenticated pairing, audio conversion, input and backpressure."""
import ctypes as c
import hashlib
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apollo_control import Apollo
from apollo_source import AudioConverter, ApolloSource, map_controller
from input import Controller
from media import prepare, prepare_audio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class Tests(unittest.TestCase):
    def test_audio_conversion_and_duration(self):
        converter = AudioConverter()
        try:
            packets = [packet for data in prepare_audio() for packet in converter.convert(data)]
            self.assertEqual(len(packets),200)
            self.assertTrue(all(len(packet)==120 for packet in packets))
            decoded = c.create_string_buffer(1920)
            self.assertEqual(converter.lib.opus_decode(converter.decoder,packets[0],len(packets[0]),decoded,480,0),480)
        finally: converter.close()

    def test_controller_mapping_and_reset(self):
        controller = Controller()
        controller.axes = (12345,-32768,-12345,32767)
        controller.buttons = {0x88:255,0x80:255,0x86:64,0x87:128,0x91:255}
        self.assertEqual(map_controller(controller),(0x101001,64,128,12345,32767,-12345,-32767))
        controller.reset()
        self.assertEqual(map_controller(controller),(0,0,0,0,0,0,0))

    def test_native_callback_bounds_and_idr_recovery(self):
        source = ApolloSource.__new__(ApolloSource)
        source.lock = threading.Lock(); source.active = True; source.wait_idr = True
        source.video_queue = queue.Queue(3); source.header = b''; source.error = None
        header,frames = prepare()
        def submit(frame,idr):
            data = c.create_string_buffer(frame)
            return source.callback(1,c.addressof(data),len(frame),idr)
        self.assertEqual(submit(frames[1],0),-1)
        self.assertEqual(submit(frames[0],1),0)
        self.assertEqual(source.header,header)
        self.assertEqual(submit(frames[1],0),0)
        self.assertEqual(submit(frames[2],0),0)
        self.assertEqual(submit(frames[3],0),-1)
        self.assertTrue(source.wait_idr)
        self.assertEqual(source.video_queue.qsize(),3)
        while not source.video_queue.empty(): source.video_queue.get_nowait()
        self.assertEqual(submit(frames[4],0),-1)
        self.assertEqual(submit(frames[60],1),0)

    def test_pairing_verifies_both_proofs_and_persists_pin(self):
        for corrupt in (False,True):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as tmp:
                client = Apollo(Path(tmp)/'client'); server = Apollo(Path(tmp)/'server')
                cert = x509.load_pem_x509_certificate(server.cert_path.read_bytes())
                key = serialization.load_pem_private_key(server.key_path.read_bytes(),None)
                clientcert = x509.load_pem_x509_certificate(client.cert_path.read_bytes())
                state = {}
                def request(path,parameters=None,secure=True,timeout=15):
                    root = ET.Element('root',status_code='200')
                    def put(name,value): ET.SubElement(root,name).text=value
                    params = parameters or {}
                    if path=='serverinfo': put('HttpsPort','47984'); return root
                    put('paired','1')
                    if params.get('phrase')=='getservercert':
                        aes = hashlib.sha256(bytes.fromhex(params['salt'])+b'1234').digest()[:16]
                        state['cipher'] = Cipher(algorithms.AES(aes),modes.ECB())
                        put('plaincert',server.cert_path.read_bytes().hex())
                    elif 'clientchallenge' in params:
                        ctx = state['cipher'].decryptor()
                        challenge = ctx.update(bytes.fromhex(params['clientchallenge']))+ctx.finalize()
                        state['secret']=b's'*16; state['challenge']=b'c'*16
                        digest = hashlib.sha256(challenge+cert.signature+state['secret']).digest()
                        ctx = state['cipher'].encryptor()
                        put('challengeresponse',(ctx.update(digest+state['challenge'])+ctx.finalize()).hex())
                    elif 'serverchallengeresp' in params:
                        ctx = state['cipher'].decryptor()
                        state['clienthash']=ctx.update(bytes.fromhex(params['serverchallengeresp']))+ctx.finalize()
                        signature = key.sign(state['secret'],padding.PKCS1v15(),hashes.SHA256())
                        if corrupt: signature = bytes([signature[0]^1])+signature[1:]
                        put('pairingsecret',(state['secret']+signature).hex())
                    elif 'clientpairingsecret' in params:
                        proof = bytes.fromhex(params['clientpairingsecret'])
                        clientcert.public_key().verify(proof[16:],proof[:16],padding.PKCS1v15(),hashes.SHA256())
                        self.assertEqual(state['clienthash'],hashlib.sha256(state['challenge']+clientcert.signature+proof[:16]).digest())
                        state['accepted']=True
                    else:
                        self.assertTrue(secure)
                        self.assertEqual(params['phrase'],'pairchallenge')
                    return root
                client.request=request
                if corrupt:
                    with self.assertRaises(Exception): client.pair('localhost','1234')
                    self.assertNotIn('server_der',Apollo(Path(tmp)/'client').state)
                    self.assertNotIn('accepted',state)
                else:
                    client.pair('localhost','1234')
                    self.assertTrue(state['accepted'])
                    self.assertEqual(Apollo(Path(tmp)/'client').state['server_der'],cert.public_bytes(serialization.Encoding.DER).hex())
                    self.assertEqual(client.key_path.stat().st_mode & 0o777,0o600)
