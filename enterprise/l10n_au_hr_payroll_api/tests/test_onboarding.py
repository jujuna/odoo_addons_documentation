# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from unittest.mock import Mock, patch

from odoo.exceptions import UserError, ValidationError, RedirectWarning
from odoo.tests import tagged, Form, new_test_user
from odoo.addons.l10n_au_hr_payroll_account.tests.common import L10nPayrollAccountCommon
from odoo.addons.l10n_au_hr_payroll_api.models import account_edi_proxy_user
from .common import TestL10nAUPayrollAPICommon


@tagged("post_install_l10n", "post_install", "-at_install", "l10n_au_hr_payroll")
class TestPayrollOnboardingAPI(L10nPayrollAccountCommon, TestL10nAUPayrollAPICommon):
    _test_user_groups = None  # FIXME list needed groups

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.sequence'].create({
            'name': 'STP Sequence',
            'code': 'stp.transaction',
            'prefix': 'PAYEVENT0004',
            'padding': 10,
            'number_next': 1,
        })
        cls.company.write({
                "vat": "85658499097",
                "email": "au_company@odoo.com",
                "phone": "123456789",
                "zip": "2000",
                'l10n_au_branch_code': '100',
        })
        cls.employee_1.l10n_au_super_account_ids.fund_id.is_valid = True

        cls.env['ir.config_parameter'].sudo().set_str('l10n_au_payroll_iap.test_endpoint', 'http://127.0.0.1:8070')
        cls.proxy_user = cls.env['account_edi_proxy_client.user']._register_proxy_user(cls.company, 'l10n_au_payroll', 'demo')
        cls.proxy_user.edi_mode = 'test'
        assert cls.company.l10n_au_payroll_mode == 'test'

    def test_payroll_without_onboarding(self):
        """ Test that the company can register payroll without going through onboarding """
        with self.assertRaises(UserError):
            payrun = self._prepare_payslip_run(self.employee_1 + self.employee_2)

        self._register_company()
        payrun = self._prepare_payslip_run(self.employee_1 + self.employee_2)
        stp = self.env["l10n_au.stp"].search([("payslip_batch_id", "=", payrun.id)])
        stp.submit_date = date.today()

        with self.mock_stp_requests():
            self._submit_stp(stp)

    def test_payroll_onboarding_constrains(self):
        # Check all constrains of the onboarding

        with self.assertRaises(ValidationError):
            self.env.ref("l10n_au_hr_payroll_api.l10n_au_payroll_odoo_disclaimer").unlink()
            self.env.ref("l10n_au_hr_payroll_api.l10n_au_payroll_superchoice_dda").unlink()

        def action_next(wizard):
            action = wizard.save().action_next()
            return Form.from_action(self.env, action)
        # Payroll responsible
        wizard = Form.from_action(self.env, self.company.action_view_payroll_onboarding())
        registration = wizard._record.registration_id
        self.assertEqual(registration.status, "pending")
        wizard.payroll_responsible_id = self.employee_1
        wizard = action_next(wizard)

        # Authorisation confirmation
        self.assertEqual(wizard.stage, "authorised")
        with self.assertRaises(ValidationError):
            wizard.authorised = "no"
            action_next(wizard)
        wizard.authorised = "yes"
        wizard = action_next(wizard)

        # Company details
        self.assertEqual(wizard.stage, "company")
        wizard = action_next(wizard)

        # Bank details (Clearing number (BSB) and bank name are essential)
        self.assertEqual(wizard.stage, "bank")
        with self.assertRaises(RedirectWarning, msg="Clearing number (BSB) is required"):
            self.company_bank_account.clearing_number = False
            wizard.journal_id = self.bank_journal
            action_next(wizard)
        with self.assertRaises(RedirectWarning, msg="The bank name is required to register the payroll"):
            self.company_bank_account.bank_name = False
            action_next(wizard)

        # BIC number is not required to continue to next step
        self.company_bank_account.bank_bic = False

        wizard.journal_id = self.bank_journal
        wizard = action_next(wizard)

        # Sign documents
        self.assertEqual(wizard.stage, "sign_docs")
        with self.assertRaises(ValidationError, msg="You must accept the Odoo Terms & Conditions to proceed."):
            wizard._record.action_next()
        wizard.odoo_disclaimer_check = True
        wizard.superchoice_dda_check = True

        with self.mock_register_request():
            wizard.save().action_next()
        self.assertTrue(self.company.l10n_au_bms_id)
        self.assertEqual(registration.status, "registered")
        self.assertEqual(self.company.l10n_au_stp_responsible_id, self.employee_1)
        self.assertEqual(self.company.l10n_au_hr_super_responsible_id, self.employee_1)

    def test_expired_registration(self):
        """ Only admins are redirected to the settings when the registration has expired. """
        self._register_company()
        payroll_manager = new_test_user(
            self.env, login="au_payroll_manager", company_id=self.company.id,
            groups="hr_payroll.group_hr_payroll_manager,account.group_account_invoice",
        )
        expired_response = {"error": "The current BMS registration has expired.", "expired": True}
        # Requests to the payroll service are blocked during tests: lift that block, only the answer is mocked
        with patch.object(account_edi_proxy_user, "tools", Mock(config={"test_enable": False})), \
             patch.object(account_edi_proxy_user, "modules", Mock(module=Mock(current_test=None))), \
             patch.object(self.registry["account_edi_proxy_client.user"], "_make_request", return_value=expired_response), \
             self.enter_registry_test_mode():
            with self.assertRaises(RedirectWarning) as admin_error:
                self.proxy_user._l10n_au_payroll_request("/superchoice/authenticateCredential")
            with self.assertRaisesRegex(UserError, "Please contact your administrator to re-register the company"):
                self.proxy_user.with_user(payroll_manager)._l10n_au_payroll_request("/superchoice/authenticateCredential")
        self.assertEqual(admin_error.exception.args[1], self.env.ref("hr_payroll.action_hr_payroll_configuration").id)
