from freezegun import freeze_time
from lxml import etree

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests.common import tagged
from odoo.tools import misc

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestAccountMoveSendFinvoice(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country('fi')
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_a.write({
            'bank_ids': [
                Command.create({
                    'account_number': '11234567899',
                    'bank_bic': 'SIUUUUUU123',
                    'bank_name': 'Test Bank',
                    'country_id': cls.env.ref('base.fi').id,
                    'allow_out_payment': True,
                })
            ],
            'invoice_edi_format': 'finvoice',
            'street': 'Street skread',
            'city': 'Bikini Bottom',
            'zip': '667',
        })
        cls.invoice_1, cls.invoice_2 = cls.env['account.move'].create([{
            'date': '2020-10-10',
            'invoice_date': '2020-10-10',
            'partner_id': cls.partner_a.id,
            'move_type': 'out_invoice',
            'journal_id': cls.company_data['default_journal_sale'].id,
            'partner_bank_id': cls.partner_a.bank_ids[0].id,
            'l10n_fi_edi_epi_charge': 'SHA',
            'invoice_line_ids': [
                Command.create({
                    'product_id': cls.product_a.id,
                    'quantity': 2,
                    'price_unit': 100,
                    'tax_ids': [],
                }),
            ],
        }, {
            'date': '2020-10-10',
            'invoice_date': '2020-10-10',
            'partner_id': cls.partner_a.id,
            'move_type': 'out_invoice',
            'journal_id': cls.company_data['default_journal_sale'].id,
            'l10n_fi_edi_epi_charge': 'SHA',
            'invoice_line_ids': [
                Command.create({
                    'product_id': cls.product_a.id,
                    'quantity': 1,
                    'price_unit': 100,
                    'tax_ids': [],
                }),
                Command.create({
                    'product_id': cls.product_b.id,
                    'quantity': 3,
                    'price_unit': 50,
                    'tax_ids': [],
                }),
            ],
        }])

    def create_send_and_print(self, invoices, **kwargs):
        wizard_model = 'account.move.send.wizard' if len(invoices) == 1 else 'account.move.send.batch.wizard'
        return self.env[wizard_model]\
            .with_context(active_model='account.move', active_ids=invoices.ids)\
            .create(kwargs)

    def post_and_send_move(self, move):
        move.action_post()
        wizard = self.create_send_and_print(move)
        wizard.action_send_and_print()

        self.assertRecordValues(move.edi_document_ids, [{
            'l10n_fi_edi_state': 'posted',
            'l10n_fi_document_identifier': move.name,
        }])

    def test_l10n_fi_edi_create_credit_note_from_invoice(self):
        self.invoice_1.action_post()

        self.assertRecordValues(self.invoice_1, [{
            'l10n_fi_edi_epi_charge': 'SHA',
            'l10n_fi_edi_invoice_type_code': 'INV01',
            'l10n_fi_edi_origin_code': 'Original',
        }])

        credit_note = self.invoice_1._reverse_moves([{
            'invoice_date': '2020-10-10',
            'l10n_fi_edi_epi_charge': 'SHA',
        }])
        credit_note.action_post()

        self.assertRecordValues(credit_note, [{
            'l10n_fi_edi_epi_charge': 'SHA',
            'l10n_fi_edi_invoice_type_code': 'INV02',
            'l10n_fi_edi_origin_code': 'Cancel',
        }])

    @freeze_time('2020-10-10')
    def test_l10n_fi_edi_send_and_print(self):
        self.post_and_send_move(self.invoice_1)

        xml_arch = etree.fromstring(self.invoice_1.edi_document_ids.attachment_id.raw.content)
        expected_xml_arch = etree.fromstring(misc.file_open('l10n_fi_edi/tests/expected_files/finvoice_send_invoice.xml', 'rb').read())
        self.assertXmlTreeEqual(xml_arch, expected_xml_arch)

    def test_l10n_fi_edi_send_and_print_invoice_without_partner_bank(self):
        self.invoice_2.action_post()
        wizard = self.create_send_and_print(self.invoice_2)
        with self.assertRaises(UserError, msg="You can't send a finvoice format invoice without setting a partner bank on the move."):
            # Should raise an error as there is no partner_bank_id on invoice_2
            wizard.action_send_and_print()

        self.invoice_2.partner_bank_id = self.partner_a.bank_ids[0].id
        wizard.action_send_and_print()
        self.assertEqual(self.invoice_2.edi_document_ids.l10n_fi_edi_state, 'posted')

    @freeze_time('2020-10-10')
    def test_l10n_fi_edi_send_and_print_credit_note(self):
        self.invoice_1.action_post()
        credit_note = self.invoice_1._reverse_moves([{
            'invoice_date': '2020-10-10',
            'l10n_fi_edi_epi_charge': 'SHA',
        }])
        self.post_and_send_move(credit_note)

        xml_arch = etree.fromstring(credit_note.edi_document_ids.attachment_id.raw.content)
        expected_xml_arch = etree.fromstring(misc.file_open('l10n_fi_edi/tests/expected_files/finvoice_send_credit_note.xml', 'rb').read())
        self.assertXmlTreeEqual(xml_arch, expected_xml_arch)

    @freeze_time('2020-10-10')
    def test_l10n_fi_edi_send_and_prin_with_discount(self):
        self.invoice_1.write({
            'invoice_line_ids': [Command.create({
                'product_id': self.product_a.id,
                'quantity': 1,
                'price_unit': 100,
                'discount': 50.0,
                'tax_ids': [],
            })],
        })
        self.post_and_send_move(self.invoice_1)

        xml_arch = etree.fromstring(self.invoice_1.edi_document_ids.attachment_id.raw.content)
        expected_xml_arch = etree.fromstring(misc.file_open('l10n_fi_edi/tests/expected_files/finvoice_send_invoice_with_discount.xml', 'rb').read())
        self.assertXmlTreeEqual(xml_arch, expected_xml_arch)

    def test_import_invoice_with_finvoice_format(self):
        file_content = misc.file_open('l10n_fi_edi/tests/expected_files/finvoice_import_invoice.xml', 'rb').read()
        attachment = self.env['ir.attachment'].create({
            'raw': file_content,
            'name': 'finvoice_import_invoice',
        })
        action_vals = self.company_data['default_journal_sale'].create_document_from_attachment(attachment.ids)
        move = self.env['account.move'].browse(action_vals['res_id'])

        self.assertRecordValues(move, [{
            'amount_untaxed': 300.0,
        }])
        self.assertRecordValues(move.partner_id, [{
            'name': 'Random Partner',
            'city': 'Liège',
            'vat': 'FI12345671',
            'country_id': self.env.ref('base.fi').id,
        }])
        self.assertRecordValues(move.invoice_line_ids, [{
            'name': 'Random Product 1',
        }, {
            'name': 'Random Product 2',
        }])

    def test_import_invoice_with_wrong_finvoice_format(self):
        file_content = misc.file_open('l10n_fi_edi/tests/expected_files/finvoice_import_invoice_wrong_format.xml', 'rb').read()
        attachment = self.env['ir.attachment'].create({
            'raw': file_content,
            'name': 'finvoice_import_invoice_wrong_format',
        })
        action_vals = self.company_data['default_journal_sale'].create_document_from_attachment(attachment.ids)
        move = self.env['account.move'].browse(action_vals['res_id'])
        self.assertRecordValues(move, [{
            'amount_untaxed': 0,
            'partner_id': False,
        }])

    def test_create_finvoice_xml_with_no_product_on_lines(self):
        self.invoice_1.write({
            'invoice_line_ids': [
                Command.create({
                    'product_id': self.product_a.id,
                    'quantity': 1,
                    'price_unit': 100,
                    'discount': 50.0,
                    'tax_ids': [],
                }),
                Command.create({
                    'quantity': 1,
                    'price_unit': 100,
                    'tax_ids': [],
                }),
                Command.create({
                    'name': 'Wide Cat',
                    'price_unit': 10000,
                    'tax_ids': [],
            })],
        })
        with self.assertRaises(UserError, msg="Each Journal Item must either have a label or a product set."):
            self.post_and_send_move(self.invoice_1)
        self.invoice_1.state = 'draft'
        self.invoice_1.invoice_line_ids.filtered(lambda line: not any({line.product_id, line.name})).name = 'Coffee'
        self.post_and_send_move(self.invoice_1)
