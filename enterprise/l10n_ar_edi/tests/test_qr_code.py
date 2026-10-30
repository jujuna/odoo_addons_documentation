# Part of Odoo. See LICENSE file for full copyright and licensing details.
import base64
import json

from odoo import Command
from odoo.tests import tagged

from odoo.addons.l10n_ar_edi.tests.common import TestArEdiCommon


@tagged('post_install', 'post_install_l10n', '-at_install')
class TestArEdiQrCode(TestArEdiCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal = cls._create_journal('wsfe')

    def test_qr_code_partner_without_arca_code(self):
        """ The QR code must be rendered even when no ARCA identification code can be
        derived from the partner identifiers (`l10n_ar_afip_code` is then not set), instead
        of crashing with int(None). Such a partner reports tipoDocRec 0, as in 17.0/18.0. """
        partner = self.env['res.partner'].create({
            'name': 'Sujeto no Categorizado sin identificacion',
            'country_id': self.env.ref('base.ar').id,
            'l10n_ar_afip_responsibility_type_id': self.env.ref('l10n_ar.res_NOCATEG').id,
        })
        self.assertFalse(partner.l10n_ar_afip_code, 'No ARCA identification code should be derived for this partner')

        invoice = self.env['account.move'].create({
            'company_id': self.company_ri.id,
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'journal_id': self.journal.id,
            'l10n_latam_document_type_id': self.document_type['invoice_b'].id,
            'invoice_date': '2026-08-04',
            'invoice_line_ids': [Command.create({'name': 'Test product', 'quantity': 1, 'price_unit': 100.0})],
        })
        invoice.l10n_latam_document_number = '00002-00000001'
        # Simulate an ARCA validated invoice (these values are normally set by the ws)
        invoice.write({
            'l10n_ar_afip_auth_mode': 'CAE',
            'l10n_ar_afip_auth_code': '12345678901234',
        })

        qr_data = json.loads(base64.b64decode(invoice.l10n_ar_afip_qr_code.split('?p=')[1]))
        self.assertEqual(qr_data['tipoDocRec'], 0)
        self.assertEqual(qr_data['nroDocRec'], 0)
