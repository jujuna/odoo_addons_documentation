# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.addons.account_saft.tests.common import TestSaftReport
from odoo.tests import tagged
from odoo import Command


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestRoSaftReport(TestSaftReport):
    """ Test the generation of the SAF-T export for Romania.

        Depending on whether the account_intrastat module is installed, the
        export has a slighly different behaviour for non-service products.
        To handle this, we only use service products in the test.
    """
    _test_user_groups = None  # FIXME list needed groups

    @classmethod
    @TestSaftReport.setup_country('ro')
    def setUpClass(cls):
        super().setUpClass()

        cls.company_data['company'].write({
            'name': 'Romanian Company',
            'city': 'Bucharest',
            'zip': '010001',
            'vat': 'RO1234567897',
            'phone': '+40 723545439',
            'account_storno': True,
            'l10n_ro_saft_tax_accounting_basis': 'A',
            'additional_identifiers': {'RO_EN': '1234567897'}
        })

        cls.env['res.partner'].create({
            'name': 'Mr Big CEO',
            'phone': '+40 723545000',
            'parent_id': cls.company_data['company'].partner_id.id,
        })

        cls.partner_a.write({
            'name': 'Romanian Partner',
            'city': 'Bucharest',
            'zip': '010001',
            'country_id': cls.env.ref('base.ro').id,
            'phone': '+40 234285561',
            'vat': 'RO18547290',
            'additional_identifiers': {'RO_EN': '18547290'},
        })

        cls.partner_b.write({
            'name': 'French Partner',
            'city': 'Saint-Étienne',
            'zip': '42000',
            'country_id': cls.env.ref('base.fr').id,
            'phone': '+33 477284765',
            'vat': 'FR23334175221',
        })

        cls.partner_bank = cls.env['res.partner.bank'].create({
            'partner_id': cls.company_data['company'].partner_id.id,
            'account_number': 'RO08 4298 6369 7813',
            'allow_out_payment': True,
            'bank_name': 'Romanian Banking United',
        })

        cls.setup_other_currency('EUR', rates=[('2023-09-30', 0.2)])

        cls.product_a.write({
            'default_code': 'PA',
            'type': 'service',
        })
        cls.product_b.write({
            'default_code': 'PB',
            'type': 'service',
            'property_account_income_id': cls.company_data['default_account_revenue'].id,
            'property_account_expense_id': cls.company_data['default_account_expense'].id,
        })

        cls.fiscal_pos_a.write({
            'account_ids': [
                Command.clear(),
                Command.create({
                    'account_src_id': cls.product_a.property_account_income_id.id,
                    'account_dest_id': cls.product_a.property_account_income_id.id,
                }),
                Command.create({
                    'account_src_id': cls.product_a.property_account_expense_id.id,
                    'account_dest_id': cls.product_a.property_account_expense_id.id,
                }),
            ],
        })

    def test_saft_report_monthly(self):
        invoices = self.env['account.move'].create([
            {
                'move_type': 'out_invoice',
                'invoice_date': '2023-10-01',
                'date': '2023-10-01',
                'partner_id': self.partner_a.id,
                'currency_id': self.env.ref('base.EUR').id,
                'invoice_line_ids': [Command.create({
                    'product_id': self.product_a.id,
                    'quantity': 5.0,
                    'price_unit': 400.0,
                    'tax_ids': [Command.set(self.company_data['default_tax_sale'].ids)],
                })],
            },
            {
                'move_type': 'out_refund',
                'invoice_date': '2023-10-11',
                'date': '2023-10-11',
                'partner_id': self.partner_a.id,
                'invoice_line_ids': [Command.create({
                    'product_id': self.product_a.id,
                    'quantity': 3.0,
                    'price_unit': 1000.0,
                    'tax_ids': [Command.set(self.company_data['default_tax_sale'].ids)],
                })],
            },
            {
                'move_type': 'in_invoice',
                'invoice_date': '2023-10-21',
                'date': '2023-10-21',
                'partner_id': self.partner_b.id,
                'invoice_line_ids': [Command.create({
                    'product_id': self.product_b.id,
                    'quantity': 10.0,
                    'price_unit': 800.0,
                    'tax_ids': [Command.set(self.company_data['default_tax_purchase'].ids)],
                })],
            },
            {
                'move_type': 'in_invoice',
                'invoice_date': '2023-10-26',
                'date': '2023-10-26',
                'partner_id': self.partner_b.id,
                'l10n_ro_is_self_invoice': True,  # This is a self-invoice
                'invoice_line_ids': [Command.create({
                    'product_id': self.product_b.id,
                    'quantity': 2.0,
                    'price_unit': 600.0,
                    'tax_ids': [Command.set(self.company_data['default_tax_purchase'].ids)],
                })]
            }
        ])
        invoices.action_post()

        self.statement = self.env['account.bank.statement'].create({
            'name': 'test_statement',
            'line_ids': [
                Command.create({
                    'date': '2023-10-15',
                    'payment_ref': 'Payment Ref',
                    'partner_id': self.partner_a.id,
                    'journal_id': self.company_data['default_journal_bank'].id,
                    'foreign_currency_id': self.env.ref('base.EUR').id,
                    'amount': 1250.0,
                    'amount_currency': 250.0,
                }),
            ],
        })
        self._report_compare_with_test_file(
            self.report_handler.l10n_ro_export_saft_to_xml_monthly(self._generate_options()),
            'saft_report_monthly.xml'
        )

    def test_saft_report_errors_01(self):
        self.company_data['company'].bank_ids.action_archive()
        self.company_data['company'].write({
            'l10n_ro_saft_tax_accounting_basis': False,
            'phone': False,
        })
        with self.assertRaises(self.ReportException) as cm:
            self.report_handler.l10n_ro_export_saft_to_xml_monthly(self._generate_options())
        self.assertEqual(set(cm.exception.errors), {
            'settings_accounting_basis_missing',
            'company_phone_missing',
            'company_bank_account_missing',
        })

    def test_saft_report_errors_02(self):
        self.env['account.move'].create({
            'move_type': 'out_invoice',
            'invoice_date': '2023-10-01',
            'partner_id': self.partner_a.id,
            'invoice_line_ids': [
                Command.create({
                    'product_id': self.product_b.id,
                    'tax_ids': [Command.set(self.company_data['default_tax_sale'].ids)],
                }),
            ],
        }).action_post()
        intrastat_installed = 'intrastat_code_id' in self.product_b
        self.partner_a.write({
            'city': False,
            'country_id': False,
        })
        self.product_b.write({
            'default_code': False,
            'type': 'consu',
        })
        if intrastat_installed:
            self.product_b.intrastat_code_id = False
        with self.assertRaises(self.ReportException) as cm:
            self.report_handler.l10n_ro_export_saft_to_xml_monthly(self._generate_options())
        expected = {
            'partner_city_missing',
            'partner_country_missing',
            'product_internal_reference_missing',
        }
        if intrastat_installed:
            expected.add('product_intrastat_code_missing')
        self.assertEqual(set(cm.exception.errors), expected)

    def test_saft_report_errors_03(self):
        self.env['account.move'].create({
            'move_type': 'out_invoice',
            'invoice_date': '2023-10-01',
            'partner_id': self.partner_a.id,
            'invoice_line_ids': [
                Command.create({
                    'product_id': self.product_a.id,
                    'tax_ids': [Command.set(self.company_data['default_tax_sale'].ids)],
                }),
                Command.create({
                    'product_id': self.product_b.id,
                    'tax_ids': [Command.set(self.company_data['default_tax_sale'].ids)],
                }),
            ],
        }).action_post()
        self.company_data['default_tax_sale'].l10n_ro_saft_tax_type_id = False
        self.company_data['company'].partner_id.write({
            "vat": False,
            "additional_identifiers": False,
        })
        self.product_b.default_code = 'PA'

        with self.assertRaises(self.ReportException) as cm:
            self.report_handler.l10n_ro_export_saft_to_xml_monthly(self._generate_options())
        self.assertEqual(set(cm.exception.errors), {
            'company_vat_registry_number_missing',
            'taxes_tax_type_missing',
            'product_internal_reference_duplicated',
        })

    def test_saft_report_errors_04(self):
        self.env['account.move'].create({
            'move_type': 'out_invoice',
            'invoice_date': '2023-10-01',
            'partner_id': self.partner_a.id,
            'invoice_line_ids': [
                Command.create({
                    'product_id': self.product_a.id,
                }),
            ],
        }).action_post()
        self.company_data['company'].partner_id.write({
            'vat': False,
            'additional_identifiers': False,
        })
        self.partner_a.country_id = self.env.ref('base.fr')
        with self.assertRaises(self.ReportException) as cm:
            self.report_handler.l10n_ro_export_saft_to_xml_monthly(self._generate_options())
        self.assertEqual(set(cm.exception.errors), {
            'company_vat_registry_number_missing',
            'partner_vat_doesnt_match_country',
        })

    def test_saft_zero_balance_partner(self):
        self.env['account.move'].create([
            {
                'move_type': 'out_invoice',
                'invoice_date': '2023-10-01',
                'partner_id': self.partner_a.id,
                'invoice_line_ids': [
                    Command.create({
                        'name': 'product',
                        'price_unit': 100,
                    }),
                ],
            },
            {
                'move_type': 'out_refund',
                'invoice_date': '2023-10-01',
                'partner_id': self.partner_a.id,
                'invoice_line_ids': [
                    Command.create({
                        'name': 'product',
                        'price_unit': 100,
                    }),
                ],
            },
        ]).action_post()

        self._report_compare_with_test_file(
            self.report_handler.l10n_ro_export_saft_to_xml_monthly(self._generate_options()),
            'saft_report_zero_balance_partner.xml'
        )

    def test_saft_zero_line(self):
        self.env['account.move'].create([
            {
                'move_type': 'out_invoice',
                'invoice_date': '2023-10-01',
                'partner_id': self.partner_a.id,
                'invoice_line_ids': [
                    Command.create({
                        'name': 'product',
                        'price_unit': 100,
                    }),
                ],
            },
            {
                'move_type': 'out_invoice',
                'invoice_date': '2023-10-01',
                'partner_id': self.partner_a.id,
                'invoice_line_ids': [
                    Command.create({
                        'name': 'product',
                        'price_unit': 0,
                    }),
                ],
            },
        ]).action_post()

        self._report_compare_with_test_file(
            self.report_handler.l10n_ro_export_saft_to_xml_monthly(self._generate_options()),
            'saft_report_zero_line.xml'
        )

    def test_saft_reverse_charge(self):
        """The TaxInformation of a reverse charge should be the amount of the tax and not 0."""
        reverse_chart_tax = self.env['account.chart.template'].ref('tvati_intrap19b')
        self.env['account.move'].create([
            {
                'move_type': 'in_invoice',
                'invoice_date': '2023-10-01',
                'partner_id': self.partner_a.id,
                'invoice_line_ids': [
                    Command.create({
                        'name': 'product',
                        'price_unit': 100,
                        'tax_ids': [Command.set(reverse_chart_tax.ids)]
                    }),
                ],
            },
        ]).action_post()

        self._report_compare_with_test_file(
            self.report_handler.l10n_ro_export_saft_to_xml_monthly(self._generate_options()),
            'saft_report_reverse_charge.xml'
        )

    def test_saft_report_direct_payment(self):
        """Test that a payment posted directly to the journal's default account
        (without bank statement matching) appears in the <Payments> section of the SAF-T XML.
        """
        # Configure the bank journal's inbound payment method to post directly
        # to the journal's default account instead of an outstanding account.
        bank_journal = self.company_data['default_journal_bank']
        bank_journal.inbound_payment_method_line_ids.payment_account_id = bank_journal.default_account_id

        payment = self.env['account.payment'].create({
            'date': '2023-10-15',
            'amount': 500.0,
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner_a.id,
            'journal_id': bank_journal.id,
        })
        payment.action_post()

        report = self.report_handler.l10n_ro_export_saft_to_xml_monthly(self._generate_options())
        report_xml = self.get_xml_tree_from_string(report['file_content'])

        payments = report_xml.xpath('//*[local-name()="Payments"]/*[local-name()="Payment"]')
        self.assertEqual(len(payments), 1)

        payment_elem = payments[0]
        self.assertEqual(payment_elem.findtext('{*}PaymentRefNo'), payment.move_id.name)
        self.assertEqual(payment_elem.findtext('{*}PaymentMethod'), '03')
        self.assertEqual(payment_elem.findtext('{*}SystemID'), str(payment.move_id.id))
        self.assertEqual(float(payment_elem.findtext('{*}PaymentLine/{*}PaymentLineAmount/{*}Amount')), 500.0)

    def test_saft_report_payment_and_statement_line_reconciliation(self):
        """Test that in a flow where a payment is registered using an outstanding
        account (move A) and subsequently matched with a bank statement line (move B),
        only move B (linked to the statement line) is included in the <Payments> section,
        avoiding double counting.
        """
        bank_journal = self.company_data['default_journal_bank']

        # 1. Register a payment posting to the outstanding receipts account (move A)
        payment = self.env['account.payment'].create({
            'date': '2023-10-15',
            'amount': 500.0,
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner_a.id,
            'journal_id': bank_journal.id,
        })
        payment.action_post()
        move_a = payment.move_id

        # 2. Create bank statement line (move B)
        st_line = self.env['account.bank.statement.line'].create({
            'date': '2023-10-15',
            'payment_ref': 'Statement line matching payment',
            'partner_id': self.partner_a.id,
            'journal_id': bank_journal.id,
            'amount': 500.0,
        })
        move_b = st_line.move_id

        # 3. Reconcile the statement line with the payment using bank.rec.widget
        payment_line = move_a.line_ids.filtered(lambda l: l.account_id == payment.payment_method_line_id.payment_account_id)
        # wizard = self.env['bank.rec.widget'].with_context(default_st_line_id=st_line.id).new({})
        # wizard._action_add_new_amls(payment_line, allow_partial=False)
        # wizard._action_validate()
        suspense_line = move_b.line_ids.filtered(lambda l: l.account_id == bank_journal.suspense_account_id)
        suspense_line.account_id = payment_line.account_id
        (payment_line + suspense_line).reconcile()

        report = self.report_handler.l10n_ro_export_saft_to_xml_monthly(self._generate_options())
        report_xml = self.get_xml_tree_from_string(report['file_content'])

        payments = report_xml.xpath('//*[local-name()="Payments"]/*[local-name()="Payment"]')
        # Only the statement line move (move B) should be present; move A should not be counted.
        self.assertEqual(len(payments), 1)

        payment_elem = payments[0]
        self.assertEqual(payment_elem.findtext('{*}SystemID'), str(move_b.id))
        self.assertEqual(payment_elem.findtext('{*}PaymentRefNo'), move_b.name)
        self.assertEqual(float(payment_elem.findtext('{*}PaymentLine/{*}PaymentLineAmount/{*}Amount')), 500.0)

    def test_saft_customer_and_supplier_partner(self):
        """ An invoice must carry exactly one of CustomerInfo / SupplierInfo (xs:choice),
        based on the document type, even if the partner is both customer and supplier. """
        self._create_invoice('out_invoice', '2023-10-01', partner_id=self.partner_a, post=True)
        self._create_invoice('in_invoice', '2023-10-02', partner_id=self.partner_a, post=True)

        report = self.report_handler.l10n_ro_export_saft_to_xml_monthly(self._generate_options())
        report_xml = self.get_xml_tree_from_string(report['file_content'])

        sales_invoice = report_xml.find('.//{*}SalesInvoices/{*}Invoice')
        self.assertEqual(len(sales_invoice.findall('{*}CustomerInfo')), 1)
        self.assertEqual(len(sales_invoice.findall('{*}SupplierInfo')), 0)

        purchase_invoice = report_xml.find('.//{*}PurchaseInvoices/{*}Invoice')
        self.assertEqual(len(purchase_invoice.findall('{*}SupplierInfo')), 1)
        self.assertEqual(len(purchase_invoice.findall('{*}CustomerInfo')), 0)
