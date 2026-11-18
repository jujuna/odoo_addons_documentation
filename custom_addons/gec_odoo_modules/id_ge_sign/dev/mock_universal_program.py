#!/usr/bin/env python3
"""Fake Georgian ID Card Universal Program - test the flow WITHOUT a card.

Like the real app in hash mode: fetches the init JSON, builds a CMS SignedData over the
document hash with a test certificate, and POSTs it back. A test CA and signing
certificate are generated once under ~/.geoeid_mock/ and reused.

Requirements (already present in an Odoo environment):
    pip install requests cryptography asn1crypto

USAGE
-----
1) Manual (quickest):
   - On the signing page, open the browser Network tab, click "Validate".
   - Copy the `launch_url` from the /sign/geoeid/launch response
     (looks like geoeid-unitool://host/sign/geoeid/init/<token>).
   - Run:
       python3 mock_universal_program.py "geoeid-unitool://host/sign/geoeid/init/<token>"
   - The signing page (still polling) flips to "thank you".

2) Register as the URL handler (hands-free): point your OS's geoeid-unitool://
   handler at this script (Windows registry, macOS Info.plist or Linux .desktop).
   The browser then launches it automatically.

IDENTITY
--------
If the signer's partner has a "Georgian Personal Number", pass the same value with
--personal-number. If the partner has none, any value is accepted.

TRUST ANCHOR
------------
The module fills id_ge_sign.trust_anchor with the state's GEO Signing CA certificates
on install and upgrade, so a mock signature is refused until the mock CA is trusted too.
Run with --print-anchor and add the printed PEM after the existing certificates in
Settings -> Technical -> Parameters -> System Parameters (developer mode),
key id_ge_sign.trust_anchor.
"""
import argparse
import datetime
import os
import sys

import requests
from asn1crypto import algos, cms, core, x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

KEY_DIR = os.path.expanduser("~/.geoeid_mock")
_DAY = datetime.timedelta(days=1)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _load_or_create(name, common_name, personal_number=None, issuer=None):
    """Return (private_key, cert) cached on disk under KEY_DIR."""
    os.makedirs(KEY_DIR, exist_ok=True)
    key_path = os.path.join(KEY_DIR, f"{name}.key")
    crt_path = os.path.join(KEY_DIR, f"{name}.pem")
    if os.path.exists(key_path) and os.path.exists(crt_path):
        with open(key_path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), None)
        with open(crt_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        return key, cert

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attrs = [x509.NameAttribute(NameOID.COUNTRY_NAME, "GE"), x509.NameAttribute(NameOID.COMMON_NAME, common_name)]
    if personal_number:
        attrs.append(x509.NameAttribute(NameOID.SERIAL_NUMBER, personal_number))
    subject = x509.Name(attrs)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer[1].subject if issuer else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - _DAY)
        .not_valid_after(_now() + (3650 if issuer is None else 365) * _DAY)
    )
    if issuer is None:
        builder = builder.add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    else:
        builder = builder.add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False),
            critical=True)
    cert = builder.sign(issuer[0] if issuer else key, hashes.SHA256())
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with open(crt_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    return key, cert


def build_cms(digest, signer_key, signer_cert):
    cert = asn1_x509.Certificate.load(signer_cert.public_bytes(serialization.Encoding.DER))
    signed_attrs = cms.CMSAttributes([cms.CMSAttribute({'type': 'content_type', 'values': ['data']}),
        cms.CMSAttribute({'type': 'signing_time', 'values': [cms.Time({'utc_time': core.UTCTime(_now().replace(microsecond=0))})]}),
        cms.CMSAttribute({'type': 'message_digest', 'values': [digest]})])
    signature = signer_key.sign(signed_attrs.dump(), padding.PKCS1v15(), hashes.SHA256())
    signer_info = cms.SignerInfo({
        'version': 'v1',
        'sid': cms.SignerIdentifier({
            'issuer_and_serial_number': cms.IssuerAndSerialNumber({'issuer': cert.issuer, 'serial_number': cert.serial_number}),
        }),
        'digest_algorithm': algos.DigestAlgorithm({'algorithm': 'sha256'}),
        'signed_attrs': signed_attrs,
        'signature_algorithm': algos.SignedDigestAlgorithm({'algorithm': 'rsassa_pkcs1v15'}),
        'signature': signature,
    })
    signed_data = cms.SignedData({
        'version': 'v1',
        'digest_algorithms': [algos.DigestAlgorithm({'algorithm': 'sha256'})],
        'encap_content_info': {'content_type': 'data'},
        'certificates': [cert],
        'signer_infos': [signer_info],
    })
    return cms.ContentInfo({'content_type': 'signed_data', 'content': signed_data}).dump()


def _to_http(url):
    if url.startswith("geoeid-unitool://"):
        rest = url[len("geoeid-unitool://"):]
        scheme = "http" if rest.startswith(("localhost", "127.0.0.1")) else "https"
        return f"{scheme}://{rest}"
    return url


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", nargs="?", help="geoeid-unitool:// or http(s):// init URL")
    parser.add_argument("--name", default="GIORGI TESTASHVILI")
    parser.add_argument("--personal-number", default="01001000001")
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification (self-signed dev)")
    parser.add_argument("--print-anchor", action="store_true", help="print the test root CA PEM and exit")
    args = parser.parse_args()

    ca = _load_or_create("root", "Test PSDA Root CA")
    # One cert per identity, so a different --name/--personal-number gets a new one.
    signer_key = "signer-%s-%s" % (args.personal_number, args.name.replace(" ", "_"))
    signer = _load_or_create(signer_key, args.name, args.personal_number, issuer=ca)

    if args.print_anchor:
        sys.stdout.write(ca[1].public_bytes(serialization.Encoding.PEM).decode())
        return
    if not args.url:
        parser.error("provide the init URL (or use --print-anchor)")

    init_url = _to_http(args.url)
    verify = not args.insecure
    print(f"[mock] GET  {init_url}")
    spec = requests.get(init_url, verify=verify, timeout=30).json()
    print(f"[mock] init: {spec}")

    # Cert-read flow: send the certificate first, then re-fetch the init spec with the hash.
    if spec.get("action") == "getCertificate":
        cert_der = signer[1].public_bytes(serialization.Encoding.DER)
        print(f"[mock] POST {spec['certUrl']}  (certificate, {len(cert_der)} bytes)")
        resp = requests.post(spec["certUrl"], data={"certificate": cert_der.hex()}, verify=verify, timeout=30)
        print(f"[mock] cert -> {resp.status_code} {resp.text}")
        if not resp.ok:
            sys.exit(1)
        spec = requests.get(init_url, verify=verify, timeout=30).json()
        print(f"[mock] init (sign): {spec}")

    cms_der = build_cms(bytes.fromhex(spec["hash"]), signer[0], signer[1])
    print(f"[mock] POST {spec['submitUrl']}  ({len(cms_der)} byte CMS)")
    resp = requests.post(spec["submitUrl"], data={"signedData": cms_der.hex()}, verify=verify, timeout=30)
    print(f"[mock] -> {resp.status_code} {resp.text}")
    sys.exit(0 if resp.ok else 1)


if __name__ == "__main__":
    main()
