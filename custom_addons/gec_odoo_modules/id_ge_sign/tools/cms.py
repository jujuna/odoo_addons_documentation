import datetime
import hashlib
import re

from asn1crypto import cms as asn1_cms
from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import ExtensionOID, NameOID

_HASHES = {'sha256': hashes.SHA256, 'sha384': hashes.SHA384, 'sha512': hashes.SHA512}
_PKCS1_ALGS = {'rsassa_pkcs1v15', 'sha256_rsa', 'sha384_rsa', 'sha512_rsa', 'rsa'}
_PDF_WHITESPACE = b'\x00\t\n\f\r '


class CmsVerificationError(Exception):
    pass


def verify_card_signature(cms_der, expected_digest, trust_anchor_pems=(), now=None):
    """Verify a card CMS against ``expected_digest`` and return signer info; raises
    :class:`CmsVerificationError` on any failure."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    signed_data = _load_signed_data(cms_der)
    signer_info = _single_signer(signed_data)
    signer_cert_asn1 = _find_signer_cert(signed_data, signer_info)
    cert = x509.load_der_x509_certificate(signer_cert_asn1.dump())

    _check_signed_attributes(signer_info, expected_digest)
    _verify_signature(cert, signer_info)
    _check_validity(cert, now)
    _check_key_usage(cert)
    trusted = _check_trust(cert, trust_anchor_pems, now)
    return _describe(cert, trusted)


def verify_pdf_signature(pdf_bytes, trust_anchor_pems=(), now=None, expected_prefix=None):
    """Verify the PAdES signature in ``pdf_bytes`` and return signer info; raises
    :class:`CmsVerificationError`. With ``expected_prefix`` the PDF must be an incremental update of those
    exact bytes."""
    prefix_length = len(expected_prefix) if expected_prefix is not None else 0
    if expected_prefix is not None and (not pdf_bytes.startswith(expected_prefix) or len(pdf_bytes) <= prefix_length):
        raise CmsVerificationError("The signed PDF does not match the document prepared by Odoo.")
    cms_der, signed_bytes = _extract_pdf_signature(pdf_bytes, prefix_length)
    signer_info = _single_signer(_load_signed_data(cms_der))
    digest_alg = signer_info['digest_algorithm']['algorithm'].native
    if digest_alg not in _HASHES:
        raise CmsVerificationError("Unsupported digest algorithm: %s." % digest_alg)
    expected_digest = hashlib.new(digest_alg, signed_bytes).digest()
    return verify_card_signature(cms_der, expected_digest, trust_anchor_pems=trust_anchor_pems, now=now)


def _extract_pdf_signature(pdf_bytes, prefix_length=0):
    """Return (cms_der, signed_bytes) for the last PAdES signature, the current signer's."""
    matches = list(re.finditer(rb'/ByteRange\s*\[\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)', pdf_bytes))
    if not matches:
        raise CmsVerificationError("No PAdES signature found in the returned document.")
    start1, len1, start2, len2 = (int(g) for g in matches[-1].groups())
    end1 = start1 + len1
    end2 = start2 + len2
    if start1 != 0 or end1 > start2 or start2 > len(pdf_bytes) or end2 > len(pdf_bytes):
        raise CmsVerificationError("The PDF signature ByteRange does not cover the whole document.")
    if end1 < prefix_length:
        raise CmsVerificationError("The returned PDF does not contain a new signature after the prepared document.")
    if pdf_bytes[end2:].strip(_PDF_WHITESPACE):
        raise CmsVerificationError("The PDF signature ByteRange leaves unsigned trailing content.")
    signed_bytes = pdf_bytes[start1:start1 + len1] + pdf_bytes[start2:start2 + len2]
    gap = pdf_bytes[end1:start2].strip(_PDF_WHITESPACE)
    if not re.fullmatch(rb'<[0-9A-Fa-f\x00\t\n\f\r ]+>', gap):
        raise CmsVerificationError("Malformed signature contents in the returned document.")
    try:
        contents = gap[1:-1].translate(None, _PDF_WHITESPACE)
        cms_der = bytes.fromhex(contents.decode('ascii'))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CmsVerificationError("Signature contents are not valid hex.") from exc
    return cms_der, signed_bytes


def _load_signed_data(cms_der):
    try:
        content_info = asn1_cms.ContentInfo.load(cms_der)
    except Exception as exc:
        raise CmsVerificationError("Malformed CMS container.") from exc
    if content_info['content_type'].native != 'signed_data':
        raise CmsVerificationError("CMS is not a SignedData structure.")
    return content_info['content']


def _single_signer(signed_data):
    signer_infos = signed_data['signer_infos']
    if len(signer_infos) != 1:
        raise CmsVerificationError("Exactly one signer is expected in the CMS.")
    return signer_infos[0]


def _find_signer_cert(signed_data, signer_info):
    certs = [c.chosen for c in signed_data['certificates'] if c.name == 'certificate']
    if not certs:
        raise CmsVerificationError("The CMS does not embed the signer certificate.")
    sid = signer_info['sid']
    if sid.name == 'issuer_and_serial_number':
        issuer = sid.chosen['issuer'].dump()
        serial = sid.chosen['serial_number'].native
        for cert in certs:
            if cert.issuer.dump() == issuer and cert.serial_number == serial:
                return cert
    else:
        key_id = sid.chosen.native
        for cert in certs:
            if cert.key_identifier == key_id:
                return cert
    raise CmsVerificationError("Signer certificate not found in the CMS.")


def _check_signed_attributes(signer_info, expected_digest):
    signed_attrs = signer_info['signed_attrs']
    if signed_attrs.native is None:
        raise CmsVerificationError("Signed attributes are required for a PAdES signature.")
    attrs = {attr['type'].native: attr['values'] for attr in signed_attrs}
    content_type = attrs.get('content_type')
    if not content_type or content_type[0].native != 'data':
        raise CmsVerificationError("The contentType signed attribute must be 'data'.")
    message_digest = attrs.get('message_digest')
    if not message_digest or message_digest[0].native != expected_digest:
        raise CmsVerificationError("messageDigest does not match the document hash.")


def _verify_signature(cert, signer_info):
    signed_attrs = signer_info['signed_attrs']
    # CMS signs the SignedAttributes DER re-tagged from [0] (0xA0) to SET (0x31).
    attrs_der = b'\x31' + signed_attrs.dump()[1:]
    signature = signer_info['signature'].native
    digest_alg = signer_info['digest_algorithm']['algorithm'].native
    sig_alg = signer_info['signature_algorithm']['algorithm'].native

    hash_cls = _HASHES.get(digest_alg)
    if hash_cls is None:
        raise CmsVerificationError("Unsupported digest algorithm: %s." % digest_alg)
    if sig_alg not in _PKCS1_ALGS:
        raise CmsVerificationError("Unsupported signature algorithm: %s (RSA PKCS#1 v1.5 only)." % sig_alg)
    try:
        cert.public_key().verify(signature, attrs_der, padding.PKCS1v15(), hash_cls())
    except InvalidSignature:
        raise CmsVerificationError("The signature does not verify against the certificate.")
    except (TypeError, ValueError, UnsupportedAlgorithm) as exc:
        raise CmsVerificationError("The certificate key cannot verify this signature algorithm.") from exc


def _validity_window(cert):
    """(not_before, not_after) as aware-UTC datetimes; older cryptography only has naive ``not_valid_*``."""
    not_after = getattr(cert, 'not_valid_after_utc', None)
    if not_after is not None:
        return cert.not_valid_before_utc, not_after
    return (cert.not_valid_before.replace(tzinfo=datetime.timezone.utc), cert.not_valid_after.replace(tzinfo=datetime.timezone.utc))


def _check_validity(cert, now):
    not_before, not_after = _validity_window(cert)
    if now < not_before or now > not_after:
        raise CmsVerificationError("The signing certificate is not valid at signing time.")


def _check_key_usage(cert):
    try:
        content_commitment = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value.content_commitment
    except x509.ExtensionNotFound:
        content_commitment = False
    if not content_commitment:
        raise CmsVerificationError("Certificate key usage does not allow document signing.")


def _check_trust(cert, trust_anchor_pems, now):
    """Chains to a configured anchor only: no full path building, OCSP/CRL freshness or timestamp validation."""
    anchors = _load_anchors(trust_anchor_pems)
    if not anchors:
        return False
    for anchor in anchors:
        if cert.issuer != anchor.subject:
            continue
        anchor_not_before, anchor_not_after = _validity_window(anchor)
        if now < anchor_not_before or now > anchor_not_after:
            continue
        try:
            try:
                basic_constraints = anchor.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value
            except x509.ExtensionNotFound:
                basic_constraints = None
            if basic_constraints is not None and not basic_constraints.ca:
                continue
            anchor.public_key().verify(cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), cert.signature_hash_algorithm)
            return True
        except InvalidSignature:
            continue
        except (TypeError, ValueError, UnsupportedAlgorithm):
            continue
    return False


def _load_anchors(trust_anchor_pems):
    anchors = []
    for pem in trust_anchor_pems or ():
        if not pem:
            continue
        data = pem.encode() if isinstance(pem, str) else pem
        anchors.extend(_load_pem_certificates(data))
    return anchors


def _load_pem_certificates(data):
    loader = getattr(x509, 'load_pem_x509_certificates', None)  # cryptography >= 39
    if loader is not None:
        return loader(data)
    blocks = re.findall(b'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', data, re.DOTALL)
    return [x509.load_pem_x509_certificate(block) for block in blocks]


def _describe(cert, trusted):
    return {
        'common_name': _name_attr(cert, NameOID.COMMON_NAME),
        'personal_number': _name_attr(cert, NameOID.SERIAL_NUMBER),
        'subject': cert.subject.rfc4514_string(),
        'serial': format(cert.serial_number, 'x'),
        'not_after': _validity_window(cert)[1].date(),
        'trusted': trusted,
        'cert_der': cert.public_bytes(Encoding.DER),
    }


def _name_attr(cert, oid):
    values = cert.subject.get_attributes_for_oid(oid)
    return values[0].value if values else False
