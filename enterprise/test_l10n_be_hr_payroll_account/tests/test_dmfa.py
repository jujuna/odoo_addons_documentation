# Part of Odoo. See LICENSE file for full copyright and licensing details.

import time
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from lxml import etree
from unittest.mock import MagicMock, patch

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import freeze_time, tagged

from odoo.addons.hr_payroll_account.tests.common import TestPayslipValidationCommon
from odoo.addons.l10n_be_hr_payroll.models.certificate import CertificateCertificate
from odoo.addons.l10n_be_hr_payroll.models.utils import xml_str_to_dict
from odoo.addons.l10n_be_hr_payroll.tests.common import TestBelgiumCommon
from odoo.addons.l10n_be_hr_payroll.models.hr_dmfa import L10n_BeDmfa
from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.test_l10n_be_hr_payroll_account.tests.common import TestPayslipNoAccountingCommon
from odoo.tools import date_utils, float_round


def get_variable_diff_as_message(actual_value, expected_value) -> str:
    """
    This function takes two values and will try to compare it (recursively if
    they are dicts/lists/tuples). If there are differences, it will return a
    description of the differences as a string, otherwise, it will return ""
    """
    # `path` represents the dict structure we are currently in
    def _diff(actual, expected, path) -> list:
        if not isinstance(actual, expected.__class__):
            return [f"{path}: type mismatch: expected {actual.__class__}, got {expected.__class__}"]

        diff_msgs_list = []
        if isinstance(expected, dict):
            all_keys = set(actual.keys()) | set(expected.keys())
            for key in sorted(all_keys):
                child_path = f"{path}[{key}]"
                if key not in actual:
                    diff_msgs_list.append(f"{child_path}: MISSING in actual (expected {expected[key]})")
                elif key not in expected:
                    diff_msgs_list.append(f"{child_path}: UNEXPECTED in actual (got {actual[key]})")
                else:
                    # values could be another dict, so we have to recursively compare it
                    diff_msgs_list.extend(_diff(actual[key], expected[key], child_path))

        elif isinstance(expected, (tuple, list)):
            if len(actual) != len(expected):
                diff_msgs_list.append(f"{path}: list length mismatch: got {len(actual)}, expected {len(expected)}")
            for i, (a_item, e_item) in enumerate(zip(actual, expected)):
                # values could be another list/tuple, so we have to recursively compare it
                diff_msgs_list.extend(_diff(a_item, e_item, f"{path}[{i}]"))
            # show extra/missing items
            if len(actual) > len(expected):
                for i, item in enumerate(actual[len(expected):], start=len(expected)):
                    diff_msgs_list.append(f"{path}[{i}]: UNEXPECTED in actual: {item}")
            elif len(expected) > len(actual):
                for i, item in enumerate(expected[len(actual):], start=len(actual)):
                    diff_msgs_list.append(f"{path}[{i}]: MISSING in actual: {item}")

        elif actual != expected:
            # values don't need to be recursively compared
            diff_msgs_list += [f"{path}"] if path != 'root' else []
            diff_msgs_list.append(f"expected: {expected}")
            diff_msgs_list.append(f"got:      {actual}")
        return diff_msgs_list

    return "\n".join(_diff(actual_value, expected_value, "root"))


# DMFA values that change from one run to another, masked in the JSON snapshots
DMFA_IGNORE_KEYS = (
    'NaturalPersonUserReference',  # hr.employee id
    'OccupationUserReference',  # hr.version id
    '@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation',  # depends on today's date
)


@tagged('post_install', '-at_install', 'dmfa', 'structural_deduction')
@patch.object(CertificateCertificate, '_decode_certificate_for_be_onss_xml', lambda contract, xml_str: b'dummy\r\nsignature\r\n')
class TestDMFA(TestPayslipNoAccountingCommon, TestBelgiumCommon):

    _test_user_groups = None  # FIXME list needed groups

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.env.user.group_ids |= cls.env.ref('hr_payroll.group_hr_payroll_user') | cls.env.ref('fleet.fleet_group_manager')
        cls.payroll_manager = mail_new_test_user(cls.env, login='blou', groups='hr_payroll.group_hr_payroll_manager,fleet.fleet_group_manager')

        cls.belgian_company = cls.env.company

        cls.belgian_company.write({
            'vat': 'BE0897223670',
            'phone': '0471098765',
            'street': 'Test street',
            'city': 'Test city',
            'zip': '8292',
            'country_id': cls.env.ref('base.be').id,
            'onss_expeditor_number': '123456',
        })
        cls.belgian_company.current_payroll_config_id.write({
            'l10n_be_revenue_code': '1234',
            'l10n_be_company_number': '0123456749',
            'onss_registration_number': '125482497',
            'l10n_be_employer_category_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00010').id,
            'l10n_be_main_joint_committee': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'onss_importance_code': '4',
        })

        cls.calendar_38h = cls.env['resource.calendar'].create({
            'name': 'Standard 38 hours/week',
            'company_id': cls.belgian_company.id,
            'hours_per_day': 7.6,
            'attendance_ids': [(5, 0, 0),
                (0, 0, {'dayofweek': '0', 'hour_from': 8, 'hour_to': 12}),
                (0, 0, {'dayofweek': '0', 'hour_from': 13, 'hour_to': 16.6}),
                (0, 0, {'dayofweek': '1', 'hour_from': 8, 'hour_to': 12}),
                (0, 0, {'dayofweek': '1', 'hour_from': 13, 'hour_to': 16.6}),
                (0, 0, {'dayofweek': '2', 'hour_from': 8, 'hour_to': 12}),
                (0, 0, {'dayofweek': '2', 'hour_from': 13, 'hour_to': 16.6}),
                (0, 0, {'dayofweek': '3', 'hour_from': 8, 'hour_to': 12}),
                (0, 0, {'dayofweek': '3', 'hour_from': 13, 'hour_to': 16.6}),
                (0, 0, {'dayofweek': '4', 'hour_from': 8, 'hour_to': 12}),
                (0, 0, {'dayofweek': '4', 'hour_from': 13, 'hour_to': 16.6})
            ],
        })
        cls.belgian_company.resource_calendar_id = cls.calendar_38h
        cls.calendar_38h.write({'reference_calendar_id': cls.calendar_38h.id})

        cls.calendar_4_days_36_hours = cls.env['resource.calendar'].create([{
            'name': "Test Calendar: 4 days, 36 hours/week",
            'company_id': cls.belgian_company.id,
            'hours_per_day': 9,
            'full_time_required_hours': 36.0,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for dayofweek, hour_from, hour_to in [
                ("0", 8.0, 12.0),
                ("0", 12.0, 13.0),
                ("0", 13.0, 18),
                ("1", 8.0, 12.0),
                ("1", 12.0, 13.0),
                ("1", 13.0, 18),
                ("2", 8.0, 12.0),
                ("2", 12.0, 13.0),
                ("2", 13.0, 18),
                ("3", 8.0, 12.0),
                ("3", 12.0, 13.0),
                ("3", 13.0, 18),
            ]]
        }]).sudo(False)
        cls.calendar_4_days_36_hours.write({'reference_calendar_id': cls.calendar_4_days_36_hours.id})

        cls.calendar_4_5_wednesday_off = cls.env['resource.calendar'].sudo().create([{
            'name': "Test Calendar: 4/5 Wednesday Off",
            'company_id': cls.belgian_company.id,
            'hours_per_day': 7.6,
            'full_time_required_hours': 38.0,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for dayofweek, hour_from, hour_to in [
                ("0", 8.0, 12.0),
                ("0", 13.0, 16.6),
                ("1", 8.0, 12.0),
                ("1", 13.0, 16.6),
                ("3", 8.0, 12.0),
                ("3", 13.0, 16.6),
                ("4", 8.0, 12.0),
                ("4", 13.0, 16.6),
            ]] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': cls.env.ref('hr_work_entry.l10n_be_work_entry_type_credit_time').id,
            }) for dayofweek, hour_from, hour_to in [
                ("2", 8.0, 12.0),
                ("2", 13.0, 16.6),
            ]],
        }]).sudo(False)

        cls.calendar_0_hours_per_week_credit_time = cls.env['resource.calendar'].create([{
            'name': "Test Calendar: 0 Hours per week",
            'company_id': cls.belgian_company.id,
            'hours_per_day': 0,
            'full_time_required_hours': 38,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': cls.env.ref('hr_work_entry.l10n_be_work_entry_type_credit_time').id,
            }) for dayofweek, hour_from, hour_to in [
                ("0", 8.0, 12.0),
                ("0", 13.0, 16.6),
                ("1", 8.0, 12.0),
                ("1", 13.0, 16.6),
                ("2", 8.0, 12.0),
                ("2", 13.0, 16.6),
                ("3", 8.0, 12.0),
                ("3", 13.0, 16.6),
                ("4", 8.0, 12.0),
                ("4", 13.0, 16.6),
            ]],
        }])

        cls.calendar_0_hours_per_week_partial_incapacity = cls.env['resource.calendar'].create([{
            'name': "Test Calendar: 0 Hours per week",
            'company_id': cls.belgian_company.id,
            'hours_per_day': 0,
            'hours_per_week': 0,
            'full_time_required_hours': 38,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': cls.env.ref('hr_work_entry.l10n_be_work_entry_type_partial_incapacity').id,
            }) for dayofweek, hour_from, hour_to in [
                ("0", 8.0, 12.0),
                ("0", 13.0, 16.6),
                ("1", 8.0, 12.0),
                ("1", 13.0, 16.6),
                ("2", 8.0, 12.0),
                ("2", 13.0, 16.6),
                ("3", 8.0, 12.0),
                ("3", 13.0, 16.6),
                ("4", 8.0, 12.0),
                ("4", 13.0, 16.6),
            ]],
        }])

        cls.work_contact = cls.env['res.partner'].create({'name': 'Test Work Contact'})

        cls.brand = cls.env['fleet.vehicle.model.brand'].sudo().create({
            'name': "Test Brand"
        })

        cls.model = cls.env['fleet.vehicle.model'].sudo().create({
            'name': "Test Model",
            'brand_id': cls.brand.id
        })

        with freeze_time('2020-10-08'):
            cls.car = cls.env['fleet.vehicle'].sudo().create({
                'name': "Test Car",
                'license_plate': "TEST",
                'driver_id': cls.work_contact.id,
                'company_id': cls.belgian_company.id,
                'model_id': cls.model.id,
                'contract_date_start': date(2020, 10, 8),
                'co2': 88.0,
                'car_value': 38000.0,
                'fuel_type': "diesel",
                'acquisition_date': date(2020, 1, 1)
            }).sudo(False)

            cls.env['fleet.vehicle.log.contract'].sudo().create({
                'name': "Test Contract",
                'vehicle_id': cls.car.id,
                'company_id': cls.belgian_company.id,
                'start_date': date(2020, 10, 8),
                'expiration_date': date(2021, 10, 8),
                'state': "open",
                'cost_generated': 0.0,
                'cost_frequency': "monthly",
                'recurring_cost_amount_depreciated': 450.0
            })

        cls.cp200 = cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Laurie Poiret',
            'work_contact_id': cls.work_contact.id,
            'niss': '91111111192',
            'marital': 'single',
            'private_street': '58 rue des Wallons',
            'private_city': 'Louvain-la-Neuve',
            'private_zip': '1348',
            'private_country_id': cls.env.ref("base.be").id,
            'private_phone': '+0032476543210',
            'private_email': 'laurie.poiret@example.com',
            'resource_calendar_id': cls.calendar_38h.id,
            'company_id': cls.belgian_company.id,
            'car_id': cls.car.id,
            'structure_type_id': cls.env.ref('hr.structure_type_employee_cp200').id,
            'contract_date_start': date(2018, 12, 31),
            'date_version': date(2018, 12, 31),
            'wage': 3000,
            'transport_mode_car': True,
            'fuel_card': 150.0,
            'internet': 38.0,
            'mobile': 30.0,
            'meal_voucher_amount': 7.45,
            'l10n_be_lsa_monthly_misc_base_amount': 283.73,
            'l10n_be_lsa_monthly_pro_other_amount': 16.27,
            'l10n_be_joint_committee_id': cls.cp200.id,
            'l10n_be_salary_scale_id': cls.env.ref('l10n_be_hr_payroll.cp200_b').id,
            # fully compensated: this suite doesn't test the annual sectorial bonus
            'l10n_be_sectorial_bonus_compensatory_amount': 1000.0,
            'lang': 'fr_BE',
        })
        cls.contract = cls.employee.version_id

        company = cls.employee.company_id
        cls.payroll_manager.company_ids = [(4, company.id)]
        cls.partner_wallonia = cls.env['res.partner'].create({'name': 'WA Work Address'})
        cls.env["hr.work.location"].with_user(cls.payroll_manager).search([
            ("address_id", "=", company.partner_id.id),
        ]).write({"bce_code": "8888888176", "location_type": "dmfa_unit"})
        cls.env['hr.work.location'].with_user(cls.payroll_manager).create({
            'company_id': cls.belgian_company.id,
            'bce_code': '8888888275',
            'location_type': 'dmfa_unit',
            'address_id': cls.partner_wallonia.id,
            'competence': 'wa',
        })

        cls.employee_2 = cls.env['hr.employee'].create({
            'name': 'Michael Demo',
            'work_contact_id': cls.work_contact.id,
            'niss': '91111111291',
            'marital': 'single',
            'private_street': '58 rue des Wallons',
            'private_city': 'Louvain-la-Neuve',
            'private_zip': '1348',
            'private_country_id': cls.env.ref("base.be").id,
            'private_phone': '+0032476543210',
            'private_email': 'michael.demo@example.com',
            'resource_calendar_id': cls.calendar_38h.id,
            'company_id': cls.belgian_company.id,
            'car_id': cls.car.id,
            'structure_type_id': cls.env.ref('hr.structure_type_employee_cp200').id,
            'contract_date_start': date(2018, 12, 31),
            'date_version': date(2018, 12, 31),
            'wage': 3000,
            'transport_mode_car': True,
            'fuel_card': 150.0,
            'internet': 38.0,
            'mobile': 30.0,
            'meal_voucher_amount': 7.45,
            'l10n_be_lsa_monthly_misc_base_amount': 283.73,
            'l10n_be_lsa_monthly_pro_other_amount': 16.27,
            'eco_checks': 250,
            'active': False,
        })
        # Activate the benefit
        cls.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', 'in', ['l10n_be_lsa_monthly_pro_other_amount', 'l10n_be_lsa_monthly_misc_base_amount'])]).active = True

        # Structural deduction
        cls.belgium_monthly_payslip_structure = cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        cls.belgium_thirteen_month_structure = cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month')

    def _assertDMFAEqual(self, dmfa_dict, ignore_keys=DMFA_IGNORE_KEYS, label=None):
        """
        Compare the DMFA dict with the JSON snapshot of the test
        (tests/test_files/dmfa/test_dmfa/<test method>.json), see
        TestPayrollBase._assert_dict_snapshot on how to (re)generate it.
        Volatile values (record ids, xsd version...) are masked with `ignore_keys`.
        """
        self._assert_dict_snapshot(
            dmfa_dict, 'dmfa', label=label, ignore_keys=ignore_keys, diff=get_variable_diff_as_message)

    @staticmethod
    def fake_time_object():
        today = datetime.now()
        day = today.strftime('%Y%m%d')
        hour = today.strftime('%H:%M:%S.%f')[:-3]
        return patch.object(time, 'strftime', lambda fmt, t: day if fmt == '%Y%m%d' else hour)

    def _generate_dmfa_declaration(self, environment='S', declaration_type='original', year='2025', quarter='1', parent=None, return_declaration=False, skip_signature=True):
        dmfa = self.env['l10n_be.dmfa'].with_user(self.payroll_manager).create({
            'name': 'TESTDMFA',
            'company_id': self.belgian_company.id,
            'year': year,
            'quarter': quarter,
            'declaration_method': 'batch',
            'declaration_type': declaration_type,
            'environment': environment,
            'parent_id': parent.id if parent else False,
        })
        with self.fake_time_object():
            dmfa.with_context(onss_skip_signature=skip_signature).generate_declaration_xml_report()
        self.assertFalse(dmfa.error_message)
        self.assertEqual(dmfa.state, 'ready')
        if return_declaration:
            return dmfa
        return xml_str_to_dict(dmfa.xml_file.content)

    def _get_ded3000(self, employee, payslips):
        occupation_data = employee.version_ids.sorted('date_start', reverse=True)._get_occupation_dates()
        occupation_groups = []
        ded3000_by_occupation = {}
        for versions, _, _ in occupation_data:
            slips = payslips.filtered(lambda p, versions=versions: p.version_id in versions)
            if slips:
                occupation_groups.append((versions, slips))
        mu_global = 0
        for _, slips in occupation_groups:
            mu_global += L10n_BeDmfa._get_l10n_be_mu(slips[:1].version_id, payslips=slips)
        for contracts, slips in occupation_groups:
            ded3000_by_occupation[contracts, slips] = L10n_BeDmfa._get_l10n_be_structural_deduction_3000(slips, mu_global)
        return ded3000_by_occupation

    @freeze_time("2025-04-10 10:00:00")
    def test_01_empty_dmfa(self):
        dmfa_dict = self._generate_dmfa_declaration()
        self._assertDMFAEqual(dmfa_dict)

    @freeze_time("2025-04-10 10:00:00")
    def test_02_declaration_classic_employee_with_commissions(self):
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025 %s',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Mar 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 3, 1),
            'date_to': datetime(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])
        payslips[0]._set_input_value('COMMISSION', 2000)

        self.employee.write({'review_state': '1_reviewed'})
        for payslip in payslips:  # No batch compute and validate for ONSS regularization
            payslip.compute_sheet()
            payslip.action_payslip_done()

        self._validate_payslip(payslips[0])
        self._validate_payslip(payslips[1])
        self._validate_payslip(payslips[2])
        dmfa_dict = self._generate_dmfa_declaration()
        self.assertEqual(dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['NaturalPersonUserReference'], str(self.employee.id))
        self.assertEqual(dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']['OccupationUserReference'], str(self.contract.id))
        self._assertDMFAEqual(dmfa_dict)
        ded3000 = self._get_ded3000(self.employee, payslips)
        self.assertIn(0, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

    @freeze_time("2025-04-10 10:00:00")
    def test_03_declaration_employee_partial_credit_time(self):
        self.contract.contract_date_end = date(2025, 2, 28)
        contract_credit_time = self.env['hr.version'].create({
            'name': "Contract Credit Time",
            'employee_id': self.employee.id,
            'resource_calendar_id': self.calendar_4_5_wednesday_off.id,
            'reference_calendar_id': self.calendar_38h.id,
            'work_time_rate': 0.8,
            'company_id': self.belgian_company.id,
            'car_id': self.car.id,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'date_version': date(2025, 3, 1),
            'contract_date_start': date(2025, 3, 1),
            'wage': 3000,
            'transport_mode_car': True,
            'fuel_card': 150.0,
            'internet': 38.0,
            'mobile': 30.0,
            'meal_voucher_amount': 7.45,
            'l10n_be_lsa_monthly_misc_base_amount': 283.73,
            'l10n_be_lsa_monthly_pro_other_amount': 16.27,
            'l10n_be_joint_committee_id': self.cp200.id,
        })
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025 %s',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Mar 2025',
            'version_id': contract_credit_time.id,
            'date_from': datetime(2025, 3, 1),
            'date_to': datetime(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])
        payslips[0]._set_input_value('COMMISSION', 2000)
        payslips.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        for payslip in payslips:  # No batch compute and validate for ONSS regularization
            payslip.compute_sheet()
            payslip.action_payslip_done()
        self._validate_payslip(payslips[0])
        self._validate_payslip(payslips[1])
        self._validate_payslip(payslips[2])

        dmfa_dict = self._generate_dmfa_declaration()
        self.assertEqual(dmfa_dict['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], self._get_dmfa_original_xsd())
        natural_person = dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']
        self.assertEqual(natural_person['NaturalPersonUserReference'], str(self.employee.id))
        self.assertEqual(natural_person['WorkerRecord']['Occupation'][0]['OccupationUserReference'], str(contract_credit_time.id))
        self.assertEqual(natural_person['WorkerRecord']['Occupation'][1]['OccupationUserReference'], str(self.contract.id))
        self._assertDMFAEqual(dmfa_dict)
        ded3000 = self._get_ded3000(self.employee, payslips)
        self.assertIn(71.66, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")
        self.assertIn(0, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

    @freeze_time("2025-04-10 10:00:00")
    def test_04_declaration_employee_full_credit_time(self):
        self.contract.contract_date_end = date(2025, 2, 28)
        contract_credit_time = self.env['hr.version'].create({
            'name': "Contract Credit Time",
            'employee_id': self.employee.id,
            'resource_calendar_id': self.calendar_0_hours_per_week_credit_time.id,
            'reference_calendar_id': self.calendar_38h.id,
            'work_time_rate': 0,
            'company_id': self.belgian_company.id,
            'car_id': self.car.id,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'date_version': date(2025, 3, 1),
            'contract_date_start': date(2025, 3, 1),
            'wage': 3000 * 4 / 5,
            'transport_mode_car': True,
            'fuel_card': 150.0,
            'internet': 38.0,
            'mobile': 30.0,
            'meal_voucher_amount': 7.45,
            'l10n_be_lsa_monthly_misc_base_amount': 283.73,
            'l10n_be_lsa_monthly_pro_other_amount': 16.27,
            'l10n_be_joint_committee_id': self.cp200.id,
        })
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025 %s',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Mar 2025',
            'version_id': contract_credit_time.id,
            'date_from': datetime(2025, 3, 1),
            'date_to': datetime(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])
        payslips[0]._set_input_value('COMMISSION', 2000)
        payslips.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        for payslip in payslips:  # No batch compute and validate for ONSS regularization
            payslip.compute_sheet()
            payslip.action_payslip_done()
        self._validate_payslip(payslips[0])
        self._validate_payslip(payslips[1])
        self._validate_payslip(payslips[2])
        dmfa_dict = self._generate_dmfa_declaration()

        self.assertEqual(dmfa_dict['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], self._get_dmfa_original_xsd())
        natural_person = dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']
        occupations = natural_person['WorkerRecord']['Occupation']
        self.assertEqual(natural_person['NaturalPersonUserReference'], str(self.employee.id))
        self.assertEqual(occupations[0]['OccupationUserReference'], str(contract_credit_time.id))
        self.assertEqual(occupations[1]['OccupationUserReference'], str(self.contract.id))
        self._assertDMFAEqual(dmfa_dict)
        ded3000 = self._get_ded3000(self.employee, payslips)
        self.assertIn(0, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

    @freeze_time("2025-04-10 10:00:00")
    def test_05_declaration_employee_partial_incapacity(self):
        self.contract.contract_date_end = date(2025, 2, 28)
        contract_credit_time = self.env['hr.version'].create({
            'name': "Contract Credit Time",
            'employee_id': self.employee.id,
            'resource_calendar_id': self.calendar_0_hours_per_week_partial_incapacity.id,
            'reference_calendar_id': self.calendar_38h.id,
            'work_time_rate': 0,
            'company_id': self.belgian_company.id,
            'car_id': self.car.id,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'date_version': date(2025, 3, 1),
            'contract_date_start': date(2025, 3, 1),
            'wage': 3000 * 4 / 5,
            'transport_mode_car': True,
            'fuel_card': 150.0,
            'internet': 38.0,
            'mobile': 30.0,
            'meal_voucher_amount': 7.45,
            'l10n_be_lsa_monthly_misc_base_amount': 283.73,
            'l10n_be_lsa_monthly_pro_other_amount': 16.27,
            'l10n_be_joint_committee_id': self.cp200.id,
        })
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025 %s',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Mar 2025',
            'version_id': contract_credit_time.id,
            'date_from': datetime(2025, 3, 1),
            'date_to': datetime(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])
        payslips[0]._set_input_value('COMMISSION', 2000)
        payslips.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        for payslip in payslips:  # No batch compute and validate for ONSS regularization
            payslip.compute_sheet()
            payslip.action_payslip_done()
        self._validate_payslip(payslips[0])
        self._validate_payslip(payslips[1])
        self._validate_payslip(payslips[2])
        dmfa_dict = self._generate_dmfa_declaration()
        self.assertEqual(dmfa_dict['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], self._get_dmfa_original_xsd())
        natural_person = dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']
        occupations = natural_person['WorkerRecord']['Occupation']
        self.assertEqual(natural_person['NaturalPersonUserReference'], str(self.employee.id))
        self.assertEqual(occupations[0]['OccupationUserReference'], str(contract_credit_time.id))
        self.assertEqual(occupations[1]['OccupationUserReference'], str(self.contract.id))
        self._assertDMFAEqual(dmfa_dict)
        ded3000 = self._get_ded3000(self.employee, payslips)
        self.assertIn(0, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

    @freeze_time("2025-04-11 10:00:00")
    def test_06_declaration_employee_no_notice_period(self):
        departure_notice = self.env['hr.employee.departure'].create({
            'employee_id': self.employee.id,
            'departure_reason_id': self.env.ref('hr.departure_fired').id,
            'dismissal_date': date(2025, 2, 10),
            'l10n_be_notice_respect': 'without',
            'departure_description': 'foo',
            'action_date': date(2025, 2, 11),
        })
        self.contract.write({
            "contract_date_end": date(2025, 2, 10)
        })
        self.employee.write({
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 283.73,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True

        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])
        payslips[0]._set_input_value('COMMISSION', 2000)
        payslips[0].compute_sheet()
        self._validate_payslip(payslips[0])
        payslips[0].action_payslip_done()
        payslips[1].compute_sheet()
        # incomplete month as the employee's last day on the 10th of february
        self._validate_payslip(payslips[1])
        payslips[1].action_payslip_done()

        self.employee.review_state = '1_reviewed'
        departure_notice._compute_payslip_history()
        departure_notice.action_register()
        departure_payslips = departure_notice._generate_termination_payslip()
        departure_payslips += departure_notice._generate_termination_holidays()

        # Termination Fees
        struct_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        termination_fees_payslip = departure_payslips.filtered(lambda pay: pay.struct_id == struct_id)
        termination_fees_payslip.compute_sheet()
        self._validate_payslip(termination_fees_payslip)

        # Holiday Attests
        structure_holidays_n = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays')
        structure_holidays_n1 = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n1_holidays')
        holiday_pay_n = departure_payslips.filtered(lambda pay: pay.struct_id == structure_holidays_n)
        holiday_pay_n1 = departure_payslips.filtered(lambda pay: pay.struct_id == structure_holidays_n1)
        self._validate_payslip(holiday_pay_n)
        self._validate_payslip(holiday_pay_n1)
        departure_payslips.action_payslip_done()

        thirteen_month_payslip = self.env['hr.payslip'].create({
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month').id,
            'company_id': self.belgian_company.id,
        })
        thirteen_month_payslip._set_input_value('MONTH', 8)
        thirteen_month_payslip.compute_sheet()
        self._validate_payslip(thirteen_month_payslip)
        self.employee.write({'review_state': '1_reviewed'})
        thirteen_month_payslip.action_payslip_done()

        dmfa_dict = self._generate_dmfa_declaration()
        self._assertDMFAEqual(dmfa_dict)
        ded3000 = self._get_ded3000(self.employee, payslips)
        self.assertIn(0, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

        # The employee without departure date anymore (e.g. rehired since): the indemnity still covers the period from
        # the day after the end of the contract
        def worker_records(dmfa):
            return etree.tostring(etree.fromstring(dmfa.xml_file.content).find('.//NaturalPerson'))
        self.env['l10n_be.dmfa'].search([('company_id', '=', self.belgian_company.id)]).unlink()
        expected = worker_records(self._generate_dmfa_declaration(return_declaration=True))
        self.env['l10n_be.dmfa'].search([('company_id', '=', self.belgian_company.id)]).unlink()
        self.employee.departure_date = False
        self.assertEqual(worker_records(self._generate_dmfa_declaration(return_declaration=True)), expected)

    def _set_declaration_employee_no_notice_period(self):
        departure_notice = self.env['hr.employee.departure'].create({
            'employee_id': self.employee.id,
            'departure_reason_id': self.env.ref('hr.departure_fired').id,
            'dismissal_date': date(2025, 2, 10),
            'l10n_be_notice_respect': 'without',
            'departure_description': 'foo',
        })

        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Sep 2024',
            'version_id': self.contract.id,
            'date_from': datetime(2024, 9, 1),
            'date_to': datetime(2024, 9, 30),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Oct 2024',
            'version_id': self.contract.id,
            'date_from': datetime(2024, 10, 1),
            'date_to': datetime(2024, 10, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Nov 2024',
            'version_id': self.contract.id,
            'date_from': datetime(2024, 11, 1),
            'date_to': datetime(2024, 11, 30),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Dec 2024',
            'version_id': self.contract.id,
            'date_from': datetime(2024, 12, 1),
            'date_to': datetime(2024, 12, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Jan 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])
        payslips.compute_sheet()
        payslips.action_payslip_done()
        departure_notice._compute_payslip_history()
        departure_notice.action_register()
        departure_payslips = departure_notice._generate_termination_payslip()
        departure_payslips += departure_notice._generate_termination_holidays()
        return [('id', 'in', departure_payslips.ids)]

    @freeze_time("2025-05-11 10:00:00")
    def test_06_bis_declaration_employee_no_notice_period_with_special_contributions_part_time(self):
        self.employee.wage = 4500  # force the wage to be high enough to trigger special contributions
        self.employee.resource_calendar_id = self.calendar_4_5_wednesday_off
        self.employee.reference_calendar_id = self.calendar_38h
        payslips_domain = self._set_declaration_employee_no_notice_period()

        departure_payslips = self.env['hr.payslip'].search(payslips_domain)

        # Termination Fees
        struct_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        termination_fees_payslip = departure_payslips.filtered(lambda pay: pay.struct_id == struct_id)
        termination_fees_payslip.compute_sheet()
        self._validate_payslip(termination_fees_payslip)

        self.employee.write({'review_state': '1_reviewed'})
        termination_fees_payslip.action_payslip_done()

        dmfa_dict = self._generate_dmfa_declaration()
        result_line = next(line for line in dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['WorkerContribution'] if line['ContributionWorkerCode'] == '812')
        expected_line = {'ContributionWorkerCode': '812', 'ContributionType': '1', 'ContributionCalculationBasis': '00002666539', 'ContributionAmount': '00000026665'}
        self.assertDictEqual(expected_line, result_line)

    @freeze_time("2025-05-11 10:00:00")
    def test_06_bis_declaration_employee_no_notice_period_with_special_contributions(self):
        self.employee.wage = 4500  # force the wage to be high enough to trigger special contributions
        payslips_domain = self._set_declaration_employee_no_notice_period()

        departure_payslips = self.env['hr.payslip'].search(payslips_domain)

        # Termination Fees
        struct_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        termination_fees_payslip = departure_payslips.filtered(lambda pay: pay.struct_id == struct_id)
        termination_fees_payslip.compute_sheet()
        self._validate_payslip(termination_fees_payslip)

        self.employee.write({'review_state': '1_reviewed'})
        termination_fees_payslip.action_payslip_done()

        dmfa_dict = self._generate_dmfa_declaration()
        result_line = next(line for line in dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['WorkerContribution'] if line['ContributionWorkerCode'] == '812')
        expected_line = {'ContributionWorkerCode': '812', 'ContributionType': '1', 'ContributionCalculationBasis': '00002679895', 'ContributionAmount': '00000026799'}
        self.assertDictEqual(expected_line, result_line)

    @freeze_time("2025-05-11 10:00:00")
    def test_06_bis_declaration_employee_no_notice_period_with_special_contributions_multiple_empty_quarters(self):
        self.employee.wage = 4500  # force the wage to be high enough to trigger special contributions

        # Create two full quarters without remuneration
        self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'request_date_from': date(2024, 10, 1),
            'request_date_to': date(2025, 3, 31),
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        })

        payslips_domain = self._set_declaration_employee_no_notice_period()

        departure_payslips = self.env['hr.payslip'].search(payslips_domain)

        # Termination Fees
        struct_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        termination_fees_payslip = departure_payslips.filtered(lambda pay: pay.struct_id == struct_id)
        termination_fees_payslip.compute_sheet()
        self._validate_payslip(termination_fees_payslip)

        # Should iterate beyond the previous quarter(s)
        yearly_salary = termination_fees_payslip._l10n_be_get_termination_yearly_salary()
        self.assertGreater(yearly_salary, 0)

        self.employee.write({'review_state': '1_reviewed'})
        termination_fees_payslip.action_payslip_done()

        dmfa_dict = self._generate_dmfa_declaration()
        result_line = next(line for line in dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['WorkerContribution'] if line['ContributionWorkerCode'] == '812')
        expected_line = {'ContributionWorkerCode': '812', 'ContributionType': '1', 'ContributionCalculationBasis': '00002679895', 'ContributionAmount': '00000026799'}
        self.assertDictEqual(expected_line, result_line)

    @freeze_time("2025-05-11 10:00:00")
    def test_06_bis_declaration_employee_no_notice_period_with_special_contributions_before_2014(self):
        """
        TERM_BASIC = 62926.33
        As this employee started before 2014, their cotisation_812 is only due on the part of the indemnity based on
        the seniority since 2014: the Part II of the notice (36 weeks), not the Part I (3 months, 13 weeks)
        So his cotisation basis will be 62926.33 * 36 / (13 + 36) = 46231.59
        so his cotisation_812 will be equal to 462.32
        """
        self.employee.wage = 4500  # force the wage to be high enough to trigger special contributions
        self.employee.contract_date_start = date(2010, 12, 31)
        self.employee.date_version = date(2010, 12, 31)
        payslips_domain = self._set_declaration_employee_no_notice_period()
        departure_payslips = self.env['hr.payslip'].search(payslips_domain)

        # Termination Fees
        struct_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        termination_fees_payslip = departure_payslips.filtered(lambda pay: pay.struct_id == struct_id)
        termination_fees_payslip.compute_sheet()

        self._validate_payslip(termination_fees_payslip)

        self.employee.write({'review_state': '1_reviewed'})
        termination_fees_payslip.action_payslip_done()

        dmfa_dict = self._generate_dmfa_declaration()
        result_line = next(line for line in dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['WorkerContribution'] if line['ContributionWorkerCode'] == '812')
        expected_line = {'ContributionWorkerCode': '812', 'ContributionType': '1', 'ContributionCalculationBasis': '00004623159', 'ContributionAmount': '00000046232'}
        self.assertDictEqual(expected_line, result_line)

    @classmethod
    def _get_dmfa_original_xsd(cls):
        """
        Part of the DMFA (for e.g.:)
        expected_dict['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation']
        would change values according to today's date.
        This function returns the correct value assuming the DMFA has been
        generated today.
        """
        target_date = date.today() - relativedelta(months=3)
        target_quarter = (target_date.month - 1) // 3 + 1
        current_year_quarter = '%s%s' % (target_date.year, target_quarter)
        return 'DmfAOriginal_' + current_year_quarter + '.xsd'

    @freeze_time("2026-07-01 10:00:00")
    def test_07_declaration_employee_notice_period(self):
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        departure_notice = self.env['hr.employee.departure'].create({
            'employee_id': self.employee.id,
            'departure_reason_id': self.env.ref('hr.departure_fired').id,
            'dismissal_date': date(2025, 2, 10),
            'l10n_be_notice_respect': 'with',
            'departure_description': 'foo',
            'action_date': date(2025, 2, 11),
        })

        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025 %s',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])
        payslips[0]._set_input_value('COMMISSION', 2000)
        payslips[0].compute_sheet()
        self._validate_payslip(payslips[0])
        payslips[0].action_payslip_done()
        payslips[1].compute_sheet()
        self._validate_payslip(payslips[1])
        payslips[1].action_payslip_done()

        departure_notice.action_register()
        departure_payslips = departure_notice._generate_termination_holidays()

        # Termination Fees
        struct_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        termination_fees_payslip = departure_payslips.filtered(lambda dep: dep.struct_id == struct_id)
        self.assertFalse(termination_fees_payslip, "There should not be a termination fees payslip as the employee is doing his departure notice.")

        # Holiday Attests
        structure_holidays_n = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays')
        structure_holidays_n1 = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n1_holidays')
        holiday_pay_n = departure_payslips.filtered(lambda pay: pay.struct_id == structure_holidays_n)
        holiday_pay_n1 = departure_payslips.filtered(lambda pay: pay.struct_id == structure_holidays_n1)
        self._validate_payslip(holiday_pay_n)
        self._validate_payslip(holiday_pay_n1)

        thirteen_month_payslip = self.env['hr.payslip'].create({
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month').id,
            'company_id': self.belgian_company.id,
        })
        thirteen_month_payslip._set_input_value('MONTH', 8)
        thirteen_month_payslip.compute_sheet()
        self._validate_payslip(thirteen_month_payslip)
        self.employee.write({'review_state': '1_reviewed'})
        (payslips + termination_fees_payslip + holiday_pay_n + holiday_pay_n1 + thirteen_month_payslip)._compute_issues()
        (payslips + termination_fees_payslip + holiday_pay_n + holiday_pay_n1 + thirteen_month_payslip).action_payslip_done()

        dmfa_dict = self._generate_dmfa_declaration()
        self.assertEqual(dmfa_dict['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], self._get_dmfa_original_xsd())
        self._assertDMFAEqual(dmfa_dict, ignore_keys=DMFA_IGNORE_KEYS + ('FormCreationDate',))
        ded3000 = self._get_ded3000(self.employee, payslips)
        self.assertIn(0, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

    @freeze_time("2025-04-10 10:00:00")
    def test_08_declaration_structural_reductions_3000(self):
        self.contract.wage = 2000
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025 %s',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Mar 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 3, 1),
            'date_to': datetime(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])
        payslips[0]._set_input_value('COMMISSION', 2000)
        payslips.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        for payslip in payslips:  # No batch compute and validate for ONSS regularization
            payslip.compute_sheet()
            payslip.action_payslip_done()
        self._validate_payslip(payslips[0])
        self._validate_payslip(payslips[1])
        self._validate_payslip(payslips[2])
        dmfa_dict = self._generate_dmfa_declaration()
        self.assertEqual(dmfa_dict['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], self._get_dmfa_original_xsd())
        self.assertEqual(dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['NaturalPersonUserReference'], str(self.employee.id))
        self.assertEqual(dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']['OccupationUserReference'], str(self.contract.id))
        self._assertDMFAEqual(dmfa_dict)
        ded3000 = self._get_ded3000(self.employee, payslips)
        self.assertIn(395.65, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

    @freeze_time("2026-12-30 10:00:00")
    def test_09_declaration_regularization_code_12_recovery(self):
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                'date_from': date(2025, 1, 1),
                'date_to': date(2025, 12, 31),
                "prev_work_time_rate": 1,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 10,
                "prev_simple_holiday_pay_paid": 2000,
                "prev_double_holiday_pay_paid": 0,
            }),
        ]
        self.contract.contract_date_start = date(2025, 1, 1)
        self.contract.wage = 2000

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave Nov",
            'calendar_id': self.calendar_38h.id,
            'company_id': self.belgian_company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime(2026, 11, 2, 6, 0, 0),
            'date_to': datetime(2026, 11, 6, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }, {
            'name': "Legal Leave Dec",
            'calendar_id': self.calendar_38h.id,
            'company_id': self.belgian_company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime(2026, 12, 7, 6, 0, 0),
            'date_to': datetime(2026, 12, 11, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        self.employee.write({'review_state': '1_reviewed'})

        for month in range(9, 13):
            payslip = self.env['hr.payslip'].create({
                'version_id': self.contract.id,
                'date_from': datetime(2026, month, 1),
                'date_to': datetime(2026, month, 30 if month in (9, 11) else 31),
                'employee_id': self.employee.id,
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
                'company_id': self.belgian_company.id,
            })
            payslip.compute_sheet()
            payslip.action_payslip_done()

        dmfa = self.env['l10n_be.dmfa'].with_user(self.payroll_manager).create({
            'name': 'TEST_REG_12',
            'company_id': self.belgian_company.id,
            'year': '2026',
            'quarter': '4',
            'declaration_method': 'batch',
            'environment': 'S',
        })
        with self.fake_time_object():
            dmfa.with_context(onss_skip_signature=True).generate_declaration_xml_report()

        dmfa_dict = xml_str_to_dict(dmfa.xml_file.content)
        self.assertEqual(dmfa_dict['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], self._get_dmfa_original_xsd())
        natural_person = dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']
        self.assertEqual(natural_person['NaturalPersonUserReference'], str(self.employee.id))
        self.assertEqual(natural_person['WorkerRecord']['Occupation']['OccupationUserReference'], str(self.contract.id))
        self._assertDMFAEqual(dmfa_dict)
        ded3000 = self._get_ded3000(self.employee, self.employee.slip_ids.filtered(lambda s: date_utils.get_quarter_number(s.date_from) == 4))
        self.assertIn(1422.44, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

    @freeze_time("2026-12-30 10:00:00")
    def test_10_declaration_regularization_code_14_reimbursement(self):
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                'date_from': date(2025, 1, 1),
                'date_to': date(2025, 12, 31),
                "prev_work_time_rate": 1,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 10,
                "prev_simple_holiday_pay_paid": 500,
                "prev_double_holiday_pay_paid": 0,
            }),
        ]
        self.contract.contract_date_start = date(2025, 1, 1)
        self.contract.wage = 4000

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave Nov",
            'calendar_id': self.calendar_38h.id,
            'company_id': self.belgian_company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime(2026, 11, 2, 6, 0, 0),
            'date_to': datetime(2026, 11, 6, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }, {
            'name': "Legal Leave Dec",
            'calendar_id': self.calendar_38h.id,
            'company_id': self.belgian_company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime(2026, 12, 7, 6, 0, 0),
            'date_to': datetime(2026, 12, 11, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        self.employee.write({'review_state': '1_reviewed'})

        for month in range(9, 13):
            payslip = self.env['hr.payslip'].create({
                'version_id': self.contract.id,
                'date_from': datetime(2026, month, 1),
                'date_to': datetime(2026, month, 30 if month in (9, 11) else 31),
                'employee_id': self.employee.id,
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
                'company_id': self.belgian_company.id,
            })
            payslip.compute_sheet()
            payslip.action_payslip_done()

        dmfa = self.env['l10n_be.dmfa'].with_user(self.payroll_manager).create({
            'name': 'TEST_REG_14',
            'company_id': self.belgian_company.id,
            'year': '2026',
            'quarter': '4',
            'declaration_method': 'batch',
            'environment': 'S',
        })
        with self.fake_time_object():
            dmfa.with_context(onss_skip_signature=True).generate_declaration_xml_report()

        dmfa_dict = xml_str_to_dict(dmfa.xml_file.content)
        self.assertEqual(dmfa_dict['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], self._get_dmfa_original_xsd())
        natural_person = dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']
        self.assertEqual(natural_person['NaturalPersonUserReference'], str(self.employee.id))
        self.assertEqual(natural_person['WorkerRecord']['Occupation']['OccupationUserReference'], str(self.contract.id))
        self._assertDMFAEqual(dmfa_dict)
        ded3000 = self._get_ded3000(self.employee, self.employee.slip_ids.filtered(lambda s: date_utils.get_quarter_number(s.date_from) == 4))
        self.assertIn(0, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

    @freeze_time("2026-01-01 10:00:00")
    def test_09_declaration_no_worked_days_lines(self):
        self.contract.wage = 2000
        self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'request_date_from': date(2025, 10, 1),
            'request_date_to': date(2025, 12, 31),
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        })
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        },
        {
            'name': 'Payslip Oct 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 10, 1),
            'date_to': datetime(2025, 10, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Nov 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 11, 1),
            'date_to': datetime(2025, 11, 30),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Dec 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 12, 1),
            'date_to': datetime(2025, 12, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'PFA',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 12, 1),
            'date_to': datetime(2025, 12, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month').id,
            'company_id': self.belgian_company.id,
        }])
        payslips.compute_sheet()
        payslips.action_payslip_done()
        dmfa_dict = self._generate_dmfa_declaration(quarter='4')
        self.assertEqual(dmfa_dict['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], self._get_dmfa_original_xsd())
        self.assertEqual(dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['NaturalPersonUserReference'], str(self.employee.id))
        self.assertEqual(dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']['OccupationUserReference'], str(self.contract.id))
        self._assertDMFAEqual(dmfa_dict)

    @freeze_time("2026-06-01 10:00:00")
    def test_11_voluntary_overtime(self):
        # Fully compensate the annual sectoral bonus so it stays out of the ONSS
        # base: this test covers voluntary overtime, not the sectoral bonus.
        self.contract.l10n_be_sectorial_bonus_compensatory_amount = 1000
        self.env['hr.leave'].create([{
            'employee_id': self.employee.id,
            'request_date_from': date(2026, 6, 1),
            'request_date_to': date(2026, 6, 1),
            'request_hour_from': 19,
            'request_hour_to': 23,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_voluntary_overtime_net').id,
            'company_id': self.belgian_company.id,
        }, {
            'employee_id': self.employee.id,
            'request_date_from': date(2026, 6, 2),
            'request_date_to': date(2026, 6, 2),
            'request_hour_from': 19,
            'request_hour_to': 23,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_voluntary_overtime_150').id,
            'company_id': self.belgian_company.id,
        }, {
            'employee_id': self.employee.id,
            'request_date_from': date(2026, 6, 3),
            'request_date_to': date(2026, 6, 3),
            'request_hour_from': 19,
            'request_hour_to': 23,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_voluntary_overtime_200').id,
            'company_id': self.belgian_company.id,
        }])
        # leave.action_approve()
        payslip = self.env['hr.payslip'].create({
            'version_id': self.contract.id,
            'date_from': datetime(2026, 6, 1),
            'date_to': datetime(2026, 6, 30),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self._validate_payslip(payslip)
        dmfa_dict = self._generate_dmfa_declaration(year="2026", quarter="2")
        self.assertEqual(dmfa_dict['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], self._get_dmfa_original_xsd())
        self.assertEqual(dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['NaturalPersonUserReference'], str(self.employee.id))
        self.assertEqual(dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']['OccupationUserReference'], str(self.contract.id))
        self._assertDMFAEqual(dmfa_dict)
        ded3000 = self._get_ded3000(self.employee, payslip)
        self.assertIn(102.76, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

    @freeze_time("2025-04-10 10:00:00")
    def test_13_declaration_employee_partial_notice_period(self):
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        departure_notice = self.env['hr.employee.departure'].create({
            'employee_id': self.employee.id,
            'departure_reason_id': self.env.ref('hr.departure_fired').id,
            'dismissal_date': date(2025, 2, 10),
            'departure_date': date(2025, 2, 28),
            'l10n_be_notice_respect': 'partial',
            'departure_description': 'foo',
            'action_date': date(2025, 3, 1),
        })

        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])
        payslips[0]._set_input_value('COMMISSION', 2000)
        payslips.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()

        departure_notice._compute_payslip_history()
        departure_notice.action_register()
        departure_payslips = departure_notice._generate_termination_payslip()
        departure_payslips += departure_notice._generate_termination_holidays()

        struct_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        termination_fees_payslip = departure_payslips.filtered(lambda pay: pay.struct_id == struct_id)
        termination_fees_payslip.compute_sheet()

        (payslips + departure_payslips)._compute_issues()
        (payslips + departure_payslips).action_payslip_done()

        dmfa_dict = self._generate_dmfa_declaration()
        self._assertDMFAEqual(dmfa_dict, ignore_keys=DMFA_IGNORE_KEYS + ('NOSSRegistrationNbr', 'CompanyID'))

    @freeze_time("2025-04-10 10:00:00")
    def test_15_declaration_services_on_full_credit_time(self):
        # The March payslip is computed with a normal working schedule, then its version becomes a
        # full time credit: its worked days would be declared on an occupation without hours,
        # refused by the ONSS (anomaly 90018-094)
        self.contract.contract_date_end = date(2025, 2, 28)
        version_credit_time = self.employee.create_version({
            'date_version': date(2025, 3, 1),
            'contract_date_start': date(2025, 3, 1),
            'contract_date_end': False,
            'resource_calendar_id': self.calendar_38h.id,
            'reference_calendar_id': self.calendar_38h.id,
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Mar 2025',
            'version_id': version_credit_time.id,
            'date_from': date(2025, 3, 1),
            'date_to': date(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        self.employee.write({'review_state': '1_reviewed'})
        payslip.compute_sheet()
        payslip.action_payslip_done()
        version_credit_time.resource_calendar_id = self.calendar_0_hours_per_week_credit_time
        self.assertTrue(payslip.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id.count_as == 'working_time'))

        with self.assertRaisesRegex(UserError, "Services are declared on occupations without hours per week(.|\n)*%s, from 2025-03-01" % self.employee.name):
            self._generate_dmfa_declaration()

    @freeze_time("2025-04-10 10:00:00")
    def test_14_declaration_multi_version_payslip_full_credit_time(self):
        # A new contract starts on the 10th of March with a full time credit, and the work resumes
        # on the 17th with a new version of that contract. The March payslip covers the three
        # versions of the month: the work and remuneration of each period must be declared on the
        # occupation of its version, never on the time credit one (ONSS anomaly 90018-094).
        version_before = self.contract
        version_before.contract_date_end = date(2025, 3, 9)
        version_credit_time = self.employee.create_version({
            'date_version': date(2025, 3, 10),
            'contract_date_start': date(2025, 3, 10),
            'contract_date_end': False,
            'resource_calendar_id': self.calendar_0_hours_per_week_credit_time.id,
            'reference_calendar_id': self.calendar_38h.id,
        })
        version_after = self.employee.create_version({
            'date_version': date(2025, 3, 17),
            'resource_calendar_id': self.calendar_38h.id,
        })
        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip {month}/2025',
            'version_id': version.id,
            'date_from': date(2025, month, 1),
            'date_to': date(2025, month, 1) + relativedelta(day=31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        } for month, version in [(1, version_before), (2, version_before), (3, version_before)]])
        self.employee.write({'review_state': '1_reviewed'})
        for payslip in payslips:  # No batch compute and validate for ONSS regularization
            payslip.compute_sheet()
            payslip.action_payslip_done()
        march_payslip = payslips[2]
        # The versions of the same Dimona category and worker code are in the same payslip
        self.assertEqual(march_payslip.worked_days_line_ids.version_id, version_before + version_credit_time + version_after)

        dmfa = self._generate_dmfa_declaration(return_declaration=True)
        occupations = {
            int(occupation.findtext('OccupationUserReference')): occupation
            for occupation in etree.fromstring(dmfa.xml_file.content).iter('Occupation')
        }
        self.assertEqual(set(occupations), set((version_before + version_credit_time + version_after).ids))

        def services(version):
            return {s.findtext('ServiceCode'): int(s.findtext('ServiceNbrHours')) / 100 for s in occupations[version.id].iter('Service')}

        def remunerations(version):
            return {r.findtext('RemunCode'): int(r.findtext('RemunAmount')) / 100 for r in occupations[version.id].iter('Remun')}

        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')

        def work_hours(version):
            return sum(wd.number_of_hours for wd in payslips.worked_days_line_ids if wd.work_entry_type_id == attendance and wd.version_id == version)

        def remuneration_001(payslips):
            return sum(line.total for line in payslips.line_ids if line.salary_rule_id.l10n_be_remuneration_code == '1')

        # Nothing on the time credit, neither work nor remuneration
        self.assertEqual(occupations[version_credit_time.id].findtext('MeanWorkingHours'), '0000')
        self.assertFalse(services(version_credit_time))
        self.assertFalse(remunerations(version_credit_time))

        # The work and remuneration of each period on the occupation of its version, the remuneration of
        # the March payslip being split pro rata to the paid amount of the worked days of each version
        def march_paid_amount(version):
            return sum(wd.amount for wd in march_payslip.worked_days_line_ids if wd.is_paid and wd.version_id == version)

        march_share_after = march_paid_amount(version_after) / (march_paid_amount(version_before) + march_paid_amount(version_after))
        self.assertTrue(0 < march_share_after < 1)
        self.assertAlmostEqual(services(version_before)['001'], work_hours(version_before))
        self.assertAlmostEqual(services(version_after)['001'], work_hours(version_after))
        self.assertAlmostEqual(
            remunerations(version_after)['001'], remuneration_001(march_payslip) * march_share_after, places=2)
        self.assertAlmostEqual(
            remunerations(version_before)['001'] + remunerations(version_after)['001'], remuneration_001(payslips), places=2)

    @freeze_time("2025-04-10 10:00:00")
    def test_14_structural_reduction_of_a_split_payslip(self):
        # The worker goes 4/5 time on the 17th of March: the March payslip is split between the full-time occupation
        # and the 4/5 one. Each occupation line has the structural reduction of its own share of the payslip, not of
        # the whole payslip: together they make the reduction of the quarter, not a third more.
        calendar_4_5 = self.env['resource.calendar'].create({
            'name': "Test Calendar: 4/5 Wednesday Off (no time credit)",
            'company_id': self.belgian_company.id,
            'hours_per_day': 7.6,
            'full_time_required_hours': 38.0,
            'reference_calendar_id': self.calendar_38h.id,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for dayofweek in ('0', '1', '3', '4') for hour_from, hour_to in ((8.0, 12.0), (13.0, 16.6))],
        })
        version_before = self.contract
        version_before.wage = 2100
        version_after = self.employee.create_version({
            'date_version': date(2025, 3, 17),
            'resource_calendar_id': calendar_4_5.id,
            'wage': 2100 * 4 / 5,
        })
        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip {month}/2025',
            'version_id': version_before.id,
            'date_from': date(2025, month, 1),
            'date_to': date(2025, month, 1) + relativedelta(day=31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        } for month in (1, 2, 3)])
        self.employee.write({'review_state': '1_reviewed'})
        for payslip in payslips:
            payslip.compute_sheet()
            payslip.action_payslip_done()
        self.assertEqual(payslips[2].worked_days_line_ids.version_id, version_before + version_after)

        dmfa = self._generate_dmfa_declaration(return_declaration=True)
        reductions = {
            int(occupation.findtext('OccupationUserReference')): sum(
                int(deduction.findtext('DeductionAmount')) / 100 for deduction in occupation.iter('OccupationDeduction')
                if deduction.findtext('DeductionCode') == '3000')
            for occupation in etree.fromstring(dmfa.xml_file.content).iter('Occupation')
        }
        self.assertEqual(set(reductions), set((version_before + version_after).ids))
        self.assertTrue(all(reductions.values()))
        mu_global = L10n_BeDmfa._get_l10n_be_mu(version_before, payslips=payslips)
        quarter_reduction = L10n_BeDmfa._get_l10n_be_structural_deduction_3000(payslips, mu_global)
        whole_march_reduction = L10n_BeDmfa._get_l10n_be_structural_deduction_3000(payslips[2], mu_global)
        # the 4/5 line has the reduction of its part of March (11 of 21 days, at 4/5), not of the whole March payslip
        self.assertLess(reductions[version_after.id], whole_march_reduction * 0.6)
        # each line's mu is rounded to the hundredth
        self.assertAlmostEqual(sum(reductions.values()), quarter_reduction, delta=quarter_reduction * 0.02)

    @freeze_time("2025-04-10 10:00:00")
    def test_15_premium_pay_of_a_split_payslip(self):
        # The worker goes 4/5 time on the 17th of March and is paid a holiday premium on the 18th: the premium pay is
        # part of the pay of the 4/5 occupation line, not shared between both lines of the March payslip
        calendar_4_5 = self.calendar_38h.copy({'name': "4/5 Wednesday off"})
        calendar_4_5.attendance_ids.filtered(lambda a: a.dayofweek == '2').unlink()
        calendar_4_5.reference_calendar_id = self.calendar_38h
        premium_type = self.env['hr.work.entry.type'].create({
            'name': 'Premium Pay',
            'code': 'PREMIUM_PAY',
            'requires_allocation': False,
            'request_unit': 'hour',
            'unit_of_measure': 'hour',
            'dmfa_code': '1',
            'optional_category_ids': [Command.link(self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_HOLIDAY').id)],
        })
        version_before = self.contract
        version_after = self.employee.create_version({
            'date_version': date(2025, 3, 17),
            'resource_calendar_id': calendar_4_5.id,
            'wage': self.contract.wage * 4 / 5,
        })
        self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'work_entry_type_id': premium_type.id,
            'request_date_from': date(2025, 3, 18),
            'request_date_to': date(2025, 3, 18),
            'request_hour_from': 8,
            'request_hour_to': 12,
            'category_options_ids': [Command.link(self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_HOLIDAY').id)],
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip 3/2025',
            'version_id': version_before.id,
            'date_from': date(2025, 3, 1),
            'date_to': date(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        self.employee.write({'review_state': '1_reviewed'})
        payslip.compute_sheet()
        payslip.action_payslip_done()
        premium = payslip._get_line_values(['PREMHOL'])['PREMHOL'][payslip.id]['total']
        self.assertTrue(premium)
        self.assertEqual(payslip.worked_days_line_ids.filtered('category_options_ids').version_id, version_after)

        dmfa = self._generate_dmfa_declaration(return_declaration=True)
        remunerations = {
            int(occupation.findtext('OccupationUserReference')): sum(
                int(remun.findtext('RemunAmount')) / 100 for remun in occupation.iter('Remun')
                if remun.findtext('RemunCode') == '001')
            for occupation in etree.fromstring(dmfa.xml_file.content).iter('Occupation')
        }
        salary = payslip._get_line_values(['SALARY'])['SALARY'][payslip.id]['total']
        paid = {version: sum(payslip.worked_days_line_ids.filtered(
            lambda wd: wd.version_id == version and wd.is_paid).mapped('amount')) for version in version_before + version_after}
        # the premium whole on the 4/5 line, the rest of the gross salary pro rata to the pay of the worked days
        self.assertAlmostEqual(
            remunerations[version_after.id],
            (salary - premium) * paid[version_after] / sum(paid.values()) + premium, delta=0.02)
        self.assertAlmostEqual(sum(remunerations.values()), salary, delta=0.01)

    @freeze_time("2025-04-10 10:00:00")
    def test_15_horeca_overtime_of_a_split_payslip(self):
        # The worker goes 4/5 time on the 17th of March and works Horeca overtime without contributions after it: that
        # overtime isn't paid in the gross salary (declared under the remuneration code 013 on its line), the gross
        # salary is shared between both lines pro rata to the pay of their worked days only
        calendar_4_5 = self.calendar_38h.copy({'name': "4/5 Wednesday off"})
        calendar_4_5.attendance_ids.filtered(lambda a: a.dayofweek == '2').unlink()
        calendar_4_5.reference_calendar_id = self.calendar_38h
        version_before = self.contract
        version_after = self.employee.create_version({
            'date_version': date(2025, 3, 17),
            'resource_calendar_id': calendar_4_5.id,
            'wage': self.contract.wage * 4 / 5,
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip 3/2025',
            'version_id': version_before.id,
            'date_from': date(2025, 3, 1),
            'date_to': date(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        work_after = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '002.00' and wd.version_id == version_after)
        overtime = work_after.copy({
            'payslip_id': payslip.id, 'number_of_days': 0, 'number_of_hours': 10,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_overtime_no_onss').id,
        })
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        self.assertTrue(overtime.amount)

        dmfa = self._generate_dmfa_declaration(return_declaration=True)
        remunerations = {
            int(occupation.findtext('OccupationUserReference')): {
                remun.findtext('RemunCode'): int(remun.findtext('RemunAmount')) / 100 for remun in occupation.iter('Remun')}
            for occupation in etree.fromstring(dmfa.xml_file.content).iter('Occupation')
        }
        salary = payslip._get_line_values(['SALARY'])['SALARY'][payslip.id]['total']
        paid = {version: sum(payslip.worked_days_line_ids.filtered(
            lambda wd: wd.version_id == version and wd.is_paid and wd != overtime).mapped('amount'))
            for version in version_before + version_after}
        self.assertAlmostEqual(
            remunerations[version_before.id]['001'], salary * paid[version_before] / sum(paid.values()), delta=0.01)
        self.assertAlmostEqual(remunerations[version_before.id]['001'] + remunerations[version_after.id]['001'], salary, delta=0.01)
        self.assertEqual(remunerations[version_after.id]['013'], round(overtime.amount, 2))
        self.assertNotIn('013', remunerations[version_before.id])

    @freeze_time("2025-04-10 10:00:00")
    def test_16_bonus_of_the_monthly_payslip(self):
        # A bonus of the monthly payslip (here the advance on commissions of a sales representative paid below the
        # scale, remuneration code 2) is in its gross salary: declared under the code 2, not under the code 1 as well
        sales_rep = self.env['hr.employee'].create({
            'name': 'Sales Rep',
            'company_id': self.belgian_company.id,
            'niss': '85010100214',
            'address_id': self.partner_wallonia.id,
            'work_contact_id': self.work_contact.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'wage': 1500,
            'resource_calendar_id': self.calendar_38h.id,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_d').id,
            'l10n_be_is_sale_representative': True,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip 3/2025',
            'employee_id': sales_rep.id,
            'version_id': sales_rep.version_id.id,
            'date_from': date(2025, 3, 1),
            'date_to': date(2025, 3, 31),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        sales_rep.write({'review_state': '1_reviewed'})
        payslip.compute_sheet()
        payslip.action_payslip_done()
        values = payslip._get_line_values(['SALARY', 'COMMISSION_ADV'])
        salary, advance = values['SALARY'][payslip.id]['total'], values['COMMISSION_ADV'][payslip.id]['total']
        self.assertTrue(advance)

        dmfa = self._generate_dmfa_declaration(return_declaration=True)
        remunerations = {}
        for natural_person in etree.fromstring(dmfa.xml_file.content).iter('NaturalPerson'):
            if natural_person.findtext('INSS') == sales_rep.niss:
                for remun in natural_person.iter('Remun'):
                    remunerations[remun.findtext('RemunCode')] = int(remun.findtext('RemunAmount')) / 100
        self.assertAlmostEqual(remunerations['002'], advance, places=2)
        self.assertAlmostEqual(remunerations['001'], salary - advance, places=2)
        # the reference wage of the structural reduction counts it once too
        wage = self.env['l10n_be.dmfa']._get_l10n_be_payslips_wage_and_hours(payslip)[0]
        self.assertAlmostEqual(wage, salary, places=2)

    @freeze_time("2025-04-10 10:00:00")
    def test_90_dmfa_sftp_flow_invalid_acrf(self):
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025 %s',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Mar 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 3, 1),
            'date_to': datetime(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])
        payslips[0]._set_input_value('COMMISSION', 2000)
        payslips.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()

        # Generate DmfA record
        self.belgian_company.sudo().onss_certificate_id = self.env['certificate.certificate'].create({})
        dmfa = self._generate_dmfa_declaration(environment='T', return_declaration=True, skip_signature=False)
        self.assertTrue(dmfa.xml_file)
        self.assertTrue(dmfa.go_file)
        self.assertTrue(dmfa.signature_file)

        # 1. Generate DmfA SFTP declaration, invalid ACRF
        dmfa.create_onss_declaration()
        declaration = dmfa.onss_declaration_ids
        self.assertEqual(dmfa.onss_declaration_count, 1)
        self.assertEqual(declaration.onss_file_count, 3)

        # Post DmfA SFTP declaration to ONSS
        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.putfo = MagicMock()
            # This mock needs to simulate the context manager behavior, specifically the __enter__ and __exit__ methods
            mock_open_conn.return_value.__enter__.return_value = fake_sftp
            mock_open_conn.return_value.__exit__.return_value = None
            declaration.action_post()
            mock_open_conn.assert_called_once()
            fake_sftp.putfo.assert_called()

        self.assertEqual(declaration.state, 'posted')

        # Receive ACRF, signaling an invalid signature
        def mock_listdir_declaration_1(folder):
            if folder in ('OUT', 'OUTTEST-S'):
                return []
            elif folder == 'OUTTEST':
                return [
                    'FO.ACRF.999999.20250410.99999.T',
                    'FS.ACRF.999999.20250410.99999.T',
                    'GO.ACRF.999999.20250410.99999.T',
                ]

        def make_file_mock(return_bytes):
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = return_bytes
            return mock_file

        def file_side_effect_declaration_1(remote_path, mode='rb'):
            if remote_path.endswith('FO.ACRF.999999.20250410.99999.T'):
                xml_str = """<?xml version="1.0" encoding="UTF-8"?>
<ACRF xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="ACRF_20251.xsd">
    <Form>
        <Identification>ACRF001</Identification>
        <FormCreationDate>2025-04-10</FormCreationDate>
        <FormCreationHour>15:36:40.276</FormCreationHour>
        <AttestationStatus>0</AttestationStatus>
        <TypeForm>FA</TypeForm>
        <FileReference>
            <FileName>%(go_filename)s</FileName>
            <ReferenceOrigin>2</ReferenceOrigin>
            <ReferenceNbr>03804UDVFMW3Z</ReferenceNbr>
        </FileReference>
        <ReceptionResult>
            <ResultCode>0</ResultCode>
            <ErrorID>ACRF-125</ErrorID>
        </ReceptionResult>
    </Form>
</ACRF>""" % {'go_filename': dmfa.go_filename}
                return make_file_mock(xml_str.encode('utf-8'))
            if remote_path.endswith('FS.ACRF.999999.20250410.99999.T'):
                return make_file_mock(b"dummy\r\nsignature\r\n")
            if remote_path.endswith('GO.ACRF.999999.20250410.99999.T'):
                return make_file_mock(b"")
            raise FileNotFoundError(f"No mock for file: {remote_path}")

        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.listdir.side_effect = mock_listdir_declaration_1
            fake_sftp.file.side_effect = file_side_effect_declaration_1

            mock_open_conn.return_value.__enter__.return_value = fake_sftp

            declaration._fetch_files()

            assert fake_sftp.file.call_count == 3
            fake_sftp.file.assert_any_call('OUTTEST/FO.ACRF.999999.20250410.99999.T', mode='rb')
            fake_sftp.file.assert_any_call('OUTTEST/FS.ACRF.999999.20250410.99999.T', mode='rb')
            fake_sftp.file.assert_any_call('OUTTEST/GO.ACRF.999999.20250410.99999.T', mode='rb')

        self.assertEqual(declaration.state, 'error')
        self.assertEqual(declaration.error_message, 'ACRF-125\nInvalid signature')
        self.assertEqual(declaration.onss_file_count, 6)

    @freeze_time("2025-04-10 10:00:00")
    def test_91_dmfa_sftp_flow_invalid_noti(self):
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025 %s',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Mar 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 3, 1),
            'date_to': datetime(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])
        payslips[0]._set_input_value('COMMISSION', 2000)
        payslips.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()

        # Generate DmfA record
        self.belgian_company.sudo().onss_certificate_id = self.env['certificate.certificate'].create({})
        dmfa = self._generate_dmfa_declaration(environment='T', return_declaration=True, skip_signature=False)
        self.assertTrue(dmfa.xml_file)
        self.assertTrue(dmfa.go_file)
        self.assertTrue(dmfa.signature_file)

        # Generate DmfA SFTP declaration, valid ACRF
        dmfa.create_onss_declaration()
        declaration = dmfa.onss_declaration_ids
        self.assertEqual(dmfa.onss_declaration_count, 1)
        self.assertEqual(declaration.onss_file_count, 3)

        # Post DmfA SFTP declaration to ONSS
        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.putfo = MagicMock()
            # This mock needs to simulate the context manager behavior, specifically the __enter__ and __exit__ methods
            mock_open_conn.return_value.__enter__.return_value = fake_sftp
            mock_open_conn.return_value.__exit__.return_value = None
            declaration.action_post()
            mock_open_conn.assert_called_once()
            fake_sftp.putfo.assert_called()

        self.assertEqual(declaration.state, 'posted')

        # Receive ACRF, ok
        def mock_listdir_declaration_2(folder):
            if folder == 'OUTTEST':
                return [
                    'FO.ACRF.999999.20250410.99998.T',
                    'FS.ACRF.999999.20250410.99998.T',
                    'GO.ACRF.999999.20250410.99998.T',
                ]
            return []

        def make_file_mock(return_bytes):
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = return_bytes
            return mock_file

        def file_side_effect_declaration_2(remote_path, mode='rb'):
            if remote_path.endswith('FO.ACRF.999999.20250410.99998.T'):
                xml_str = """<?xml version="1.0" encoding="UTF-8"?>
<ACRF xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="ACRF_20251.xsd">
    <Form>
        <Identification>ACRF001</Identification>
        <FormCreationDate>2025-04-10</FormCreationDate>
        <FormCreationHour>12:05:55.075</FormCreationHour>
        <AttestationStatus>0</AttestationStatus>
        <TypeForm>FA</TypeForm>
        <FileReference>
            <FileName>%(go_filename)s</FileName>
            <ReferenceOrigin>2</ReferenceOrigin>
            <ReferenceNbr>03804UE9XCMQZ</ReferenceNbr>
        </FileReference>
        <ReceptionResult>
            <ResultCode>1</ResultCode>
        </ReceptionResult>
    </Form>
</ACRF>""" % {'go_filename': dmfa.go_filename}
                return make_file_mock(xml_str.encode('utf-8'))
            if remote_path.endswith('FS.ACRF.999999.20250410.99998.T'):
                return make_file_mock(b"dummy\r\nsignature\r\n")
            if remote_path.endswith('GO.ACRF.999999.20250410.99998.T'):
                return make_file_mock(b"")
            raise FileNotFoundError(f"No mock for file: {remote_path}")

        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.listdir.side_effect = mock_listdir_declaration_2
            fake_sftp.file.side_effect = file_side_effect_declaration_2

            mock_open_conn.return_value.__enter__.return_value = fake_sftp

            declaration._fetch_files()

            assert fake_sftp.file.call_count == 3
            fake_sftp.file.assert_any_call('OUTTEST/FO.ACRF.999999.20250410.99998.T', mode='rb')
            fake_sftp.file.assert_any_call('OUTTEST/FS.ACRF.999999.20250410.99998.T', mode='rb')
            fake_sftp.file.assert_any_call('OUTTEST/GO.ACRF.999999.20250410.99998.T', mode='rb')

        self.assertEqual(declaration.state, 'received')
        self.assertFalse(declaration.error_message)
        self.assertEqual(declaration.onss_file_count, 6)

        # Receive Notification, signaling an invalid declaration (blocking anomaly)
        def mock_listdir_notification_1(folder):
            if folder in ('OUT', 'OUTTEST-S'):
                return []
            elif folder == 'OUTTEST':
                return [
                    'FO.NOTI.999999.20250410.99998.T',
                    'FS.NOTI.999999.20250410.99998.T',
                    'GO.NOTI.999999.20250410.99998.T',
                ]

        def file_side_effect_notification_1(remote_path, mode='rb'):
            if remote_path.endswith('FO.NOTI.999999.20250410.99998.T'):
                xml_str = """<?xml version="1.0" encoding="UTF-8"?><NOTIFICATION xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="NOTIFICATION_20251.xsd">
  <Form>
    <Identification>NOTI001</Identification>
    <FormCreationDate>2025-04-10</FormCreationDate>
    <FormCreationHour>16:35:16.359</FormCreationHour>
    <AttestationStatus>0</AttestationStatus>
    <TypeForm>FA</TypeForm>
    <FileReference>
      <FileName>%(go_filename)s</FileName>
      <ReferenceOrigin>2</ReferenceOrigin>
      <ReferenceNbr>03804UAVJS3PZ</ReferenceNbr>
    </FileReference>
    <HandledOriginalForm>
      <Identification>DMFA</Identification>
      <FormCreationDate>2025-04-10</FormCreationDate>
      <FormCreationHour>14:34:30.000</FormCreationHour>
      <AttestationStatus>0</AttestationStatus>
      <TypeForm>SU</TypeForm>
    </HandledOriginalForm>
    <Reference>
      <ReferenceType>1</ReferenceType>
      <ReferenceOrigin>1</ReferenceOrigin>
      <ReferenceNbr>2025/1</ReferenceNbr>
    </Reference>
    <EmployerId>
      <NOSSRegistrationNbr>125482497</NOSSRegistrationNbr>
      <CompanyID>0123456749</CompanyID>
    </EmployerId>
    <ConcernedQuarter>
      <Quarter>20251</Quarter>
    </ConcernedQuarter>
    <HandledReference>
      <ReferenceType>1</ReferenceType>
      <ReferenceOrigin>2</ReferenceOrigin>
      <ReferenceNbr>0340822PQ9CMZ</ReferenceNbr>
    </HandledReference>
    <WorkerRecordIdentification>
      <Quarter>20251</Quarter>
      <NOSSRegistrationNbr>125482497</NOSSRegistrationNbr>
      <CompanyID>0123456749</CompanyID>
      <NaturalPersonSequenceNbr>1</NaturalPersonSequenceNbr>
      <INSS>91111111192</INSS>
      <EmployerClass>578</EmployerClass>
      <WorkerCode>495</WorkerCode>
    </WorkerRecordIdentification>
    <HandlingResult>
      <ResultCode>0</ResultCode>
      <AnomalyReport>
        <ErrorID>00011-155</ErrorID>
        <TagName>NOSSRegistrationNbr</TagName>
        <Value>125482497</Value>
        <AnomalyClass>B</AnomalyClass>
        <AnomalyLocation>
          <Location>1,1,7,2</Location>
        </AnomalyLocation>
      </AnomalyReport>
    </HandlingResult>
  </Form>
</NOTIFICATION>""" % {'go_filename': dmfa.go_filename}
                return make_file_mock(xml_str.encode('utf-8'))
            if remote_path.endswith('FS.NOTI.999999.20250410.99998.T'):
                return make_file_mock(b"dummy\r\nsignature\r\n")
            if remote_path.endswith('GO.NOTI.999999.20250410.99998.T'):
                return make_file_mock(b"")
            raise FileNotFoundError(f"No mock for file: {remote_path}")

        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.listdir.side_effect = mock_listdir_notification_1
            fake_sftp.file.side_effect = file_side_effect_notification_1

            mock_open_conn.return_value.__enter__.return_value = fake_sftp

            declaration._fetch_files()

            assert fake_sftp.file.call_count == 3
            fake_sftp.file.assert_any_call('OUTTEST/FO.NOTI.999999.20250410.99998.T', mode='rb')
            fake_sftp.file.assert_any_call('OUTTEST/FS.NOTI.999999.20250410.99998.T', mode='rb')
            fake_sftp.file.assert_any_call('OUTTEST/GO.NOTI.999999.20250410.99998.T', mode='rb')

        self.assertEqual(declaration.state, 'error')
        self.assertEqual(declaration.error_message, 'Declaration rejected - blocking anomalies\nAnomaly (1/1) - Code: 00011-155\nNo or no longer a mandate\n- Tag Name: NOSSRegistrationNbr\n- Value: 125482497\n- NISS: False\n- Anomaly Class: Blocking anomaly\n\n')
        self.assertEqual(declaration.onss_file_count, 9)

    @freeze_time("2025-04-10 10:00:00")
    def test_92_dmfa_sftp_flow_valid_noti(self):
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025 %s',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Mar 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 3, 1),
            'date_to': datetime(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])
        payslips[0]._set_input_value('COMMISSION', 2000)
        payslips.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()

        # Generate DmfA record
        self.belgian_company.sudo().onss_certificate_id = self.env['certificate.certificate'].create({})
        dmfa = self._generate_dmfa_declaration(environment='T', return_declaration=True, skip_signature=False)
        self.assertTrue(dmfa.xml_file)
        self.assertTrue(dmfa.go_file)
        self.assertTrue(dmfa.signature_file)

        # Generate DmfA SFTP declaration, valid ACRF, valid NOTI
        dmfa.create_onss_declaration()
        declaration = dmfa.onss_declaration_ids
        self.assertEqual(dmfa.onss_declaration_count, 1)
        self.assertEqual(declaration.onss_file_count, 3)

        # Post DmfA SFTP declaration to ONSS
        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.putfo = MagicMock()
            # This mock needs to simulate the context manager behavior, specifically the __enter__ and __exit__ methods
            mock_open_conn.return_value.__enter__.return_value = fake_sftp
            mock_open_conn.return_value.__exit__.return_value = None
            declaration.action_post()
            mock_open_conn.assert_called_once()
            fake_sftp.putfo.assert_called()

        self.assertEqual(declaration.state, 'posted')

        # Receive ACRF, ok
        def mock_listdir_declaration_3(folder):
            if folder == 'OUTTEST':
                return [
                    'FO.ACRF.999999.20250410.99997.T',
                    'FS.ACRF.999999.20250410.99997.T',
                    'GO.ACRF.999999.20250410.99997.T',
                ]
            return []

        def make_file_mock(return_bytes):
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = return_bytes
            return mock_file

        def file_side_effect_declaration_3(remote_path, mode='rb'):
            if remote_path.endswith('FO.ACRF.999999.20250410.99997.T'):
                xml_str = """<?xml version="1.0" encoding="UTF-8"?>
<ACRF xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="ACRF_20251.xsd">
    <Form>
        <Identification>ACRF001</Identification>
        <FormCreationDate>2025-04-10</FormCreationDate>
        <FormCreationHour>12:05:55.075</FormCreationHour>
        <AttestationStatus>0</AttestationStatus>
        <TypeForm>FA</TypeForm>
        <FileReference>
            <FileName>%(go_filename)s</FileName>
            <ReferenceOrigin>2</ReferenceOrigin>
            <ReferenceNbr>03804UE9XCMQZ</ReferenceNbr>
        </FileReference>
        <ReceptionResult>
            <ResultCode>1</ResultCode>
        </ReceptionResult>
    </Form>
</ACRF>""" % {'go_filename': dmfa.go_filename}
                return make_file_mock(xml_str.encode('utf-8'))
            if remote_path.endswith('FS.ACRF.999999.20250410.99997.T'):
                return make_file_mock(b"dummy\r\nsignature\r\n")
            if remote_path.endswith('GO.ACRF.999999.20250410.99997.T'):
                return make_file_mock(b"")
            raise FileNotFoundError(f"No mock for file: {remote_path}")

        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.listdir.side_effect = mock_listdir_declaration_3
            fake_sftp.file.side_effect = file_side_effect_declaration_3

            mock_open_conn.return_value.__enter__.return_value = fake_sftp

            declaration._fetch_files()

            assert fake_sftp.file.call_count == 3
            fake_sftp.file.assert_any_call('OUTTEST/FO.ACRF.999999.20250410.99997.T', mode='rb')
            fake_sftp.file.assert_any_call('OUTTEST/FS.ACRF.999999.20250410.99997.T', mode='rb')
            fake_sftp.file.assert_any_call('OUTTEST/GO.ACRF.999999.20250410.99997.T', mode='rb')

        self.assertEqual(declaration.state, 'received')
        self.assertFalse(declaration.error_message)
        self.assertEqual(declaration.onss_file_count, 6)

        # Receive Notification, signaling an invalid declaration (blocking anomaly)
        def mock_listdir_notification_2(folder):
            if folder in ('OUT', 'OUTTEST-S'):
                return []
            elif folder == 'OUTTEST':
                return [
                    'FO.NOTI.999999.20250410.99997.T',
                    'FS.NOTI.999999.20250410.99997.T',
                    'GO.NOTI.999999.20250410.99997.T',
                ]

        def file_side_effect_notification_2(remote_path, mode='rb'):
            dmfa_onss_file = declaration.onss_file_ids.filtered(lambda f: f.declaration_type == 'DMFA' and f.file_type == 'FI')
            if remote_path.endswith('FO.NOTI.999999.20250410.99997.T'):
                xml_str = """<?xml version="1.0" encoding="UTF-8"?><NOTIFICATION xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="NOTIFICATION_20251.xsd">
<Form>
    <Identification>NOTI001</Identification>
    <FormCreationDate>2025-04-10</FormCreationDate>
    <FormCreationHour>21:48:14.795</FormCreationHour>
    <AttestationStatus>0</AttestationStatus>
    <TypeForm>FA</TypeForm>
    <HandledOriginalForm>
      <Identification>DMFA</Identification>
      <FormCreationDate>%(form_creation_date)s</FormCreationDate>
      <FormCreationHour>%(form_creation_hour)s</FormCreationHour>
      <AttestationStatus>0</AttestationStatus>
      <TypeForm>SU</TypeForm>
    </HandledOriginalForm>
    <Reference>
      <ReferenceType>1</ReferenceType>
      <ReferenceOrigin>1</ReferenceOrigin>
      <ReferenceNbr>2025/1</ReferenceNbr>
    </Reference>
<EmployerId>
      <NOSSRegistrationNbr>125482497</NOSSRegistrationNbr>
      <CompanyID>0123456749</CompanyID>
    </EmployerId>
    <ConcernedQuarter>
      <Quarter>20251</Quarter>
    </ConcernedQuarter>
<HandledReference>
      <ReferenceType>1</ReferenceType>
      <ReferenceOrigin>2</ReferenceOrigin>
      <ReferenceNbr>034081YBAQWPZ</ReferenceNbr>
    </HandledReference>
    <DeclarationComplInformations>
      <DMFAWorkersNbr>1</DMFAWorkersNbr>
      <DIMONAWorkersNbr>1</DIMONAWorkersNbr>
    </DeclarationComplInformations>
    <HandlingResult>
      <ResultCode>1</ResultCode>
      <AnomalyReport>
        <ErrorID>90007-262</ErrorID>
        <AnomalyClass>NP</AnomalyClass>
        <AnomalyLabel>Déclaration employeur - Plus de travailleurs déclarés en DmfA qu'en DIMONA</AnomalyLabel>
        <Path>
          <Quarter>20251</Quarter>
          <NOSSRegistrationNbr>125482497</NOSSRegistrationNbr>
          <Trusteeship>0</Trusteeship>
          <CompanyID>0123456749</CompanyID>
        </Path>
      </AnomalyReport>
      <AnomalyReport>
        <ErrorID>90001-476</ErrorID>
        <AnomalyClass>NP</AnomalyClass>
        <AnomalyLabel>Cotisation due pour la ligne travailleur - Cotisation spéciale sur les indemnités de rupture non présente</AnomalyLabel>
        <Path>
          <Quarter>20251</Quarter>
          <NOSSRegistrationNbr>125482497</NOSSRegistrationNbr>
          <Trusteeship>0</Trusteeship>
          <CompanyID>0123456749</CompanyID>
          <NaturalPersonSequenceNbr>1</NaturalPersonSequenceNbr>
          <INSS>91111111192</INSS>
          <EmployerClass>010</EmployerClass>
          <WorkerCode>495</WorkerCode>
          <NaturalPersonUserReference>4482041</NaturalPersonUserReference>
        </Path>
      </AnomalyReport>
    </HandlingResult>
  </Form>
</NOTIFICATION>""" % {'form_creation_date': dmfa_onss_file.form_creation_date, 'form_creation_hour': dmfa_onss_file.form_creation_hour}
                return make_file_mock(xml_str.encode('utf-8'))
            if remote_path.endswith('FS.NOTI.999999.20250410.99997.T'):
                return make_file_mock(b"dummy\r\nsignature\r\n")
            if remote_path.endswith('GO.NOTI.999999.20250410.99997.T'):
                return make_file_mock(b"")
            raise FileNotFoundError(f"No mock for file: {remote_path}")

        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.listdir.side_effect = mock_listdir_notification_2
            fake_sftp.file.side_effect = file_side_effect_notification_2

            mock_open_conn.return_value.__enter__.return_value = fake_sftp

            declaration._fetch_files()

            assert fake_sftp.file.call_count == 3
            fake_sftp.file.assert_any_call('OUTTEST/FO.NOTI.999999.20250410.99997.T', mode='rb')
            fake_sftp.file.assert_any_call('OUTTEST/FS.NOTI.999999.20250410.99997.T', mode='rb')
            fake_sftp.file.assert_any_call('OUTTEST/GO.NOTI.999999.20250410.99997.T', mode='rb')

        self.assertEqual(declaration.state, 'notified')
        self.assertEqual(declaration.error_message, 'Anomaly (1/2) - Code: 90007-262\nMore workers declared in DmfA than in DIMONA\n- NISS: False\n- Anomaly Class: Non-percentage-based anomaly\n\n\nAnomaly (2/2) - Code: 90001-476\nSpecial contribution on severance pay not present\n- Employee: Laurie Poiret (NISS: 91111111192)\n- Anomaly Class: Non-percentage-based anomaly\n\n')
        self.assertEqual(declaration.onss_file_count, 9)

    @freeze_time("2025-04-10 10:00:00")
    def test_10_dmfa_groups_duplicate_niss_into_single_natural_person(self):

        def _sort_occupations(dmfa_dict):
            occupations = dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord'][
                'Occupation']
            occupations.sort(key=lambda o: int(o['OccupationUserReference']))

        niss = '91111111192'
        first_employee, second_employee = self.env['hr.employee'].create([
            {
                'name': 'Employee 1',
                'company_id': self.belgian_company.id,
                'country_id': self.env.ref('base.be').id,
                'niss': niss,
                'contract_date_start': datetime(2020, 1, 1),
                'contract_date_end': None,
                'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
                'work_contact_id': self.work_contact.id,
                'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
                'lang': 'fr_BE',
            },
            {
                'name': 'Employee 2',
                'company_id': self.belgian_company.id,
                'country_id': self.env.ref('base.be').id,
                'niss': niss,
                'contract_date_start': datetime(2020, 1, 1),
                'contract_date_end': None,
                'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
                'work_contact_id': self.work_contact.id,
                'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
                'lang': 'fr_BE',
            }
        ]).sorted('id')

        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025 %s',
            'version_id': first_employee.version_id.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': first_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Jan 2025',
            'version_id': second_employee.version_id.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': second_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id}])
        payslips.compute_sheet()
        first_employee.write({'review_state': '1_reviewed'})
        second_employee.write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()
        dmfa_dict = self._generate_dmfa_declaration()
        _sort_occupations(dmfa_dict)
        self.assertEqual(dmfa_dict['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], self._get_dmfa_original_xsd())
        natural_person = dmfa_dict["DmfAOriginal"]["Form"]["EmployerDeclaration"]["NaturalPerson"]
        occupations = natural_person["WorkerRecord"]["Occupation"]
        self.assertEqual(natural_person["NaturalPersonUserReference"], str(first_employee.id))
        self.assertEqual(occupations[0]["OccupationUserReference"], str(first_employee.version_id.id))
        self.assertEqual(occupations[1]["OccupationUserReference"], str(second_employee.version_id.id))
        self._assertDMFAEqual(dmfa_dict)
        ded3000 = self._get_ded3000(first_employee, payslips[0])
        self.assertIn(0, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")
        ded3000 = self._get_ded3000(second_employee, payslips[1])
        self.assertIn(0, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

    def test_93_dmfa_WorkingDaysSystems_4_days_week(self):
        self.belgian_company.resource_calendar_id = self.calendar_4_days_36_hours
        self.contract.reference_calendar_id = self.calendar_4_days_36_hours
        self.contract.resource_calendar_id = self.calendar_4_days_36_hours
        payslip = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
                       'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])
        payslip.compute_sheet()
        payslip.action_payslip_done()
        dmfa_dict = self._generate_dmfa_declaration()
        self.assertEqual(
            dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']['WorkingDaysSystem'],
            '400'
        )

    @freeze_time("2025-04-10 10:00:00")
    def test_11_remove_employee_from_dmfa(self):
        first_employee, second_employee = self.env['hr.employee'].create([
            {
                'name': 'Employee 1',
                'company_id': self.belgian_company.id,
                'country_id': self.env.ref('base.be').id,
                'niss': '91111111192',
                'contract_date_start': datetime(2020, 1, 1),
                'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
                'work_contact_id': self.work_contact.id,
                'wage': 3000,
                'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
                'lang': 'fr_BE',
            },
            {
                'name': 'Employee 2',
                'company_id': self.belgian_company.id,
                'country_id': self.env.ref('base.be').id,
                'niss': '99010112390',
                'contract_date_start': datetime(2020, 1, 1),
                'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
                'work_contact_id': self.work_contact.id,
                'wage': 4000,
                'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
                'lang': 'fr_BE',
            }
        ])

        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025 - First employee',
            'version_id': first_employee.version_id.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': first_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Jan 2025 - Second employee',
            'version_id': second_employee.version_id.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': second_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id}])
        payslips.compute_sheet()
        first_employee.write({'review_state': '1_reviewed'})
        second_employee.write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()

        dmfa = self.env['l10n_be.dmfa'].with_user(self.payroll_manager).create({
            'name': 'TESTDMFA',
            'company_id': self.belgian_company.id,
            'year': '2025',
            'quarter': '1',
            'declaration_method': 'batch',
            'declaration_type': 'original',
            'environment': 'S',
        })
        with self.fake_time_object():
            dmfa.with_context(onss_skip_signature=True).generate_declaration_xml_report()
        self.assertFalse(dmfa.error_message)
        self.assertEqual(dmfa.state, 'ready')
        dmfa_with_all_employees_dict = xml_str_to_dict(dmfa.xml_file.content)
        self.assertEqual(dmfa_with_all_employees_dict['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], self._get_dmfa_original_xsd())
        self.assertEqual(dmfa_with_all_employees_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson'][0]['NaturalPersonUserReference'], str(first_employee.id))
        self.assertEqual(dmfa_with_all_employees_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson'][0]['WorkerRecord']['Occupation']['OccupationUserReference'], str(first_employee.version_id.id))
        self.assertEqual(dmfa_with_all_employees_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson'][1]['NaturalPersonUserReference'], str(second_employee.id))
        self.assertEqual(dmfa_with_all_employees_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson'][1]['WorkerRecord']['Occupation']['OccupationUserReference'], str(second_employee.version_id.id))
        self._assertDMFAEqual(dmfa_with_all_employees_dict)
        ded3000 = self._get_ded3000(first_employee, payslips.filtered(lambda p: p.employee_id == first_employee))
        self.assertIn(145.91, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")
        ded3000 = self._get_ded3000(second_employee, payslips.filtered(lambda p: p.employee_id == second_employee))
        self.assertIn(0, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

        removed_payslip = payslips.filtered(lambda p: p.employee_id.name == 'Employee 2')
        dmfa.payslip_ids = [(3, removed_payslip.id)]
        removed_payslip.l10n_be_is_dmfa_reported = True
        with self.fake_time_object():
            dmfa.with_context(dmfa_skip_signature=True).generate_declaration_xml_report()
        self.assertFalse(dmfa.error_message)
        self.assertEqual(dmfa.state, 'ready')
        dmfa_with_filtered_employees_dict = xml_str_to_dict(dmfa.xml_file.content)
        self.assertEqual(dmfa_with_filtered_employees_dict['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], self._get_dmfa_original_xsd())
        self.assertEqual(dmfa_with_filtered_employees_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['NaturalPersonUserReference'], str(first_employee.id))
        self.assertEqual(dmfa_with_filtered_employees_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']['OccupationUserReference'], str(first_employee.version_id.id))
        self._assertDMFAEqual(dmfa_with_filtered_employees_dict)
        ded3000 = self._get_ded3000(first_employee, payslips.filtered(lambda p: p.employee_id == first_employee))
        self.assertIn(145.91, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

    @freeze_time("2025-04-10 10:00:00")
    def test_dmfa_deduction_onssrestructuring_when_amount_zero(self):
        """ONSSRESTRUCTURING should be included when at least one line has amount > 0"""
        restructuring_employee = self.env['hr.employee'].create({
            'name': 'Employee 1',
            'company_id': self.belgian_company.id,
            'country_id': self.env.ref('base.be').id,
            'niss': '91111111192',
            'contract_date_start': datetime(2026, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'work_contact_id': self.work_contact.id,
            'birthday': datetime(2001, 1, 1),
            'restructuring_reduction_date_start': False,
            'wage': 2100,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        })
        payslip = self.env['hr.payslip'].create({
            'version_id': restructuring_employee.version_id.id,
            'date_from': datetime(2026, 1, 1),
            'date_to': datetime(2026, 1, 31),
            'employee_id': restructuring_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        restructuring_employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()

        dmfa = self.env['l10n_be.dmfa'].with_user(self.payroll_manager).create({
            'name': 'TESTDMFA',
            'company_id': self.belgian_company.id,
            'year': '2026',
            'quarter': '1',
            'declaration_method': 'batch',
            'environment': 'S',
        })
        with self.fake_time_object():
            dmfa.with_context(onss_skip_signature=True).generate_declaration_xml_report()
        dmfa_xml_response = xml_str_to_dict(dmfa.xml_file.content)
        self.assertEqual(dmfa_xml_response['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], self._get_dmfa_original_xsd())
        self.assertEqual(dmfa_xml_response['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['NaturalPersonUserReference'], f'{restructuring_employee.id}')
        self.assertEqual(dmfa_xml_response['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']['OccupationUserReference'], f'{restructuring_employee.version_id.id}')
        self._assertDMFAEqual(dmfa_xml_response)
        ded3000 = self._get_ded3000(restructuring_employee, payslip)
        self.assertIn(497.38, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

    @freeze_time("2025-04-10 10:00:00")
    def test_dmfa_deduction_onssrestructuring_when_amount_positive(self):
        """ONSSRESTRUCTURING should be included when at least one line has amount > 0"""
        restructuring_employee = self.env['hr.employee'].create({
            'name': 'Employee 1',
            'company_id': self.belgian_company.id,
            'country_id': self.env.ref('base.be').id,
            'niss': '91111111192',
            'contract_date_start': datetime(2026, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'work_contact_id': self.work_contact.id,
            'birthday': datetime(2001, 1, 1),
            'restructuring_reduction_date_start': datetime(2026, 1, 1),
            'wage': 2100,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        })
        payslip = self.env['hr.payslip'].create({
            'version_id': restructuring_employee.version_id.id,
            'date_from': datetime(2026, 1, 1),
            'date_to': datetime(2026, 1, 31),
            'employee_id': restructuring_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        restructuring_employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()

        dmfa = self.env['l10n_be.dmfa'].with_user(self.payroll_manager).create({
            'name': 'TESTDMFA',
            'company_id': self.belgian_company.id,
            'year': '2026',
            'quarter': '1',
            'declaration_method': 'batch',
            'environment': 'S',
        })
        with self.fake_time_object():
            dmfa.with_context(onss_skip_signature=True).generate_declaration_xml_report()
        dmfa_xml_response = xml_str_to_dict(dmfa.xml_file.content)
        self.assertEqual(dmfa_xml_response['DmfAOriginal']['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], self._get_dmfa_original_xsd())
        self.assertEqual(dmfa_xml_response['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['NaturalPersonUserReference'], str(restructuring_employee.id))
        self.assertEqual(dmfa_xml_response['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']['OccupationUserReference'], str(restructuring_employee.version_id.id))
        self._assertDMFAEqual(dmfa_xml_response)
        ded3000 = self._get_ded3000(restructuring_employee, payslip)
        self.assertIn(497.38, ded3000.values(), "Computing structural deduction using payslips results in a different amount than via dmfa services")

    @freeze_time("2025-04-10 10:00:00")
    def test_12_eco_friendly_vehicle(self):
        def _listify(value):
            return value if isinstance(value, list) else [value]

        def _check_remuneration_amount(person_dict, code, amount):
            remunerations = _listify(person_dict['WorkerRecord']['Occupation']['Remun'])
            if amount == '-1':
                self.assertFalse(any(r['RemunCode'] == code for r in remunerations))
            else:
                self.assertTrue(any(r['RemunCode'] == code and r['RemunAmount'] == amount for r in remunerations))

        def _check_contribution_amount(person_dict, code, amount):
            contributions = _listify(person_dict['WorkerRecord']['WorkerContribution'])
            if amount == '-1':
                self.assertFalse(any(c['ContributionWorkerCode'] == code for c in contributions))
            else:
                self.assertIn({'ContributionAmount': amount, 'ContributionType': '0', 'ContributionWorkerCode': code}, contributions)

        car_1 = self.car
        car_1.write({'co2': 110.0})

        brand_2 = self.env['fleet.vehicle.model.brand'].sudo().create({'name': "Another Brand"})
        model_2 = self.env['fleet.vehicle.model'].sudo().create({'name': "Another Model", 'brand_id': brand_2.id})
        car_2 = self.env['fleet.vehicle'].sudo().create({
            'name': "Eco Car",
            'license_plate': "Eco Car 1",
            'company_id': self.belgian_company.id,
            'model_id': model_2.id,
            'contract_date_start': date(2020, 10, 8),
            'co2': 0.0,
            'car_value': 38000.0,
            'fuel_type': "electric",
            'acquisition_date': date(2020, 1, 1)
        })

        car_3 = car_2.copy({'license_plate': "Eco Car 2"})

        employee_data = [
            ('Employee 1', '91111111192', car_1, False),
            ('Employee 2', '99010112390', car_2, False),
            ('Employee 3', '85010100115', car_3, True),
            ('Employee 4', '92022900306', False, True),
        ]
        employees = self.env['hr.employee'].create([
            {
                'name': name,
                'company_id': self.belgian_company.id,
                'country_id': self.env.ref('base.be').id,
                'niss': niss,
                'contract_date_start': datetime(2020, 1, 1),
                'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
                'work_contact_id': self.work_contact.copy().id,
                'wage': 3000,
                'car_id': car.id if car else False,
                'transport_mode_car': bool(car),
                'l10n_be_mobility_budget': mobility_budget,
                'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
                'lang': 'fr_BE',
            }
            for name, niss, car, mobility_budget in employee_data
        ])

        emp_1 = employees.filtered(lambda e: e.name == 'Employee 1')
        emp_2 = employees.filtered(lambda e: e.name == 'Employee 2')
        emp_3 = employees.filtered(lambda e: e.name == 'Employee 3')

        car_1.write({'driver_employee_id': emp_1.id})
        car_2.write({'driver_employee_id': emp_2.id})
        car_3.write({'driver_employee_id': emp_3.id})

        existing_logs = self.env['fleet.vehicle.assignation.log'].search([
                    ('vehicle_id', '=', car_1.id),
                    ('date_end', '=', False),
                ])
        if existing_logs:
            existing_logs.write({'date_end': date(2024, 12, 31)})

        self.env['fleet.vehicle.assignation.log'].search([
            ('vehicle_id', 'in', (car_1 | car_2 | car_3).ids),
            ('date_end', '=', False),
        ]).write({'date_start': date(2025, 1, 1)})

        struct = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        payslips = self.env['hr.payslip'].create([
            {
                'name': f'Payslip Jan 2025 - {employee.name}',
                'version_id': employee.version_id.id,
                'date_from': datetime(2025, 1, 1),
                'date_to': datetime(2025, 1, 31),
                'employee_id': employee.id,
                'struct_id': struct.id,
                'company_id': self.belgian_company.id,
            }
            for employee in employees
        ])

        payslips.compute_sheet()
        employees.write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()

        slips = payslips.filtered(lambda p: p.employee_id.name == 'Employee 1')
        line_co2_fee = slips.line_ids.filtered(lambda l: l.code == 'CO2FEE')
        self.assertAlmostEqual(line_co2_fee.total, 51.83, places=2)
        self.assertFalse(slips.line_ids.filtered(lambda l: l.code == 'ONSSEMPLOYER_868'))

        slips = payslips.filtered(lambda p: p.employee_id.name == 'Employee 2')
        line_co2_fee = slips.line_ids.filtered(lambda l: l.code == 'CO2FEE')
        self.assertAlmostEqual(line_co2_fee.total, 33.22, places=2)
        self.assertFalse(slips.line_ids.filtered(lambda l: l.code == 'ONSSEMPLOYER_868'))

        slips = payslips.filtered(lambda p: p.employee_id.name == 'Employee 3')
        self.assertFalse(slips.line_ids.filtered(lambda l: l.code == 'CO2FEE'))
        line_868 = slips.line_ids.filtered(lambda l: l.code == 'ONSSEMPLOYER_868')
        self.assertAlmostEqual(line_868.total, 33.22, places=2)

        slips = payslips.filtered(lambda p: p.employee_id.name == 'Employee 4')
        self.assertFalse(slips.line_ids.filtered(lambda l: l.code == 'CO2FEE'))
        self.assertFalse(slips.line_ids.filtered(lambda l: l.code == 'ONSSEMPLOYER_868'))

        dmfa = self.env['l10n_be.dmfa'].with_user(self.payroll_manager).create({
            'name': 'TESTDMFA',
            'company_id': self.belgian_company.id,
            'year': '2025',
            'quarter': '1',
            'declaration_method': 'batch',
            'environment': 'S',
        })
        with self.fake_time_object():
            dmfa.with_context(onss_skip_signature=True).generate_declaration_xml_report()
        self.assertFalse(dmfa.error_message)
        self.assertEqual(dmfa.state, 'ready')
        dmfa_dict = xml_str_to_dict(dmfa.xml_file.content)

        # Company vehicle list:
        vehicles = _listify(dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['CompanyVehicle'])
        # Only an eco-friendly car of a mobility budget is an eco vehicle
        self.assertTrue(any(v['LicensePlate'] == 'Eco Car 1' and not v.get('EcoVehicle') for v in vehicles))
        self.assertTrue(any(v['LicensePlate'] == 'Eco Car 2' and v['EcoVehicle'] == '1' for v in vehicles))
        self.assertTrue(any(v['LicensePlate'] == 'TEST' for v in vehicles))
        self.assertFalse(any(v['LicensePlate'] == 'TEST' and v.get('EcoVehicle') == '1' for v in vehicles))

        # CO2 Fee:
        common_contributions = _listify(dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['ContributionUnrelatedToNP'])
        self.assertIn({'UnrelatedAmount': '00000032158', 'UnrelatedEmployerClass': '010', 'UnrelatedWorkerCode': '862'}, common_contributions)

        # Per employee: 1. Remuneration BIK car; 2. Contribution for eco-friendly car
        natural_persons = _listify(dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson'])
        for person in natural_persons:
            if person.get('INSS') == '91111111192':
                # employee with diesel car
                _check_remuneration_amount(person, '010', '00000020526')
                _check_contribution_amount(person, '868', '-1')

            elif person.get('INSS') == '99010112390':
                # employee with electric car
                _check_remuneration_amount(person, '010', '00000014014')
                _check_contribution_amount(person, '868', '-1')

            elif person.get('INSS') == '85010100115':
                # employee with electric car and mobility budget
                _check_remuneration_amount(person, '010', '00000014014')
                _check_contribution_amount(person, '868', '00000003322')

            else:
                # employee with mobility budget and no car
                _check_remuneration_amount(person, '010', '-1')
                _check_contribution_amount(person, '868', '-1')

    def test_branch_vehicles(self):
        """ The cars of the branches are declared by the company, as their pool cars contribution """
        branch = self.env['res.company'].create({'name': 'Branch', 'parent_id': self.belgian_company.id})
        branch_car = self.car.copy({'license_plate': 'BRANCH', 'company_id': branch.id, 'driver_id': False})
        self.env['fleet.vehicle.assignation.log'].sudo().create({
            'vehicle_id': branch_car.id,
            'driver_id': self.work_contact.id,
            'date_start': date(2025, 1, 1),
        })
        dmfa = self.env['l10n_be.dmfa'].create({
            'name': 'TESTDMFA',
            'company_id': self.belgian_company.id,
            'year': '2025',
            'quarter': '1',
        })
        self.assertIn(branch_car, dmfa.vehicle_ids)
        # No payslip covers the car: it is a pool car of the branch
        self.assertTrue(dmfa._get_vehicles_contribution())

    @freeze_time("2026-05-12 10:00:00")
    def test_post_declaration_from_branch(self):
        """ The declarations are sent to the ONSS with the access of the employer, from any of its branches """
        branch = self.env['res.company'].create({'name': 'Branch', 'parent_id': self.belgian_company.id})
        self.payroll_manager.company_ids |= branch
        self.belgian_company.onss_certificate_id = self.env['certificate.certificate'].create({})
        self.belgian_company.onss_technical_user_name = 'EMPLOYER_USER'
        dmfa = self._generate_dmfa_declaration(environment='R', declaration_type='consultation', return_declaration=True, skip_signature=False)
        dmfa.create_onss_declaration()
        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            mock_open_conn.return_value.__enter__.return_value = MagicMock()
            dmfa.onss_declaration_ids.with_company(branch).action_post()
        mock_open_conn.assert_called_once()
        self.assertEqual(mock_open_conn.call_args.args[1], 'EMPLOYER_USER')

    @freeze_time("2026-07-01 10:00:00")
    def test_car_change_of_branch_employee_after_dmfa(self):
        """ The DmfA declared by the root company holds the cars of the employees of its branches: changing the
        car declared on it asks for a correction """
        branch = self.env['res.company'].create({
            'name': 'Branch', 'parent_id': self.belgian_company.id, 'country_id': self.env.ref('base.be').id})
        self.env.user.company_ids |= branch
        self.env = self.env(context=dict(self.env.context, allowed_company_ids=(self.belgian_company | branch).ids))
        branch_employee = self.env['hr.employee'].create({
            'name': 'Branch Driver',
            'niss': '93051822361',
            'private_street': 'Rue de la Station 1',
            'private_city': 'Perwez',
            'private_zip': '1360',
            'private_country_id': self.env.ref('base.be').id,
            'resource_calendar_id': self.calendar_38h.id,
            'company_id': branch.id,
            'address_id': self.belgian_company.partner_id.id,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'contract_date_start': date(2018, 12, 31),
            'date_version': date(2018, 12, 31),
            'wage': 3000,
            'car_id': self.car.id,
            'transport_mode_car': True,
            'l10n_be_joint_committee_id': self.cp200.id,
            'lang': 'fr_BE',
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip April 2026',
            'employee_id': branch_employee.id,
            'version_id': branch_employee.version_id.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': branch.id,
        })
        payslip.compute_sheet()
        branch_employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        self.assertEqual(payslip.vehicle_id, self.car)
        dmfa = self.env['l10n_be.dmfa'].create({
            'name': 'TESTDMFA',
            'company_id': self.belgian_company.id,
            'year': '2026',
            'quarter': '2',
            'declaration_method': 'web',
        })
        dmfa.state = 'done'
        self.assertTrue(self.env['fleet.vehicle'].version_requires_prompt(branch_employee.version_id.id))

    def test_consultation_branch_employees(self):
        """ The consultation (DMRQ) asks for the employees of all the branches of the company """
        branch = self.env['res.company'].create({'name': 'Branch', 'parent_id': self.belgian_company.id})
        branch_employee = self.env['hr.employee'].create({
            'name': 'Branch Worker',
            'niss': '93051822361',
            'company_id': branch.id,
        })
        dmfa = self.env['l10n_be.dmfa'].create({
            'name': 'TESTDMFA',
            'company_id': self.belgian_company.id,
            'year': '2026',
            'quarter': '2',
            'declaration_type': 'consultation',
        })
        employees = {natural_person.employee for natural_person in dmfa._get_rendering_data()['natural_persons']}
        self.assertIn(self.employee, employees)
        self.assertIn(branch_employee, employees)

    @freeze_time("2026-07-01 10:00:00")
    def test_preview_branch(self):
        """ The preview shows the whole company or one of its branches, and only the employees the user can access """
        branch = self.env['res.company'].create({'name': 'Branch', 'parent_id': self.belgian_company.id})
        branch_employee = self.env['hr.employee'].create({
            'name': 'Branch Worker',
            'niss': '93051822361',
            'private_street': 'Rue de la Station 1',
            'private_city': 'Perwez',
            'private_zip': '1360',
            'private_country_id': self.env.ref('base.be').id,
            'resource_calendar_id': self.calendar_38h.id,
            'company_id': branch.id,
            # declared on the location unit of the company
            'address_id': self.belgian_company.partner_id.id,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'contract_date_start': date(2018, 12, 31),
            'date_version': date(2018, 12, 31),
            'wage': 3000,
            'l10n_be_joint_committee_id': self.cp200.id,
            'lang': 'fr_BE',
        })
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip April 2026',
            'employee_id': employee.id,
            'version_id': employee.version_id.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': employee.company_id.id,
        } for employee in self.employee | branch_employee])
        payslips.compute_sheet()
        (self.employee | branch_employee).write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()
        dmfa = self.env['l10n_be.dmfa'].create({
            'name': 'TESTDMFA',
            'company_id': self.belgian_company.id,
            'year': '2026',
            'quarter': '2',
            'declaration_method': 'web',
        })
        self.assertEqual(dmfa.payslip_ids, payslips)

        def preview_employees(dmfa, company=None):
            data = dmfa._get_rendering_data(preview=True, preview_company=company or self.env['res.company'])
            return {natural_person.employee for natural_person in data['natural_persons']}

        self.assertEqual(preview_employees(dmfa), {self.employee, branch_employee})
        self.assertEqual(preview_employees(dmfa, branch), {branch_employee})
        self.assertEqual(preview_employees(dmfa, self.belgian_company), {self.employee})
        self.assertEqual(
            [company['id'] for company in dmfa.get_preview_companies()],
            [False, self.belgian_company.id, branch.id])

        # A payroll manager without access to the branch doesn't see its employees, even in the preview of the
        # whole company
        other_branch = self.env['res.company'].create({'name': 'Other Branch', 'parent_id': self.belgian_company.id})
        companies = self.belgian_company | other_branch
        manager = mail_new_test_user(
            self.env, login='other_branch_manager', groups='hr_payroll.group_hr_payroll_manager',
            company_id=self.belgian_company.id, company_ids=[Command.set(companies.ids)])
        manager_dmfa = dmfa.with_user(manager).with_context(allowed_company_ids=companies.ids)
        self.assertEqual(
            [company['id'] for company in manager_dmfa.get_preview_companies()],
            [False, self.belgian_company.id, other_branch.id])
        html = str(manager_dmfa.get_preview_html())
        self.assertIn(self.employee.name, html)
        self.assertNotIn('Branch Worker', html)
        with self.assertRaises(UserError):
            manager_dmfa.get_preview_html(branch.id)
        self.assertEqual(
            manager_dmfa.action_print_preview(other_branch.id)['data'],
            {'dmfa_preview': True, 'preview_company_id': other_branch.id})

        # Nothing is kept of the preview, as the states of the natural persons the declaration creates
        self.assertFalse(self.env['l10n_be.dmfa.natural_person.state'].search([('quarter_start', '=', date(2026, 4, 1))]))
        self.assertFalse(dmfa.dmfa_pdf)

    @freeze_time("2025-04-10 10:00:00")
    def test_pool_cars_co2_contribution(self):
        def _listify(value):
            return value if isinstance(value, list) else [value]

        # Pool Car, No employee payslip assignment
        car_1 = self.env['fleet.vehicle'].sudo().create({
            'name': "Car 1",
            'license_plate': "CAR-001",
            'company_id': self.belgian_company.id,
            'model_id': self.model.id,
            'co2': 120.0,
            'fuel_type': "diesel",
            'acquisition_date': date(2024, 1, 1),
        })
        self.env['fleet.vehicle.assignation.log'].sudo().create({
            'vehicle_id': car_1.id,
            'driver_id': self.work_contact.id,
            'date_start': date(2025, 1, 1),
        })

        # Employee Car, Assigned Jan-Feb and returned as a pool car in March
        car_2 = self.env['fleet.vehicle'].sudo().create({
            'name': "Car 2",
            'license_plate': "CAR-002",
            'company_id': self.belgian_company.id,
            'model_id': self.model.id,
            'co2': 100.0,
            'fuel_type': "gasoline",
            'acquisition_date': date(2024, 1, 1),
        })
        self.env['fleet.vehicle.assignation.log'].sudo().create({
            'vehicle_id': car_2.id,
            'driver_id': self.work_contact.id,
            'date_start': date(2025, 1, 1),
        })

        # Pool Car, Acquired at Feb
        car_3 = self.env['fleet.vehicle'].sudo().create({
            'name': "Late Pool Car",
            'license_plate': "CAR-003",
            'company_id': self.belgian_company.id,
            'model_id': self.model.id,
            'co2': 110.0,
            'fuel_type': "diesel",
            'acquisition_date': date(2025, 2, 1),
        })
        self.env['fleet.vehicle.assignation.log'].sudo().create({
            'vehicle_id': car_3.id,
            'driver_id': self.work_contact.id,
            'date_start': date(2025, 2, 1),
        })

        # Employee assigned transition_car for Jan & Feb payslips
        self.employee.car_id = car_2.id

        struct = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        payslip_jan = self.env['hr.payslip'].create({
            'name': 'Payslip Jan 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 1, 1),
            'date_to': datetime(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': struct.id,
            'company_id': self.belgian_company.id,
            'vehicle_id': car_2.id,
        })

        payslip_feb = self.env['hr.payslip'].create({
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 2, 1),
            'date_to': datetime(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': struct.id,
            'company_id': self.belgian_company.id,
            'vehicle_id': car_2.id,
        })

        payslip_mar = self.env['hr.payslip'].create({
            'name': 'Payslip Mar 2025',
            'version_id': self.contract.id,
            'date_from': datetime(2025, 3, 1),
            'date_to': datetime(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': struct.id,
            'company_id': self.belgian_company.id,
            'vehicle_id': False,
        })

        payslips = payslip_jan + payslip_feb + payslip_mar
        payslips.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()

        dmfa = self.env['l10n_be.dmfa'].with_user(self.payroll_manager).create({
            'name': 'TEST_POOL_CARS',
            'company_id': self.belgian_company.id,
            'year': '2025',
            'quarter': '1',
            'declaration_method': 'batch',
            'environment': 'S',
        })
        with self.fake_time_object():
            dmfa.with_context(onss_skip_signature=True).generate_declaration_xml_report()

        self.assertFalse(dmfa.error_message)
        self.assertEqual(dmfa.state, 'ready')

        dmfa_dict = xml_str_to_dict(dmfa.xml_file.content)

        vehicles = _listify(dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['CompanyVehicle'])
        plates = [v['LicensePlate'] for v in vehicles]

        self.assertEqual(len(vehicles), 4)
        self.assertIn('TEST', plates)
        self.assertIn('CAR-001', plates)
        self.assertIn('CAR-002', plates)
        self.assertIn('CAR-003', plates)

        # CO2 Fee Calculations Per Car (Greening Rules Applied - 2025):
        # -------------------------------------------------------------
        # TEST (Class Default Car):
        #   = 33.22
        # CAR-001 (Diesel, CO2=120):
        #   ((120 * 9 - 600) / 12) * (181.93 / 114.08) * 2.75 = 175.42
        #
        # CAR-002 (Gasoline, CO2=100):
        #   ((100 * 9 - 768) / 12) * (181.93 / 114.08) * 2.75 = 48.24
        #
        # CAR-003 (Diesel, CO2=110):
        #   ((110 * 9 - 600) / 12) * (181.93 / 114.08) * 2.75 = 142.53
        #

        # Total Vehicles Contribution Breakdown (Q1 2025):
        # ------------------------------------------------
        # 1. Payslips CO2 Fees:
        #    - CAR-002 on Employee Payslips (Jan & Feb): 48.24 * 2 = 96.48

        # 2. Pool Cars Monthly CO2 Fees (Jan, Feb, Mar):
        #    - January:
        #      * TEST:    33.22
        #      * CAR-001: 175.42
        #      Jan: 208.64
        #
        #    - February:
        #      * TEST:    33.22
        #      * CAR-001: 175.42
        #      * CAR-003: 142.53
        #      Feb: 351.17
        #
        #    - March:
        #      * TEST:    33.22
        #      * CAR-001: 175.42
        #      * CAR-002: 48.24
        #      * CAR-003: 142.53
        #      Mar: 399.41
        #
        # Total Vehicles Contribution: 96.48 "paid_payslips" + (208.64 + 351.17 + 399.41) "pool" = 1055.71

        self.assertEqual(dmfa._get_vehicles_contribution(), 1055.71)

    @freeze_time("2026-05-12 10:00:00")
    def test_100_dmfa_consultation_request_flow_invalid_noti(self):
        # Generate DmfA record
        self.belgian_company.onss_certificate_id = self.env['certificate.certificate'].create({})
        dmfa = self._generate_dmfa_declaration(environment='R', declaration_type='consultation', return_declaration=True, skip_signature=False)
        self.assertTrue(dmfa.xml_file)
        self.assertTrue(dmfa.xml_filename.startswith('FI.DMRQ.123456.20260512.'))
        self.assertTrue(dmfa.go_file)
        self.assertTrue(dmfa.go_filename.startswith('GO.DMRQ.123456.20260512.'))
        self.assertTrue(dmfa.signature_file)
        self.assertTrue(dmfa.signature_filename.startswith('FS.DMRQ.123456.20260512.'))
        dmfa_dict = xml_str_to_dict(dmfa.xml_file.content)
        self.assertEqual(dmfa_dict['DmfAConsultationRequest']['Form']['EmployerDeclarationId']['NaturalPerson']['NaturalPersonUserReference'], str(self.employee.id))
        self._assertDMFAEqual(dmfa_dict)

        # Generate DmfA SFTP declaration, valid ACRF, invalid NOTI
        dmfa.create_onss_declaration()
        declaration = dmfa.onss_declaration_ids
        self.assertEqual(dmfa.onss_declaration_count, 1)
        self.assertEqual(declaration.onss_file_count, 3)

        # Post DmfA SFTP declaration to ONSS
        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.putfo = MagicMock()
            # This mock needs to simulate the context manager behavior, specifically the __enter__ and __exit__ methods
            mock_open_conn.return_value.__enter__.return_value = fake_sftp
            mock_open_conn.return_value.__exit__.return_value = None
            declaration.action_post()
            mock_open_conn.assert_called_once()
            fake_sftp.putfo.assert_called()

        self.assertEqual(declaration.state, 'posted')

        # Receive ACRF, ok
        def mock_listdir_declaration_3(folder):
            if folder == 'OUT':
                return [
                    'FO.ACRF.999999.20260512.00043.R',
                    'FS.ACRF.999999.20260512.00043.R',
                    'GO.ACRF.999999.20260512.00043.R',
                ]
            return []

        def make_file_mock(return_bytes):
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = return_bytes
            return mock_file

        def file_side_effect_declaration_4(remote_path, mode='rb'):
            if remote_path.endswith('FO.ACRF.999999.20260512.00043.R'):
                xml_str = """<?xml version="1.0" encoding="UTF-8"?>
<ACRF xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="ACRF_20261.xsd">
    <Form>
        <Identification>ACRF001</Identification>
        <FormCreationDate>2026-05-12</FormCreationDate>
        <FormCreationHour>12:05:55.075</FormCreationHour>
        <AttestationStatus>0</AttestationStatus>
        <TypeForm>FA</TypeForm>
        <FileReference>
            <FileName>%(go_filename)s</FileName>
            <ReferenceOrigin>2</ReferenceOrigin>
            <ReferenceNbr>038055048FXXZ</ReferenceNbr>
        </FileReference>
        <ReceptionResult>
            <ResultCode>1</ResultCode>
        </ReceptionResult>
    </Form>
</ACRF>""" % {'go_filename': dmfa.go_filename}
                return make_file_mock(xml_str.encode('utf-8'))
            if remote_path.endswith('FS.ACRF.999999.20260512.00043.R'):
                return make_file_mock(b"dummy\r\nsignature\r\n")
            if remote_path.endswith('GO.ACRF.999999.20260512.00043.R'):
                return make_file_mock(b"")
            raise FileNotFoundError(f"No mock for file: {remote_path}")

        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.listdir.side_effect = mock_listdir_declaration_3
            fake_sftp.file.side_effect = file_side_effect_declaration_4

            mock_open_conn.return_value.__enter__.return_value = fake_sftp

            declaration._fetch_files()

            assert fake_sftp.file.call_count == 3
            fake_sftp.file.assert_any_call('OUT/FO.ACRF.999999.20260512.00043.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/FS.ACRF.999999.20260512.00043.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/GO.ACRF.999999.20260512.00043.R', mode='rb')

        self.assertEqual(declaration.state, 'received')
        self.assertFalse(declaration.error_message)
        self.assertEqual(declaration.onss_file_count, 6)

        # Receive Notification, signaling an invalid declaration (blocking anomaly)
        def mock_listdir_notification_2(folder):
            if folder in ('OUTTEST', 'OUTTEST-S'):
                return []
            elif folder == 'OUT':
                return [
                    'FO.NOTI.999999.20260512.00008.R',
                    'FS.NOTI.999999.20260512.00008.R',
                    'GO.NOTI.999999.20260512.00008.R',
                ]

        def file_side_effect_notification_2(remote_path, mode='rb'):
            dmfa_onss_file = declaration.onss_file_ids.filtered(lambda f: f.declaration_type == 'DMRQ' and f.file_type == 'FI')
            if remote_path.endswith('FO.NOTI.999999.20260512.00008.R'):
                xml_str = """<?xml version="1.0" encoding="UTF-8"?><NOTIFICATION xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="NOTIFICATION_20261.xsd">
<Form>
    <Identification>NOTI001</Identification>
    <FormCreationDate>2026-05-12</FormCreationDate>
    <FormCreationHour>10:03:05.124</FormCreationHour>
    <AttestationStatus>0</AttestationStatus>
    <TypeForm>FA</TypeForm>
    <HandledOriginalForm>
        <Identification>DMFAREQ</Identification>
          <FormCreationDate>%(form_creation_date)s</FormCreationDate>
          <FormCreationHour>%(form_creation_hour)s</FormCreationHour>
        <AttestationStatus>0</AttestationStatus>
        <TypeForm>RE</TypeForm>
    </HandledOriginalForm>
    <EmployerId>
        <NOSSRegistrationNbr>123456789</NOSSRegistrationNbr>
        <CompanyID>0123456789</CompanyID>
        </EmployerId>
        <ConcernedQuarter>
            <Quarter>20262</Quarter>
        </ConcernedQuarter>
        <HandledReference>
            <ReferenceType>1</ReferenceType>
            <ReferenceOrigin>2</ReferenceOrigin>
            <ReferenceNbr>034090QVTP68Z</ReferenceNbr>
        </HandledReference>
        <HandlingResult>
            <ResultCode>0</ResultCode>
            <Diagnosis>3</Diagnosis>
            <AnomalyReport>
                <ErrorID>00013-008</ErrorID>
                <AnomalyClass>B</AnomalyClass>
                <AnomalyLabel>ANNÉE - TRIMESTRE - Pas dans le domaine de définition</AnomalyLabel>
                <Path>
                    <Quarter>20262</Quarter>
                    <NOSSRegistrationNbr>123456789</NOSSRegistrationNbr>
                    <Trusteeship>0</Trusteeship>
                    <CompanyID>0123456789</CompanyID>
                </Path>
            </AnomalyReport>
        </HandlingResult></Form>
</NOTIFICATION>""" % {'form_creation_date': dmfa_onss_file.form_creation_date, 'form_creation_hour': dmfa_onss_file.form_creation_hour}
                return make_file_mock(xml_str.encode('utf-8'))
            if remote_path.endswith('FS.NOTI.999999.20260512.00008.R'):
                return make_file_mock(b"dummy\r\nsignature\r\n")
            if remote_path.endswith('GO.NOTI.999999.20260512.00008.R'):
                return make_file_mock(b"")
            raise FileNotFoundError(f"No mock for file: {remote_path}")

        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.listdir.side_effect = mock_listdir_notification_2
            fake_sftp.file.side_effect = file_side_effect_notification_2

            mock_open_conn.return_value.__enter__.return_value = fake_sftp

            declaration._fetch_files()

            assert fake_sftp.file.call_count == 3
            fake_sftp.file.assert_any_call('OUT/FO.NOTI.999999.20260512.00008.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/FS.NOTI.999999.20260512.00008.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/GO.NOTI.999999.20260512.00008.R', mode='rb')

        self.assertEqual(declaration.state, 'error')
        self.assertEqual(declaration.error_message, 'Declaration rejected - blocking anomalies\nAnomaly (1/1) - Code: 00013-008\nNot within scope\n- NISS: False\n- Anomaly Class: Blocking anomaly\n\n')
        self.assertEqual(declaration.onss_file_count, 9)

    @freeze_time("2026-05-12 10:00:00")
    def test_101_dmfa_consultation_request_flow_valid_dmdb(self):
        # Generate DmfA record
        self.belgian_company.onss_certificate_id = self.env['certificate.certificate'].create({})
        dmfa = self._generate_dmfa_declaration(environment='R', declaration_type='consultation', return_declaration=True, skip_signature=False)
        self.assertTrue(dmfa.xml_file)
        self.assertTrue(dmfa.xml_filename.startswith('FI.DMRQ.123456.20260512.'))
        self.assertTrue(dmfa.go_file)
        self.assertTrue(dmfa.go_filename.startswith('GO.DMRQ.123456.20260512.'))
        self.assertTrue(dmfa.signature_file)
        self.assertTrue(dmfa.signature_filename.startswith('FS.DMRQ.123456.20260512.'))
        dmfa_dict = xml_str_to_dict(dmfa.xml_file.content)
        self.assertEqual(dmfa_dict['DmfAConsultationRequest']['Form']['EmployerDeclarationId']['NaturalPerson']['NaturalPersonUserReference'], str(self.employee.id))
        self._assertDMFAEqual(dmfa_dict)

        # Generate DmfA SFTP declaration, valid ACRF, invalid NOTI
        dmfa.create_onss_declaration()
        declaration = dmfa.onss_declaration_ids
        self.assertEqual(dmfa.onss_declaration_count, 1)
        self.assertEqual(declaration.onss_file_count, 3)

        # Post DmfA SFTP declaration to ONSS
        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.putfo = MagicMock()
            # This mock needs to simulate the context manager behavior, specifically the __enter__ and __exit__ methods
            mock_open_conn.return_value.__enter__.return_value = fake_sftp
            mock_open_conn.return_value.__exit__.return_value = None
            declaration.action_post()
            mock_open_conn.assert_called_once()
            fake_sftp.putfo.assert_called()

        self.assertEqual(declaration.state, 'posted')

        # Receive ACRF, ok
        def mock_listdir_declaration_3(folder):
            if folder == 'OUT':
                return [
                    'FO.ACRF.999999.20260512.05142.R',
                    'FS.ACRF.999999.20260512.05142.R',
                    'GO.ACRF.999999.20260512.05142.R',
                ]
            return []

        def make_file_mock(return_bytes):
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = return_bytes
            return mock_file

        def file_side_effect_declaration_4(remote_path, mode='rb'):
            if remote_path.endswith('FO.ACRF.999999.20260512.05142.R'):
                xml_str = """<?xml version="1.0" encoding="UTF-8"?>
<ACRF xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="ACRF_20261.xsd">
    <Form>
        <Identification>ACRF001</Identification>
        <FormCreationDate>2026-05-12</FormCreationDate>
        <FormCreationHour>12:05:55.075</FormCreationHour>
        <AttestationStatus>0</AttestationStatus>
        <TypeForm>FA</TypeForm>
        <FileReference>
            <FileName>%(go_filename)s</FileName>
            <ReferenceOrigin>2</ReferenceOrigin>
            <ReferenceNbr>038055048FXXZ</ReferenceNbr>
        </FileReference>
        <ReceptionResult>
            <ResultCode>1</ResultCode>
        </ReceptionResult>
    </Form>
</ACRF>""" % {'go_filename': dmfa.go_filename}
                return make_file_mock(xml_str.encode('utf-8'))
            if remote_path.endswith('FS.ACRF.999999.20260512.05142.R'):
                return make_file_mock(b"dummy\r\nsignature\r\n")
            if remote_path.endswith('GO.ACRF.999999.20260512.05142.R'):
                return make_file_mock(b"")
            raise FileNotFoundError(f"No mock for file: {remote_path}")

        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.listdir.side_effect = mock_listdir_declaration_3
            fake_sftp.file.side_effect = file_side_effect_declaration_4

            mock_open_conn.return_value.__enter__.return_value = fake_sftp

            declaration._fetch_files()

            assert fake_sftp.file.call_count == 3
            fake_sftp.file.assert_any_call('OUT/FO.ACRF.999999.20260512.05142.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/FS.ACRF.999999.20260512.05142.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/GO.ACRF.999999.20260512.05142.R', mode='rb')

        self.assertEqual(declaration.state, 'received')
        self.assertFalse(declaration.error_message)
        self.assertEqual(declaration.onss_file_count, 6)

        # Receive Notification, signaling an invalid declaration (blocking anomaly)
        def mock_listdir_notification_2(folder):
            if folder in ('OUTTEST', 'OUTTEST-S'):
                return []
            elif folder == 'OUT':
                return [
                    'FO.DMDB.999999.20260512.00089.R',
                    'FS.DMDB.999999.20260512.00089.R',
                    'GO.DMDB.999999.20260512.00089.R',
                ]

        def file_side_effect_notification_2(remote_path, mode='rb'):
            dmfa_onss_file = declaration.onss_file_ids.filtered(lambda f: f.declaration_type == 'DMRQ' and f.file_type == 'FI')
            if remote_path.endswith('FO.DMDB.999999.20260512.00089.R'):
                xml_str = """<?xml version="1.0" encoding="UTF-8"?><DmfAConsultationAnswer xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="DmfAConsultationAnswer_20261.xsd">
<Form>
    <Identification>DMFADB</Identification>
    <FormCreationDate>2026-05-12</FormCreationDate>
    <FormCreationHour>11:30:05.900</FormCreationHour>
    <AttestationStatus>0</AttestationStatus>
    <TypeForm>FA</TypeForm>
    <HandledOriginalForm>
        <Identification>DMFAREQ</Identification>
        <FormCreationDate>%(form_creation_date)s</FormCreationDate>
        <FormCreationHour>%(form_creation_hour)s</FormCreationHour>
        <AttestationStatus>0</AttestationStatus>
        <TypeForm>RE</TypeForm>
    </HandledOriginalForm>
    <HandledReference>
        <ReferenceType>1</ReferenceType>
        <ReferenceOrigin>2</ReferenceOrigin>
        <ReferenceNbr>034090RQSZY1Z</ReferenceNbr>
    </HandledReference>
    <EmployerDeclarationConsult>
        <Quarter>20261</Quarter>
        <NOSSRegistrationNbr>123456789</NOSSRegistrationNbr>
        <Trusteeship>0</Trusteeship>
        <CompanyID>0123456789</CompanyID>
        <System5>0</System5>
        <EmployerDeclarationPID>09199674454</EmployerDeclarationPID>
        <EmployerDeclarationVersionNbr>09310425029</EmployerDeclarationVersionNbr>
        <ResultCodeResearch>0</ResultCodeResearch>
        <NaturalPersonConsult>
            <NaturalPersonSequenceNbr>0000001</NaturalPersonSequenceNbr>
            <INSS>91111111192</INSS>
            <WorkerName>POIRET</WorkerName>
            <WorkerFirstName>LAURIE</WorkerFirstName>
            <NaturalPersonUserReference>5936591             </NaturalPersonUserReference>
            <NaturalPersonPID>00010908994</NaturalPersonPID>
            <DeclNaturalPersonPID>09199693297</DeclNaturalPersonPID>
            <DeclNaturalPersonVersionNbr>09199693297</DeclNaturalPersonVersionNbr>
            <ResultCodeResearch>0</ResultCodeResearch>
            <WorkerRecordConsult>
                <EmployerClass>010</EmployerClass>
                <WorkerCode>495</WorkerCode>
                <NOSSQuarterStartingDate>2026-01-01</NOSSQuarterStartingDate>
                <NOSSQuarterEndingDate>2026-03-31</NOSSQuarterEndingDate>
                <Border>0</Border>
                <WorkerRecordPID>09199693298</WorkerRecordPID>
                <WorkerRecordVersionNbr>09199693298</WorkerRecordVersionNbr>
                <CodeSubjected>0</CodeSubjected>
                <Action>2</Action>
                <OccupationConsultation>
                    <OccupationSequenceNbr>01</OccupationSequenceNbr>
                    <OccupationStartingDate>2025-11-03</OccupationStartingDate>
                    <JointCommissionNbr>200</JointCommissionNbr>
                    <WorkingDaysSystem>500</WorkingDaysSystem>
                    <ContractType>0</ContractType>
                    <RefMeanWorkingHours>3800</RefMeanWorkingHours>
                    <MeanWorkingHours>3800</MeanWorkingHours>
                    <Retired>0</Retired>
                    <OccupationUserReference>3300666</OccupationUserReference>
                    <OccupationVersionNbr>09199693299</OccupationVersionNbr>
                    <Action>2</Action>
                    <LocalUnitID>2131430983</LocalUnitID>
                    <ServiceAction>
                        <ServiceSequenceNbr>01</ServiceSequenceNbr>
                        <ServiceCode>001</ServiceCode>
                        <ServiceNbrDays>06400</ServiceNbrDays>
                        <ServiceNbrHours>0048640</ServiceNbrHours>
                        <Action>2</Action>
                    </ServiceAction>
                    <RemunAction>
                        <RemunSequenceNbr>01</RemunSequenceNbr>
                        <RemunCode>001</RemunCode>
                        <RemunAmount>00000838002</RemunAmount>
                        <Action>2</Action>
                    </RemunAction>
                    <RemunAction>
                        <RemunSequenceNbr>02</RemunSequenceNbr>
                        <RemunCode>010</RemunCode>
                        <RemunAmount>00000045754</RemunAmount>
                        <Action>2</Action>
                    </RemunAction>
                    <OccupationDeductionAction>
                        <DeductionCode>3000</DeductionCode>
                        <DeductionAmount>00000055747</DeductionAmount>
                        <Action>2</Action>
                    </OccupationDeductionAction>
                </OccupationConsultation>
                <WorkerContributionAction>
                    <ContributionWorkerCode>255</ContributionWorkerCode>
                    <ContributionType>0</ContributionType>
                    <ContributionCalculationBasis>00000838002</ContributionCalculationBasis>
                    <ContributionAmount>00000000168</ContributionAmount>
                    <Action>2</Action>
                </WorkerContributionAction>
                <WorkerContributionAction>
                    <ContributionWorkerCode>256</ContributionWorkerCode>
                    <ContributionType>0</ContributionType>
                    <ContributionCalculationBasis>00000838002</ContributionCalculationBasis>
                    <ContributionAmount>00000000084</ContributionAmount>
                    <Action>2</Action>
                </WorkerContributionAction>
                <WorkerContributionAction>
                    <ContributionWorkerCode>495</ContributionWorkerCode>
                    <ContributionType>0</ContributionType>
                    <ContributionCalculationBasis>00000838002</ContributionCalculationBasis>
                    <ContributionAmount>00000319027</ContributionAmount>
                    <Action>2</Action>
                </WorkerContributionAction>
                <WorkerContributionAction>
                    <ContributionWorkerCode>809</ContributionWorkerCode>
                    <ContributionType>5</ContributionType>
                    <ContributionCalculationBasis>00000838002</ContributionCalculationBasis>
                    <ContributionAmount>00000003268</ContributionAmount>
                    <Action>2</Action>
                </WorkerContributionAction>
                <WorkerContributionAction>
                    <ContributionWorkerCode>810</ContributionWorkerCode>
                    <ContributionType>0</ContributionType>
                    <ContributionCalculationBasis>00000838002</ContributionCalculationBasis>
                    <ContributionAmount>00000000838</ContributionAmount>
                    <Action>2</Action>
                </WorkerContributionAction>
                <WorkerContributionAction>
                    <ContributionWorkerCode>831</ContributionWorkerCode>
                    <ContributionType>0</ContributionType>
                    <ContributionCalculationBasis>00000838002</ContributionCalculationBasis>
                    <ContributionAmount>00000001927</ContributionAmount>
                    <Action>2</Action>
                </WorkerContributionAction>
                <WorkerContributionAction>
                    <ContributionWorkerCode>855</ContributionWorkerCode>
                    <ContributionType>0</ContributionType>
                    <ContributionCalculationBasis>00000838002</ContributionCalculationBasis>
                    <ContributionAmount>00000014162</ContributionAmount>
                    <Action>2</Action>
                </WorkerContributionAction>
                <WorkerContributionAction>
                    <ContributionWorkerCode>856</ContributionWorkerCode>
                    <ContributionType>0</ContributionType>
                    <ContributionAmount>00000005088</ContributionAmount>
                    <Action>2</Action>
                </WorkerContributionAction>
                <WorkerContributionAction>
                    <ContributionWorkerCode>859</ContributionWorkerCode>
                    <ContributionType>0</ContributionType>
                    <ContributionCalculationBasis>00000838002</ContributionCalculationBasis>
                    <ContributionAmount>00000000838</ContributionAmount>
                    <Action>2</Action>
                </WorkerContributionAction>
                <WorkerDeductionAction>
                    <DeductionCode>0001</DeductionCode>
                    <DeductionAmount>00000040134</DeductionAmount>
                    <Action>2</Action>
               </WorkerDeductionAction>
               </WorkerRecordConsult>
        </NaturalPersonConsult>
        <NaturalPersonConsult>
            <NaturalPersonSequenceNbr>0000001</NaturalPersonSequenceNbr>
            <INSS>91111111192</INSS>
            <NaturalPersonPID>00010861969</NaturalPersonPID>
            <ResultCodeResearch>3</ResultCodeResearch>
        </NaturalPersonConsult>
    </EmployerDeclarationConsult>
</Form></DmfAConsultationAnswer>
""" % {'form_creation_date': dmfa_onss_file.form_creation_date, 'form_creation_hour': dmfa_onss_file.form_creation_hour}
                return make_file_mock(xml_str.encode('utf-8'))
            if remote_path.endswith('FS.DMDB.999999.20260512.00089.R'):
                return make_file_mock(b"dummy\r\nsignature\r\n")
            if remote_path.endswith('GO.DMDB.999999.20260512.00089.R'):
                return make_file_mock(b"")
            raise FileNotFoundError(f"No mock for file: {remote_path}")

        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.listdir.side_effect = mock_listdir_notification_2
            fake_sftp.file.side_effect = file_side_effect_notification_2
            mock_open_conn.return_value.__enter__.return_value = fake_sftp

            declaration._fetch_files()

            assert fake_sftp.file.call_count == 3
            fake_sftp.file.assert_any_call('OUT/FO.DMDB.999999.20260512.00089.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/FS.DMDB.999999.20260512.00089.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/GO.DMDB.999999.20260512.00089.R', mode='rb')

        self.assertEqual(declaration.state, 'notified')
        self.assertFalse(declaration.error_message)
        self.assertEqual(declaration.onss_file_count, 9)

        quarter_start, quarter_end = date_utils.get_quarter(date(2026, 1, 1))
        state = self.env['l10n_be.dmfa.natural_person.state'].sudo().search([
            ('niss', 'in', [self.employee.niss]),
            ('quarter_start', '=', quarter_start),
            ('quarter_end', '=', quarter_end),
        ])

        self.assertEqual(state.occupation_version_map, {'3300666': '09199693299'})
        self.assertEqual(state.natural_person_pid, '00010908994')
        self.assertEqual(state.decl_natural_person_pid, '09199693297')
        self.assertEqual(state.version_number, '09199693297')
        self.assertEqual(state.worker_record_version_number, '09199693298')

        expected_dict = {'deductions': [{'code': '0001',
                                         'deduction_calculation_basis': None,
                                         'deduction_amount': '00000040134',
                                         'deduction_right_starting_date': None,
                                         'applicant_inss': None,
                                         'certificate_origin': None}],
                         'contributions': [{'worker_code': '255',
                                            'contribution_type': '0',
                                            'amount': '00000000168',
                                            'calculation_basis': '00000838002',
                                            'first_hiring_date': None},
                                           {'worker_code': '256',
                                            'contribution_type': '0',
                                            'amount': '00000000084',
                                            'calculation_basis': '00000838002',
                                            'first_hiring_date': None},
                                           {'worker_code': '495',
                                            'contribution_type': '0',
                                            'amount': '00000319027',
                                            'calculation_basis': '00000838002',
                                            'first_hiring_date': None},
                                           {'worker_code': '809',
                                            'contribution_type': '5',
                                            'amount': '00000003268',
                                            'calculation_basis': '00000838002',
                                            'first_hiring_date': None},
                                           {'worker_code': '810',
                                            'contribution_type': '0',
                                            'amount': '00000000838',
                                            'calculation_basis': '00000838002',
                                            'first_hiring_date': None},
                                           {'worker_code': '831',
                                            'contribution_type': '0',
                                            'amount': '00000001927',
                                            'calculation_basis': '00000838002',
                                            'first_hiring_date': None},
                                           {'worker_code': '855',
                                            'contribution_type': '0',
                                            'amount': '00000014162',
                                            'calculation_basis': '00000838002',
                                            'first_hiring_date': None},
                                           {'worker_code': '856',
                                            'contribution_type': '0',
                                            'amount': '00000005088',
                                            'calculation_basis': None,
                                            'first_hiring_date': None},
                                           {'worker_code': '859',
                                            'contribution_type': '0',
                                            'amount': '00000000838',
                                            'calculation_basis': '00000838002',
                                            'first_hiring_date': None}],
                         'occupations': [{'ActivityCode': None,
                                          'TenthOrTwelfth': None,
                                          'apprenticeship': None,
                                          'commission': '200',
                                          'is_parttime': '0',
                                          'days_per_week': '500',
                                          'employment_promotion': None,
                                          'flying_staff_class': None,
                                          'days_justification': None,
                                          'position_code': None,
                                          'ref_mean_working_hours': '3800',
                                          'remun_method': None,
                                          'date_start': '2025-11-03',
                                          'date_end': None,
                                          'retired': '0',
                                          'mean_working_hours': '3800',
                                          'contract_id': '3300666',
                                          'version_number': '09199693299',
                                          'remunerations': [{'sequence': '01',
                                                             'code': '001',
                                                             'frequency': None,
                                                             'amount': '00000838002',
                                                             'percentage_paid': None},
                                                            {'sequence': '02',
                                                             'code': '010',
                                                             'frequency': None,
                                                             'amount': '00000045754',
                                                             'percentage_paid': None}],
                                          'occupation_deductions': [{'deduction_code': '3000',
                                                                     'deduction_calculation_basis': None,
                                                                     'deduction_amount': '00000055747',
                                                                     'deduction_right_starting_date': None,
                                                                     'management_cost_nbr_months': None,
                                                                     'replaced_inss': None,
                                                                     'applicant_inss': None,
                                                                     'certificate_origin': None}]}],
                         'student_contributions': [],
                         'update_action': 9}
        # The worker records of the consultation are keyed by worker code
        self.assertDictEqual(state.worker_record_data, {'495': expected_dict})

    @freeze_time("2026-05-12 10:00:00")
    def test_120_dmfa_update_flow_invalid_noti(self):
        # First, create an original declaration
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2026 %s',
            'version_id': self.contract.id,
            'date_from': datetime(2026, 1, 1),
            'date_to': datetime(2026, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2026',
            'version_id': self.contract.id,
            'date_from': datetime(2026, 2, 1),
            'date_to': datetime(2026, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Mar 2026',
            'version_id': self.contract.id,
            'date_from': datetime(2026, 3, 1),
            'date_to': datetime(2026, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])
        payslips.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()

        # Generate DmfA record
        self.belgian_company.onss_certificate_id = self.env['certificate.certificate'].create({})
        dmfa = self._generate_dmfa_declaration(environment='R', return_declaration=True, skip_signature=False)
        self.assertTrue(dmfa.xml_file)
        self.assertTrue(dmfa.go_file)
        self.assertTrue(dmfa.signature_file)

        # Generate DmfA SFTP declaration, valid ACRF, valid NOTI
        dmfa.create_onss_declaration()
        declaration = dmfa.onss_declaration_ids
        self.assertEqual(dmfa.onss_declaration_count, 1)
        self.assertEqual(declaration.onss_file_count, 3)

        # Post DmfA SFTP declaration to ONSS
        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.putfo = MagicMock()
            # This mock needs to simulate the context manager behavior, specifically the __enter__ and __exit__ methods
            mock_open_conn.return_value.__enter__.return_value = fake_sftp
            mock_open_conn.return_value.__exit__.return_value = None
            declaration.action_post()
            mock_open_conn.assert_called_once()
            fake_sftp.putfo.assert_called()

        self.assertEqual(declaration.state, 'posted')

        # Receive ACRF, ok
        def mock_listdir_declaration_3(folder):
            if folder == 'OUT':
                return [
                    'FO.ACRF.999999.20260512.99997.R',
                    'FS.ACRF.999999.20260512.99997.R',
                    'GO.ACRF.999999.20260512.99997.R',
                ]
            return []

        def make_file_mock(return_bytes):
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = return_bytes
            return mock_file

        def file_side_effect_declaration_3(remote_path, mode='rb'):
            if remote_path.endswith('FO.ACRF.999999.20260512.99997.R'):
                xml_str = """<?xml version="1.0" encoding="UTF-8"?>
<ACRF xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="ACRF_20251.xsd">
    <Form>
        <Identification>ACRF001</Identification>
        <FormCreationDate>2026-05-12</FormCreationDate>
        <FormCreationHour>12:05:55.075</FormCreationHour>
        <AttestationStatus>0</AttestationStatus>
        <TypeForm>FA</TypeForm>
        <FileReference>
            <FileName>%(go_filename)s</FileName>
            <ReferenceOrigin>2</ReferenceOrigin>
            <ReferenceNbr>03804UE9XCMQZ</ReferenceNbr>
        </FileReference>
        <ReceptionResult>
            <ResultCode>1</ResultCode>
        </ReceptionResult>
    </Form>
</ACRF>""" % {'go_filename': dmfa.go_filename}
                return make_file_mock(xml_str.encode('utf-8'))
            if remote_path.endswith('FS.ACRF.999999.20260512.99997.R'):
                return make_file_mock(b"dummy\r\nsignature\r\n")
            if remote_path.endswith('GO.ACRF.999999.20260512.99997.R'):
                return make_file_mock(b"")
            raise FileNotFoundError(f"No mock for file: {remote_path}")

        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.listdir.side_effect = mock_listdir_declaration_3
            fake_sftp.file.side_effect = file_side_effect_declaration_3

            mock_open_conn.return_value.__enter__.return_value = fake_sftp

            declaration._fetch_files()

            assert fake_sftp.file.call_count == 3
            fake_sftp.file.assert_any_call('OUT/FO.ACRF.999999.20260512.99997.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/FS.ACRF.999999.20260512.99997.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/GO.ACRF.999999.20260512.99997.R', mode='rb')

        self.assertEqual(declaration.state, 'received')
        self.assertFalse(declaration.error_message)
        self.assertEqual(declaration.onss_file_count, 6)

        # Receive Notification, signaling an invalid declaration (blocking anomaly)
        def mock_listdir_notification_2(folder):
            if folder in ('OUTTEST', 'OUTTEST-S'):
                return []
            elif folder == 'OUT':
                return [
                    'FO.NOTI.999999.20260512.99997.R',
                    'FS.NOTI.999999.20260512.99997.R',
                    'GO.NOTI.999999.20260512.99997.R',
                ]

        def file_side_effect_notification_2(remote_path, mode='rb'):
            dmfa_onss_file = declaration.onss_file_ids.filtered(lambda f: f.declaration_type == 'DMFA' and f.file_type == 'FI')
            if remote_path.endswith('FO.NOTI.999999.20260512.99997.R'):
                xml_str = """<?xml version="1.0" encoding="UTF-8"?><NOTIFICATION xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="NOTIFICATION_20251.xsd">
<Form>
    <Identification>NOTI001</Identification>
    <FormCreationDate>2026-05-12</FormCreationDate>
    <FormCreationHour>21:48:14.795</FormCreationHour>
    <AttestationStatus>0</AttestationStatus>
    <TypeForm>FA</TypeForm>
    <HandledOriginalForm>
      <Identification>DMFA</Identification>
      <FormCreationDate>%(form_creation_date)s</FormCreationDate>
      <FormCreationHour>%(form_creation_hour)s</FormCreationHour>
      <AttestationStatus>0</AttestationStatus>
      <TypeForm>SU</TypeForm>
    </HandledOriginalForm>
    <Reference>
      <ReferenceType>1</ReferenceType>
      <ReferenceOrigin>1</ReferenceOrigin>
      <ReferenceNbr>2025/1</ReferenceNbr>
    </Reference>
<EmployerId>
      <NOSSRegistrationNbr>123456789</NOSSRegistrationNbr>
      <CompanyID>0123456789</CompanyID>
    </EmployerId>
    <ConcernedQuarter>
      <Quarter>20251</Quarter>
    </ConcernedQuarter>
<HandledReference>
      <ReferenceType>1</ReferenceType>
      <ReferenceOrigin>2</ReferenceOrigin>
      <ReferenceNbr>034081YBAQWPZ</ReferenceNbr>
    </HandledReference>
    <DeclarationComplInformations>
      <DMFAWorkersNbr>1</DMFAWorkersNbr>
      <DIMONAWorkersNbr>1</DIMONAWorkersNbr>
    </DeclarationComplInformations>
    <HandlingResult>
      <ResultCode>1</ResultCode>
    </HandlingResult>
  </Form>
</NOTIFICATION>""" % {'form_creation_date': dmfa_onss_file.form_creation_date, 'form_creation_hour': dmfa_onss_file.form_creation_hour}
                return make_file_mock(xml_str.encode('utf-8'))
            if remote_path.endswith('FS.NOTI.999999.20260512.99997.R'):
                return make_file_mock(b"dummy\r\nsignature\r\n")
            if remote_path.endswith('GO.NOTI.999999.20260512.99997.R'):
                return make_file_mock(b"")
            raise FileNotFoundError(f"No mock for file: {remote_path}")

        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.listdir.side_effect = mock_listdir_notification_2
            fake_sftp.file.side_effect = file_side_effect_notification_2

            mock_open_conn.return_value.__enter__.return_value = fake_sftp

            declaration._fetch_files()

            assert fake_sftp.file.call_count == 3
            fake_sftp.file.assert_any_call('OUT/FO.NOTI.999999.20260512.99997.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/FS.NOTI.999999.20260512.99997.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/GO.NOTI.999999.20260512.99997.R', mode='rb')

        self.assertEqual(declaration.state, 'notified')
        self.assertFalse(declaration.error_message)
        self.assertEqual(declaration.onss_file_count, 9)

        # Second, receive DMPI file

        # Receive Notification, signaling an invalid declaration (blocking anomaly)
        def mock_listdir_notification_3(folder):
            if folder in ('OUTTEST', 'OUTTEST-S'):
                return []
            elif folder == 'OUT':
                return [
                    'FO.DMPI.999999.20260512.04481.R.1.1',
                ]

        def file_side_effect_notification_3(remote_path, mode='rb'):
            if remote_path.endswith('FO.DMPI.999999.20260512.04481.R.1.1'):
                xml_str = """<?xml version="1.0" encoding="UTF-8"?>
<DmfAPID xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:noNamespaceSchemaLocation="DmfAPID_20261.xsd">
   <Form>
      <Identification>DMFAPID</Identification>
      <FormCreationDate>2026-04-10</FormCreationDate>
      <FormCreationHour>20:00:19.000</FormCreationHour>
      <AttestationStatus>0</AttestationStatus>
      <TypeForm>SU</TypeForm>
      <Reference>
         <ReferenceType>3</ReferenceType>
         <ReferenceOrigin>2</ReferenceOrigin>
         <ReferenceNbr>03408XUJ0JUXZ</ReferenceNbr>
      </Reference>
      <Reference>
         <ReferenceType>3</ReferenceType>
         <ReferenceOrigin>1</ReferenceOrigin>
         <ReferenceNbr>%(original_reference)s</ReferenceNbr>
      </Reference>
      <Reference>
         <ReferenceType>1</ReferenceType>
         <ReferenceOrigin>2</ReferenceOrigin>
         <ReferenceNbr>03408XXN9L6DZ</ReferenceNbr>
      </Reference>
      <IDEmployerDeclaration>
         <Quarter>20251</Quarter>
         <NOSSRegistrationNbr>130387593</NOSSRegistrationNbr>
         <Trusteeship>0</Trusteeship>
         <CompanyID>477472701</CompanyID>
         <EmployerDeclarationPID>9199674454</EmployerDeclarationPID>
         <IDNaturalPerson>
            <INSS>91111111192</INSS>
            <NaturalPersonUserReference>3796105</NaturalPersonUserReference>
            <NaturalPersonPID>7786615</NaturalPersonPID>
            <DeclNaturalPersonPID>9199674455</DeclNaturalPersonPID>
            <DeclNaturalPersonVersionNbr>9199674455</DeclNaturalPersonVersionNbr>
            <IDWorkerRecord>
               <EmployerClass>010</EmployerClass>
               <WorkerCode>495</WorkerCode>
               <WorkerRecordVersionNbr>9199674456</WorkerRecordVersionNbr>
               <IDOccupation>
                  <OccupationSequenceNbr>1</OccupationSequenceNbr>
                  <OccupationVersionNbr>9199674457</OccupationVersionNbr>
                  <OccupationUserReference>5263452</OccupationUserReference>
               </IDOccupation>
            </IDWorkerRecord>
         </IDNaturalPerson>
        <IDNaturalPerson>
            <INSS>91111111291</INSS>
            <NaturalPersonUserReference>3796106</NaturalPersonUserReference>
            <NaturalPersonPID>7786616</NaturalPersonPID>
            <DeclNaturalPersonPID>9199674456</DeclNaturalPersonPID>
            <DeclNaturalPersonVersionNbr>9199674456</DeclNaturalPersonVersionNbr>
            <IDWorkerRecord>
               <EmployerClass>010</EmployerClass>
               <WorkerCode>495</WorkerCode>
               <WorkerRecordVersionNbr>9199674457</WorkerRecordVersionNbr>
               <IDOccupation>
                  <OccupationSequenceNbr>1</OccupationSequenceNbr>
                  <OccupationVersionNbr>9199674458</OccupationVersionNbr>
                  <OccupationUserReference>5263453</OccupationUserReference>
               </IDOccupation>
            </IDWorkerRecord>
         </IDNaturalPerson>
         <IDContUnrelatedToNP>
            <UnrelatedEmployerClass>010</UnrelatedEmployerClass>
            <UnrelatedWorkerCode>862</UnrelatedWorkerCode>
            <ContUnrelatedToNPVersionNbr>9199700637</ContUnrelatedToNPVersionNbr>
         </IDContUnrelatedToNP>
         <IDContUnrelatedToNP>
            <UnrelatedEmployerClass>010</UnrelatedEmployerClass>
            <UnrelatedWorkerCode>870</UnrelatedWorkerCode>
            <ContUnrelatedToNPVersionNbr>9199700638</ContUnrelatedToNPVersionNbr>
         </IDContUnrelatedToNP>
         <IDContUnrelatedToNP>
            <UnrelatedEmployerClass>010</UnrelatedEmployerClass>
            <UnrelatedWorkerCode>861</UnrelatedWorkerCode>
            <ContUnrelatedToNPVersionNbr>0000000000</ContUnrelatedToNPVersionNbr>
         </IDContUnrelatedToNP>
         <CompanyVehicleID>
            <LicensePlate>1-HAC-866</LicensePlate>
            <CompanyVehicleVersionNbr>9199700813</CompanyVehicleVersionNbr>
         </CompanyVehicleID>
      </IDEmployerDeclaration>
   </Form>
</DmfAPID>
""" % {'original_reference': declaration.batch_declaration_id.name}
                return make_file_mock(xml_str.encode('utf-8'))
            raise FileNotFoundError(f"No mock for file: {remote_path}")

        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.listdir.side_effect = mock_listdir_notification_3
            fake_sftp.file.side_effect = file_side_effect_notification_3
            mock_open_conn.return_value.__enter__.return_value = fake_sftp

            self.employee_2.active = True
            quarter_start, quarter_end = date_utils.get_quarter(date(2025, 1, 1))
            emp1_state = self.env['l10n_be.dmfa.natural_person.state'].sudo().create({
                'niss': self.employee.niss,
                'employee_id': self.employee.id,
                'quarter_start': quarter_start,
                'quarter_end': quarter_end,
            })
            declaration._fetch_files()
            emp2_state = self.env['l10n_be.dmfa.natural_person.state'].sudo().search([
                ('niss', 'in', [self.employee_2.niss]),
                ('quarter_start', '=', quarter_start),
                ('quarter_end', '=', quarter_end),
            ])

            self.assertEqual(dmfa.company_pid, '09199674454')

            self.assertEqual(emp1_state.natural_person_pid, '7786615')
            self.assertEqual(emp1_state.decl_natural_person_pid, '9199674455')
            self.assertEqual(emp1_state.version_number, '9199674455')
            self.assertEqual(emp1_state.worker_record_version_number, '9199674456')

            emp2_state = self.env['l10n_be.dmfa.natural_person.state'].sudo().search([
                ('niss', 'in', [self.employee_2.niss]),
                ('quarter_start', '=', quarter_start),
                ('quarter_end', '=', quarter_end),
            ])

            self.assertEqual(emp2_state.natural_person_pid, '7786616')
            self.assertEqual(emp2_state.decl_natural_person_pid, '9199674456')
            self.assertEqual(emp2_state.version_number, '9199674456')
            self.assertEqual(emp2_state.worker_record_version_number, '9199674457')

            assert fake_sftp.file.call_count == 1
            fake_sftp.file.assert_any_call('OUT/FO.DMPI.999999.20260512.04481.R.1.1', mode='rb')

        # Last, generate DMFA update record
        with freeze_time("2026-05-12 12:00:00"):
            # Generate DmfA record
            self.belgian_company.onss_certificate_id = self.env['certificate.certificate'].create({})
            dmfa = self._generate_dmfa_declaration(environment='R', declaration_type='modification', return_declaration=True, skip_signature=False, parent=declaration.batch_declaration_id)
            self.assertTrue(dmfa.xml_file)
            self.assertTrue(dmfa.xml_filename.startswith('FI.DMWA.123456.20260512.'))
            self.assertTrue(dmfa.go_file)
            self.assertTrue(dmfa.go_filename.startswith('GO.DMWA.123456.20260512.'))
            self.assertTrue(dmfa.signature_file)
            self.assertTrue(dmfa.signature_filename.startswith('FS.DMWA.123456.20260512.'))
            dmfa_dict = xml_str_to_dict(dmfa.xml_file.content)
            self._assertDMFAEqual(dmfa_dict)

            # Generate DmfA SFTP declaration, valid ACRF, invalid NOTI
            dmfa.create_onss_declaration()
            declaration = dmfa.onss_declaration_ids
            self.assertEqual(dmfa.onss_declaration_count, 1)
            self.assertEqual(declaration.onss_file_count, 3)

            # Post DmfA SFTP declaration to ONSS
            with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
                fake_sftp = MagicMock()
                fake_sftp.putfo = MagicMock()
                # This mock needs to simulate the context manager behavior, specifically the __enter__ and __exit__ methods
                mock_open_conn.return_value.__enter__.return_value = fake_sftp
                mock_open_conn.return_value.__exit__.return_value = None
                declaration.action_post()
                mock_open_conn.assert_called_once()
                fake_sftp.putfo.assert_called()

            self.assertEqual(declaration.state, 'posted')

        # Receive ACRF, ok
        def mock_listdir_declaration_4(folder):
            if folder == 'OUT':
                return [
                    'FO.ACRF.999999.20260512.00071.R',
                    'FS.ACRF.999999.20260512.00071.R',
                    'GO.ACRF.999999.20260512.00071.R',
                ]
            return []

        def file_side_effect_declaration_4(remote_path, mode='rb'):
            if remote_path.endswith('FO.ACRF.999999.20260512.00071.R'):
                xml_str = """<?xml version="1.0" encoding="UTF-8"?>
<ACRF xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="ACRF_20261.xsd">
    <Form>
        <Identification>ACRF001</Identification>
        <FormCreationDate>2026-05-12</FormCreationDate>
        <FormCreationHour>12:05:55.075</FormCreationHour>
        <AttestationStatus>0</AttestationStatus>
        <TypeForm>FA</TypeForm>
        <FileReference>
            <FileName>%(go_filename)s</FileName>
            <ReferenceOrigin>2</ReferenceOrigin>
            <ReferenceNbr>038055048FXXZ</ReferenceNbr>
        </FileReference>
        <ReceptionResult>
            <ResultCode>1</ResultCode>
        </ReceptionResult>
    </Form>
</ACRF>""" % {'go_filename': dmfa.go_filename}
                return make_file_mock(xml_str.encode('utf-8'))
            if remote_path.endswith('FS.ACRF.999999.20260512.00071.R'):
                return make_file_mock(b"dummy\r\nsignature\r\n")
            if remote_path.endswith('GO.ACRF.999999.20260512.00071.R'):
                return make_file_mock(b"")
            raise FileNotFoundError(f"No mock for file: {remote_path}")

        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.listdir.side_effect = mock_listdir_declaration_4
            fake_sftp.file.side_effect = file_side_effect_declaration_4

            mock_open_conn.return_value.__enter__.return_value = fake_sftp

            declaration._fetch_files()

            assert fake_sftp.file.call_count == 3
            fake_sftp.file.assert_any_call('OUT/FO.ACRF.999999.20260512.00071.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/FS.ACRF.999999.20260512.00071.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/GO.ACRF.999999.20260512.00071.R', mode='rb')

        self.assertEqual(declaration.state, 'received')
        self.assertFalse(declaration.error_message)
        self.assertEqual(declaration.onss_file_count, 6)

        # Receive Notification, signaling an invalid declaration (blocking anomaly)
        def mock_listdir_notification_4(folder):
            if folder in ('OUTTEST', 'OUTTEST-S'):
                return []
            elif folder == 'OUT':
                return [
                    'FO.NOTI.999999.20260512.00034.R',
                    'FS.NOTI.999999.20260512.00034.R',
                    'GO.NOTI.999999.20260512.00034.R',
                ]

        def file_side_effect_notification_4(remote_path, mode='rb'):
            dmfa_onss_file = declaration.onss_file_ids.filtered(lambda f: f.declaration_type == 'DMWA' and f.file_type == 'FI')
            if remote_path.endswith('FO.NOTI.999999.20260512.00034.R'):
                xml_str = """<?xml version="1.0" encoding="UTF-8"?><NOTIFICATION xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="NOTIFICATION_20261.xsd">
<Form>
    <Identification>NOTI001</Identification>
    <FormCreationDate>2026-05-12</FormCreationDate>
    <FormCreationHour>12:39:21.812</FormCreationHour>
    <AttestationStatus>0</AttestationStatus>
    <TypeForm>FA</TypeForm>
    <HandledOriginalForm>
        <Identification>DMFAUPD</Identification>
        <FormCreationDate>%(form_creation_date)s</FormCreationDate>
        <FormCreationHour>%(form_creation_hour)s</FormCreationHour>
        <AttestationStatus>1</AttestationStatus>
        <TypeForm>SU</TypeForm>
    </HandledOriginalForm>
    <Reference>
        <ReferenceType>1</ReferenceType>
        <ReferenceOrigin>1</ReferenceOrigin>
        <ReferenceNbr>%(original_reference)s</ReferenceNbr>
    </Reference>
    <EmployerId>
        <NOSSRegistrationNbr>130387593</NOSSRegistrationNbr>
        <CompanyID>477472701</CompanyID>
    </EmployerId>
    <ConcernedQuarter>
        <Quarter>20261</Quarter>
    </ConcernedQuarter>
    <HandledReference>
        <ReferenceType>1</ReferenceType>
        <ReferenceOrigin>2</ReferenceOrigin>
        <ReferenceNbr>034090RTM7L9Z</ReferenceNbr>
    </HandledReference>
    <HandlingResult>
        <ResultCode>0</ResultCode>
        <Diagnosis>3</Diagnosis>
        <AnomalyReport>
        <ErrorID>00534-182</ErrorID>
        <AnomalyClass>B</AnomalyClass>
        <AnomalyLabel>IDENTIFIANT PERMANENT DE LA DÉCLARATION EMPLOYEUR - Non trouvé en DB DmfA</AnomalyLabel>
        <Path>
            <Quarter>20261</Quarter>
            <NOSSRegistrationNbr>130387593</NOSSRegistrationNbr>
            <Trusteeship>0</Trusteeship>
            <CompanyID>477472701</CompanyID>
        </Path>
        </AnomalyReport>
    </HandlingResult>
</Form>
</NOTIFICATION>
""" % {'form_creation_date': dmfa_onss_file.form_creation_date, 'form_creation_hour': dmfa_onss_file.form_creation_hour, 'original_reference': declaration.batch_declaration_id.name}
                return make_file_mock(xml_str.encode('utf-8'))
            if remote_path.endswith('FS.NOTI.999999.20260512.00034.R'):
                return make_file_mock(b"dummy\r\nsignature\r\n")
            if remote_path.endswith('GO.NOTI.999999.20260512.00034.R'):
                return make_file_mock(b"")
            raise FileNotFoundError(f"No mock for file: {remote_path}")

        with patch('odoo.addons.l10n_be_hr_payroll.models.l10n_be_onss_declaration.open_sftp_connection') as mock_open_conn:
            fake_sftp = MagicMock()
            fake_sftp.listdir.side_effect = mock_listdir_notification_4
            fake_sftp.file.side_effect = file_side_effect_notification_4

            mock_open_conn.return_value.__enter__.return_value = fake_sftp

            declaration._fetch_files()

            assert fake_sftp.file.call_count == 3
            fake_sftp.file.assert_any_call('OUT/FO.NOTI.999999.20260512.00034.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/FS.NOTI.999999.20260512.00034.R', mode='rb')
            fake_sftp.file.assert_any_call('OUT/GO.NOTI.999999.20260512.00034.R', mode='rb')

        self.assertEqual(declaration.state, 'error')
        self.assertEqual(declaration.error_message, 'Declaration rejected - blocking anomalies\nAnomaly (1/1) - Code: 00534-182\nNot found in DmfA database\n- NISS: False\n- Anomaly Class: Blocking anomaly\n\n')
        self.assertEqual(declaration.onss_file_count, 9)

    @freeze_time("2026-04-01 10:00:00")
    def test_artist_reduction_dmfa(self):
        artist_worker_code = self.env['l10n.be.worker.code'].search([('dmfa_code', '=', '046')])
        artist_employee = self.env['hr.employee'].create({
            'name': 'Artist Employee',
            'company_id': self.belgian_company.id,
            'country_id': self.env.ref('base.be').id,
            'address_id': self.partner_wallonia.id,
            'l10n_be_worker_code_id': artist_worker_code.id,
            'niss': '85010100115',
            'contract_date_start': datetime(2026, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'work_contact_id': self.work_contact.id,
            'wage': 5000,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        })

        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Apr 2026',
            'version_id': artist_employee.version_id.id,
            'date_from': datetime(2026, 4, 1),
            'date_to': datetime(2026, 4, 30),
            'employee_id': artist_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip May 2026',
            'version_id': artist_employee.version_id.id,
            'date_from': datetime(2026, 5, 1),
            'date_to': datetime(2026, 5, 31),
            'employee_id': artist_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Jun 2026',
            'version_id': artist_employee.version_id.id,
            'date_from': datetime(2026, 6, 1),
            'date_to': datetime(2026, 6, 30),
            'employee_id': artist_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])

        payslips.compute_sheet()
        payslips.action_payslip_done()

        self._validate_payslip(payslips[0])

        dmfa = self._generate_dmfa_declaration(year=2026, quarter='2', return_declaration=True)
        dmfa_dict = xml_str_to_dict(dmfa.xml_file.content)

        # Testing 'l10n_be.dmfa.artist.reduction.line': Used solely for the
        # visibility of artist reductions on the payroll officer's DMFA tab.
        artist_line = dmfa.artist_reduction_line_ids.filtered(lambda l: l.employee_id == artist_employee)
        self.assertTrue(artist_line)
        self.assertEqual(artist_line.deduction_code, '4300')
        self.assertAlmostEqual(artist_line.amount, 517.0)

        # Testing the reduction on the dmfa itself
        # the only deduction of the occupation: no structural reduction block without an amount
        occupation_deductions = dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']['OccupationDeduction']
        self.assertEqual(occupation_deductions, {'DeductionCode': '4300', 'DeductionAmount': '00000051700'})

    @freeze_time("2026-04-01 10:00:00")
    def test_artist_reduction_dmfa_low_salary(self):
        artist_worker_code = self.env['l10n.be.worker.code'].search([('dmfa_code', '=', '046')])
        artist_employee = self.env['hr.employee'].create({
            'name': 'Artist Employee',
            'company_id': self.belgian_company.id,
            'country_id': self.env.ref('base.be').id,
            'address_id': self.partner_wallonia.id,
            'l10n_be_worker_code_id': artist_worker_code.id,
            'niss': '85010100115',
            'contract_date_start': datetime(2026, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'work_contact_id': self.work_contact.id,
            'wage': 2000,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        })

        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Apr 2026',
            'version_id': artist_employee.version_id.id,
            'date_from': datetime(2026, 4, 1),
            'date_to': datetime(2026, 4, 30),
            'employee_id': artist_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip May 2026',
            'version_id': artist_employee.version_id.id,
            'date_from': datetime(2026, 5, 1),
            'date_to': datetime(2026, 5, 31),
            'employee_id': artist_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Jun 2026',
            'version_id': artist_employee.version_id.id,
            'date_from': datetime(2026, 6, 1),
            'date_to': datetime(2026, 6, 30),
            'employee_id': artist_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }])

        payslips.compute_sheet()
        payslips.action_payslip_done()

        self._validate_payslip(payslips[0])

        dmfa = self._generate_dmfa_declaration(year=2026, quarter='2', return_declaration=True)
        dmfa_dict = xml_str_to_dict(dmfa.xml_file.content)

        # Testing the reduction on the dmfa itself
        occupation_deductions = dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']['OccupationDeduction']
        self.assertFalse(any(d['DeductionCode'] == '4300' for d in [occupation_deductions]))

    @freeze_time("2026-07-01 10:00:00")
    def test_manual_worker_contribution_rates(self):
        """
        Ensure that a manual worker is declared with the rates of the contribution type 1, on its declared basis.
        """
        worker = self.env['hr.employee'].create({
            'name': 'Manual Worker',
            'company_id': self.belgian_company.id,
            'country_id': self.env.ref('base.be').id,
            'address_id': self.partner_wallonia.id,
            'l10n_be_worker_code_id': self.env['l10n.be.worker.code'].search([('dmfa_code', '=', '015')]).id,
            'niss': '85010100115',
            'contract_date_start': datetime(2026, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'work_contact_id': self.work_contact.id,
            # 108% of the gross salary is 3240.2268, declared 3240.23: its contribution is 1233.56, not 1233.55
            'wage': 3000.21,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Apr 2026',
            'employee_id': worker.id,
            'version_id': worker.version_id.id,
            'date_from': datetime(2026, 4, 1),
            'date_to': datetime(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        payslip.action_payslip_done()

        worker_record = self._generate_dmfa_declaration(year=2026, quarter='2')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']
        contribution = next(c for c in worker_record['WorkerContribution'] if c['ContributionWorkerCode'] == '015')
        self.assertEqual(contribution['ContributionCalculationBasis'], '00000324023')
        # The declared basis is multiplied by the 38.07 percent total rate of the manual workers.
        expected_amount = round(int(contribution['ContributionCalculationBasis']) * 0.3807)
        self.assertEqual(contribution['ContributionType'], '1', "Manual workers should use the contribution type 1.")
        self.assertEqual(int(contribution['ContributionAmount']), expected_amount, "The contribution should use the worker rates.")
        deduction = worker_record['Occupation']['OccupationDeduction']
        self.assertGreater(int(deduction['DeductionAmount']), 0, "The structural deduction should not be zero.")
        # The quarterly annual holidays contribution of the manual workers, computed on the payslip
        self.assertTrue(payslip._get_line_values(['ONSSEMPLOYER_253'])['ONSSEMPLOYER_253'][payslip.id]['total'])
        holidays = next(c for c in worker_record['WorkerContribution'] if c['ContributionWorkerCode'] == '253')
        self.assertEqual(holidays['ContributionType'], '0')
        self.assertEqual(holidays['ContributionCalculationBasis'], contribution['ContributionCalculationBasis'])
        holidays_rate = payslip._get_onss_rates('253')['total_rate']
        self.assertEqual(int(holidays['ContributionAmount']), round(int(holidays['ContributionCalculationBasis']) * holidays_rate / 100))

    @freeze_time("2026-07-01 10:00:00")
    def test_young_manual_worker_subsistence_first_hiring_date(self):
        """
        The subsistence fund contribution (826) of a manual worker younger than 25 uses the reduced
        flat rate (contribution type 2), which requires the date of their first hiring.
        """
        worker = self.env['hr.employee'].create({
            'name': 'Young Manual Worker',
            'company_id': self.belgian_company.id,
            'country_id': self.env.ref('base.be').id,
            'address_id': self.partner_wallonia.id,
            'l10n_be_worker_code_id': self.env['l10n.be.worker.code'].search([('dmfa_code', '=', '015')]).id,
            'niss': '05010100113',
            'birthday': date(2005, 1, 1),
            'contract_date_start': datetime(2025, 9, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'work_contact_id': self.work_contact.id,
            'wage': 3000,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Apr 2026',
            'employee_id': worker.id,
            'version_id': worker.version_id.id,
            'date_from': datetime(2026, 4, 1),
            'date_to': datetime(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        # The subsistence fund contribution is owed by this employer class for the manual workers,
        # with a flat rate for the young ones (contribution type 2)
        employer_class = payslip.payroll_config_id.l10n_be_employer_category_id.dmfa_code
        code = f'l10n_be_onss_combinations_{employer_class}_015'
        combinations = payslip._rule_parameter(code)
        self.env['hr.rule.parameter.value'].sudo().create({
            'rule_parameter_id': self.env['hr.rule.parameter'].sudo().search([('code', '=', code)]).id,
            'parameter_value': str({**combinations, '826': ['0']}),
            'date_from': date(2026, 4, 1),
        })
        self.env['hr.rule.parameter'].sudo().create({
            'name': 'ONSS rates 826 type 2',
            'code': f'l10n_be_onss_rates_{employer_class}_826_2',
            'country_id': self.env.ref('base.be').id,
            'parameter_version_ids': [(0, 0, {
                'parameter_value': str({'personal_rate': 0, 'employer_rate': 10, 'salary_moderation_rate': 0, 'total_rate': 10}),
                'date_from': date(2026, 1, 1),
            })],
        })
        payslip.compute_sheet()
        payslip.action_payslip_done()

        worker_record = self._generate_dmfa_declaration(year=2026, quarter='2')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']
        contribution = next(c for c in worker_record['WorkerContribution'] if c['ContributionWorkerCode'] == '826')
        self.assertEqual(contribution['ContributionType'], '2')
        self.assertEqual(contribution['FirstHiringDate'], '2025-09-01')

    @freeze_time("2026-07-01 10:00:00")
    def test_flemish_training_leave_hours(self):
        """
        The hours of absence for a Flemish training leave are declared in the occupation
        informations (FlemishTrainingHolidayHoursNbr), in hundredths of hours.
        """
        flemish_training_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_flemish_training_time_off')
        flemish_training_type.requires_allocation = False
        self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'request_date_from': date(2026, 4, 14),
            'request_date_to': date(2026, 4, 15),
            'work_entry_type_id': flemish_training_type.id,
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Apr 2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        flemish_training_hours = sum(
            payslip.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == flemish_training_type).mapped('number_of_hours'))
        self.assertAlmostEqual(flemish_training_hours, 15.2)
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()

        occupation = self._generate_dmfa_declaration(year=2026, quarter='2')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']
        self.assertEqual(occupation['OccupationInformations']['FlemishTrainingHolidayHoursNbr'], '0001520')

    @freeze_time("2026-07-01 10:00:00")
    def test_illness_gross_remuneration(self):
        """
        The gross remuneration paid by the employer for an illness (guaranteed salary) is declared in the occupation
        informations (IllnessGrossRemunAmount, zone 01011) for the workers of the construction sector (CP 124, brick
        industry CP 114) only since 2024/2 (from 2020/2 to 2024/1, for all the sectors).
        """
        sick_leave_type = self.env.ref('hr_work_entry.be_work_entry_type_sick_leave')
        self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'request_date_from': date(2026, 4, 14),
            'request_date_to': date(2026, 4, 15),
            'work_entry_type_id': sick_leave_type.id,
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Apr 2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        illness_amount = sum(
            payslip.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == sick_leave_type).mapped('amount'))
        self.assertTrue(illness_amount)
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()

        # CP 200: not declared
        dmfa = self._generate_dmfa_declaration(year=2026, quarter='2', return_declaration=True)
        occupation = xml_str_to_dict(dmfa.xml_file.content)['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']
        self.assertFalse(occupation.get('OccupationInformations', {}).get('IllnessGrossRemunAmount'))
        dmfa.unlink()

        # An employee of the CP 124: not declared either
        self.contract.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_124')
        dmfa = self._generate_dmfa_declaration(year=2026, quarter='2', return_declaration=True)
        occupation = xml_str_to_dict(dmfa.xml_file.content)['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']
        self.assertFalse(occupation.get('OccupationInformations', {}).get('IllnessGrossRemunAmount'))
        dmfa.unlink()

        # A worker of the CP 124: declared
        # (the joint committee follows the type of employee: set again after it)
        self.contract.employee_type_id = self.env.ref('l10n_be_hr_payroll.l10n_be_contract_type_be_worker')
        self.contract.write({
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_124').id,
            'l10n_be_worker_code_id': self.env['l10n.be.worker.code'].search([('dmfa_code', '=', '015')]).id,
        })
        dmfa = self._generate_dmfa_declaration(year=2026, quarter='2', return_declaration=True)
        self.assertEqual(
            [node.text for node in etree.fromstring(dmfa.xml_file.content).iter('IllnessGrossRemunAmount')],
            [str(round(illness_amount * 100)).zfill(11)])

    @freeze_time("2025-04-10 10:00:00")
    def test_partial_parental_leave_services(self):
        """ The parental leave days are known from the occupation (reorganisation measure): they
        aren't declared as services, their DMFA code 998 isn't a service code """
        calendar_parental_leave = self.calendar_4_5_wednesday_off.copy({'name': "4/5 Parental Leave Wednesday"})
        calendar_parental_leave.attendance_ids.filtered(
            lambda a: a.work_entry_type_id == self.env.ref('hr_work_entry.l10n_be_work_entry_type_credit_time')
        ).work_entry_type_id = self.env.ref('hr_work_entry.l10n_be_work_entry_type_parental_time_off')
        version_parental_leave = self.employee.create_version({
            'date_version': date(2025, 3, 1),
            'resource_calendar_id': calendar_parental_leave.id,
            'reference_calendar_id': self.calendar_38h.id,
        })
        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip {month}/2025',
            'version_id': version.id,
            'date_from': date(2025, month, 1),
            'date_to': date(2025, month, 1) + relativedelta(day=31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        } for month, version in [(1, self.contract), (2, self.contract), (3, version_parental_leave)]])
        self.employee.write({'review_state': '1_reviewed'})
        for payslip in payslips:
            payslip.compute_sheet()
            payslip.action_payslip_done()
        self.assertIn('998', payslips[2].worked_days_line_ids.work_entry_type_id.mapped('dmfa_code'))

        dmfa = self._generate_dmfa_declaration(return_declaration=True)
        service_codes = [code.text for code in etree.fromstring(dmfa.xml_file.content).iter('ServiceCode')]
        self.assertTrue(service_codes)
        self.assertNotIn('998', service_codes)

    @freeze_time("2025-04-10 10:00:00")
    def test_overtime_to_recover_services(self):
        """ The overtime to recover (026.00) is paid for its premium alone: its hours are declared when they are
        recovered (046.00), not twice """
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip 1/2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        work = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '002.00')
        overtime = work.copy({
            'payslip_id': payslip.id, 'number_of_days': 0, 'number_of_hours': 10,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_overtime_recoverable').id,
        })
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        self.assertTrue(overtime.amount)

        dmfa = self._generate_dmfa_declaration(return_declaration=True)
        services = {
            s.findtext('ServiceCode'): int(s.findtext('ServiceNbrHours')) / 100
            for s in etree.fromstring(dmfa.xml_file.content).iter('Service')}
        normal_hours = sum((payslip.worked_days_line_ids - overtime).filtered(
            lambda wd: wd.work_entry_type_id.dmfa_code == '1').mapped('number_of_hours'))
        self.assertEqual(services['001'], round(normal_hours, 2))

    def test_horeca_net_overtime_remuneration(self):
        """ The Horeca overtime without contributions is declared with its hours (service code 080) and its pay
        (remuneration code 013), though no salary rule pays it; its hours without a day of their own get the
        technical minimum of 0.01 day """
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip 1/2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        work = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '002.00')
        overtime = work.copy({
            'payslip_id': payslip.id, 'number_of_days': 0, 'number_of_hours': 10,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_overtime_no_onss').id,
        })
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        self.assertTrue(overtime.amount)

        dmfa = self._generate_dmfa_declaration(return_declaration=True)
        declaration = etree.fromstring(dmfa.xml_file.content)
        services = {
            s.findtext('ServiceCode'): int(s.findtext('ServiceNbrHours')) / 100 for s in declaration.iter('Service')}
        remunerations = {
            r.findtext('RemunCode'): int(r.findtext('RemunAmount')) / 100 for r in declaration.iter('Remun')}
        self.assertEqual(services['080'], 10)
        service_days = {s.findtext('ServiceCode'): s.findtext('ServiceNbrDays') for s in declaration.iter('Service')}
        self.assertEqual(service_days['080'], '00001')
        self.assertEqual(remunerations.get('013'), round(overtime.amount, 2))

    def test_services_days_balanced_in_half_days(self):
        """ The days of the service codes of an occupation line are balanced in half days of its hours a day (38 hours
        on 5 days: 3.8 hours a half day): each code but the most frequent one gets its hours in half days, rounded half
        up, a code below a quarter of a day is left out, and the most frequent code gets the other days of the line """
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip 1/2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        work_lines = payslip.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id.dmfa_code == '1')
        work_days, work_hours = sum(work_lines.mapped('number_of_days')), sum(work_lines.mapped('number_of_hours'))
        work = work_lines.filtered(lambda wd: wd.code == '002.00')
        # an illness of 9.5 hours counted as a day (1.25 day of 7.6 hours: 1.5 day), an unpaid absence of 1.35 hours
        # counted as a half day (less than a quarter of a day: left out)
        work.copy({
            'payslip_id': payslip.id, 'number_of_days': 1, 'number_of_hours': 9.5,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_common_law_illness_after_legal_period').id,
        })
        work.copy({
            'payslip_id': payslip.id, 'number_of_days': 0.5, 'number_of_hours': 1.35,
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        })
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()

        dmfa = self._generate_dmfa_declaration(return_declaration=True)
        services = {
            s.findtext('ServiceCode'): (int(s.findtext('ServiceNbrDays')) / 100, int(s.findtext('ServiceNbrHours')) / 100)
            for s in etree.fromstring(dmfa.xml_file.content).iter('Service')}
        self.assertEqual(services['050'], (1.5, 9.5))
        self.assertNotIn('030', services)
        # the days of the line (the work days, the illness day and the unpaid half day) less the illness days
        self.assertEqual(services['001'], (work_days, round(work_hours, 2)))

    @freeze_time("2026-01-10 10:00:00")
    def test_positive_holiday_pay_regularization_remuneration(self):
        """ A positive regularization of the simple holiday pay of the previous employer (HolPayReg) is in the gross
        salary of the December payslip: declared under the remuneration code 014, not under the code 001 as well """
        explanation = {'recovered': 0, 'total_100_pct_wage': 100, 'amount_to_recover': 100, 'max_amount': 100}
        with patch.object(self.registry['hr.employee'], '_get_simple_holiday_pay_recoverable_amount', return_value=100), \
                patch.object(self.registry['hr.payslip'], '_get_holiday_pay_regularization', return_value=(100, explanation)):
            payslip = self.env['hr.payslip'].create({
                'name': 'Payslip 12/2025',
                'version_id': self.contract.id,
                'date_from': date(2025, 12, 1),
                'date_to': date(2025, 12, 31),
                'employee_id': self.employee.id,
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
                'company_id': self.belgian_company.id,
            })
            payslip.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        line_values = payslip._get_line_values(['HolPayReg', 'SALARY'])
        self.assertAlmostEqual(line_values['HolPayReg'][payslip.id]['total'], 100, places=2)
        salary = line_values['SALARY'][payslip.id]['total']

        dmfa = self._generate_dmfa_declaration(year='2025', quarter='4', return_declaration=True)
        remunerations = {
            r.findtext('RemunCode'): int(r.findtext('RemunAmount')) / 100
            for r in etree.fromstring(dmfa.xml_file.content).iter('Remun')}
        self.assertEqual(remunerations['014'], 100)
        self.assertAlmostEqual(remunerations['001'], salary - 100, places=2)

    def test_blue_collar_extra_legal_holidays_service_code(self):
        """ The extra-legal holidays granted by the employer (011.00) are declared with the worked days (service code
        001) for a white collar, under the service code 003 for a blue collar (complementary holidays paid by the
        employer, subject to the contributions) """
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip 1/2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        work = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '002.00')
        work.write({'number_of_days': work.number_of_days - 2, 'number_of_hours': work.number_of_hours - 15.2})
        work.copy({
            'payslip_id': payslip.id, 'number_of_days': 2, 'number_of_hours': 15.2,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_extra_legal').id,
        })
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()

        def services():
            dmfa = self._generate_dmfa_declaration(return_declaration=True)
            result = {
                s.findtext('ServiceCode'): (int(s.findtext('ServiceNbrDays')) / 100, int(s.findtext('ServiceNbrHours')) / 100)
                for s in etree.fromstring(dmfa.xml_file.content).iter('Service')}
            dmfa.unlink()
            return result

        white_collar_services = services()
        self.assertNotIn('003', white_collar_services)

        self.contract.write({
            'employee_type_id': self.env.ref('l10n_be_hr_payroll.l10n_be_contract_type_be_worker').id,
            'l10n_be_worker_code_id': self.env['l10n.be.worker.code'].search([('dmfa_code', '=', '015')]).id,
        })
        blue_collar_services = services()
        self.assertEqual(blue_collar_services['003'], (2, 15.2))
        self.assertEqual(blue_collar_services['001'][0], white_collar_services['001'][0] - 2)
        self.assertEqual(round(blue_collar_services['001'][1], 2), round(white_collar_services['001'][1] - 15.2, 2))

    @freeze_time("2027-01-15 10:00:00")
    def test_wijninckx_contribution_unrelated_to_natural_person(self):
        """ The Wijninckx contribution is declared globally, not per worker """
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Dec 2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, 12, 1),
            'date_to': date(2026, 12, 31),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip._set_input_value('ONSSEMPLOYER_867', 10000)
        payslip.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        wijninckx_amount = payslip._get_line_values(['ONSSEMPLOYER_867'], compute_sum=True)['ONSSEMPLOYER_867']['sum']['total']
        self.assertTrue(wijninckx_amount)

        declaration = xml_str_to_dict(self._generate_dmfa_declaration(year='2026', quarter='4', return_declaration=True).xml_file.content)
        employer_declaration = declaration['DmfAOriginal']['Form']['EmployerDeclaration']
        worker_contributions = employer_declaration['NaturalPerson']['WorkerRecord']['WorkerContribution']
        self.assertNotIn('867', [c['ContributionWorkerCode'] for c in worker_contributions])
        unrelated = employer_declaration['ContributionUnrelatedToNP']
        wijninckx = next(c for c in (unrelated if isinstance(unrelated, list) else [unrelated]) if c['UnrelatedWorkerCode'] == '867')
        self.assertEqual(wijninckx['UnrelatedCalculationBasis'], '00001000000')
        self.assertEqual(int(wijninckx['UnrelatedAmount']), round(wijninckx_amount * 100))

    @freeze_time("2027-01-15 10:00:00")
    def test_contributions_unrelated_to_natural_person_all_workers(self):
        """ The contributions declared globally are computed on the payslips of every worker """
        employee_2 = self.env['hr.employee'].create({
            'name': 'Employee 2',
            'company_id': self.belgian_company.id,
            'country_id': self.env.ref('base.be').id,
            'niss': '99010112390',
            'contract_date_start': datetime(2020, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'work_contact_id': self.work_contact.copy().id,
            'wage': 3000,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        })
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Dec 2026',
            'employee_id': employee.id,
            'version_id': employee.version_id.id,
            'date_from': date(2026, 12, 1),
            'date_to': date(2026, 12, 31),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        } for employee in self.employee | employee_2])
        for payslip in payslips:
            payslip._set_input_value('ONSSEMPLOYER_867', 10000)
        payslips.compute_sheet()
        (self.employee | employee_2).write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()
        wijninckx_amount = payslips._get_line_values(['ONSSEMPLOYER_867'], compute_sum=True)['ONSSEMPLOYER_867']['sum']['total']

        declaration = xml_str_to_dict(self._generate_dmfa_declaration(year='2026', quarter='4', return_declaration=True).xml_file.content)
        unrelated = declaration['DmfAOriginal']['Form']['EmployerDeclaration']['ContributionUnrelatedToNP']
        wijninckx = next(c for c in (unrelated if isinstance(unrelated, list) else [unrelated]) if c['UnrelatedWorkerCode'] == '867')
        self.assertEqual(wijninckx['UnrelatedCalculationBasis'], '00002000000')
        self.assertEqual(int(wijninckx['UnrelatedAmount']), round(wijninckx_amount * 100))

    @freeze_time("2026-04-10 10:00:00")
    def test_wage_cap_reduction_calculation_basis(self):
        """ The calculation basis of the wage cap reduction (1360) is mandatory: the remuneration above the cap """
        self.contract.wage = 35000
        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip {month}/2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, month, 1),
            'date_to': date(2026, month, 1) + relativedelta(day=31),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        } for month in (1, 2, 3)])
        self.employee.write({'review_state': '1_reviewed'})
        for payslip in payslips:
            payslip.compute_sheet()
            payslip.action_payslip_done()
        reduction = -payslips._get_line_values(['ONSSEMPLOYERBASICDEDUC'], compute_sum=True)['ONSSEMPLOYERBASICDEDUC']['sum']['total']
        self.assertTrue(reduction)

        worker_record = self._generate_dmfa_declaration(year='2026', quarter='1')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']
        worker_deductions = worker_record['WorkerDeduction']
        deduction = next(d for d in (worker_deductions if isinstance(worker_deductions, list) else [worker_deductions]) if d['DeductionCode'] == '1360')
        self.assertEqual(int(deduction['DeductionAmount']), round(reduction * 100))
        rates = payslips[0]._get_onss_global_rates()
        self.assertEqual(int(deduction['DeductionCalculationBasis']), round(reduction * 100 / (rates['employer_rate'] + rates['salary_moderation_rate']) * 100))

    @freeze_time("2026-04-10 10:00:00")
    def test_wage_cap_reduction_on_remuneration_code_1(self):
        """ The remuneration code 1 counts to reach the ceiling of the wage cap reduction (1360), the commissions
        (pay of the quarter's work, remuneration code 1) included """
        self.contract.wage = 27000
        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip {month}/2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, month, 1),
            'date_to': date(2026, month, 1) + relativedelta(day=31),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        } for month in (1, 2, 3)])
        self.employee.write({'review_state': '1_reviewed'})
        for payslip in payslips:
            payslip._set_input_value('COMMISSION', 3000)
            payslip.compute_sheet()
            payslip.action_payslip_done()
        line_values = payslips._get_line_values(['SALARY', 'COMMISSION', 'ONSSEMPLOYERBASICDEDUC'], compute_sum=True)
        self.assertGreater(line_values['SALARY']['sum']['total'], payslips[0]._rule_parameter('employer_contribution_capping_amount'))
        self.assertLess(
            line_values['SALARY']['sum']['total'] - line_values['COMMISSION']['sum']['total'],
            payslips[0]._rule_parameter('employer_contribution_capping_amount'))
        self.assertTrue(line_values['ONSSEMPLOYERBASICDEDUC']['sum']['total'])

    @freeze_time("2026-04-10 10:00:00")
    def test_one_natural_person_state_per_quarter(self):
        """ The data declared for a worker in a quarter is kept once, for the later modifications """
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jan 2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        self._generate_dmfa_declaration(year='2026', quarter='1')
        states = self.env['l10n_be.dmfa.natural_person.state'].sudo().search([
            ('employee_id', '=', self.employee.id), ('quarter_start', '=', date(2026, 1, 1))])
        self.assertEqual(len(states), 1)

    @freeze_time("2026-04-10 10:00:00")
    def test_cct90_bonus_above_ceiling(self):
        """ A CCT 90 bonus is remuneration subject to the ordinary contributions only above the ceiling """
        payslips = self.env['hr.payslip'].create([{
            'name': name,
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'struct_id': self.env.ref(struct_xmlid).id,
            'company_id': self.belgian_company.id,
        } for name, struct_xmlid in [
            ('Payslip Jan 2026', 'l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary'),
            ('CCT90 2026', 'l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_cct90'),
        ]])
        payslips[1]._set_input_value('CCT90BONUSPLAN', 10000)
        payslips.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()
        line_values = payslips._get_line_values(['SALARY', 'BONUS_SALARY'])
        salary = line_values['SALARY'][payslips[0].id]['total']
        bonus = line_values['BONUS_SALARY'][payslips[1].id]['total']
        excess = bonus - payslips[1]._rule_parameter('cct90_employer_onss_threshold')
        self.assertGreater(excess, 0)

        worker_record = self._generate_dmfa_declaration(year='2026', quarter='1')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']
        remunerations = worker_record['Occupation']['Remun']
        remunerations = remunerations if isinstance(remunerations, list) else [remunerations]
        self.assertEqual([int(r['RemunAmount']) for r in remunerations if r['RemunCode'] == '002'], [round(excess * 100)])
        contribution = next(c for c in worker_record['WorkerContribution'] if c['ContributionWorkerCode'] == worker_record['WorkerCode'])
        self.assertEqual(int(contribution['ContributionCalculationBasis']), round((salary + excess) * 100))
        # The special contribution (888) is due on the bonus up to the ceiling, employer and worker rates together
        contribution = next(c for c in worker_record['WorkerContribution'] if c['ContributionWorkerCode'] == '888')
        self.assertEqual(contribution['ContributionType'], '0')
        ceiling = payslips[1]._rule_parameter('cct90_employer_onss_threshold')
        self.assertEqual(int(contribution['ContributionCalculationBasis']), round(ceiling * 100))
        self.assertEqual(int(contribution['ContributionAmount']), round(ceiling * 46.07))
        # As on the payslip
        employer_line = payslips[1].line_ids.filtered(lambda l: l.code == 'ONSSEMPLOYER_888')
        self.assertEqual(employer_line.total, round(ceiling * 0.33, 2))

    @freeze_time("2026-04-10 10:00:00")
    def test_local_unit_of_the_quarter(self):
        """ The establishment unit is the one of the work address of the quarter, not the current one """
        self.employee.create_version({
            'date_version': date(2026, 4, 1),
            'address_id': self.partner_wallonia.id,
        })
        self.assertEqual(self.employee.address_id, self.partner_wallonia)
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jan 2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        unit = self.env['hr.work.location'].search([('address_id', '=', self.contract.address_id.id), ('location_type', '=', 'dmfa_unit')])
        self.assertEqual(unit.bce_code, '8888888176')

        occupation = self._generate_dmfa_declaration(year='2026', quarter='1')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']
        self.assertEqual(occupation['LocalUnitID'], '8888888176')

    @freeze_time("2026-04-10 10:00:00")
    def test_apprentice_apprenticeship(self):
        """ The apprenticeship zone is mandatory for an apprentice """
        self.employee.birthday = date(2009, 5, 1)
        self.contract.write({
            'l10n_be_worker_code_id': self.env['l10n.be.worker.code'].search([('dmfa_code', '=', '439')]).id,
            'l10n_be_apprenticeship_contract_number': False,
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jan 2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()

        occupation = self._generate_dmfa_declaration(year='2026', quarter='1')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']
        self.assertEqual(occupation.get('Apprenticeship'), '1')

    @freeze_time("2026-04-10 10:00:00")
    def test_part_time_working_days_system(self):
        """ The working days system is the days a week of the worker's schedule: a half-time over 5 days
        works 5 days a week """
        self.contract.write({
            'resource_calendar_id': self.env['resource.calendar'].create({
                'name': 'Half-time 19 hours over 5 days',
                'company_id': self.belgian_company.id,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': 8.0,
                    'hour_to': 11.8,
                }) for dayofweek in ['0', '1', '2', '3', '4']],
            }).id,
            'reference_calendar_id': self.calendar_38h.id,
        })
        self.assertAlmostEqual(self.contract.work_time_rate, 0.5, places=2)
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jan 2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()

        occupation = self._generate_dmfa_declaration(year='2026', quarter='1')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']
        self.assertEqual(occupation['WorkingDaysSystem'], '500')
        self.assertEqual(occupation['MeanWorkingHours'], '1900')

    @freeze_time("2026-04-10 10:00:00")
    def test_worker_code_change_in_quarter(self):
        """ A worker changing of worker code in the quarter (a white collar becoming a blue collar) has a
        worker record per worker code """
        white_collar_code = self.contract.l10n_be_worker_code_id
        blue_collar_code = self.env['l10n.be.worker.code'].search([('dmfa_code', '=', '015')])
        self.assertNotEqual(white_collar_code, blue_collar_code)
        blue_collar_version = self.employee.create_version({
            'date_version': date(2026, 2, 1),
            'l10n_be_worker_code_id': blue_collar_code.id,
        })
        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip {month}/2026',
            'employee_id': self.employee.id,
            'version_id': version.id,
            'date_from': date(2026, month, 1),
            'date_to': date(2026, month, 1) + relativedelta(day=31),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        } for month, version in ((1, self.contract), (2, blue_collar_version), (3, blue_collar_version))])
        self.employee.write({'review_state': '1_reviewed'})
        for payslip in payslips:
            payslip.compute_sheet()
            payslip.action_payslip_done()

        worker_records = self._generate_dmfa_declaration(year='2026', quarter='1')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']
        self.assertEqual(
            sorted((w['WorkerCode'], w['Occupation']['OccupationStartingDate'], w['Occupation'].get('OccupationEndingDate')) for w in worker_records),
            sorted([
                (white_collar_code.dmfa_code, self.contract.date_start.isoformat(), '2026-01-31'),
                ('015', '2026-02-01', None),
            ]))
        states = self.env['l10n_be.dmfa.natural_person.state'].sudo().search([
            ('employee_id', '=', self.employee.id), ('quarter_start', '=', date(2026, 1, 1))])
        self.assertEqual(len(states), 1)
        self.assertEqual(set(states.worker_record_data), {white_collar_code.dmfa_code, '015'})

    @freeze_time("2027-01-15 10:00:00")
    def test_starterjob_thirteen_month_remuneration(self):
        """ The starter job deduction of a 13th month is part of the bonus remuneration (code 2), not
        declared again as a negative remuneration """
        employee = self.env['hr.employee'].create({
            'name': 'StarterJob Employee',
            'company_id': self.belgian_company.id,
            'country_id': self.env.ref('base.be').id,
            'address_id': self.partner_wallonia.id,
            'niss': '07020118374',
            'birthday': datetime(2007, 2, 1),
            'contract_date_start': datetime(2025, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'work_contact_id': self.work_contact.id,
            'wage': 2500,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'l10n_be_is_starterjob': True,
            'lang': 'fr_BE',
        })
        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip Dec 2026 {struct}',
            'employee_id': employee.id,
            'version_id': employee.version_id.id,
            'date_from': date(2026, 12, 1),
            'date_to': date(2026, 12, 31),
            'struct_id': self.env.ref(f'l10n_be_hr_payroll.{struct}').id,
            'company_id': self.belgian_company.id,
        } for struct in ('hr_payroll_structure_cp200_employee_salary', 'hr_payroll_structure_cp200_thirteen_month')])
        employee.write({'review_state': '1_reviewed'})
        for payslip in payslips:
            payslip.compute_sheet()
            payslip.action_payslip_done()
        line_values = payslips._get_line_values(['BONUS_SALARY', 'DED_STARTERJOB_BONUS_SALARY'], compute_sum=True)
        self.assertTrue(line_values['DED_STARTERJOB_BONUS_SALARY']['sum']['total'])

        dmfa = self._generate_dmfa_declaration(year='2026', quarter='4', return_declaration=True)
        remunerations = [
            (remun.findtext('RemunCode'), remun.findtext('RemunAmount'))
            for remun in etree.fromstring(dmfa.xml_file.content).iter('Remun')
        ]
        self.assertFalse([amount for code, amount in remunerations if amount.startswith('-')])
        self.assertEqual(
            sum(int(amount) for code, amount in remunerations if code == '002'),
            round(line_values['BONUS_SALARY']['sum']['total'] * 100))

    @freeze_time("2026-07-01 10:00:00")
    def test_other_contributions_computed_on_payslips(self):
        """ The contributions computed on the payslips are declared: closing fund of the non commercial
        employers (811), risk groups (852) """
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Apr 2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payroll_config = payslip.payroll_config_id
        payroll_config.l10n_be_at_risk_groups_contribution = True
        employer_class = payroll_config.l10n_be_employer_category_id.dmfa_code
        code = f'l10n_be_onss_combinations_{employer_class}_495'
        combinations = payslip._rule_parameter(code)
        self.env['hr.rule.parameter.value'].sudo().create({
            'rule_parameter_id': self.env['hr.rule.parameter'].sudo().search([('code', '=', code)]).id,
            'parameter_value': str({**combinations, '811': ['0'], '852': ['0']}),
            'date_from': date(2026, 4, 1),
        })
        payslip.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        line_values = payslip._get_line_values(['ONSSEMPLOYER_811', 'ONSSEMPLOYER_852'])
        self.assertTrue(line_values['ONSSEMPLOYER_811'][payslip.id]['total'])
        self.assertTrue(line_values['ONSSEMPLOYER_852'][payslip.id]['total'])

        worker_record = self._generate_dmfa_declaration(year='2026', quarter='2')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']
        contributions = {c['ContributionWorkerCode']: c for c in worker_record['WorkerContribution']}
        ffe_type = '0' if payslip._with_salary_moderation() else '2'
        for worker_code, contribution_type in (('811', ffe_type), ('852', '0')):
            contribution = contributions[worker_code]
            self.assertEqual(contribution['ContributionType'], contribution_type)
            rate = payslip._get_onss_rates(worker_code, contribution_type)['total_rate']
            self.assertEqual(int(contribution['ContributionAmount']), round(int(contribution['ContributionCalculationBasis']) * rate / 100))

    @freeze_time("2026-07-01 10:00:00")
    def test_closure_fund_contributions_subsidised_contract(self):
        """ The special Closure Fund contribution (810) and the basic one of the employers without industrial or
        commercial purpose (811) are of type 2 for a subsidised contract (ACS), as without wage moderation, though
        its ordinary contributions include it, and of type 0 for an ordinary employee """
        self.contract.l10n_be_worker_code_id = self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00484')
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Apr 2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.payroll_config_id.l10n_be_ffe_employer_type = 'B'
        payslip.compute_sheet()
        self.assertTrue(payslip._with_salary_moderation())
        self.assertEqual(payslip._get_ffe_without_headcount_contribution_type(), '2')
        for worker_code, rate in (('810', 0.09), ('811', 0.01)):
            self.assertEqual(payslip.line_ids.filtered(lambda line: line.code == f'ONSSEMPLOYER_{worker_code}').rate, rate)
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()

        worker_record = self._generate_dmfa_declaration(year='2026', quarter='2')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']
        contributions = {c['ContributionWorkerCode']: c for c in worker_record['WorkerContribution']}
        for worker_code, rate in (('810', 0.09), ('811', 0.01)):
            contribution = contributions[worker_code]
            self.assertEqual(contribution['ContributionType'], '2')
            self.assertEqual(int(contribution['ContributionAmount']), round(int(contribution['ContributionCalculationBasis']) * rate / 100))

        # An ordinary employee, with wage moderation
        self.contract.l10n_be_worker_code_id = self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00495')
        self.assertEqual(payslip._get_ffe_without_headcount_contribution_type(), '0')

    @freeze_time("2026-07-01 10:00:00")
    def test_activation_contribution(self):
        """ The activation contribution of a worker exempted from work during the whole quarter is declared, with the
        exemption notion of the occupation and the activation block """
        self.employee.birthday = date(1968, 3, 1)
        self.contract.write({'l10n_be_work_exemption': '2', 'l10n_be_work_exemption_date': date(2026, 1, 1)})
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip %s 2026' % month,
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, month, 1),
            'date_to': date(2026, month, 1) + relativedelta(months=1, days=-1),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        } for month in (4, 5, 6)])
        payslips.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslips.action_payslip_done()
        self.assertTrue(payslips._get_line_values(['ONSSEMPLOYER_260'], compute_sum=True)['ONSSEMPLOYER_260']['sum']['total'])

        worker_record = self._generate_dmfa_declaration(year='2026', quarter='2')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']
        self.assertEqual(worker_record['Occupation']['OccupationInformations']['ServiceExemptionNotion'], '2')
        activation = worker_record['ActivationInformation']
        self.assertEqual(activation['ServiceExemptionStartDate'], '2026-01-01')
        self.assertEqual(activation['TrainingSituationStartDate'], '2026-01-01')
        self.assertEqual(activation['TrainingSituation'], '0')
        contribution = next(c for c in worker_record['WorkerContribution'] if c['ContributionWorkerCode'] == '260')
        # Aged 57 at the start of the exemption, increased when due for at least 10% of the workers
        self.assertEqual(contribution['ContributionType'], '5' if activation['ActivationPercentageStatus'] == '1' else '0')
        rate = payslips[0]._get_onss_rates('260', contribution['ContributionType'])['total_rate']
        basis = int(contribution['ContributionCalculationBasis'])
        self.assertEqual(int(contribution['ContributionAmount']), max(30000, round(basis * rate / 100)))
        main_contribution = next(c for c in worker_record['WorkerContribution'] if c['ContributionWorkerCode'] == worker_record['WorkerCode'])
        self.assertEqual(basis, int(main_contribution['ContributionCalculationBasis']))

    def test_activation_contribution_former_workers(self):
        """ The former workers of the company are not taken into account to determine if the
        activation contribution is due for at least 10% of the workers """
        self.employee.birthday = date(1968, 3, 1)
        self.contract.write({'l10n_be_work_exemption': '2', 'l10n_be_work_exemption_date': date(2026, 1, 1)})
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip April 2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        _contribution_type, _minimum, increased = payslip._l10n_be_get_activation_contribution_type()
        self.assertTrue(increased)
        self.env['hr.employee'].create([{
            'name': 'Former Worker %s' % i,
            'company_id': self.belgian_company.id,
            'date_version': date(2015, 1, 1),
            'contract_date_start': date(2015, 1, 1),
            'contract_date_end': date(2020, 12, 31),
        } for i in range(20)])
        _contribution_type, _minimum, increased = payslip._l10n_be_get_activation_contribution_type()
        self.assertTrue(increased)

    def test_activation_contribution_branch_workers(self):
        """ The workers of the branches are workers of the employer: the activation contribution is due for less
        than 10% of them """
        self.employee.birthday = date(1968, 3, 1)
        self.contract.write({'l10n_be_work_exemption': '2', 'l10n_be_work_exemption_date': date(2026, 1, 1)})
        branch = self.env['res.company'].create({'name': 'Branch', 'parent_id': self.belgian_company.id})
        self.env['hr.employee'].create([{
            'name': 'Branch Worker %s' % i,
            'company_id': branch.id,
            'date_version': date(2015, 1, 1),
            'contract_date_start': date(2015, 1, 1),
        } for i in range(20)])
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip April 2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        _contribution_type, _minimum, increased = payslip._l10n_be_get_activation_contribution_type()
        self.assertFalse(increased)

    @freeze_time("2026-07-01 10:00:00")
    def test_economic_unemployment_contribution(self):
        """ The economic unemployment contribution computed on the payslips is declared without calculation basis """
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Apr 2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        # 6 days of economic unemployment in the quarter, more than 130 days in the last 4 quarters: 40 € a day
        self.env['hr.payslip.line'].create({
            'slip_id': payslip.id,
            'salary_rule_id': self.env.ref('l10n_be_hr_payroll.l10n_be_employees_salary_onss_employer_800').id,
            'name': 'Economic Unemployment Contribution',
            'code': 'ONSSEMPLOYER_800',
            'amount': 240,
            'quantity': 1,
            'rate': 100,
            'total': 240,
        })

        worker_record = self._generate_dmfa_declaration(year='2026', quarter='2')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']
        contribution = next(c for c in worker_record['WorkerContribution'] if c['ContributionWorkerCode'] == '800')
        self.assertEqual(contribution['ContributionType'], '0')
        self.assertNotIn('ContributionCalculationBasis', contribution)
        self.assertEqual(int(contribution['ContributionAmount']), 24000)

    def _create_flexi_employee(self, worker_code='450'):
        flexi = self.env['hr.employee'].create({
            'name': 'Flexi Worker',
            'company_id': self.belgian_company.id,
            'country_id': self.env.ref('base.be').id,
            'address_id': self.partner_wallonia.id,
            'l10n_be_worker_code_id': self.env['l10n.be.worker.code'].search([('dmfa_code', '=', worker_code)]).id,
            'niss': '85010100214',
            'contract_date_start': datetime(2026, 4, 1),
            'contract_date_end': datetime(2026, 6, 30),
            'date_version': datetime(2026, 4, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'work_contact_id': self.work_contact.id,
            'l10n_be_flexi_monthly_wage': 2500,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        })
        flexi.version_id.l10n_be_dimona_category = 'flx'
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Apr 2026',
            'employee_id': flexi.id,
            'version_id': flexi.version_id.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        return flexi, payslip

    @freeze_time("2026-07-01 10:00:00")
    def test_flexi_manual_worker_contribution_basis(self):
        """ The holiday pay of a flexi-job is in its pay: the basis of a manual flexi worker isn't
        raised to 108%, as on the payslip """
        flexi, payslip = self._create_flexi_employee(worker_code='050')
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self.assertTrue(flexi.version_id.is_worker())
        self.assertEqual(payslip._l10n_be_get_onss_basis_uplift(), 1)
        salary_codes = self.env['hr.payslip']._get_salary_wage_line_codes() - {'DH_SALARY'}
        line_values = payslip._get_line_values(salary_codes)
        basis = round(sum(line_values[code][payslip.id]['total'] for code in salary_codes), 2)
        self.assertTrue(basis)

        worker_record = self._generate_dmfa_declaration(year='2026', quarter='2')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']
        contributions = worker_record['WorkerContribution']
        contribution = next(c for c in (contributions if isinstance(contributions, list) else [contributions]) if c['ContributionWorkerCode'] == '050')
        self.assertEqual(int(contribution['ContributionCalculationBasis']), round(basis * 100))
        # The rates of a flexi-job are under the contribution type 0, a manual worker's as the others'
        self.assertEqual(contribution['ContributionType'], '0')
        self.assertEqual(int(contribution['ContributionAmount']), round(basis * 28))

    @freeze_time("2026-07-01 10:00:00")
    def test_flexi_remuneration_code(self):
        """ The pay of a flexi-job, its bonus and its flexi holiday pay included, is declared once under the code 22 """
        _flexi, payslip = self._create_flexi_employee()
        payslip._set_input_value('FLEXI_BONUS', 100)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        line_values = payslip._get_line_values(['SALARY', 'FLEXI_BONUS', 'FLEXI_PECULE'])
        self.assertEqual(line_values['FLEXI_BONUS'][payslip.id]['total'], 100)
        self.assertTrue(line_values['FLEXI_PECULE'][payslip.id]['total'])
        salary = line_values['SALARY'][payslip.id]['total']

        occupation = self._generate_dmfa_declaration(year='2026', quarter='2')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']
        remunerations = occupation['Remun']
        remunerations = remunerations if isinstance(remunerations, list) else [remunerations]
        self.assertEqual([(r['RemunCode'], int(r['RemunAmount'])) for r in remunerations], [('022', round(salary * 100))])

    @freeze_time("2026-07-01 10:00:00")
    def test_flexi_remuneration_split_between_day_lines(self):
        """ A flexi-job's monthly payslip over day contracts (one occupation line each): each line gets the pay of
        its own worked days, and a share of the rest of the gross salary and of the flexi holiday pay pro rata to
        its hours, each truncated to the cent, the rest on the last line """
        flexi, payslip = self._create_flexi_employee(worker_code='050')
        payslip.unlink()
        monday = flexi.version_id
        monday.write({
            'contract_date_start': date(2026, 4, 6),
            'contract_date_end': date(2026, 4, 6),
            'date_version': date(2026, 4, 6),
            'wage_type': 'hourly',
            'hourly_wage': 12.07,
            'l10n_be_flexi_hourly_wage': 12.07,
        })
        tuesday, thursday = (flexi.create_version({
            'date_version': day,
            'contract_date_start': day,
            'contract_date_end': day,
        }) for day in (date(2026, 4, 7), date(2026, 4, 9)))
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Apr 2026',
            'employee_id': flexi.id,
            'version_id': monday.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip._set_input_value('ADDITIONALGROSS', 10.04)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self.assertEqual(payslip.worked_days_line_ids.version_id, monday | tuesday | thursday)
        line_values = payslip._get_line_values(['SALARY', 'FLEXI_PECULE'])
        salary = line_values['SALARY'][payslip.id]['total']
        pecule = line_values['FLEXI_PECULE'][payslip.id]['total']

        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        remunerations = {
            o.findtext('OccupationStartingDate'): int(o.find('Remun').findtext('RemunAmount'))
            for o in etree.fromstring(dmfa.xml_file.content).iter('Occupation')}
        # 7.6 hours a day at 12.07: 91.73 a day; the additional gross 10.04 and the flexi holiday pay 21.88 shared on
        # 3 x 7.6 hours, each truncated to the cent: 3.3467 -> 3.34 (not 3.35) and 7.2933 -> 7.29, the rest of the
        # gross salary on the last day
        self.assertAlmostEqual(salary, 307.11, 2)
        self.assertAlmostEqual(pecule, 21.88, 2)
        self.assertEqual(remunerations, {'2026-04-06': 10236, '2026-04-07': 10236, '2026-04-09': 10239})

    def test_flexi_premium_of_a_day_split_between_day_lines(self):
        """ A flexi-job's premium of a day (e.g. a Sunday or public holiday premium) is pay of that day's line: the
        line gets the pay of its worked days with the premium, and a share of the rest of the gross salary and of
        the flexi holiday pay pro rata to its hours, each truncated to the cent, the rest on the last line """
        flexi, payslip = self._create_flexi_employee(worker_code='050')
        payslip.unlink()
        monday = flexi.version_id
        monday.write({
            'contract_date_start': date(2026, 4, 6),
            'contract_date_end': date(2026, 4, 6),
            'date_version': date(2026, 4, 6),
            'wage_type': 'hourly',
            'hourly_wage': 12.07,
            'l10n_be_flexi_hourly_wage': 12.07,
        })
        tuesday, thursday = (flexi.create_version({
            'date_version': day,
            'contract_date_start': day,
            'contract_date_end': day,
        }) for day in (date(2026, 4, 7), date(2026, 4, 9)))
        premium_category = self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_HOLIDAY')
        premium_type = self.env['hr.work.entry.type'].create({
            'name': 'Premium Pay',
            'code': 'PREMIUM_PAY',
            'requires_allocation': False,
            'request_unit': 'hour',
            'unit_of_measure': 'hour',
            'dmfa_code': '1',
            'optional_category_ids': [Command.link(premium_category.id)],
        })
        flexi.write({'review_state': '1_reviewed'})
        self.env['hr.leave'].create({
            'employee_id': flexi.id,
            'work_entry_type_id': premium_type.id,
            'request_date_from': date(2026, 4, 7),
            'request_date_to': date(2026, 4, 7),
            'request_hour_from': 8,
            'request_hour_to': 12,
            'category_options_ids': [Command.link(premium_category.id)],
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Apr 2026',
            'employee_id': flexi.id,
            'version_id': monday.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip._set_input_value('ADDITIONALGROSS', 10.04)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self.assertEqual(payslip.worked_days_line_ids.filtered('category_options_ids').version_id, tuesday)
        line_values = payslip._get_line_values(['SALARY', 'FLEXI_PECULE', 'PREMHOL'])
        salary = line_values['SALARY'][payslip.id]['total']
        pecule = line_values['FLEXI_PECULE'][payslip.id]['total']
        premium = line_values['PREMHOL'][payslip.id]['total']
        self.assertTrue(premium)
        paid = {
            version: sum(payslip.worked_days_line_ids.filtered(lambda wd: wd.version_id == version).mapped('amount'))
            for version in monday | tuesday | thursday}
        rest = salary - pecule - sum(paid.values()) - premium

        def truncated(amount):
            return float_round(amount, 2, rounding_method='DOWN')

        # the 3 days of 7.6 hours: a third of the rest and of the flexi holiday pay each, truncated
        expected = {
            '2026-04-06': round(paid[monday], 2) + truncated(rest / 3) + truncated(pecule / 3),
            '2026-04-07': round(paid[tuesday] + premium, 2) + truncated(rest / 3) + truncated(pecule / 3),
        }
        expected['2026-04-09'] = salary - sum(expected.values())
        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        remunerations = {
            o.findtext('OccupationStartingDate'): int(o.find('Remun').findtext('RemunAmount'))
            for o in etree.fromstring(dmfa.xml_file.content).iter('Occupation')}
        self.assertEqual(remunerations, {day: round(amount * 100) for day, amount in expected.items()})

    @freeze_time("2026-07-01 10:00:00")
    def test_student_contribution_rate(self):
        """ The student solidarity contribution is computed with the rate of the payslips, on the salary of the
        payslips, an additional gross included, as their contribution """
        student, payslip = self._create_flexi_employee(worker_code='841')
        student.version_id.write({'l10n_be_dimona_category': 'stu', 'wage': 1500})
        payslip._set_input_value('ADDITIONALGROSS', 100)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        rate = payslip._get_onss_global_rates()['total_rate']
        self.assertEqual(rate, 8.14)
        line_values = payslip._get_line_values(['BASIC', 'SALARY', 'ONSS'])
        salary = line_values['SALARY'][payslip.id]['total']
        self.assertAlmostEqual(salary, line_values['BASIC'][payslip.id]['total'] + 100, places=2)
        # the student's contribution on the payslip is computed on the salary
        self.assertAlmostEqual(line_values['ONSS'][payslip.id]['total'], -round(salary * 2.71 / 100, 2), places=2)

        worker_record = self._generate_dmfa_declaration(year='2026', quarter='2')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']
        contribution = worker_record['StudentContribution']
        basis = int(contribution['StudentRemunAmount'])
        self.assertEqual(basis, round(salary * 100))
        self.assertEqual(int(contribution['StudentContributionAmount']), round(basis * rate / 100))

    @freeze_time("2026-07-01 10:00:00")
    def test_student_worked_hours_rounded_up(self):
        """ The student hours are the hours actually worked, a worked public holiday included, a paid public holiday
        not worked or an unpaid absence not, in whole hours rounded up (100h30 counts 101h), while the remuneration
        is all the pay of the student """
        student, payslip = self._create_flexi_employee(worker_code='841')
        student.version_id.write({'l10n_be_dimona_category': 'stu', 'wage': 1500})
        payslip.compute_sheet()
        work = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '002.00')
        self.assertEqual(len(work), 1)
        work.write({'number_of_days': 13, 'number_of_hours': 96.5})
        work.copy({
            'payslip_id': payslip.id, 'number_of_days': 1, 'number_of_hours': 4,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_public_holiday_working_with_recovery').id,
        })
        public_holiday = work.copy({
            'payslip_id': payslip.id, 'number_of_days': 1, 'number_of_hours': 8,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id,
        })
        self.assertTrue(public_holiday.is_paid)
        unpaid = work.copy({
            'payslip_id': payslip.id, 'number_of_days': 1, 'number_of_hours': 8,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_justified_reason_unpaid').id,
        })
        self.assertFalse(unpaid.is_paid)
        payslip.action_payslip_done()
        self.assertEqual(payslip._l10n_be_get_student_worked_hours(), 101)

        worker_record = self._generate_dmfa_declaration(year='2026', quarter='2')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']
        contribution = worker_record['StudentContribution']
        # 96.5 hours of attendance and 4 hours of a worked public holiday, not the 8 hours of the paid public holiday
        self.assertEqual(int(contribution['StudentHoursNbr']), 101)
        salary = payslip._get_line_values(['SALARY'])['SALARY'][payslip.id]['total']
        self.assertEqual(int(contribution['StudentRemunAmount']), round(salary * 100))

    def _occupation_periods(self, employee):
        groups = employee.version_ids.sorted('date_start', reverse=True)._get_occupation_dates()
        return sorted((date_from, date_to) for _versions, date_from, date_to in groups)

    @freeze_time("2026-07-01 10:00:00")
    def test_flexi_one_occupation_per_dimona_period(self):
        """ The occupation lines of a flexi-job follow its Dimona periods: the back-to-back day contracts of a
        flexi-job, each with its own daily Dimona, are one occupation each, while a Dimona period of several days
        is one occupation """
        flexi, payslip = self._create_flexi_employee(worker_code='050')
        monday = flexi.version_id
        monday.write({
            'contract_date_start': date(2026, 4, 6),
            'contract_date_end': date(2026, 4, 6),
            'date_version': date(2026, 4, 6),
        })
        tuesday, thursday = (flexi.create_version({
            'date_version': date_start,
            'contract_date_start': date_start,
            'contract_date_end': date_end,
        }) for date_start, date_end in ((date(2026, 4, 7), date(2026, 4, 7)), (date(2026, 4, 9), date(2026, 4, 10))))
        self.assertEqual((tuesday | thursday).mapped('l10n_be_dimona_category'), ['flx', 'flx'])
        payslip.unlink()
        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip {version.date_start}',
            'employee_id': flexi.id,
            'version_id': version.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        } for version in monday | tuesday | thursday])
        payslips.compute_sheet()
        payslips.action_payslip_done()

        occupations = self._generate_dmfa_declaration(year='2026', quarter='2')['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']
        self.assertEqual(sorted((o['OccupationStartingDate'], o['OccupationEndingDate']) for o in occupations), [
            ('2026-04-06', '2026-04-06'), ('2026-04-07', '2026-04-07'), ('2026-04-09', '2026-04-10'),
        ])

        # The Dimona periods known, they decide: two periods are two occupations, one period over both day
        # contracts one occupation
        def dimona(name, date_start, date_end):
            self.env['l10n.be.dimona.period'].with_company(self.belgian_company).create({
                'name': name,
                'company_id': self.belgian_company.id,
                'content': {'worker': {'ssin': flexi.niss}, 'startDate': str(date_start), 'endDate': str(date_end)},
            })
            return self.env['l10n.be.dimona.declaration'].with_company(self.belgian_company).create({
                'name': f'declaration {name}',
                'company_id': self.belgian_company.id,
                'content': {'declarationStatus': {'result': 'A', 'period': {'id': name}}},
            })

        monday.l10n_be_dimona_declaration_id = dimona('100', date(2026, 4, 6), date(2026, 4, 6))
        tuesday.l10n_be_dimona_declaration_id = dimona('101', date(2026, 4, 7), date(2026, 4, 7))
        self.assertEqual(self._occupation_periods(flexi)[:2], [
            (date(2026, 4, 6), date(2026, 4, 6)), (date(2026, 4, 7), date(2026, 4, 7)),
        ])
        tuesday.l10n_be_dimona_declaration_id = monday.l10n_be_dimona_declaration_id
        self.assertEqual(self._occupation_periods(flexi)[:1], [(date(2026, 4, 6), date(2026, 4, 7))])

    @freeze_time("2026-07-01 10:00:00")
    def test_flexi_variable_schedule_without_hours_occupation(self):
        """ A flexi-job on a variable schedule without hours a week declares, on an occupation line of a week or
        more, the days and hours of its services over the weeks of the line (a whole number of days when close to
        it); on a shorter line, the hours of a longer occupation (its hours a day on each day a week of its schedule)
        and the days a week of its schedule. A full time when the hours reach the reference worker's """
        flexi, payslip = self._create_flexi_employee(worker_code='050')
        payslip.unlink()
        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        planned = {date(2026, 4, day): (8, 12, 13, 17) for day in (7, 8, 9, 13, 14, 15, 20, 21, 22)}
        planned.update({date(2026, 6, day): (8, 12, 13, 17) for day in (15, 16, 17, 18, 19)})
        planned[date(2026, 6, 1)] = (8, 12, 13, 13.5)
        planned.update({
            date(2026, 5, day): (8, 12, 13, 17) for day in (4, 5, 6, 7, 11, 12, 13, 14, 18, 19, 20, 25, 26)})
        calendar = self.env['resource.calendar'].create({
            'name': "Flexi planned day by day",
            'company_id': self.belgian_company.id,
            'calendar_type': 'variable',
            'hours_per_week': 0,
            'days_per_week': 6,
            'reference_calendar_id': self.calendar_38h.id,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'date': day, 'hour_from': hour_from, 'hour_to': hour_to, 'work_entry_type_id': attendance.id})
                for day, (from_1, to_1, from_2, to_2) in planned.items()
                for hour_from, hour_to in ((from_1, to_1), (from_2, to_2))
            ],
        })
        april = flexi.version_id
        april.write({
            'resource_calendar_id': calendar.id,
            'date_version': date(2026, 4, 7),
            'contract_date_start': date(2026, 4, 7),
            'contract_date_end': date(2026, 4, 30),
        })
        may, june_1, june_15 = (flexi.create_version({
            'date_version': date_start,
            'contract_date_start': date_start,
            'contract_date_end': date_end,
        }) for date_start, date_end in (
            (date(2026, 5, 1), date(2026, 5, 30)),
            (date(2026, 6, 1), date(2026, 6, 1)),
            (date(2026, 6, 15), date(2026, 6, 20)),
        ))
        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip {version.date_start}',
            'employee_id': flexi.id,
            'version_id': version.id,
            'date_from': version.date_start.replace(day=1),
            'date_to': version.date_start + relativedelta(day=31),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        } for version in april | may | june_1 | june_15])
        payslips.compute_sheet()
        payslips.action_payslip_done()

        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        values = {o.findtext('OccupationStartingDate'): tuple(o.findtext(tag) for tag in (
            'OccupationEndingDate', 'WorkingDaysSystem', 'ContractType', 'MeanWorkingHours', 'RefMeanWorkingHours',
        )) for o in etree.fromstring(dmfa.xml_file.content).iter('Occupation')}
        self.assertEqual(values, {
            # 9 days and 72 hours over the 24 / 7 = 3.4286 weeks (4 decimals) of the line: 2.62 days (not 2.63 with
            # 3.428571... weeks) and 21 hours a week
            '2026-04-07': ('2026-04-30', '262', '1', '2100', '3800'),
            # 13 days over the 30 / 7 = 4.29 weeks of the line: 3.03 days, close to 3; 104 hours: 24.27 hours a week
            '2026-05-01': ('2026-05-30', '300', '1', '2427', '3800'),
            # 4.5 hours on a day: 27 hours a week on the 6 days a week of the schedule
            '2026-06-01': ('2026-06-01', '600', '1', '2700', '3800'),
            # 40 hours on 5 days: 48 hours a week on the 6 days a week of the schedule, the reference 38 hours
            '2026-06-15': ('2026-06-20', '600', '0', '3800', '3800'),
        })

    @freeze_time("2026-07-01 10:00:00")
    def test_flexi_variable_schedule_without_cycle_occupation(self):
        """ A flexi-job on a variable schedule without cycle with hours a week declares these hours, and as days a
        week the days declared over the weeks of its occupation line, not the days a week of its calendar """
        flexi, payslip = self._create_flexi_employee(worker_code='050')
        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        flexi.version_id.resource_calendar_id = self.env['resource.calendar'].create({
            'name': "Flexi planned day by day, 11.4 hours a week",
            'company_id': self.belgian_company.id,
            'calendar_type': 'variable',
            'hours_per_week': 11.4,
            'days_per_week': 5,
            'reference_calendar_id': self.calendar_38h.id,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'date': date(2026, 4, day), 'hour_from': hour_from, 'hour_to': hour_to,
                        'work_entry_type_id': attendance.id})
                for day in (1, 2, 3, 7, 8, 9, 10, 14, 15, 16, 17, 21, 22, 23, 24, 28)
                for hour_from, hour_to in ((8, 12), (13, 16.8))
            ],
        })
        payslip.compute_sheet()
        payslip.action_payslip_done()

        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        occupation = next(etree.fromstring(dmfa.xml_file.content).iter('Occupation'))
        # 16 days over the 13 weeks of the line (the quarter): 1.23 days a week
        self.assertEqual(occupation.findtext('OccupationStartingDate'), '2026-04-01')
        self.assertEqual(occupation.findtext('OccupationEndingDate'), '2026-06-30')
        self.assertEqual(occupation.findtext('WorkingDaysSystem'), '123')
        self.assertEqual(occupation.findtext('MeanWorkingHours'), '1140')

    def test_occasional_worker_one_occupation_per_contract(self):
        """ An occasional worker (Dimona EXT) has one occupation per day contract, even on consecutive days, while
        the consecutive contracts of an ordinary worker with the same characteristics are one occupation """
        occasional, payslip = self._create_flexi_employee(worker_code='015')
        payslip.unlink()
        friday = occasional.version_id
        friday.write({
            'l10n_be_dimona_category': 'ext',
            'contract_date_start': date(2026, 5, 22),
            'contract_date_end': date(2026, 5, 22),
            'date_version': date(2026, 5, 22),
        })
        saturday = occasional.create_version({
            'date_version': date(2026, 5, 23),
            'contract_date_start': date(2026, 5, 23),
            'contract_date_end': date(2026, 5, 23),
        })
        self.assertEqual(saturday.l10n_be_dimona_category, 'ext')
        self.assertEqual(self._occupation_periods(occasional), [
            (date(2026, 5, 22), date(2026, 5, 22)), (date(2026, 5, 23), date(2026, 5, 23)),
        ])
        (friday | saturday).l10n_be_dimona_category = 'oth'
        self.assertEqual(self._occupation_periods(occasional), [(date(2026, 5, 22), date(2026, 5, 23))])

    @freeze_time("2026-07-01 10:00:00")
    def test_horeca_occasional_worker_day_occupation(self):
        """ The occupation line of a day of a Horeca occasional worker declares the hours a week of a longer
        occupation (its hours a day on each day of the reference worker's week, at most the reference hours), the
        reference worker's days a week, a full time when it reaches the reference hours, and the function number of
        its flat wage: daily (94) from 6 hours a day, by the hour (95) below """
        self.belgian_company.current_payroll_config_id.l10n_be_employer_category_id = self.env.ref(
            'l10n_be_hr_payroll.l10n_be_employer_category_00017')
        occasional, payslip = self._create_flexi_employee(worker_code='011')
        payslip.unlink()
        # the calendars of the day contracts: their weekly hours are the ones of their only day
        calendar_friday = self.calendar_38h.copy({'name': "Fridays"})
        calendar_friday.attendance_ids.filtered(lambda a: a.dayofweek != '4').unlink()
        calendar_mornings = self.calendar_38h.copy({'name': "Thursday mornings"})
        calendar_mornings.attendance_ids.filtered(lambda a: a.hour_from == 13 or a.dayofweek != '3').unlink()
        (calendar_friday | calendar_mornings).reference_calendar_id = self.calendar_38h
        friday = occasional.version_id
        friday.write({
            'l10n_be_dimona_category': 'ext',
            'resource_calendar_id': calendar_friday.id,
            'contract_date_start': date(2026, 5, 22),
            'contract_date_end': date(2026, 5, 22),
            'date_version': date(2026, 5, 22),
        })
        thursday = occasional.create_version({
            'date_version': date(2026, 5, 21),
            'resource_calendar_id': calendar_mornings.id,
            'contract_date_start': date(2026, 5, 21),
            'contract_date_end': date(2026, 5, 21),
        })
        self.assertEqual(thursday._l10n_be_get_employer_category_dmfa_code(), '317')
        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip {version.date_start}',
            'employee_id': occasional.id,
            'version_id': version.id,
            'date_from': date(2026, 5, 1),
            'date_to': date(2026, 5, 31),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        } for version in friday | thursday])
        payslips.compute_sheet()
        payslips.action_payslip_done()

        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        occupations = {
            o.findtext('OccupationStartingDate'): o for o in etree.fromstring(dmfa.xml_file.content).iter('Occupation')}
        self.assertEqual(sorted(occupations), ['2026-05-21', '2026-05-22'])
        values = {day: tuple(o.findtext(tag) for tag in (
            'WorkingDaysSystem', 'ContractType', 'MeanWorkingHours', 'RefMeanWorkingHours', 'PositionCode',
        )) for day, o in occupations.items()}
        # 7.6 hours on each of the 5 days of the reference week: the reference 38 hours, a full time
        self.assertEqual(values['2026-05-22'], ('500', '0', '3800', '3800', '94'))
        # 4 hours: 20 hours a week, part time
        self.assertEqual(values['2026-05-21'], ('500', '1', '2000', '3800', '95'))

        # Beyond the worker's yearly contingent of days, a day is an ordinary one: no function number of a flat wage
        dmfa.unlink()
        payslips.l10n_be_dmfa_id = False
        self.env['hr.rule.parameter.value'].create({
            'rule_parameter_id': self.env.ref('l10n_be_hr_payroll.rule_parameter_horeca_occasional_days').id,
            'date_from': date(2026, 1, 1),
            'parameter_value': '0',
        })
        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        position_codes = {
            o.findtext('OccupationStartingDate'): o.findtext('PositionCode')
            for o in etree.fromstring(dmfa.xml_file.content).iter('Occupation')}
        self.assertEqual(position_codes, {'2026-05-21': None, '2026-05-22': None})

    @freeze_time("2026-07-01 10:00:00")
    def test_flexi_notion(self):
        """ The flexi notion is only declared for a flexi-job declared as an ordinary worker, as its
        Dimona flexi was refused (late Dimona) """
        flexi, payslip = self._create_flexi_employee()
        payslip.compute_sheet()
        payslip.action_payslip_done()
        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        self.assertFalse(list(etree.fromstring(dmfa.xml_file.content).iter('FlexiNotion')))
        # No special unemployment contribution for a flexi-job, as on its payslip
        self.assertFalse(payslip._get_line_values(['ONSSEMPLOYER_855'])['ONSSEMPLOYER_855'][payslip.id]['total'])
        contribution_codes = [c.text for c in etree.fromstring(dmfa.xml_file.content).iter('ContributionWorkerCode')]
        self.assertTrue(contribution_codes)
        self.assertNotIn('855', contribution_codes)

        dmfa.unlink()
        payslip.l10n_be_dmfa_id = False
        flexi.version_id.l10n_be_refused_flexijob = True
        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        self.assertEqual([n.text for n in etree.fromstring(dmfa.xml_file.content).iter('FlexiNotion')], ['FL'])

    @freeze_time("2026-07-01 10:00:00")
    def test_flexi_no_structural_reduction(self):
        """ A flexi-job gets no structural reduction, neither on its payslip nor in the DmfA, unless its
        Dimona flexi was refused (declared as an ordinary worker) """
        flexi, payslip = self._create_flexi_employee()
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self.assertFalse(payslip._get_line_values(['ONSS_STRUCTURAL'])['ONSS_STRUCTURAL'][payslip.id]['total'])
        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        self.assertNotIn('3000', [n.text for n in etree.fromstring(dmfa.xml_file.content).iter('DeductionCode')])

        dmfa.unlink()
        payslip.l10n_be_dmfa_id = False
        flexi.version_id.l10n_be_refused_flexijob = True
        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        self.assertIn('3000', [n.text for n in etree.fromstring(dmfa.xml_file.content).iter('DeductionCode')])

    @freeze_time("2026-07-01 10:00:00")
    def test_dimona_notification_refused_flexijob(self):
        """ A Dimona flexi refused by the ONSS (access conditions 510, late Dimona 460) flags the flexi-job as
        refused, also among several anomalies of the period """
        flexi, _payslip = self._create_flexi_employee()
        for anomaly_report in ({'ErrorID': '00911-510'}, [{'ErrorID': '00911-401'}, {'ErrorID': '00911-460'}]):
            flexi.version_id.l10n_be_refused_flexijob = False
            self.env['l10n.be.onss.declaration']._analyse_notification_file({'NOTIFICATION': {'Form': {
                'HandledOriginalForm': {'Identification': 'DIMONA'},
                'NaturalPerson': {'INSS': flexi.niss},
                'HandlingResult': {
                    'ResultCode': '1',
                    'AnomalyReport': anomaly_report,
                    'ImpactReport': {'DimonaImpactReport': {'DimonaPeriodAfter': {
                        'StartingDate': '2026-04-01',
                        'EndingDate': '2026-06-30',
                    }}},
                },
            }}})
            self.assertTrue(flexi.version_id.l10n_be_refused_flexijob, anomaly_report)

    @freeze_time("2026-07-01 10:00:00")
    def test_occupation_out_of_quarter(self):
        """ The ONSS refuses the occupations ending before the declared quarter """
        self.contract.contract_date_end = date(2026, 3, 31)
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Apr 2026',
            'employee_id': self.employee.id,
            'version_id': self.contract.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()

        with self.assertRaisesRegex(UserError, "The occupations of these employees aren't in the quarter.*%s" % self.employee.name):
            self._generate_dmfa_declaration(year='2026', quarter='2')

    @freeze_time("2026-07-01 10:00:00")
    def test_no_hours_occupation_days_justification(self):
        """
        0 hours per week are only allowed for a complete career interruption, or with the days
        justification 7: worker with no services to perform during the period.
        """
        calendar_0_hours = self.env['resource.calendar'].create({
            'name': "Test Calendar: no hours",
            'company_id': self.belgian_company.id,
            'hours_per_day': 0,
            'hours_per_week': 0,
            'full_time_required_hours': 38,
            'attendance_ids': [(5, 0, 0)],
        })
        version_0_hours = self.employee.create_version({
            'date_version': date(2026, 6, 1),
            'resource_calendar_id': calendar_0_hours.id,
        })
        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip {month}/2026',
            'employee_id': self.employee.id,
            'version_id': version.id,
            'date_from': date(2026, month, 1),
            'date_to': date(2026, month, 1) + relativedelta(day=31),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        } for month, version in [(4, self.contract), (5, self.contract), (6, version_0_hours)]])
        self.employee.write({'review_state': '1_reviewed'})
        for payslip in payslips:
            payslip.compute_sheet()
            payslip.action_payslip_done()

        dmfa = self._generate_dmfa_declaration(year=2026, quarter='2', return_declaration=True)
        occupations = {
            int(occupation.findtext('OccupationUserReference')): occupation
            for occupation in etree.fromstring(dmfa.xml_file.content).iter('Occupation')
        }
        self.assertEqual(occupations[version_0_hours.id].findtext('MeanWorkingHours'), '0000')
        self.assertEqual(occupations[version_0_hours.id].findtext('DaysJustification'), '7')
        self.assertIsNone(occupations[self.contract.id].find('DaysJustification'))

    @freeze_time("2026-07-01 10:00:00")
    def test_remuneration_without_services(self):
        """ A remuneration paid without any service (e.g. a bonus during a full career break) is declared with its
        contributions, as they are paid on the payslip """
        calendar_0_hours = self.env['resource.calendar'].create({
            'name': "Test Calendar: no hours",
            'company_id': self.belgian_company.id,
            'hours_per_day': 0,
            'hours_per_week': 0,
            'full_time_required_hours': 38,
            'attendance_ids': [(5, 0, 0)],
        })
        version_0_hours = self.employee.create_version({
            'date_version': date(2026, 4, 1),
            'resource_calendar_id': calendar_0_hours.id,
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jun 2026',
            'employee_id': self.employee.id,
            'version_id': version_0_hours.id,
            'date_from': date(2026, 6, 1),
            'date_to': date(2026, 6, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        self.employee.write({'review_state': '1_reviewed'})
        payslip.compute_sheet()
        payslip._set_input_value('ADDITIONALGROSS', 100)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self.assertFalse(payslip._get_total_basic_wage_without_double_holiday())
        salary = payslip._get_line_values(['SALARY'])['SALARY'][payslip.id]['total']
        self.assertTrue(salary)

        dmfa = self._generate_dmfa_declaration(year=2026, quarter='2', return_declaration=True)
        worker_record = next(
            wr for wr in etree.fromstring(dmfa.xml_file.content).iter('WorkerRecord')
            if any(o.findtext('OccupationUserReference') == str(version_0_hours.id) for o in wr.iter('Occupation')))
        occupation = next(o for o in worker_record.iter('Occupation') if o.findtext('OccupationUserReference') == str(version_0_hours.id))
        self.assertFalse(occupation.findall('Service'))
        # the company car stays available without services: its benefit is due (remuneration code 10)
        car_benefit = payslip._get_line_values(['ATN.CAR'])['ATN.CAR'][payslip.id]['total']
        self.assertTrue(car_benefit)
        self.assertEqual(sum(int(r.findtext('RemunAmount')) for r in occupation.iter('Remun')
                             if r.findtext('RemunCode') != '010'), round(salary * 100))
        self.assertEqual(sum(int(r.findtext('RemunAmount')) for r in occupation.iter('Remun')
                             if r.findtext('RemunCode') == '010'), round(car_benefit * 100))
        self.assertTrue(worker_record.findall('WorkerContribution'))

        # The same bonus on a month of illness without pay (absences only, service 050)
        payslip.action_payslip_cancel()
        payslip.unlink()
        dmfa.unlink()
        illness = self.env.ref('hr_work_entry.l10n_be_work_entry_type_common_law_illness_after_legal_period')
        calendar_illness = self.calendar_38h.copy({'name': "Illness"})
        calendar_illness.attendance_ids.work_entry_type_id = illness
        version_0_hours.resource_calendar_id = calendar_illness
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jun 2026',
            'employee_id': self.employee.id,
            'version_id': version_0_hours.id,
            'date_from': date(2026, 6, 1),
            'date_to': date(2026, 6, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        payslip._set_input_value('ADDITIONALGROSS', 100)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self.assertEqual(payslip.worked_days_line_ids.work_entry_type_id, illness)
        dmfa = self._generate_dmfa_declaration(year=2026, quarter='2', return_declaration=True)
        worker_record = next(
            wr for wr in etree.fromstring(dmfa.xml_file.content).iter('WorkerRecord')
            if any(o.findtext('OccupationUserReference') == str(version_0_hours.id) for o in wr.iter('Occupation')))
        occupation = next(o for o in worker_record.iter('Occupation') if o.findtext('OccupationUserReference') == str(version_0_hours.id))
        self.assertEqual([s.findtext('ServiceCode') for s in occupation.iter('Service')], ['050'])
        self.assertTrue(occupation.findall('Remun'))
        self.assertTrue(worker_record.findall('WorkerContribution'))

    @freeze_time("2026-07-01 10:00:00")
    def test_no_hours_occupation_with_services_no_days_justification(self):
        """ A worker with services had services to perform: no days justification 7, even if the
        working schedule has no hours per week (e.g. not set on a variable schedule). Its average weekly hours are
        the ones of its services over the weeks of the occupation, at most the ones of the reference worker """
        calendar_no_hours_per_week = self.calendar_38h.copy({'name': "38h without hours per week"})
        calendar_no_hours_per_week.hours_per_week = 0
        version = self.employee.create_version({
            'date_version': date(2026, 6, 1),
            'resource_calendar_id': calendar_no_hours_per_week.id,
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jun 2026',
            'employee_id': self.employee.id,
            'version_id': version.id,
            'date_from': date(2026, 6, 1),
            'date_to': date(2026, 6, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        self.employee.write({'review_state': '1_reviewed'})
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self.assertTrue(payslip.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id.count_as == 'working_time'))

        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        occupation = next(
            o for o in etree.fromstring(dmfa.xml_file.content).iter('Occupation')
            if o.findtext('OccupationUserReference') == str(version.id))
        # 22 days of 7.6 hours in the 30 days of June: 39.01 hours a week, the 38 hours of the reference worker
        self.assertEqual(occupation.findtext('MeanWorkingHours'), '3800')
        self.assertIsNone(occupation.find('DaysJustification'))

    @freeze_time("2026-07-01 10:00:00")
    def test_no_hours_occupation_average_weekly_hours(self):
        """ Without hours per week, the average weekly hours and days of the occupation are the ones of its services
        over its weeks, as a social secretariat declares them """
        calendar_no_hours_per_week = self.calendar_38h.copy({'name': "Mondays and Tuesdays without hours per week"})
        calendar_no_hours_per_week.attendance_ids.filtered(lambda a: a.dayofweek not in ('0', '1')).unlink()
        calendar_no_hours_per_week.hours_per_week = 0
        version = self.employee.create_version({
            'date_version': date(2026, 6, 1),
            'resource_calendar_id': calendar_no_hours_per_week.id,
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jun 2026',
            'employee_id': self.employee.id,
            'version_id': version.id,
            'date_from': date(2026, 6, 1),
            'date_to': date(2026, 6, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        self.employee.write({'review_state': '1_reviewed'})
        payslip.compute_sheet()
        payslip.action_payslip_done()

        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        occupation = next(
            o for o in etree.fromstring(dmfa.xml_file.content).iter('Occupation')
            if o.findtext('OccupationUserReference') == str(version.id))
        # 10 Mondays and Tuesdays of 7.6 hours in the 30 days of June: 76 / (30 / 7) = 17.73 hours, 2.33 days a week
        self.assertEqual(occupation.findtext('MeanWorkingHours'), '1773')
        self.assertEqual(occupation.findtext('WorkingDaysSystem'), '233')
        # below the reference hours: part time
        self.assertEqual(occupation.findtext('ContractType'), '1')

    @freeze_time("2026-07-01 10:00:00")
    def test_no_hours_occupation_full_time(self):
        """ Without hours per week, an occupation whose average weekly hours reach the reference worker's is a full
        time one """
        calendar_no_hours_per_week = self.calendar_38h.copy({'name': "Full weeks without hours per week"})
        calendar_no_hours_per_week.hours_per_week = 0
        version = self.employee.create_version({
            'date_version': date(2026, 6, 1),
            'resource_calendar_id': calendar_no_hours_per_week.id,
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jun 2026',
            'employee_id': self.employee.id,
            'version_id': version.id,
            'date_from': date(2026, 6, 1),
            'date_to': date(2026, 6, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        self.employee.write({'review_state': '1_reviewed'})
        payslip.compute_sheet()
        payslip.action_payslip_done()

        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        occupation = next(
            o for o in etree.fromstring(dmfa.xml_file.content).iter('Occupation')
            if o.findtext('OccupationUserReference') == str(version.id))
        # 22 days of 7.6 hours in the 30 days of June: more than 38 hours a week, the reference ones
        self.assertEqual(occupation.findtext('MeanWorkingHours'), '3800')
        self.assertEqual(occupation.findtext('ContractType'), '0')

    @freeze_time("2026-07-01 10:00:00")
    def test_variable_schedule_without_cycle_occupation(self):
        """ A variable schedule without cycle (days planned one by one) declares the days declared over the weeks of
        the quarter as days a week, whatever the days of its calendar, on an occupation line of the quarter """
        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        calendar_variable = self.env['resource.calendar'].create({
            'name': "Planned day by day",
            'company_id': self.belgian_company.id,
            'calendar_type': 'variable',
            'hours_per_week': 15.2,
            'days_per_week': 2,
            'reference_calendar_id': self.calendar_38h.id,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'date': date(2026, 6, day), 'hour_from': hour_from, 'hour_to': hour_to,
                        'work_entry_type_id': attendance.id})
                for day in (1, 8, 15, 22, 29) for hour_from, hour_to in ((8, 12), (13, 16.6))
            ],
        })
        version = self.employee.create_version({
            'date_version': date(2026, 3, 1),
            'resource_calendar_id': calendar_variable.id,
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jun 2026',
            'employee_id': self.employee.id,
            'version_id': version.id,
            'date_from': date(2026, 6, 1),
            'date_to': date(2026, 6, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        self.employee.write({'review_state': '1_reviewed'})
        payslip.compute_sheet()
        payslip.action_payslip_done()

        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        occupation = next(
            o for o in etree.fromstring(dmfa.xml_file.content).iter('Occupation')
            if o.findtext('OccupationUserReference') == str(version.id))
        self.assertEqual(occupation.findtext('OccupationStartingDate'), '2026-04-01')
        self.assertEqual(occupation.findtext('OccupationEndingDate'), '2026-06-30')
        # the 5 Mondays of June over the 13 weeks of the quarter
        self.assertEqual(occupation.findtext('WorkingDaysSystem'), '038')

    def test_time_credit_variable_schedule_without_cycle_occupation(self):
        """ A time credit (reorganisation measure 4) on a schedule planned day by day is a variable schedule without
        cycle too: its occupation line runs over the quarter, its days a week the days declared over its weeks """
        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        time_credit = self.env.ref('hr_work_entry.l10n_be_work_entry_type_credit_time')
        calendar_variable = self.env['resource.calendar'].create({
            'name': "Time credit planned day by day",
            'company_id': self.belgian_company.id,
            'calendar_type': 'variable',
            'hours_per_week': 15.2,
            'days_per_week': 2,
            'reference_calendar_id': self.calendar_38h.id,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'date': date(2026, 6, day), 'hour_from': hour_from, 'hour_to': hour_to,
                        'work_entry_type_id': attendance.id})
                for day in (1, 8, 15, 22, 29) for hour_from, hour_to in ((8, 12), (13, 16.6))
            ] + [
                (0, 0, {'date': date(2026, 6, 2), 'hour_from': 8, 'hour_to': 12, 'work_entry_type_id': time_credit.id}),
            ],
        })
        version = self.employee.create_version({
            'date_version': date(2026, 3, 1),
            'resource_calendar_id': calendar_variable.id,
        })
        self.assertTrue(version.l10n_be_time_credit)
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jun 2026',
            'employee_id': self.employee.id,
            'version_id': version.id,
            'date_from': date(2026, 6, 1),
            'date_to': date(2026, 6, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        self.employee.write({'review_state': '1_reviewed'})
        payslip.compute_sheet()
        payslip.action_payslip_done()

        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        occupation = next(
            o for o in etree.fromstring(dmfa.xml_file.content).iter('Occupation')
            if o.findtext('OccupationUserReference') == str(version.id))
        self.assertEqual(occupation.findtext('ReorganisationMeasure'), '4')
        self.assertEqual(occupation.findtext('MeanWorkingHours'), '1520')
        self.assertEqual(occupation.findtext('OccupationStartingDate'), '2026-04-01')
        self.assertEqual(occupation.findtext('OccupationEndingDate'), '2026-06-30')
        # the 5 Mondays of June over the 13 weeks of the quarter
        self.assertEqual(occupation.findtext('WorkingDaysSystem'), '038')

    def test_partial_resumption_after_illness_reference_worker(self):
        """ A partial resumption of work after an illness (reorganisation measure 5) declares the hours a week and the
        days a week of the reference worker, here 40 hours on 4 days, not 38 hours on 5 days """
        partial_incapacity = self.env.ref('hr_work_entry.l10n_be_work_entry_type_partial_incapacity')
        calendar = self.calendar_4_days_36_hours.copy({'name': "Partial resumption, Thursday off"})
        calendar.attendance_ids.filtered(lambda a: a.dayofweek == '3').work_entry_type_id = partial_incapacity
        calendar.reference_calendar_id = self.calendar_4_days_36_hours
        version = self.employee.create_version({
            'date_version': date(2026, 3, 1),
            'resource_calendar_id': calendar.id,
        })
        self.assertTrue(version.l10n_be_time_credit)
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jun 2026',
            'employee_id': self.employee.id,
            'version_id': version.id,
            'date_from': date(2026, 6, 1),
            'date_to': date(2026, 6, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        })
        self.employee.write({'review_state': '1_reviewed'})
        payslip.compute_sheet()
        payslip.action_payslip_done()

        dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
        occupation = next(
            o for o in etree.fromstring(dmfa.xml_file.content).iter('Occupation')
            if o.findtext('OccupationUserReference') == str(version.id))
        self.assertEqual(occupation.findtext('ReorganisationMeasure'), '5')
        # the hours a week of the reference worker (S): its calendar's 40 hours a week (4 days of 10 hours)
        self.assertEqual(occupation.findtext('RefMeanWorkingHours'), '4000')
        self.assertEqual(occupation.findtext('MeanWorkingHours'), '4000')
        self.assertEqual(occupation.findtext('WorkingDaysSystem'), '400')

    def test_additional_hours_days_of_a_part_time_worker(self):
        """ A part-time worker's additional hours (not recovered) worked on a day of normal services add no day; on a
        day off its schedule (a Saturday), they are a day of the code 1 of their own, whatever their hours, out of the
        days a week, with the days justification 5 """
        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        additional_hours = self.env.ref('hr_work_entry.be_work_entry_type_additional_hours')
        calendar_variable = self.env['resource.calendar'].create({
            'name': "Planned day by day",
            'company_id': self.belgian_company.id,
            'calendar_type': 'variable',
            'hours_per_week': 15.2,
            'days_per_week': 2,
            'reference_calendar_id': self.calendar_38h.id,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'date': date(2026, 6, day), 'hour_from': hour_from, 'hour_to': hour_to,
                        'work_entry_type_id': attendance.id})
                for day in (1, 8, 15, 22, 29) for hour_from, hour_to in ((8, 12), (13, 16.6))
            ] + [
                # an additional hour on a Monday of normal services
                (0, 0, {'date': date(2026, 6, 8), 'hour_from': 16.6, 'hour_to': 17.6,
                        'work_entry_type_id': additional_hours.id}),
            ],
        })
        version = self.employee.create_version({
            'date_version': date(2026, 3, 1),
            'resource_calendar_id': calendar_variable.id,
        })
        self.employee.write({'review_state': '1_reviewed'})

        def declare():
            payslip = self.env['hr.payslip'].create({
                'name': 'Payslip Jun 2026',
                'employee_id': self.employee.id,
                'version_id': version.id,
                'date_from': date(2026, 6, 1),
                'date_to': date(2026, 6, 30),
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
                'company_id': self.belgian_company.id,
            })
            payslip.compute_sheet()
            payslip.action_payslip_done()
            dmfa = self._generate_dmfa_declaration(year='2026', quarter='2', return_declaration=True)
            occupation = next(
                o for o in etree.fromstring(dmfa.xml_file.content).iter('Occupation')
                if o.findtext('OccupationUserReference') == str(version.id))
            services = {
                s.findtext('ServiceCode'): (int(s.findtext('ServiceNbrDays')) / 100, int(s.findtext('ServiceNbrHours')) / 100)
                for s in occupation.iter('Service')}
            return payslip, dmfa, occupation, services

        payslip, dmfa, occupation, services = declare()
        self.assertEqual(services, {'001': (5.0, 39.0)})
        self.assertEqual(occupation.findtext('WorkingDaysSystem'), '038')
        self.assertIsNone(occupation.find('DaysJustification'))

        payslip.action_payslip_cancel()
        payslip.unlink()
        dmfa.unlink()
        # 2 additional hours on a Saturday off its schedule
        calendar_variable.attendance_ids = [(0, 0, {
            'date': date(2026, 6, 6), 'hour_from': 9, 'hour_to': 11, 'work_entry_type_id': additional_hours.id})]
        occupation, services = declare()[2:]
        self.assertEqual(services, {'001': (6.0, 41.0)})
        # still the 5 Mondays of June over the 13 weeks of the quarter
        self.assertEqual(occupation.findtext('WorkingDaysSystem'), '038')
        self.assertEqual(occupation.findtext('DaysJustification'), '5')

    def test_bik_remuneration_code_without_working_days(self):

        def create_payslips_first_quarter():
            months = [(1, 31), (2, 28), (3, 31)]
            payslips = []
            for m, d in months:
                payslip = self.env['hr.payslip'].create({
                    'name': f'Payslip {datetime(2026, m, 1):%b %Y}',
                    'version_id': self.employee.version_id.id,
                    'date_from': datetime(2026, m, 1),
                    'date_to': datetime(2026, m, d),
                    'employee_id': self.employee.id,
                    'struct_id': struct.id,
                    'company_id': self.belgian_company.id,
                })
                payslip.compute_sheet()
                payslip.action_payslip_done()
                payslips.append(payslip)
            return payslips

        def get_bik_amount(payslip):
            bik_total = abs(payslip.line_ids.filtered(lambda line: line.code == 'ATN_DED').total)
            bik_car_total = abs(payslip.line_ids.filtered(lambda line: line.code == 'ATN.CAR').total)
            return bik_total - bik_car_total

        def get_remunerations(dmfa_dict):
            remunerations = (dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']['Remun'])
            return {
                remuneration['RemunCode']: int(remuneration['RemunAmount']) / 100
                for remuneration in remunerations
            }

        struct = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        employee_wage = self.employee.version_id.wage

        # Part 1: Without any absences
        payslips = create_payslips_first_quarter()
        dmfa = self._generate_dmfa_declaration(year='2026', quarter='1', return_declaration=True)
        remunerations = get_remunerations(xml_str_to_dict(dmfa.xml_file.content))

        bik_amount = 0
        for payslip in payslips:
            bik_amount += get_bik_amount(payslip)

        self.assertAlmostEqual(remunerations['001'], employee_wage * 3 + bik_amount, places=2)
        self.assertNotIn('002', remunerations)

        # Part 2: Sick Leave in January - March
        for slip in payslips:
            slip.action_payslip_cancel()
            slip.unlink()
        dmfa.unlink()

        sick_work_entry_type = self.env.ref('hr_work_entry.be_work_entry_type_sick_leave')
        self.env["hr.leave"].create({
            "name": "Long sick leave",
            "employee_id": self.employee.id,
            'work_entry_type_id': sick_work_entry_type.id,
            "request_date_from": date(2026, 1, 1),
            "request_date_to": date(2026, 3, 31),
        })
        payslips = create_payslips_first_quarter()
        dmfa_dict = self._generate_dmfa_declaration(year='2026', quarter='1')
        remunerations = get_remunerations(dmfa_dict)

        self.assertAlmostEqual(remunerations['001'], employee_wage, places=2)   # Only first 30 days of sick leave are paid
        self.assertAlmostEqual(remunerations['002'], bik_amount, places=2)

    @freeze_time("2026-07-01 10:00:00")
    def test_starterjob_reduction_dmfa(self):
        # Compensate the loss on commission on PTO with the double holiday pay (SIMPLE_VARIABLE) instead of monthly (COM_LOSS_PTO)
        self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_double_holiday').active = True

        starterjob_employee, regular_employee, lower_wage_employee = self.env['hr.employee'].create([{
            'name': 'StarterJob Employee',
            'company_id': self.belgian_company.id,
            'country_id': self.env.ref('base.be').id,
            'address_id': self.partner_wallonia.id,
            'niss': '07020118374',
            'birthday': datetime(2007, 2, 1),
            'contract_date_start': datetime(2025, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'work_contact_id': self.work_contact.id,
            'wage': 2500,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'l10n_be_is_starterjob': True,
            'lang': 'fr_BE',
        }, {
            'name': 'Regular Employee',
            'company_id': self.belgian_company.id,
            'country_id': self.env.ref('base.be').id,
            'address_id': self.partner_wallonia.id,
            'niss': '07020118572',
            'birthday': datetime(2007, 2, 1),
            'contract_date_start': datetime(2025, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'work_contact_id': self.work_contact.id,
            'wage': 2500,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        }, {
            'name': 'Lowerwage Employee',
            'company_id': self.belgian_company.id,
            'country_id': self.env.ref('base.be').id,
            'address_id': self.partner_wallonia.id,
            'niss': '07020118473',
            'birthday': datetime(2007, 2, 1),
            'contract_date_start': datetime(2025, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'work_contact_id': self.work_contact.id,
            'wage': 2200,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        }])

        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Feb 2026 - StarterJob Employee',
            'version_id': starterjob_employee.version_id.id,
            'date_from': datetime(2026, 2, 1),
            'date_to': datetime(2026, 2, 28),
            'employee_id': starterjob_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Jun 2026 - StarterJob Employee',
            'version_id': starterjob_employee.version_id.id,
            'date_from': datetime(2026, 6, 1),
            'date_to': datetime(2026, 6, 30),
            'employee_id': starterjob_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Jun 2026 - StarterJob Employee - Double Holiday',
            'version_id': starterjob_employee.version_id.id,
            'date_from': datetime(2026, 6, 1),
            'date_to': datetime(2026, 6, 30),
            'employee_id': starterjob_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2026 - Regular Employee',
            'version_id': regular_employee.version_id.id,
            'date_from': datetime(2026, 2, 1),
            'date_to': datetime(2026, 2, 28),
            'employee_id': regular_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Jun 2026 - Regular Employee',
            'version_id': regular_employee.version_id.id,
            'date_from': datetime(2026, 6, 1),
            'date_to': datetime(2026, 6, 30),
            'employee_id': regular_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Jun 2026 - Regular Employee - Double Holiday',
            'version_id': regular_employee.version_id.id,
            'date_from': datetime(2026, 6, 1),
            'date_to': datetime(2026, 6, 30),
            'employee_id': regular_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2026 - Lower wage Employee',
            'version_id': lower_wage_employee.version_id.id,
            'date_from': datetime(2026, 2, 1),
            'date_to': datetime(2026, 2, 28),
            'employee_id': lower_wage_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Jun 2026 - Lower wage Employee',
            'version_id': lower_wage_employee.version_id.id,
            'date_from': datetime(2026, 6, 1),
            'date_to': datetime(2026, 6, 30),
            'employee_id': lower_wage_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Jun 2026 - Lower wage Employee - Double Holiday',
            'version_id': lower_wage_employee.version_id.id,
            'date_from': datetime(2026, 6, 1),
            'date_to': datetime(2026, 6, 30),
            'employee_id': lower_wage_employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'company_id': self.belgian_company.id,
        }])

        payslips.compute_sheet()
        payslips.action_payslip_done()
        regular_payslip = payslips.filtered(lambda p: p.employee_id == regular_employee)
        lower_wage_payslip = payslips.filtered(lambda p: p.employee_id == lower_wage_employee)
        starterjob_payslip = payslips - regular_payslip - lower_wage_payslip
        # This employee is 19 yo so with his starterjob status he will be pay 88% of his wage (2500 * 88% =) 2200
        self.assertAlmostEqual(regular_payslip[0].line_ids.filtered(lambda l: l.code == 'NET').total - lower_wage_payslip[0].line_ids.filtered(lambda l: l.code == 'NET').total, 64.03, 2, "should be equal to the COMPSUPP's value of the starterjob's payslip")
        self._validate_payslip(starterjob_payslip[0])

        self.assertAlmostEqual(regular_payslip[1].line_ids.filtered(lambda l: l.code == 'NET').total - lower_wage_payslip[1].line_ids.filtered(lambda l: l.code == 'NET').total, 51.6, 2, "should be equal to the COMPSUPP's value of the starterjob's payslip")
        self._validate_payslip(starterjob_payslip[1])

        # This employee is 19 yo so with his starterjob status he will be pay 88% of his Double holiday Pay DH_BASIC (= (DOUBLE + DOUBLE_COMPLEMENTARY) * 88%)
        self.assertAlmostEqual(regular_payslip[2].line_ids.filtered(lambda l: l.code == 'NET').total - lower_wage_payslip[2].line_ids.filtered(lambda l: l.code == 'NET').total, 105.44, 2, "should be equal to the COMPSUPP's value of the starterjob's payslip")
        self._validate_payslip(starterjob_payslip[2])

        dmfa = self._generate_dmfa_declaration(year=2026, quarter='2', return_declaration=True)
        dmfa_dict = xml_str_to_dict(dmfa.xml_file.content)
        # Testing the reduction on the dmfa itself for the starterjob's employee
        employee_occupation = dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson'][0]['WorkerRecord']['Occupation']
        employment_promotion = employee_occupation['EmploymentPromotion']
        career_measure = employee_occupation['OccupationInformations']['CareerMeasure']
        self.assertEqual(employment_promotion, '10')
        self.assertEqual(career_measure, '2')

    @freeze_time("2026-04-10 10:00:00")
    def test_13_declaration_warrants(self):
        warrant_structure = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_warrant')
        regular_structure = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')

        self.contract.generate_work_entries(date(2026, 1, 1), date(2026, 1, 31))

        payslips = self.env['hr.payslip'].create([{
            'name': 'Regular Payslip',
            'version_id': self.contract.id,
            'date_from': datetime(2026, 1, 1),
            'date_to': datetime(2026, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': regular_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Warrant Without ONSS',
            'version_id': self.contract.id,
            'date_from': datetime(2026, 1, 1),
            'date_to': datetime(2026, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': warrant_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Warrant With ONSS',
            'version_id': self.contract.id,
            'date_from': datetime(2026, 1, 1),
            'date_to': datetime(2026, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': warrant_structure.id,
            'company_id': self.belgian_company.id,
        }])

        payslips[1]._set_input_value('WARRANT_WITHOUT_ONSS', 10000.00)
        payslips[2]._set_input_value('WARRANT_WITH_ONSS', 5000.00)

        self.employee.write({'review_state': '1_reviewed'})

        for payslip in payslips:
            payslip.compute_sheet()
            payslip.action_payslip_done()

        dmfa_dict = self._generate_dmfa_declaration(year='2026', quarter='1')

        self._assertDMFAEqual(dmfa_dict)

    @freeze_time("2026-04-10 10:00:00")
    def test_intellectual_property_remuneration_codes(self):
        # Since 2026, the intellectual property exempt from ONSS (within 30 % of the total
        # remuneration) is declared under the remuneration code 47 and excluded from the code 1
        self.contract.write({'ip_wage_rate': 0.25, 'ip_onss': False})  # 750 € on a 3000 € wage, exempt from ONSS
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip %s 2026' % date_from.strftime('%B'),
            'version_id': self.contract.id,
            'date_from': date_from,
            'date_to': date_from + relativedelta(months=1, days=-1),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.belgian_company.id,
        } for date_from in (date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1))])
        self.employee.write({'review_state': '1_reviewed'})
        for payslip in payslips:  # No batch compute and validate for ONSS regularization
            payslip.compute_sheet()
            payslip.action_payslip_done()
        line_values = payslips._get_line_values(['SALARY', 'IP.EXEMPT', 'IP'], compute_sum=True)
        self.assertAlmostEqual(line_values['IP.EXEMPT']['sum']['total'], -2250, 2)
        self.assertAlmostEqual(line_values['IP']['sum']['total'], 2250, 2)

        dmfa_dict = self._generate_dmfa_declaration(year='2026', quarter='1')
        natural_person = dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']
        if isinstance(natural_person, list):
            natural_person = next(p for p in natural_person if p['NaturalPersonUserReference'] == str(self.employee.id))
        remunerations = natural_person['WorkerRecord']['Occupation']['Remun']
        if isinstance(remunerations, dict):
            remunerations = [remunerations]
        amounts_by_code = {remun['RemunCode']: int(remun['RemunAmount']) for remun in remunerations}
        self.assertEqual(amounts_by_code['047'], 225000)  # in cents
        self.assertEqual(amounts_by_code['001'], round(line_values['SALARY']['sum']['total'] * 100))

    def test_ded3000_while_computing_payslips(self):
        """
        Make sure that ONSS_STRUCTURAL (ded3000) is correctly computed while computing payslips
        using the localdict instead of the payslip lines (not yet populated),
        and that the value is the same in DMFA declaration.
        """
        date_from = date(2025, 1, 1)
        date_to = date(2025, 1, 31)
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jan 2025',
            'employee_id': self.employee.id,
            'version_id': self.employee.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': date_from,
            'date_to': date_to,
            'company_id': self.belgian_company.id,
        })
        self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'request_date_from': date(2025, 1, 6),
            'request_date_to': date(2025, 1, 10),
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        })
        payslip.compute_sheet()
        self.assertEqual(payslip.state, 'draft')
        ded3000_draft = - sum(payslip.line_ids.filtered(lambda line: line.code == 'ONSS_STRUCTURAL').mapped('total'))
        ded3000_draft_recomputed = self._get_ded3000(self.employee, payslip)
        self.assertIn(ded3000_draft, ded3000_draft_recomputed.values())

        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')
        ded3000_validated = self._get_ded3000(self.employee, payslip)
        self.assertIn(ded3000_draft, ded3000_validated.values())

        dmfa = self._generate_dmfa_declaration(year=2025, quarter='1')
        occupations = dmfa['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']
        occupations = [occupations] if isinstance(occupations, dict) else occupations
        ded3000_dmfa = []
        for occupation in occupations:
            deductions = occupation.get('OccupationDeduction', [])
            deductions = [deductions] if isinstance(deductions, dict) else deductions
            ded3000_dmfa.extend([int(d.get('DeductionAmount')) / 100.0 for d in deductions if d.get('DeductionCode') == '3000'])
        self.assertIn(ded3000_draft, ded3000_dmfa)

    def _validate_dmfa_structural_deduction(self, year, quarter, payslips):
        """
        Helper to verify that Structural Deduction (code 3000) in DMFA XML report matches the amount from payslips.
        """
        dmfa_dict = self._generate_dmfa_declaration(year=str(year), quarter=str(quarter))
        natural_persons = dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']
        if isinstance(natural_persons, dict):
            natural_persons = [natural_persons]

        dmfa_amount = 0
        for natural_person in natural_persons:
            worker_record = natural_person.get('WorkerRecord', {})
            occupations = worker_record.get('Occupation', [])
            if isinstance(occupations, dict):
                occupations = [occupations]

            for occ in occupations:
                deductions = occ.get('OccupationDeduction', [])
                if isinstance(deductions, dict):
                    deductions = [deductions]

                for ded in deductions:
                    if ded.get('DeductionCode') == '3000':
                        dmfa_amount += int(ded.get('DeductionAmount', 0)) / 100.0

        prev_line_values = payslips._get_line_values(['ONSS_STRUCTURAL'], compute_sum=True)
        payslip_deduction = abs(prev_line_values['ONSS_STRUCTURAL']['sum']['total'])
        self.assertAlmostEqual(
            dmfa_amount,
            payslip_deduction, 2,
            f"DMFA structural deduction ({dmfa_amount} euros) does not match expected ({payslip_deduction} euros from payslips)."
        )

    @freeze_time("2025-04-10 10:00:00")
    def test_regular_first_quarter(self):
        """
        Normal Q1 payslips with regularization.
        """
        payslips = self.env['hr.payslip'].create([{
            'version_id': self.contract.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'version_id': self.contract.id,
            'date_from': date(2025, 2, 1),
            'date_to': date(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'version_id': self.contract.id,
            'date_from': date(2025, 3, 1),
            'date_to': date(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }])

        # Need to compute and validate in order to ensure that the payslip lines are available
        for slip in payslips:
            slip.compute_sheet()
            slip.action_payslip_done()

        self._validate_payslip(payslips[0])

        self._validate_payslip(payslips[1])

        self._validate_payslip(payslips[2])

        self._validate_dmfa_structural_deduction(year=2025, quarter=1, payslips=payslips)

    @freeze_time("2025-04-10 10:00:00")
    def test_contract_end_in_february(self):
        """
        Employee contract end in February, structural deduction should be applied in February payslip.
        """
        self.employee.departure_date = date(2025, 2, 15)
        self.contract.date_end = date(2025, 2, 15)

        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 2, 1),
            'date_to': date(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
        }])

        payslips[0].compute_sheet()
        payslips[0].action_payslip_done()
        self._validate_payslip(payslips[0])

        # February payslip should be prorated since the contract ended partway through the month
        payslips[1].compute_sheet()
        payslips[1].action_payslip_done()
        self._validate_payslip(payslips[1])

        self._validate_dmfa_structural_deduction(year=2025, quarter=1, payslips=payslips)

    @freeze_time("2025-12-31 10:00:00")
    def test_13th_month_regularization(self):
        """
        Test 13th month payslip in December adds remunerations without worked hours, so the total remunerations for the quarter
        are higher, so the structural deduction should be adjusted to be lower.
        """
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Oct 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 10, 1),
            'date_to': date(2025, 10, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Nov 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 11, 1),
            'date_to': date(2025, 11, 30),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Dec 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 12, 1),
            'date_to': date(2025, 12, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'name': '13th Month 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 12, 1),
            'date_to': date(2025, 12, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_thirteen_month_structure.id,
        }])

        for slip in payslips:
            slip.compute_sheet()
            slip.action_payslip_done()

        self._validate_payslip(payslips[3])

        self._validate_dmfa_structural_deduction(year=2025, quarter=4, payslips=payslips)

    @freeze_time("2025-04-10 10:00:00")
    def test_refund_and_correct_paid_payslip(self):
        """
        Test the scenario where a payslip is paid, refunded, and then corrected with a new payslip.
        The structural deduction on the payslips should reflect the changes in the refund and correction payslips
        when computing the deduction.
        """
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 2, 1),
            'date_to': date(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Mar 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 3, 1),
            'date_to': date(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }])

        for slip in payslips:
            slip.compute_sheet()
            slip.action_payslip_done()
            slip.action_payslip_paid()

        original_march_slip = payslips[2]
        refund_slip = original_march_slip._action_refund_payslips()
        correction_slip = original_march_slip._action_correct_payslips()

        correction_slip._set_input_value('COMMISSION', 1000)
        correction_slip.compute_sheet()
        correction_slip.action_payslip_done()

        # The net structural reduction for Q1 should equal the sum across all slips:
        # Jan + Feb + Original Mar (Paid) + Refund Mar (Negative) + Correction Mar
        # Because Original + Refund = 0, the sum is effectively Jan + Feb + Correction Mar.
        all_q1_payslips = payslips | refund_slip | correction_slip

        self._validate_payslip(original_march_slip)
        self._validate_payslip(refund_slip)
        self._validate_payslip(correction_slip)

        self._validate_dmfa_structural_deduction(year=2025, quarter=1, payslips=all_q1_payslips)

    @freeze_time("2025-04-10 10:00:00")
    def test_no_remuneration(self):
        """
        In a quarter where an employee has no remunerations, the structural deduction should not
        apply the BiKs and the structural deduction should be 0.
        """
        self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'request_date_from': date(2025, 1, 1),
            'request_date_to': date(2025, 3, 31),
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        })

        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 2, 1),
            'date_to': date(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Mar 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 3, 1),
            'date_to': date(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }])

        payslips.compute_sheet()
        payslips.action_payslip_done()

        structural_deduction_lines = payslips.line_ids.filtered(lambda line: line.code == "ONSS_STRUCTURAL")
        for line in structural_deduction_lines:
            self.assertEqual(0.0, line.total, f"Payslip {line.slip_id.name} has a non zero structural deduction for a quarter with no remunerations.")

        self._validate_dmfa_structural_deduction(year=2025, quarter=1, payslips=payslips)

    @freeze_time("2025-04-10 10:00:00")
    def test_contract_change_to_part_time(self):
        """
        Test employee changing from full-time to part time in the middle of a quarter.
        Since this creates a new occupation, the structural deduction should be computed as the sum of structural deductions
        for each occupation.
        """
        self.contract.date_end = date(2025, 2, 28)

        calendar_19h = self.env['resource.calendar'].create({
            'name': '19h Part Time',
            'company_id': self.belgian_company.id,
            'hours_per_day': 3.8,
            'full_time_required_hours': 38.0,
            'is_fulltime': False,
            'attendance_ids': [(0, 0, {
                'dayofweek': str(i),
                'hour_from': 8.0,
                'hour_to': 11.8,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id
            }) for i in range(5)]
        })

        part_time_contract = self.employee.create_version({
            'name': 'Part Time Contract',
            'date_start': date(2025, 3, 1),
            'date_version': date(2025, 3, 1),
            'date_end': False,
            'wage': 1500,
            'resource_calendar_id': calendar_19h.id,
            'reference_calendar_id': self.calendar_38h.id,
        })

        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025 (Full-Time)',
            'version_id': self.contract.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025 (Full-Time)',
            'version_id': self.contract.id,
            'date_from': date(2025, 2, 1),
            'date_to': date(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Mar 2025 (Part-Time)',
            'version_id': part_time_contract.id,
            'date_from': date(2025, 3, 1),
            'date_to': date(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }])

        for payslip in payslips:
            payslip.compute_sheet()
            payslip.action_payslip_done()

        self._validate_payslip(payslips[2])

        self._validate_dmfa_structural_deduction(year=2025, quarter=1, payslips=payslips)

    @freeze_time("2025-04-10 10:00:00")
    def test_full_time_schedule_change_other_reference(self):
        """
        Full-time employee moving in the middle of the quarter to another full-time schedule (38h on other weekdays)
        that is its own reference calendar. Same work time rate, so both versions are one occupation, with two
        reference calendars of the same weekly hours: the structural deduction is computed with U = 38.
        """
        calendar_38h_tue_sat = self.env['resource.calendar'].create({
            'name': '38h Tuesday-Saturday',
            'company_id': self.belgian_company.id,
            'hours_per_day': 7.6,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'dayofweek': str(i), 'hour_from': hour_from, 'hour_to': hour_to})
                for i in range(1, 6)
                for hour_from, hour_to in [(8, 12), (13, 16.6)]
            ],
        })
        calendar_38h_tue_sat.reference_calendar_id = calendar_38h_tue_sat
        tue_sat_version = self.employee.create_version({
            'date_version': date(2025, 2, 1),
            'resource_calendar_id': calendar_38h_tue_sat.id,
        })
        self.assertEqual(len(self.employee.version_ids.sorted('date_start', reverse=True)._get_occupation_dates()), 1)

        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip {month}/2025',
            'version_id': (self.contract if month == 1 else tue_sat_version).id,
            'date_from': date(2025, month, 1),
            'date_to': date(2025, month, 1) + relativedelta(day=31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        } for month in (1, 2, 3)])
        for slip in payslips:
            slip.compute_sheet()
            slip.action_payslip_done()

        self.assertEqual(payslips.mapped('state'), ['validated'] * 3)
        quarter_deduction = payslips._get_line_values(['ONSS_STRUCTURAL'], compute_sum=True)['ONSS_STRUCTURAL']['sum']['total']
        # U = 38, W = 3 x 3,009, H = 64 days x 7.6h = 486.4 (as many days as Monday-Friday in the quarter),
        # S = 9,027 x round(13 x 38 / 486.4, 2) = 9,207.54, R = 0.14 x (11,013.62 - 9,207.54), mu x beta = 1
        self.assertAlmostEqual(quarter_deduction, -252.85, 2)

        self._validate_dmfa_structural_deduction(year=2025, quarter=1, payslips=payslips)

    @freeze_time("2026-04-10 10:00:00")
    def test_full_time_counted_in_days(self):
        """
        A full-time occupation is declared in days only: its reference wage is S = W x 13 x D / J, whatever the hours of
        its days. A 38-hour week of 8-hour days with a 6-hour Wednesday works 488 hours over the 64 days of the first
        quarter of 2026: 13 x 38 / 488 = 1.01, while 13 x 5 / 64 = 1.02.
        """
        calendar_38h_short_wednesday = self.env['resource.calendar'].create({
            'name': '38h, short Wednesday',
            'company_id': self.belgian_company.id,
            'hours_per_day': 7.6,
            'full_time_required_hours': 38.0,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'dayofweek': str(i), 'hour_from': hour_from, 'hour_to': hour_to})
                for i in range(5)
                for hour_from, hour_to in ([(8, 12), (13, 15)] if i == 2 else [(8, 12), (13, 17)])
            ],
        })
        calendar_38h_short_wednesday.reference_calendar_id = self.calendar_38h
        version = self.employee.create_version({
            'date_version': date(2026, 1, 1),
            'resource_calendar_id': calendar_38h_short_wednesday.id,
        })
        self.assertEqual(version.work_time_rate, 1.0)

        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip {month}/2026',
            'version_id': version.id,
            'date_from': date(2026, month, 1),
            'date_to': date(2026, month, 1) + relativedelta(day=31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        } for month in (1, 2, 3)])
        for slip in payslips:
            slip.compute_sheet()
            slip.action_payslip_done()

        self.assertEqual(sum(payslips.worked_days_line_ids.mapped('number_of_hours')), 488)
        quarter_deduction = payslips._get_line_values(['ONSS_STRUCTURAL'], compute_sum=True)['ONSS_STRUCTURAL']['sum']['total']
        # W = 3 x 3,009, S = 9,027 x round(13 x 5 / 64, 2) = 9,207.54 (with the hours: 9,027 x 1.01 = 9,117.27),
        # R = 0.14 x (11,458.57 - 9,207.54) + 0.15 x (9,547.20 - 9,207.54) = 315.1442 + 50.949, truncated as a whole
        # (366.08 with each part truncated), mu x beta = 1
        self.assertAlmostEqual(quarter_deduction, -366.09, 2)

        self._validate_dmfa_structural_deduction(year=2026, quarter=1, payslips=payslips)

    @freeze_time("2025-04-10 10:00:00")
    def test_out_of_order_validation(self):
        """
        Q1 payslips computed in reverse order (i.e. March -> February -> January). February and March should add
        the adjustment/correction deduction amounts.
        """
        payslips = self.env['hr.payslip'].create([{
            'name': 'Payslip Jan 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Feb 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 2, 1),
            'date_to': date(2025, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }, {
            'name': 'Payslip Mar 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 3, 1),
            'date_to': date(2025, 3, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }])

        # Compute and validate in reverse order
        for slip in payslips[::-1]:
            slip.compute_sheet()
            slip.action_payslip_done()

        for slip in payslips:
            self.assertTrue(slip.line_ids.filtered(lambda l: l.code == 'ONSS_STRUCTURAL'),
                             f"Structural deduction should be applied in {slip.name} since there should be a correction.")

        # March
        self._validate_payslip(payslips[2])

        # February
        self._validate_payslip(payslips[1])

        # January
        self._validate_payslip(payslips[0])

        self._validate_dmfa_structural_deduction(year=2025, quarter=1, payslips=payslips)

    def test_batch_correction(self):
        """
        Test payrun with all payslips of the quarter computed at the same time using the correction wizard.
        All new payslips in the batch will initially be in draft so they will be filtered out when
        searching for validated payslips, but they should be included in the computation.
        """
        # Create original payslips in the "paid_state" so they can be corrected
        past_date = fields.Datetime.now() - timedelta(days=5)  # need this to trigger the "has_wrong_data" field
        base_slip_vals = {
            'version_id': self.contract.id,
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        }

        payslips = self.env['hr.payslip'].create([{
            **base_slip_vals,
            'name': 'Payslip Jan 2025',
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
        }, {
            **base_slip_vals,
            'name': 'Payslip Feb 2025',
            'date_from': date(2025, 2, 1),
            'date_to': date(2025, 2, 28),
        }, {
            **base_slip_vals,
            'name': 'Payslip Mar 2025',
            'date_from': date(2025, 3, 1),
            'date_to': date(2025, 3, 31),
        }, {
            **base_slip_vals,
            'name': 'Payslip Mar 2025',
            'date_from': date(2025, 4, 1),
            'date_to': date(2025, 4, 30),  # including April payslip to check that the rule does not use payslips in the batch outside the quarter
        }])

        payslips.compute_sheet()
        payslips.action_payslip_done()
        payslips.action_payslip_paid()

        payslips.write({
            'done_date': past_date,
        })

        self.contract.last_modified_date = fields.Datetime.now()
        wizard = self.env['hr.payslip.correction.wizard'].create({
            'employee_ids': [Command.set([self.employee.id])],
            'payslip_ids': [Command.set([payslips[0].id])],
            'correction_choice': 'multi',
        })
        self.assertEqual(len(wizard.allowed_payslip_ids), 4, "Wizard should find all 4 payslips that should be corrected.")

        result_action = wizard.action_correct_payslips()
        all_correction_wizard_slips = self.env['hr.payslip'].search(result_action['domain'])
        corrections = all_correction_wizard_slips.filtered(lambda p: p.state == 'draft')

        self.assertEqual(len(corrections), 4, "There should be 4 correction payslips.")
        correction_payrun = corrections.payslip_run_id
        correction_payrun.action_confirm()
        corrections.action_payslip_done()

        q1_payslips = (all_correction_wizard_slips + payslips).filtered(
            lambda p: p.date_from >= date(2025, 1, 1) and p.date_to <= date(2025, 3, 31)
        )
        self._validate_dmfa_structural_deduction(year=2025, quarter=1, payslips=q1_payslips)

    def test_manual_payslip_line_change_computes_correct_deduction(self):
        jan_payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Jan 2025',
            'version_id': self.contract.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        })
        jan_payslip.compute_sheet()
        structural_deduction_amount_before = jan_payslip.line_ids.filtered(lambda line: line.code == 'ONSS_STRUCTURAL').total

        meal_voucher_lines = jan_payslip.line_ids.filtered(lambda line: line.code in ['MEAL_V_EMP', 'MEAL_VOUCHER_EMPLOYER'])
        jan_payslip.write({
            'line_ids': [Command.update(line.id, {'quantity': line.quantity + 1}) for line in meal_voucher_lines]
        })

        structural_deduction_amount_after = jan_payslip.line_ids.filtered(lambda line: line.code == 'ONSS_STRUCTURAL').total

        self.assertEqual(structural_deduction_amount_before, structural_deduction_amount_after, "Structural deduction amount should remain the same when changing meal voucher quantity by a small amount.")

    @freeze_time("2025-04-10 10:00:00")
    def test_no_reduction_below_minimum_occupation(self):
        """
        No structural reduction below 27.5% of a full time (mu glob), except for a worker at least half-time.
        """
        def _create_payslip(hours_per_day):
            self.contract.resource_calendar_id = self.env['resource.calendar'].create({
                'name': f'Part-time {hours_per_day * 5} hours',
                'company_id': self.belgian_company.id,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': 8.0,
                    'hour_to': 8.0 + hours_per_day,
                }) for dayofweek in ['0', '1', '2', '3', '4']],
            })
            self.contract.write({'reference_calendar_id': self.calendar_38h.id, 'wage': 1000})
            payslip = self.env['hr.payslip'].create({
                'version_id': self.contract.id,
                'date_from': date(2025, 1, 1),
                'date_to': date(2025, 1, 31),
                'employee_id': self.employee.id,
                'struct_id': self.belgium_monthly_payslip_structure.id,
                'company_id': self.belgian_company.id,
            })
            payslip.compute_sheet()
            return payslip

        Dmfa = self.env['l10n_be.dmfa']
        less_than_half_time = _create_payslip(2.0)  # 10 hours a week
        self.assertEqual(Dmfa._get_l10n_be_structural_deduction_3000(less_than_half_time, mu_global=0.26), 0)
        less_than_half_time.action_payslip_cancel()
        less_than_half_time.unlink()
        half_time = _create_payslip(3.8)  # 19 hours a week
        self.assertGreater(Dmfa._get_l10n_be_structural_deduction_3000(half_time, mu_global=0.26), 0)
        half_time.action_payslip_cancel()
        half_time.unlink()
        # no minimum for an artist (with the rates of an ordinary white collar)
        rates_parameter = self.env['hr.rule.parameter'].sudo().create({
            'name': 'ONSS Rates: 010_046_0',
            'code': 'l10n_be_onss_rates_010_046_0',
            'country_id': self.env.ref('base.be').id,
        })
        self.env['hr.rule.parameter.value'].sudo().create({
            'rule_parameter_id': rates_parameter.id,
            'parameter_value': str(self.env['hr.rule.parameter']._get_parameter_from_code('l10n_be_onss_rates_010_495_0', date(2025, 1, 1))),
            'date_from': date(2000, 1, 1),
        })
        self.contract.l10n_be_worker_code_id = self.env['l10n.be.worker.code'].search([('dmfa_code', '=', '046')])
        artist = _create_payslip(2.0)
        self.assertGreater(Dmfa._get_l10n_be_structural_deduction_3000(artist, mu_global=0.26), 0)

    @freeze_time("2025-04-10 10:00:00")
    def test_carried_over_leave_in_fraction_of_performance(self):
        """
        The carried over leave days (service codes 16 and 17) are part of the fraction of performance μ.
        """
        self.contract.wage = 2000
        payslip = self.env['hr.payslip'].create({
            'version_id': self.contract.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'employee_id': self.employee.id,
            'struct_id': self.belgium_monthly_payslip_structure.id,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        attendance = payslip.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id.dmfa_code == '1')
        carried_over_leave = attendance.copy({
            'payslip_id': payslip.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_postponed_paid_time_off_n1').id,
            'number_of_days': 5,
            'number_of_hours': 38,
        })
        attendance.write({'number_of_days': attendance.number_of_days - 5, 'number_of_hours': attendance.number_of_hours - 38})
        Dmfa = self.env['l10n_be.dmfa']
        with_carried_over_leave = Dmfa._get_l10n_be_structural_deduction_3000(payslip, mu_global=1)
        # the same days as a sickness (service code 50): out of the fraction of performance
        carried_over_leave.work_entry_type_id = self.env.ref('hr_work_entry.l10n_be_work_entry_type_long_sick')
        with_sickness = Dmfa._get_l10n_be_structural_deduction_3000(payslip, mu_global=1)
        self.assertGreater(with_carried_over_leave, with_sickness)


@tagged('post_install', '-at_install', 'dmfa')
class TestDMFAOnssPaymentWarning(TestPayslipValidationCommon, TestBelgiumCommon):
    """ The ONSS payment warning reads the ONSS accounts: it needs the chart of accounts. """

    @classmethod
    @TestPayslipValidationCommon.setup_country('be')
    def setUpClass(cls):
        super().setUpClass()
        cls.belgian_company = cls.company_data['company']

    def test_onss_payment_warning_provisions_paid(self):
        """ The provisions paid are the payments to the ONSS for the quarter of the DmfA, not the
        balance of the ONSS account since its creation. """
        company = self.belgian_company
        accounts = {
            code: self.env['account.account'].search([
                *self.env['account.account']._check_company_domain(company),
                ('code', '=', code),
            ], limit=1)
            for code in ('454000', '620200')
        }
        bank_journal = self.company_data['default_journal_bank']
        misc_journal = self.company_data['default_journal_misc']

        def post_entry(entry_date, journal, debit_account, credit_account, amount):
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'date': entry_date,
                'journal_id': journal.id,
                'line_ids': [
                    Command.create({'account_id': debit_account.id, 'debit': amount, 'credit': 0.0}),
                    Command.create({'account_id': credit_account.id, 'debit': 0.0, 'credit': amount}),
                ],
            })
            move.action_post()

        # Contributions and provision of the last quarter of 2025
        post_entry(date(2025, 10, 31), misc_journal, accounts['620200'], accounts['454000'], 9000.0)
        post_entry(date(2025, 11, 5), bank_journal, accounts['454000'], bank_journal.default_account_id, 2000.0)
        # Contributions and provisions of the first quarter of 2026
        post_entry(date(2026, 1, 31), misc_journal, accounts['620200'], accounts['454000'], 10000.0)
        post_entry(date(2026, 2, 5), bank_journal, accounts['454000'], bank_journal.default_account_id, 3000.0)
        post_entry(date(2026, 3, 5), bank_journal, accounts['454000'], bank_journal.default_account_id, 3500.0)

        dmfa = self.env['l10n_be.dmfa'].create({
            'name': 'DmfA 2026 Q1',
            'company_id': company.id,
            'year': '2026',
            'quarter': '1',
        })
        with patch.object(L10n_BeDmfa, '_get_rendering_data', return_value={'global_contribution': '1000000'}):
            action = self.env['hr.payroll.warning'].with_company(company).with_context(
                report_ids=dmfa.ids,
            ).action_l10n_be_onss_payment_warning()
        self.assertEqual(action['params']['onss_balance'], 10000.0)
        self.assertAlmostEqual(action['params']['paid_amount'], 6500.0, places=2)
