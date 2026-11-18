import datetime
import hashlib
import re

from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools.pdf.signature import PdfSigner

from odoo.addons.id_ge_sign.tools import protocol
from odoo.addons.id_ge_sign.tools.cms import CmsVerificationError, verify_card_signature, verify_pdf_signature

from .common import COMMON_NAME, PERSONAL_NUMBER, GeoeidCommon, certificate_pem


@tagged('post_install', '-at_install')
class TestCms(GeoeidCommon):

    def sign_sample(self, company=None):
        return PdfSigner(self.pdf_raw, company or self.card_company).sign_pdf(None, 'Sample')

    def test_valid_signature_returns_the_signer_identity(self):
        info = verify_pdf_signature(self.sign_sample(), expected_prefix=self.pdf_raw)
        self.assertEqual({key: info[key] for key in info if key != 'cert_der'}, {
            'common_name': COMMON_NAME,
            'personal_number': 'PNOGE-' + PERSONAL_NUMBER,
            'subject': self.card_cert.subject.rfc4514_string(),
            'serial': format(self.card_cert.serial_number, 'x'),
            'not_after': self.card_cert.not_valid_after_utc.date(),
            'trusted': False,
        })

    def test_prefix_mismatch_is_refused(self):
        with self.assertRaises(CmsVerificationError):
            verify_pdf_signature(self.sign_sample(), expected_prefix=b'%PDF-another document')

    def test_previous_signature_cannot_be_replayed_with_or_without_whitespace(self):
        signed = self.sign_sample()
        for suffix in (b'', b'\n ', b'\t'):
            with self.subTest(suffix=suffix), self.assertRaises(CmsVerificationError):
                verify_pdf_signature(signed + suffix, expected_prefix=signed, trust_anchor_pems=[self.card_pem])

    def test_a_second_incremental_signature_is_accepted(self):
        first = self.sign_sample()
        second = PdfSigner(first, self.card_company).sign_pdf(None, 'Second')
        info = verify_pdf_signature(second, expected_prefix=first)
        self.assertEqual(info['personal_number'], 'PNOGE-' + PERSONAL_NUMBER)

    def test_signature_gap_must_not_overlap_the_frozen_prefix(self):
        signed = self.sign_sample()
        match = list(re.finditer(rb'/ByteRange\s*\[\s*0\s+(\d+)', signed))[-1]
        frozen = signed[:int(match.group(1)) + 1]
        with self.assertRaisesRegex(CmsVerificationError, 'new signature'):
            verify_pdf_signature(signed, expected_prefix=frozen)

    def test_a_cryptographically_signed_pdf_with_extra_unsigned_gap_entries_is_refused(self):
        signer = PdfSigner(self.pdf_raw, self.card_company)
        prepared = signer.write_signature_placeholder(None, 'Invalid_gap')
        raw = bytes(prepared.pdf_data)
        match = list(re.finditer(rb'/ByteRange\s*(\[[^\]]*\])', raw))[-1]
        start_gap = prepared.hex_start - 1
        end_gap = raw.find(b'>', prepared.hex_end + 1)
        byte_range = ('[0 %d %d %d]' % (start_gap, end_gap, len(raw) - end_gap)).encode()
        prepared.pdf_data[match.start(1):match.end(1)] = byte_range.ljust(len(match.group(1)), b' ')
        prepared.digest = hashlib.sha256(prepared.pdf_data[:start_gap] + prepared.pdf_data[end_gap:]).digest()
        signed = signer.fill_signature_placeholder(prepared, signer._get_cms_object(prepared.digest).dump())
        with self.assertRaisesRegex(CmsVerificationError, 'Malformed signature contents'):
            verify_pdf_signature(signed, expected_prefix=self.pdf_raw)

    def test_pdf_without_byte_range_is_refused(self):
        with self.assertRaisesRegex(CmsVerificationError, "No PAdES signature"):
            verify_pdf_signature(self.pdf_raw)

    def test_trailing_bytes_after_the_signed_range_are_refused(self):
        with self.assertRaisesRegex(CmsVerificationError, "trailing"):
            verify_pdf_signature(self.sign_sample() + b'\n%unsigned tail')

    def test_a_flipped_byte_in_a_signed_range_is_refused(self):
        signed = self.sign_sample()
        for position in (200, len(signed) - 10):
            with self.subTest(position=position):
                tampered = bytearray(signed)
                tampered[position] ^= 0xFF
                with self.assertRaises(CmsVerificationError):
                    verify_pdf_signature(bytes(tampered))

    def test_expired_and_not_yet_valid_certificates_are_refused(self):
        signed = self.sign_sample()
        day = datetime.timedelta(days=1)
        not_after = self.card_cert.not_valid_after_utc
        for now in (not_after + day, self.card_cert.not_valid_before_utc - day):
            with self.subTest(now=now):
                with self.assertRaisesRegex(CmsVerificationError, "not valid at signing time"):
                    verify_pdf_signature(signed, now=now)

    def test_certificate_without_signing_key_usage_is_refused(self):
        company, __ = self.make_card('KEY AGREEMENT', 'PNOGE-01001000003', signing_usage=False)
        with self.assertRaisesRegex(CmsVerificationError, "key usage"):
            verify_pdf_signature(self.sign_sample(company))

    def test_certificate_with_digital_signature_only_is_refused(self):
        company, __ = self.make_card('DIGITAL ONLY', 'PNOGE-01001000005', signing_usage='digital_signature')
        with self.assertRaisesRegex(CmsVerificationError, "key usage"):
            verify_pdf_signature(self.sign_sample(company))

    def test_certificate_without_key_usage_extension_is_refused(self):
        company, __ = self.make_card('NO EXTENSION', 'PNOGE-01001000006', signing_usage=None)
        with self.assertRaisesRegex(CmsVerificationError, "key usage"):
            verify_pdf_signature(self.sign_sample(company))

    def test_malformed_cms_is_refused(self):
        with self.assertRaisesRegex(CmsVerificationError, "Malformed CMS"):
            verify_card_signature(b'not a cms', b'')

    def test_anchor_that_issued_the_certificate_makes_it_trusted(self):
        info = verify_pdf_signature(self.sign_sample(), trust_anchor_pems=[self.card_pem])
        self.assertTrue(info['trusted'])

    def test_another_certificate_as_anchor_does_not_trust(self):
        __, other = self.make_card('OTHER', 'PNOGE-01001000004')
        info = verify_pdf_signature(self.sign_sample(), trust_anchor_pems=[certificate_pem(other)])
        self.assertFalse(info['trusted'])


@tagged('post_install', '-at_install')
class TestProtocol(TransactionCase):

    def test_launch_url_drops_the_scheme_and_the_trailing_slash(self):
        for base in ('https://odoo.example.com/', 'https://odoo.example.com', 'odoo.example.com'):
            with self.subTest(base=base):
                url = protocol.launch_url(base, 'tok')
                self.assertEqual(url, 'geoeid-unitool://odoo.example.com/sign/geoeid/init/tok')

    def test_launch_url_keeps_the_port(self):
        self.assertEqual(
            protocol.launch_url('http://localhost:8069', 'tok'), 'geoeid-unitool://localhost:8069/sign/geoeid/init/tok')

    def test_init_document_json(self):
        spec = protocol.build_init_document_json(
            'https://odoo.example.com/', 'tok', description='Contract', language='en')
        self.assertEqual(spec, {
            'dataType': 'document',
            'docType': 'PDF',
            'dataUrl': 'https://odoo.example.com/sign/geoeid/document/tok',
            'submitUrl': 'https://odoo.example.com/sign/geoeid/submit/tok',
            'signAlg': 'sha256withRSA',
            'padesUsage': True,
            'description': 'Contract',
            'language': 'en',
            'keyId': 'sign',
            'signatureProfile': 'B',
        })

    def test_init_document_json_defaults(self):
        spec = protocol.build_init_document_json('https://odoo.example.com', 'tok', None, language='')
        self.assertEqual((spec['description'], spec['language'], spec['signatureProfile']), ('', 'ka', 'B'))
