# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('-at_install', 'post_install_l10n', 'post_install')
class AccountTestSAFTImport(AccountTestInvoicingCommon):
    _test_user_groups = None  # FIXME list needed groups

    @classmethod
    @AccountTestInvoicingCommon.setup_country('dk')
    def setUpClass(cls):
        super().setUpClass()

        cls.company.write({'name': 'SAF-T test company'})

        cls.saft_filedata = cls.file_read('l10n_dk_saft_import/tests/data/saft_example_dk.xml')
        cls.saft_2_file_data = cls.file_read('l10n_dk_saft_import/tests/data/saft_example_dk_2_0.xml')

        # Accounts codes that should be present after import of the SAF-T example file
        cls.reference_accounts = {
            "1500", "19201", "19202", "2400", "2701", "2711", "3000", "4000", "999999"
        }

    #############################
    #       Test methods        #
    #############################

    def test_saft_import(self, wizard=False):
        wizard = wizard or self.env['account.saft.import.wizard'].create({
            'attachment_id': self.saft_filedata,
        })
        wizard.action_import()

        # Check journals
        journals = self.env['account.journal'].search([('code', 'like', 'JOU%')])
        self.assertTrue(len(journals.ids) == 3, "Journal creation failed")

        # Check partners
        file_partners = ['Acme Corporation', 'Azure Interior', 'Beautiful partner']
        partners = self.env['res.partner'].search([('name', 'in', file_partners)])
        self.assertEqual(file_partners, partners.mapped('name'), "Partners creation failed")

        moves = self.env['account.move'].search(self.env['account.move']._check_company_domain(self.env.company))
        self.assertEqual(len(moves), 12, "Move import failed")
        self.assertEqual(
            sum(self.env['account.move'].search(self.env['account.move']._check_company_domain(self.env.company)).line_ids.mapped('debit')),
            276762.5,
            "Move debit amount imported is wrong"
        )

        self.assertEqual(
            len(self.env['account.move'].search(self.env['account.move']._check_company_domain(self.env.company)).line_ids.mapped('tax_ids')),
            1, "The tax is put on the move imported"
        )

    def test_saft_v2_import(self):
        wizard = self.env['account.saft.import.wizard'].create({
            'attachment_id': self.saft_2_file_data,
        })
        wizard.action_import()

        journals = self.env['account.journal'].search([('code', 'like', 'SAF%')])
        self.assertEqual(len(journals.ids), 2, "Journal creation failed")

        # v2 journal types must be remapped to Odoo types:
        # AR → sale, AP → purchase, GL → general, AJ → bank
        journal_types = set(journals.mapped('type'))
        self.assertIn('sale', journal_types, "AR journal not remapped to sale")
        self.assertIn('purchase', journal_types, "AP journal not remapped to purchase")

        file_partners = ['Debitor 1', 'Leverandør 1', 'Skattestyrelsen']
        partners = self.env['res.partner'].search([('name', 'in', file_partners)])
        self.assertEqual(file_partners, partners.mapped('name'), "Partners creation failed")

        moves = self.env['account.move'].search([('journal_id', 'in', journals.ids)])
        self.assertEqual(len(moves), 2, "Move import failed")
        self.assertEqual(
            sum(moves.line_ids.mapped('debit')),
            60000.0,
            "Move debit amount imported is wrong"
        )
