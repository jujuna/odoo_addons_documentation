# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged, freeze_time

from odoo.addons.l10n_ca_payment_cpa005.tests.common import CPA005Common


@tagged("post_install_l10n", "post_install", "-at_install")
@freeze_time("2020-11-30 19:45:00")
class TestCPA005EFT(CPA005Common):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal.l10n_ca_cpa005_fcn_number_next = 103

        transaction_codes = cls.env["l10n_ca_cpa005.transaction.code"]
        code_430 = transaction_codes.search([("code", "=", "430")], limit=1)
        code_200 = transaction_codes.search([("code", "=", "200")], limit=1)
        cls.batch = cls._create_batch_payment(
            cls._create_eft_payment(code_430, cls.partner_a, cls.bank_partner_a, 123.45, "partner_a_1")
            | cls._create_eft_payment(code_430, cls.partner_a, cls.bank_partner_a, 543.21, "partner_a_2")
            | cls._create_eft_payment(code_430, cls.partner_b, cls.bank_partner_b, 456.78, "partner_b_1", days_from_now=1)
            | cls._create_eft_payment(code_200, cls.partner_b, cls.bank_partner_b, 567.89, "partner_b_2"),
            "outbound",
        )

    @classmethod
    def _create_eft_payment(cls, transaction_code, partner, partner_bank, amount, memo, days_from_now=0):
        return cls._create_cpa005_payment(
            payment_type="outbound",
            l10n_ca_cpa005_transaction_code_id=transaction_code,
            partner_id=partner,
            partner_bank_id=partner_bank,
            amount=amount,
            memo=memo,
            date=fields.Date.add(fields.Date.today(), days=days_from_now),
        )

    def test_cpa005_eft(self):
        self.maxDiff = None  # show full diff in case of errors
        self.company.sudo().write({"name": "Long Compàny Nàme"})
        expected_item_trace_numbers = [f"{payment.id:022d}" for payment in self.batch.payment_ids.sorted()]
        expected = [
            # A record ("header")
            "A0000000011234567890010302033501600                    CAD                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              ",
            # C records ("outgoing payments")
            f"C000000002123456789001034300000045678020336077788888444444444   {expected_item_trace_numbers[0]}000COMP_NAME      partner_b                     Long Company Name             1234567890                   0222333339999999                                            00000000000                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                ",
            f"C000000003123456789001032000000056789020335077788888444444444   {expected_item_trace_numbers[1]}000COMP_NAME      partner_b                     Long Company Name             1234567890                   0222333339999999                                            00000000000                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                ",
            f"C000000004123456789001034300000054321020335055566666333333333   {expected_item_trace_numbers[2]}000COMP_NAME      partner_a                     Long Company Name             1234567890                   0222333339999999                                            00000000000                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                ",
            f"C000000005123456789001034300000012345020335055566666333333333   {expected_item_trace_numbers[3]}000COMP_NAME      partner_a                     Long Company Name             1234567890                   0222333339999999                                            00000000000                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                ",
            # Z record ("footer")
            "Z000000006123456789001030000000000000000000000000000001691330000000400000000000000000000000000000000000000000000                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        ",
        ]

        for line in expected:
            self.assertEqual(
                len(line), 1464, "Every line in our CPA file should have 1464 characters (excluding \\r\\n)."
            )

        self.assertEqual(
            len(expected),
            len(self.batch.payment_ids) + 2,
            "There should be an A record, one C record per payment and one Z record.",
        )

        generated = self.batch._generate_cpa005_file()
        self.assertEqual(
            generated.count("\r\n"), len(expected) - 1, "The generated CPA 005 file should use DOS line endings."
        )
        self.assertEqual(
            generated.count("à"), 0, "The generated CPA 005 file should not have special characters."
        )

        generated = generated.splitlines()
        self.assertEqual(len(generated), len(expected), "The generated CPA 005 file has an incorrect amount of lines.")

        for line in generated:
            self.assertEqual(
                len(line), 1464, "Every line in the generated CPA file should have 1464 characters (excluding \\r\\n)."
            )

        for generated_line, expected_line in zip(generated, expected):
            self.assertEqual(generated_line, expected_line, "Generated line in CPA 005 file does not match expected.")

    def test_cpa005_rollover_step_1(self):
        self.journal.l10n_ca_cpa005_fcn_number_next = 9999
        self.assertEqual(
            self.journal._l10n_ca_cpa005_next_file_creation_nr(), "9999", "FCN different from what was set."
        )
        self.assertEqual(self.journal._l10n_ca_cpa005_next_file_creation_nr(), "0001", "FCN should have rolled over back to 0001.")

    def test_cpa005_rollover_step_10(self):
        self.journal.l10n_ca_cpa005_fcn_number_next = 9991
        self.journal.l10n_ca_cpa005_fcn_sequence_id.sudo().number_increment = 10
        self.assertEqual(
            self.journal._l10n_ca_cpa005_next_file_creation_nr(), "9991", "FCN different from what was set."
        )
        self.assertEqual(self.journal._l10n_ca_cpa005_next_file_creation_nr(), "0002", "FCN should have rolled over back to 0002.")

    def test_cpa005_financial_institution_number_sources(self):
        bank = self.bank_partner_a
        ca_clearing_label = self.env.ref("base.clearing_label_ca")

        self.assertEqual(bank._l10n_ca_cpa005_get_financial_institution_number(), "055566666")

        # Both fields hold the same information, the Canadian one wins when both are set
        bank.write({"clearing_label_id": ca_clearing_label.id, "clearing_number": "0004-12345"})
        self.assertEqual(bank._l10n_ca_cpa005_get_financial_institution_number(), "055566666")

        # The generic clearing number is used, separators included, when the Canadian field is empty
        bank.l10n_ca_financial_institution_number = False
        self.assertEqual(bank._l10n_ca_cpa005_get_financial_institution_number(), "000412345")

        # A clearing number that is not a Canadian institution number is rejected
        with self.assertRaisesRegex(ValidationError, "must be a 9 digit number"):
            bank.clearing_number = "12345"
        with self.assertRaisesRegex(ValidationError, "must be a 9 digit number"):
            bank.clearing_number = "100412345"

        # Neither can a clearing number of another country
        bank.write({"clearing_label_id": self.env.ref("base.clearing_label_us").id, "clearing_number": "000412345"})
        self.assertFalse(bank._l10n_ca_cpa005_get_financial_institution_number())

    def test_cpa005_with_generic_clearing_number(self):
        """The generated file is the same whether the institution numbers are set on the
        Canadian field or on the generic clearing number."""
        expected = self.batch._generate_cpa005_file()  # fixes the file creation number on the batch

        ca_clearing_label = self.env.ref("base.clearing_label_ca")
        for bank in self.journal.bank_account_id | self.bank_partner_a | self.bank_partner_b:
            bank.write(
                {
                    "clearing_label_id": ca_clearing_label.id,
                    "clearing_number": bank.l10n_ca_financial_institution_number,
                    "l10n_ca_financial_institution_number": False,
                }
            )

        self.assertEqual(self.batch._generate_cpa005_file(), expected)

    def test_cpa005_file_routing_header(self):
        """ RBC files start with their File Transmission Routing Record, which the system parameter can replace. """
        self.assertTrue(self.batch._generate_cpa005_file().startswith("A000000001"), "Only RBC needs a routing record.")  # default bank from setup != RBC

        bank_sudo = self.journal.bank_account_id.sudo()
        bank_sudo.write(
            {
                "clearing_label_id": self.env.ref("base.clearing_label_ca").id,
                "clearing_number": "000312345",  # digits [1:4] == '003', it's RBC
                "l10n_ca_financial_institution_number": False,  # it would win over the clearing number
            }
        )
        generated = self.batch._generate_cpa005_file().splitlines()
        self.assertEqual(generated[0], "$$AA01CPA1464[PROD[NL$$")
        self.assertTrue(generated[1].startswith("A000000001"), "The routing record is not a logical record.")
        self.assertTrue(generated[-1].startswith("Z000000006"), "The routing record is not a logical record.")

        self.env['ir.config_parameter'].sudo().set_str('l10n_ca_payment_cpa005.rbc_file_routing_header', "$$AA01CPA1464[TEST[NL$$")
        self.assertTrue(self.batch._generate_cpa005_file().startswith("$$AA01CPA1464[TEST[NL$$\r\nA000000001"))

        bank_sudo.clearing_number = "022233333"  # not RBC
        self.assertTrue(self.batch._generate_cpa005_file().startswith("A000000001"), "The parameter only overrides RBC's routing record.")
