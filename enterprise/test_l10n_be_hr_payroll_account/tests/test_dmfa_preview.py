# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.tests import HttpCase, freeze_time, tagged

from odoo.addons.hr_payroll_account.tests.common import TestPayslipValidationCommon


@tagged('post_install', '-at_install', 'dmfa')
class TestDMFAPreview(TestPayslipValidationCommon, HttpCase):

    @classmethod
    @TestPayslipValidationCommon.setup_country('be')
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data['company']
        cls.company.onss_expeditor_number = '123456'
        cls.company.current_payroll_config_id.write({
            'l10n_be_company_number': '0123456749',
            'onss_registration_number': '125482497',
            'l10n_be_employer_category_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00010').id,
            'onss_importance_code': '4',
        })
        cls.branch = cls.env['res.company'].create({'name': 'Perwez', 'parent_id': cls.company.id})
        cls.env.user.company_ids |= cls.branch
        # With an active Belgian language (e.g. with the demo data), the payslips are only validated in a Belgian
        # language: the one of the unit, as the employees are in English
        cls.env['hr.work.location'].search([('address_id', '=', cls.company.partner_id.id)]).write({
            'bce_code': '8888888176',
            'location_type': 'dmfa_unit',
            'payslip_language_id': cls.env['res.lang']._activate_lang('fr_BE').id,
        })
        cls.employees = cls.env['hr.employee'].create([{
            'name': name,
            'niss': niss,
            'private_street': 'Rue de la Station 1',
            'private_city': 'Perwez',
            'private_zip': '1360',
            'private_country_id': cls.env.ref('base.be').id,
            'company_id': company.id,
            'address_id': cls.company.partner_id.id,
            'structure_type_id': cls.env.ref('hr.structure_type_employee_cp200').id,
            'contract_date_start': date(2018, 12, 31),
            'date_version': date(2018, 12, 31),
            'wage': 3000,
            'l10n_be_joint_committee_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'en_US',
        } for name, niss, company in [
            ('Head Office Worker', '91111111192', cls.company),
            ('Branch Worker', '93051822361', cls.branch),
        ]])

    @freeze_time("2026-07-01 10:00:00")
    def test_dmfa_preview_tour(self):
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip April 2026',
            'employee_id': employee.id,
            'version_id': employee.version_id.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': employee.company_id.id,
        } for employee in self.employees])
        payslips.compute_sheet()
        self.employees.write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()
        dmfa = self.env['l10n_be.dmfa'].create({
            'name': 'TESTDMFA',
            'company_id': self.company.id,
            'year': '2026',
            'quarter': '2',
            'declaration_method': 'web',
        })
        self.assertEqual(dmfa.payslip_ids, payslips)
        self.start_tour(
            f'/odoo/action-l10n_be_hr_payroll.hr_payslip_report_action_dmfa/{dmfa.id}', 'l10n_be_dmfa_preview',
            login=self.env.user.login, cookies={'cids': f'{self.company.id}-{self.branch.id}'})
