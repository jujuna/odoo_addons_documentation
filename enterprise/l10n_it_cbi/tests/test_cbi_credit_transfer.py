from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import freeze_time
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
@freeze_time('2024-01-01')
class TestL10nItCbiCreditTransfer(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        italy = cls.env.ref('base.it')

        cls.company_it = cls.company_data['company']
        cls.company_it.write({
            'account_fiscal_country_id': italy.id,
            'country_id': italy.id,
            'vat': 'IT12345670017',
        })

        cls.company_it.partner_id.write({
            'additional_identifiers': {
                **(cls.company_it.partner_id.additional_identifiers or {}),
                'IT_CUC': 'ABC12345',
            }
        })

        cls.bank_journal = cls.company_data['default_journal_bank']
        cls.bank_journal.bank_account_id = cls.env['res.partner.bank'].create({
            'account_number': 'IT12A1234512345123456789012',
            'partner_id': cls.company_it.partner_id.id,
            'company_id': cls.company_it.id,
        })

        cls.vendor = cls.env['res.partner'].create({
            'name': 'Italian Vendor',
            'country_id': italy.id,
            'city': 'Rome',
        })
        cls.vendor_bank = cls.env['res.partner.bank'].create({
            'account_number': 'IT99B9876598765987654321098',
            'partner_id': cls.vendor.id,
            'allow_out_payment': True,
        })
        cls.cbi_method = cls.env.ref('l10n_it_cbi.account_payment_method_cbi_ct')

        cls.bank_journal.write({
            'outbound_payment_method_line_ids': [Command.create({'payment_method_id': cls.cbi_method.id})]
        })

    def _create_cbi_batch_payment(self):
        """ Helper to create a posted payment and link it to a draft CBI batch. """
        payment = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.vendor.id,
            'amount': 150.0,
            'currency_id': self.env.ref('base.EUR').id,
            'journal_id': self.bank_journal.id,
            'partner_bank_id': self.vendor_bank.id,
            'payment_method_line_id': self.bank_journal.outbound_payment_method_line_ids.filtered(
                lambda l: l.payment_method_id == self.cbi_method
            ).id,
        })
        payment.action_post()

        return self.env['account.batch.payment'].create({
            'journal_id': self.bank_journal.id,
            'batch_type': 'outbound',
            'payment_method_id': self.cbi_method.id,
            'payment_ids': [Command.link(payment.id)],
            'date': '2024-01-01',
        })

    def test_cbi_method_auto_assigned_to_it_journals(self):
        """ Test that creating a new bank journal in Italy automatically adds the CBI method. """
        new_journal = self.env['account.journal'].create({
            'name': 'New IT Bank',
            'type': 'bank',
            'code': 'ITBNK',
            'company_id': self.company_it.id,
        })

        outbound_methods = new_journal.outbound_payment_method_line_ids.payment_method_id
        self.assertIn(self.cbi_method, outbound_methods, "CBI method should be automatically added to Italian bank journals.")

    def test_cbi_batch_xml_generation(self):
        """ Test the successful generation of the CBI XML. """
        batch = self._create_cbi_batch_payment()
        batch.validate_batch()

        export_data = batch._generate_export_file()

        self.assertTrue(export_data.get('file'), "The XML file should be generated.")
        self.assertTrue(export_data.get('filename').endswith('.xml'), "The file extension should be .xml")
        self.assertIn('ABC12345', export_data.get('filename', ''))

        xml_content = export_data['file'].content

        self.assertIn(b'<CBIPaymentRequest', xml_content, "The generated file should contain the CBI root tag.")
        self.assertIn(b'SUPP', xml_content, "The category purpose 'SUPP' should be present for Italian creditors.")
