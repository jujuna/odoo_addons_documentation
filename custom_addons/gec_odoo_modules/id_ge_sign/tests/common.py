import base64
import datetime
import io

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from PIL import Image

from odoo import Command
from odoo.tests.common import TransactionCase
from odoo.tools import BinaryBytes
from odoo.tools.pdf.signature import PdfSigner

COMMON_NAME = 'GIORGI TESTASHVILI'
PERSONAL_NUMBER = '01001000001'
PLACEHOLDER_DOMAIN = 'id-card.invalid'


def build_card_certificate(common_name, personal_number, signing_usage=True):
    """A self-signed certificate shaped like the card's: CN and serialNumber 'PNOGE-<personal number>'.

    ``signing_usage``: True is nonRepudiation + digitalSignature, False is keyEncipherment only, 'digital_signature' is digitalSignature
    only, None has no key-usage extension.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.SERIAL_NUMBER, personal_number),
        x509.NameAttribute(NameOID.COUNTRY_NAME, 'GE'),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    usage = x509.KeyUsage(bool(signing_usage), signing_usage is True, not signing_usage, False, False, False, False, False, False)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))
    )
    if signing_usage is not None:
        builder = builder.add_extension(usage, critical=True)
    cert = builder.sign(key, hashes.SHA256())
    return key, cert


def certificate_pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM).decode()


class GeoeidCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        def host_call_forbidden(item, route, **params):
            raise AssertionError("The signature host must not be called: %s" % route)

        cls.classPatch(cls.env.registry['sign.request.item'], '_qes_host_call', host_call_forbidden)
        Role = cls.env['sign.item.role']
        cls.card_role_1 = Role.create({'name': 'Card 1', 'auth_method': 'geoeid'})
        cls.card_role_2 = Role.create({'name': 'Card 2', 'auth_method': 'geoeid'})
        cls.plain_role = Role.create({'name': 'Plain 1'})
        cls.plain_role_2 = Role.create({'name': 'Plain 2'})
        cls.card_company, cls.card_cert = cls.make_card(COMMON_NAME, 'PNOGE-' + PERSONAL_NUMBER)
        cls.card_pem = certificate_pem(cls.card_cert)
        cls.env['ir.config_parameter'].sudo().set_str('id_ge_sign.trust_anchor', cls.card_pem)
        cls.pdf_raw = bytes(cls.file_read('sign/static/demo/sample_contract.pdf'))
        buffer = io.BytesIO()
        Image.new('RGB', (40, 20), 'white').save(buffer, 'PNG')
        cls.signature_value = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
        cls.signer = cls.make_partner('Giorgi', email='giorgi@example.com', vat=PERSONAL_NUMBER)

    @classmethod
    def make_card(cls, common_name, personal_number, signing_usage=True):
        """A throwaway company holding the card's certificate and key, the way the card app signs."""
        key, cert = build_card_certificate(common_name, personal_number, signing_usage)
        company = cls.env['res.company'].create({'name': 'Card %s' % personal_number})
        key_record = cls.env['certificate.key'].create({
            'content': BinaryBytes(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())),
            'company_id': company.id,
        })
        company.signing_certificate_id = cls.env['certificate.certificate'].create({
            'name': common_name,
            'content': BinaryBytes(cert.public_bytes(serialization.Encoding.PEM)),
            'private_key_id': key_record.id,
            'company_id': company.id,
        })
        return company, cert

    @classmethod
    def make_partner(cls, name, **vals):
        return cls.env['res.partner'].with_context(no_vat_validation=True).create({'name': name, **vals})

    def placeholder(self, email):
        return self.make_partner('Georgian ID Card signer', active=False, email=email)

    def make_template(self, roles, documents=1):
        template = self.env['sign.template'].create({'name': 'Geoeid template'})
        signature_type = self.env.ref('sign.sign_item_type_signature')
        for number in range(documents):
            attachment = self.env['ir.attachment'].create(
                {'type': 'binary', 'raw': self.pdf_raw, 'name': 'c%s.pdf' % number})
            document = self.env['sign.document'].create({'attachment_id': attachment.id, 'template_id': template.id})
            self.env['sign.item'].create([{
                'type_id': signature_type.id, 'required': True, 'responsible_id': role.id, 'page': 1,
                'posX': 0.1, 'posY': 0.1 + 0.2 * position, 'width': 0.2, 'height': 0.05, 'document_id': document.id,
            } for position, role in enumerate(roles)])
        return template

    def make_request(self, pairs, template=None):
        """``pairs``: (partner, role) or (partner, role, extra item values), in request order."""
        template = template or self.make_template([pair[1] for pair in pairs])
        return self.env['sign.request'].with_context(no_sign_mail=True).create({
            'template_id': template.id,
            'reference': 'Geoeid request',
            'request_item_ids': [
                Command.create({'partner_id': partner.id, 'role_id': role.id, **(extra[0] if extra else {})})
                for partner, role, *extra in pairs
            ],
        })

    def card_item(self, partner, role=None):
        return self.make_request([(partner, role or self.card_role_1)]).request_item_ids

    def signature_for(self, item):
        sign_items = item.sign_request_id.template_id.sign_item_ids.filtered(lambda s: s.responsible_id == item.role_id)
        return {str(sign_items.id): self.signature_value}

    def launch(self, item):
        return item.sudo()._sign_externally(self.signature_for(item))

    def launched_item(self, partner, role=None):
        item = self.card_item(partner, role)
        self.launch(item)
        return item

    def card_sign(self, item, card_company=None, pdf=None):
        """What the card app does: signs the frozen bytes (or ``pdf``). Returns (frozen bytes, signed bytes)."""
        frozen = bytes(item._get_documents_awaiting_external_signature().frozen_file)
        now = datetime.datetime.now(datetime.timezone.utc)
        signed = PdfSigner(pdf or frozen, card_company or self.card_company, now).sign_pdf(None, 'Card_%s' % item.id)
        return frozen, signed
