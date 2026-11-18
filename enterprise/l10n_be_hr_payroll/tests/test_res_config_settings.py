# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import tagged

from .common import TestBelgiumCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nBeResConfigSettings(TestBelgiumCommon):

    def test_loss_on_commission_pto_setting(self):
        # The setting reflects and chooses which of the two mutually exclusive benefits is active
        monthly = self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_monthly')
        double_holiday = self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_double_holiday')
        com_loss_pto = self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_loss_on_commissions_pto')
        simple_variable = self.env.ref('l10n_be_hr_payroll.cp200_employees_double_holiday_single_holiday_variable_revenues')

        double_holiday.active = True
        settings = self.env['res.config.settings'].create({})
        self.assertEqual(settings.l10n_be_loss_on_commission_pto, 'double_holiday')

        self.env['res.config.settings'].create({'l10n_be_loss_on_commission_pto': 'monthly'}).execute()
        self.assertTrue(monthly.active)
        self.assertFalse(double_holiday.active)
        self.assertTrue(com_loss_pto.active)
        # skipped by its condition in JC 200 only, it still pays the other joint committees
        self.assertTrue(simple_variable.active)
        self.assertEqual(self.env['res.config.settings'].create({}).l10n_be_loss_on_commission_pto, 'monthly')

        # Saving the settings without changing the choice keeps it
        self.env['res.config.settings'].create({}).execute()
        self.assertTrue(monthly.active)
        self.assertFalse(double_holiday.active)

        self.env['res.config.settings'].create({'l10n_be_loss_on_commission_pto': 'double_holiday'}).execute()
        self.assertFalse(monthly.active)
        self.assertTrue(double_holiday.active)
        self.assertFalse(com_loss_pto.active)
        self.assertTrue(simple_variable.active)
        self.assertEqual(self.env['res.config.settings'].create({}).l10n_be_loss_on_commission_pto, 'double_holiday')

        # The choice is shared by all the companies: the benefits and the salary rules have no company
        other_company = self.env['res.company'].create({'name': 'Other BE Company', 'country_id': self.env.ref('base.be').id})
        settings = self.env['res.config.settings'].with_company(other_company).create({})
        self.assertEqual(settings.l10n_be_loss_on_commission_pto, 'double_holiday')
