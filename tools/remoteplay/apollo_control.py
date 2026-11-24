"""GameStream pairing/control for Apollo, with PIN-authenticated certificate pinning."""
import argparse
import datetime
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import secrets
import ssl
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.x509.oid import NameOID
from private_files import protect


def private_write(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        protect(temporary)
        stream.write(data)
    os.replace(temporary, path)


class Apollo:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.state_path = self.directory / 'apollo.json'
        self.cert_path = self.directory / 'client.pem'
        self.key_path = self.directory / 'client.key'
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text())
        else:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Apollo Remote Play adapter')])
            now = datetime.datetime.now(datetime.timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now-datetime.timedelta(days=1))
                    .not_valid_after(now+datetime.timedelta(days=3650)).sign(key, hashes.SHA256()))
            private_write(self.key_path, key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            private_write(self.cert_path, cert.public_bytes(serialization.Encoding.PEM))
            self.state = {'uniqueid': secrets.token_hex(8)}
            self.save()

    def save(self):
        private_write(self.state_path, json.dumps(self.state).encode())

    def request(self, path, parameters=None, secure=True, timeout=15):
        host = self.state['host']
        if secure:
            expected = self.state.get('server_der')
            if not expected:
                raise ValueError('Apollo must be paired before HTTPS control')
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE  # Exact certificate checked before sending request.
            context.load_cert_chain(self.cert_path, self.key_path)
            connection = http.client.HTTPSConnection(host, self.state['https_port'], context=context, timeout=timeout)
        else:
            connection = http.client.HTTPConnection(host, self.state['http_port'], timeout=timeout)
        try:
            connection.connect()
            if secure and not hmac.compare_digest(connection.sock.getpeercert(binary_form=True), bytes.fromhex(expected)):
                raise ValueError('Apollo certificate changed; refusing control request')
            query = {'uniqueid': self.state['uniqueid'], 'uuid': str(uuid.uuid4())}
            query.update(parameters or {})
            connection.request('GET', '/' + path + '?' + urllib.parse.urlencode(query))
            response = connection.getresponse()
            body = response.read(1024*1024+1)
            if len(body) > 1024*1024 or response.status != 200:
                raise ValueError('Invalid Apollo HTTP response')
            root = ET.fromstring(body)
            if root.get('status_code') != '200':
                raise ValueError('Apollo rejected request: ' + root.get('status_message', root.get('status_code', '?')))
            return root
        finally:
            connection.close()

    def pair(self, host, pin, http_port=47989):
        if len(pin) != 4 or not pin.isdigit():
            raise ValueError('Apollo PIN must contain four digits')
        self.state.update(host=host, http_port=http_port)
        info = self.request('serverinfo', secure=False)
        self.state['https_port'] = int(info.findtext('HttpsPort', str(http_port-5)))
        salt = secrets.token_bytes(16)
        cipher = Cipher(algorithms.AES(hashlib.sha256(salt+pin.encode()).digest()[:16]), modes.ECB())
        def transform(data, decrypt=False):
            ctx = cipher.decryptor() if decrypt else cipher.encryptor()
            return ctx.update(data) + ctx.finalize()
        def step(**params):
            root = self.request('pair', params, secure=False, timeout=120)
            if root.findtext('paired') != '1': raise ValueError('Apollo pairing failed')
            return root
        result = step(phrase='getservercert', devicename='Apollo Remote Play adapter',
                      clientcert=self.cert_path.read_bytes().hex(), salt=salt.hex())
        server = x509.load_pem_x509_certificate(bytes.fromhex(result.findtext('plaincert')))
        challenge = secrets.token_bytes(16)
        result = step(clientchallenge=transform(challenge).hex())
        response = transform(bytes.fromhex(result.findtext('challengeresponse')), True)
        if len(response) != 48: raise ValueError('Bad pairing challenge length')
        client = x509.load_pem_x509_certificate(self.cert_path.read_bytes())
        secret = secrets.token_bytes(16)
        digest = hashlib.sha256(response[32:]+client.signature+secret).digest()
        result = step(serverchallengeresp=transform(digest).hex())
        proof = bytes.fromhex(result.findtext('pairingsecret'))
        server.public_key().verify(proof[16:], proof[:16], padding.PKCS1v15(), hashes.SHA256())
        if not hmac.compare_digest(response[:32], hashlib.sha256(challenge+server.signature+proof[:16]).digest()):
            raise ValueError('Apollo PIN authentication failed')
        key = serialization.load_pem_private_key(self.key_path.read_bytes(), password=None)
        step(clientpairingsecret=(secret+key.sign(secret,padding.PKCS1v15(),hashes.SHA256())).hex())
        self.state['server_der'] = server.public_bytes(serialization.Encoding.DER).hex()
        self.save()
        self.request('pair', {'phrase':'pairchallenge'})

    def launch(self, appid):
        info = self.request('serverinfo')
        current = int(info.findtext('currentgame', '0'))
        if current and current != appid:
            raise ValueError('Another Apollo application is running; refusing to replace it')
        key, key_id = secrets.token_bytes(16), secrets.randbits(31)
        result = self.request('resume' if current else 'launch', {
            'appid':appid, 'mode':'1280x720x60', 'rikey':key.hex(), 'rikeyid':key_id,
            'localAudioPlayMode':0, 'surroundAudioInfo':196610, 'remoteControllersBitmap':1,
            'gcmap':1, 'gcpersist':0})
        url = result.findtext('sessionUrl0')
        if not url: raise ValueError('Apollo did not provide an RTSP session URL')
        return info, url, key, key_id


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=Path(__file__).parent/'build'/'apollo')
    commands = parser.add_subparsers(dest='command', required=True)
    pair = commands.add_parser('pair')
    pair.add_argument('host')
    pair.add_argument('--port', type=int, default=47989)
    commands.add_parser('apps')
    args = parser.parse_args()
    apollo = Apollo(args.state_dir)
    if args.command == 'pair':
        pin = f'{secrets.randbelow(10000):04d}'
        print(f'Enter PIN {pin} in Apollo pairing UI. Waiting up to 120 seconds.', flush=True)
        apollo.pair(args.host, pin, args.port)
        print('Apollo paired; server certificate pinned.')
    else:
        for app in apollo.request('applist').findall('App'):
            print(app.findtext('ID'), app.findtext('AppTitle'))
