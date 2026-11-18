# Part of Odoo. See LICENSE file for full copyright and licensing details.

import calendar
import datetime
from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import Command
from odoo.tests.common import freeze_time, tagged

from odoo.addons.hr_payroll_account.tests.common import TestPayslipValidationCommon
from odoo.addons.l10n_be_hr_payroll.tests.common import TestBelgiumCommon
from odoo.exceptions import UserError, ValidationError
from odoo.tools import convert_file
import math

IMPULSION_CODES = ('IMPULSION25', 'IMPULSION12')


@tagged('post_install', '-at_install', 'payslips_validation', 'yoyo')
class TestPayslipValidation(TestPayslipValidationCommon, TestBelgiumCommon):

    _test_user_groups = None  # FIXME list needed groups

    @classmethod
    @TestPayslipValidationCommon.setup_country('be')
    def setUpClass(cls):
        super().setUpClass()

        cls.company_data['company'].current_payroll_config_id.write({
            'l10n_be_employer_category_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00010').id,
            'l10n_be_main_joint_committee': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
        })
        cls.env.user.group_ids += cls.quick_ref('hr_holidays.group_hr_holidays_manager')\
                                  | cls.quick_ref('hr_payroll.group_hr_payroll_officer')\
                                  | cls.quick_ref('fleet.fleet_group_manager')\
                                  | cls.quick_ref('hr.group_hr_manager')
        cls.date_from = datetime.date(2020, 9, 1)
        cls.date_to = datetime.date(2020, 9, 30)

        cls.resource_calendar_38_hours_per_week, \
        cls.resource_calendar_40_hours_per_week, \
        cls.resource_calendar_80_hours_per_week, \
        cls.resource_calendar_38_hours_per_week_odoo, \
        cls.resource_calendar_4_5_wednesday_off, \
        cls.resource_calendar_4_5_wednesday_off_time_credit, \
        cls.resource_calendar_4_5_thurday_off, \
        cls.resource_calendar_4_5_friday_off, \
        cls.resource_calendar_half_time, \
        cls.resource_calendar_1_5_monday_on, \
        cls.resource_calendar_0_hours_per_week, \
        cls.resource_calendar_19_part_time_sick, \
        cls.resource_calendar_15_2_part_time_sick, \
        cls.resource_calendar_9_10_monday_off, \
        cls.resource_calendar_9_10_monday_off_credit_time, \
        cls.resource_calendar_9_10_strange, \
        cls.resource_calendar_4_5_monday_off_equal_morning_afternoon, \
        cls.resource_calendar_eco_unemployment_full, \
        cls.resource_calendar_eco_unemployment_partial, \
        = cls.env['resource.calendar'].sudo().create([
            *[{
                'name': "Test Calendar : 38 Hours/Week",
                'company_id': cls.env.company.id,
                'hours_per_day': 7.6,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id
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
            }],
            *[{
                'name': "Test Calendar : 40 Hours/Week",
                'company_id': cls.env.company.id,
                'hours_per_day': 8,
                'hours_per_week': 40.0,
                'full_time_required_hours': 40.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id

                }) for dayofweek, hour_from, hour_to in [
                    ("0", 8.0, 12.0),
                    ("0", 13.0, 17.0),
                    ("1", 8.0, 12.0),
                    ("1", 13.0, 17.0),
                    ("2", 8.0, 12.0),
                    ("2", 13.0, 17.0),
                    ("3", 8.0, 12.0),
                    ("3", 13.0, 17.0),
                    ("4", 8.0, 12.0),
                    ("4", 13.0, 17.0),
                ]],
            }],
            *[{
                    'name': "Test Calendar : 80 Hours/Week",
                    'company_id': cls.env.company.id,
                    'hours_per_day': 16,
                    'hours_per_week': 80.0,
                    'full_time_required_hours': 80.0,
                    'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                        'dayofweek': dayofweek,
                        'hour_from': hour_from,
                        'hour_to': hour_to,
                        'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id
                    }) for dayofweek, hour_from, hour_to in [
                        ("0", 4.0, 12.0),
                        ("0", 13.0, 21.0),
                        ("1", 4.0, 12.0),
                        ("1", 13.0, 21.0),
                        ("2", 4.0, 12.0),
                        ("2", 13.0, 21.0),
                        ("3", 4.0, 12.0),
                        ("3", 13.0, 21.0),
                        ("4", 4.0, 12.0),
                        ("4", 13.0, 21.0),
                    ]],
            }],
            *[{
                'name': "Test Calendar : 38 Hours/Week",
                'company_id': cls.env.company.id,
                'hours_per_day': 7.6,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id
                }) for dayofweek, hour_from, hour_to in [
                    ("0", 9.0, 12.8),
                    ("0", 13.8, 17.6),
                    ("1", 9.0, 12.8),
                    ("1", 13.8, 17.6),
                    ("2", 9.0, 12.8),
                    ("2", 13.8, 17.6),
                    ("3", 9.0, 12.8),
                    ("3", 13.8, 17.6),
                    ("4", 9.0, 12.8),
                    ("4", 13.8, 17.6),
                ]],
            }],
            *[{
                'name': "Test Calendar: 4/5 Wednesday Off",
                'company_id': cls.env.company.id,
                'hours_per_day': 7.6,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id
                }) for dayofweek, hour_from, hour_to in [
                    ("0", 8.0, 12.0),
                    ("0", 13.0, 16.6),
                    ("1", 8.0, 12.0),
                    ("1", 13.0, 16.6),
                    ("3", 8.0, 12.0),
                    ("3", 13.0, 16.6),
                    ("4", 8.0, 12.0),
                    ("4", 13.0, 16.6),
                ]],
            }],
            *[{
                'name': "Test Calendar: 4/5 Wednesday Off Credit Time",
                'company_id': cls.env.company.id,
                'hours_per_day': 7.6,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id
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
                    'work_entry_type_id': cls.env.ref('hr_work_entry.l10n_be_work_entry_type_credit_time').id
                }) for dayofweek, hour_from, hour_to in [
                    ("2", 8.0, 12.0),
                    ("2", 13.0, 16.6),
                ]],
            }],
            *[{
                'name': "Test Calendar: 4/5 Thursday Off",
                'company_id': cls.env.company.id,
                'hours_per_day': 7.6,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id
                }) for dayofweek, hour_from, hour_to in [
                    ("0", 8.0, 12.0),
                    ("0", 13.0, 16.6),
                    ("1", 8.0, 12.0),
                    ("1", 13.0, 16.6),
                    ("2", 8.0, 12.0),
                    ("2", 13.0, 16.6),
                    ("4", 8.0, 12.0),
                    ("4", 13.0, 16.6),
                ]] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.l10n_be_work_entry_type_credit_time').id
                }) for dayofweek, hour_from, hour_to in [
                    ("3", 8.0, 12.0),
                    ("3", 13.0, 16.6),
                ]],
            }],
            *[{
                'name': "Test Calendar: 4/5 Friday Off",
                'company_id': cls.env.company.id,
                'hours_per_day': 7.6,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id
                }) for dayofweek, hour_from, hour_to in [
                    ("0", 8.0, 12.0),
                    ("0", 13.0, 16.6),
                    ("1", 8.0, 12.0),
                    ("1", 13.0, 16.6),
                    ("2", 8.0, 12.0),
                    ("2", 13.0, 16.6),
                    ("3", 8.0, 12.0),
                    ("3", 13.0, 16.6),
                ]] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.l10n_be_work_entry_type_credit_time').id
                }) for dayofweek, hour_from, hour_to in [
                    ("4", 8.0, 12.0),
                    ("4", 13.0, 16.6),
                ]],
            }],
            *[{
                'name': "Test Calendar: Half Time",
                'company_id': cls.env.company.id,
                'hours_per_day': 6.33,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id
                }) for dayofweek, hour_from, hour_to in [
                    ("0", 8.0, 12.0),
                    ("0", 13.0, 16.6),
                    ("1", 8.0, 12.0),
                    ("1", 13.0, 16.6),
                    ("2", 8.0, 11.8),
                ]],
            }],
            *[{
                'name': "Test Calendar: 1/5 Monday On",
                'company_id': cls.env.company.id,
                'hours_per_day': 7.6,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id
                }) for dayofweek, hour_from, hour_to in [
                    ("0", 8.0, 12.0),
                    ("0", 13.0, 16.6),
                ]],
            }],
            *[{
                'name': "Test Calendar: 0 Hours per week",
                'company_id': cls.env.company.id,
                'hours_per_day': 0,
                'full_time_required_hours': 38,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.l10n_be_work_entry_type_credit_time').id
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
            }],
            *[{
                'name': "Test Calendar: 19 Hours/Week Part Time Sick PM",
                'company_id': cls.env.company.id,
                'hours_per_day': 7.6,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id
                }) for dayofweek, hour_from, hour_to in [
                    ("0", 9.0, 12.8),
                    ("1", 9.0, 12.8),
                    ("2", 9.0, 12.8),
                    ("3", 9.0, 12.8),
                    ("4", 9.0, 12.8),
                ]] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.l10n_be_work_entry_type_partial_incapacity').id
                }) for dayofweek, hour_from, hour_to in [
                    ("0", 13.8, 17.6),
                    ("1", 13.8, 17.6),
                    ("2", 13.8, 17.6),
                    ("3", 13.8, 17.6),
                    ("4", 13.8, 17.6),
                ]],
            }],
            *[{
                'name': "Test Calendar: 15.2 Hours/Week Part Time Sick",
                'company_id': cls.env.company.id,
                'hours_per_day': 7.6,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.l10n_be_work_entry_type_partial_incapacity').id
                }) for dayofweek, hour_from, hour_to in [
                    ("0", 9.0, 12.8),
                    ("0", 13.8, 17.6),
                    ("1", 9.0, 12.8),
                    ("1", 13.8, 17.6),
                    ("2", 9.0, 12.8),
                    ("2", 13.8, 17.6),
                ]] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id
                }) for dayofweek, hour_from, hour_to in [
                    ("3", 9.0, 12.8),
                    ("3", 13.8, 17.6),
                    ("4", 9.0, 12.8),
                    ("4", 13.8, 17.6),
                ]],
            }],
            *[{
                'name': "Test Calendar: 9/10 Hours/Week 1 Monday over 2 Off",
                'company_id': cls.env.company.id,
                'calendar_type': 'variable',
                'hours_per_day': 7.6,
                'days_per_week': 4.5,
                'hours_per_week': 34.2,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'date': datetime.date(1, 1, 1) + datetime.timedelta(days=d, weeks=w),
                    'hour_from': 8.0,
                    'hour_to': 15.6,
                    'recurrency': True,
                    'recurrency_type': 'weeks',
                    'recurrency_interval': 2,
                    'recurrency_end_type': 'forever',
                    'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
                }) for d in range(5) for w in range(2) if not (d == 0 and w == 1)],
            }],
            *[{
                'name': "Test Calendar: 9/10 Hours/Week 1 Monday over 2 Off",
                'company_id': cls.env.company.id,
                'calendar_type': 'variable',
                'hours_per_day': 7.6,
                'days_per_week': 4.5,
                'hours_per_week': 34.2,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'date': date,
                    'hour_from': 8.0,
                    'hour_to': 15.6,
                    'recurrency': True,
                    'recurrency_type': 'weeks',
                    'recurrency_interval': 2,
                    'recurrency_end_type': 'forever',
                    'work_entry_type_id': cls.env.ref(work_entry_type).id,
                }) for date, work_entry_type in [
                    *[(datetime.date(1, 1, 1) + datetime.timedelta(days=d, weeks=w), 'hr_work_entry.be_work_entry_type_attendance')
                        for d in range(5) for w in range(2) if not (d == 0 and w == 1)],
                    (datetime.date(1, 1, 8), 'hr_work_entry.l10n_be_work_entry_type_credit_time'),
                ]],
            }],
            *[{
                'name': "Test Calendar: 9/10 Hours/Week 1 hour less every day on second week + 1 wed pm off",
                'company_id': cls.env.company.id,
                'calendar_type': 'variable',
                'hours_per_day': 6.82,
                'days_per_week': 5,
                'hours_per_week': 34.1,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'date': date,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'recurrency': True,
                    'recurrency_type': 'weeks',
                    'recurrency_interval': 2,
                    'recurrency_end_type': 'forever',
                    'work_entry_type_id': cls.env.ref(work_entry_type).id
                }) for date, hour_from, hour_to, work_entry_type in [
                    *[(datetime.date(1, 1, 1) + datetime.timedelta(days=d, weeks=w), 9.0, 16.6 if w == 0 else (12.8 if d == 2 else 15.6), 'hr_work_entry.be_work_entry_type_attendance')
                        for d in range(5) for w in range(2)],
                    *[(datetime.date(1, 1, 8) + datetime.timedelta(days=d), 15.6, 16.6, 'hr_work_entry.l10n_be_work_entry_type_credit_time')
                        for d in range(5) if d != 2],
                    (datetime.date(1, 1, 10), 12.8, 15.8, 'hr_work_entry.l10n_be_work_entry_type_credit_time'),
                ]],
            }],
            *[{
                'name': "Test Calendar: 4/5 Monday/Friday Afternoon Off (equal morning/afternoon)",
                'company_id': cls.env.company.id,
                'hours_per_day': 6.08,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id
                }) for dayofweek, hour_from, hour_to in [
                    ("0", 9.0, 12.8),
                    ("1", 9.0, 12.8),
                    ("1", 13.8, 17.6),
                    ("2", 9.0, 12.8),
                    ("2", 13.8, 17.6),
                    ("3", 9.0, 12.8),
                    ("3", 13.8, 17.6),
                    ("4", 9.0, 12.8),
                ]],
            }],
            *[{
                'name': "Test Calendar : Economic Unemployment",
                'company_id': cls.env.company.id,
                'hours_per_day': 7.6,
                'hours_per_week': 38.0,
                'days_per_week': 5.0,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment').id
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
            }],
            *[{
                'name': "Test Calendar : Economic Unemployment Partial",
                'company_id': cls.env.company.id,
                'hours_per_day': 7.6,
                'hours_per_week': 38.0,
                'days_per_week': 5.0,
                'full_time_required_hours': 38.0,
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment').id
                }) for dayofweek, hour_from, hour_to in [
                    ("0", 8.0, 12.0),
                    ("0", 13.0, 16.6),
                    ("1", 8.0, 12.0),
                    ("1", 13.0, 16.6),
                    ("2", 8.0, 12.0),
                    ("2", 13.0, 16.6),
                ]] + [(0, 0, {
                    'dayofweek': dayofweek,
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id
                }) for dayofweek, hour_from, hour_to in [
                    ("3", 8.0, 12.0),
                    ("3", 13.0, 16.6),
                    ("4", 8.0, 12.0),
                    ("4", 13.0, 16.6),
                ]],
            }],
        ]).sudo(False)

        # These calendars are created before _setup_common switches the company schedule, so the
        # default reference calendar they captured is the company's original 40h/week schedule.
        # The full time equivalent of this suite is 38h/week, as the explicit
        # full_time_required_hours above state.
        cls.env['resource.calendar'].sudo().search([
            ('company_id', '=', cls.env.company.id),
        ]).reference_calendar_id = cls.resource_calendar_38_hours_per_week

        cls.work_contact = cls.env['res.partner'].create({'name': 'Test Work Contact'})

        cls.brand = cls.env['fleet.vehicle.model.brand'].sudo().create([{
            'name': "Test Brand"
        }])

        cls.model = cls.env['fleet.vehicle.model'].sudo().create([{
            'name': "Test Model",
            'brand_id': cls.brand.id
        }])

        with freeze_time('2019-01-01'):
            cls.car = cls.env['fleet.vehicle'].sudo().create([{
                'name': "Test Car",
                'license_plate': "TEST",
                'driver_id': cls.work_contact.id,
                'company_id': cls.env.company.id,
                'model_id': cls.model.id,
                'contract_date_start': datetime.date(2019, 1, 1),
                'co2': 88.0,
                'car_value': 38000.0,
                'fuel_type': "diesel",
                'acquisition_date': datetime.date(2019, 1, 1)
            }]).sudo(False)

            cls.vehicle_contract = cls.env['fleet.vehicle.log.contract'].sudo().create({
                'name': "Test Contract",
                'vehicle_id': cls.car.id,
                'company_id': cls.env.company.id,
                'start_date': datetime.date(2020, 10, 8),
                'expiration_date': datetime.date.today() + relativedelta(months=1),
                'state': "open",
                'cost_generated': 0.0,
                'cost_frequency': "monthly",
                'recurring_cost_amount_depreciated': 450.0
            })

        cls._setup_common(
            country=cls.env.ref('base.be'),
            structure=cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary'),
            structure_type=cls.env.ref('hr.structure_type_employee_cp200'),
            tz='Europe/Brussels',
            resource_calendar=cls.resource_calendar_38_hours_per_week,
            car=cls.car,
            version_fields={
                'contract_date_start': datetime.date(2018, 12, 31),
                'date_version': datetime.date(2018, 12, 31),
                'wage': 2650.0,
                'transport_mode_car': True,
                'fuel_card': 150.0,
                'internet': 38.0,
                'mobile': 30.0,
                'meal_voucher_amount': 7.45,
                'ip_wage_rate': 0.25,
                'l10n_be_lsa_monthly_misc_base_amount': 150,
                'l10n_be_joint_committee_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            },
            employee_fields={
                'distance_home_work': 75,
                'work_contact_id': cls.work_contact.id,
                'lang': 'fr_BE',
            },
        )

        cls.sick_time_off_type = cls.env.ref('hr_work_entry.be_work_entry_type_sick_leave')
        cls.long_term_sick_time_off_type = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_long_sick')
        cls.paid_time_off_type = cls.env.ref('hr_work_entry.be_work_entry_type_legal_leave')
        cls.unpaid_time_off_type = cls.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave')
        cls.european_time_off_type = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_european')
        cls.economic_unemployment_time_off_type = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment')
        cls.economic_unemployment_for_employee_time_off_type = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_temporary_economic_unemployement_employee')
        cls.work_entry_type_small_unemployment = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_small_unemployment')
        cls.extra_legal_time_off_type = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_extra_legal')

        (
            cls.sick_time_off_type +
            cls.long_term_sick_time_off_type +
            cls.paid_time_off_type +
            cls.unpaid_time_off_type +
            cls.european_time_off_type +
            cls.economic_unemployment_time_off_type +
            cls.economic_unemployment_for_employee_time_off_type +
            cls.work_entry_type_small_unemployment +
            cls.extra_legal_time_off_type
        ).with_context(install_mode=True).requires_allocation = False

        cls.company_executive_employee = cls.env['hr.employee'].create({
            'name': 'Company Executive',
            'employee_type_id': cls.env.ref('hr.contract_type_company_executive').id,
            'date_version': '2019-01-01',
            'contract_date_start': '2019-01-01',
            'internet': 1,
            'mobile': 1,
            'laptop': 1,
            'meal_voucher_amount': 8,
            'wage': 3750,
            'marital': 'married',
            'l10n_be_joint_committee_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id,
            # The employee form clears the worker code when selecting CP999.
            'l10n_be_worker_code_id': False,
            'lang': 'fr_BE',
        })
        # Activate the benefit
        cls.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', 'in', ['l10n_be_lsa_monthly_pro_other_amount', 'l10n_be_lsa_monthly_misc_base_amount'])]).active = True

        cls.additional_hours_type = cls.env.ref('hr_work_entry.be_work_entry_type_additional_hours')
        cls.additional_hours_50_type = cls.env.ref('hr_work_entry.be_work_entry_type_additional_hours_50')
        cls.additional_hours_100_type = cls.env.ref('hr_work_entry.be_work_entry_type_additional_hours_100')
        cls.env['account.chart.template']._configure_payroll_account_be(cls.env.company)
        # Compensate the loss on commission on PTO with the double holiday pay (SIMPLE_VARIABLE) instead of monthly
        # (COM_LOSS_PTO): the tests of the monthly compensation select it
        cls.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_double_holiday').active = True

        # Double holiday pay
        cls.calendar_30_4h_per_week = cls.env['resource.calendar'].create({
            'name': '30.4h calendar',
            'attendance_ids': [
                (0, 0, {'dayofweek': '0', 'hour_from': 8, 'hour_to': 12}),
                (0, 0, {'dayofweek': '0', 'hour_from': 13, 'hour_to': 16.6}),
                (0, 0, {'dayofweek': '1', 'hour_from': 8, 'hour_to': 12}),
                (0, 0, {'dayofweek': '1', 'hour_from': 13, 'hour_to': 16.6}),
                (0, 0, {'dayofweek': '2', 'hour_from': 8, 'hour_to': 12}),
                (0, 0, {'dayofweek': '2', 'hour_from': 13, 'hour_to': 16.6}),
                (0, 0, {'dayofweek': '3', 'hour_from': 8, 'hour_to': 12}),
                (0, 0, {'dayofweek': '3', 'hour_from': 13, 'hour_to': 16.6}),
            ]
        })

        partial_incapacity = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_partial_incapacity')

        cls.calendar_15_12h_per_week_med = cls.env['resource.calendar'].create({
            'name': '15.12h med calendar',
            'attendance_ids': [
                (0, 0, {'dayofweek': '0', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '0', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '1', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '1', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '2', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '2', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '3', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '3', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '4', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '4', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
            ]
        })

        cls.calendar_19h_per_week_med = cls.env['resource.calendar'].create({
            'name': '19h med calendar',
            'attendance_ids': [
                (0, 0, {'dayofweek': '0', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '0', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '1', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '1', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '2', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '2', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '3', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '3', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '4', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '4', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
            ]
        })

        cls.calendar_22_8h_per_week_med = cls.env['resource.calendar'].create({
            'name': '22.8h med calendar',
            'attendance_ids': [
                (0, 0, {'dayofweek': '0', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '0', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '1', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '1', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '2', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '2', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '3', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '3', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '4', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '4', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
            ]
        })

        cls.calendar_26_6h_per_week_med = cls.env['resource.calendar'].create({
            'name': '26.6h med calendar',
            'attendance_ids': [
                (0, 0, {'dayofweek': '0', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '0', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '1', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '1', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '2', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '2', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '3', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '3', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '4', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '4', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
            ]
        })

        cls.calendar_30_4h_per_week_med = cls.env['resource.calendar'].create({
            'name': '30.4h med calendar',
            'attendance_ids': [
                (0, 0, {'dayofweek': '0', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '0', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '1', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '1', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '2', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '2', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '3', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '3', 'duration_hours': 3.8}),
                (0, 0, {'dayofweek': '4', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
                (0, 0, {'dayofweek': '4', 'duration_hours': 3.8, 'work_entry_type_id': partial_incapacity.id}),
            ]
        })

        cls.env.ref('hr.structure_type_employee_cp200').default_resource_calendar_id = cls.company.resource_calendar_id

        # Impulsion plans
        cls.cp200 = cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200')
        cls.city_namur, cls.city_liege, cls.city_brussels, cls.city_eupen = cls.env['res.city'].create([{
            'name': name,
            'zipcode': zipcode,
            'country_id': cls.env.ref('base.be').id,
            'l10n_be_nis_code': nis_code,
        } for name, zipcode, nis_code in (
            ('Namur', '5000', '92094'),
            ('Liège', '4000', '62063'),
            ('Bruxelles', '1000', '21004'),
            ('Eupen', '4700', '63023'),
        )])
        cls.partner_brussels = cls.env['res.partner'].create({'name': 'Brussels Work Address'})
        cls.partner_namur = cls.env['res.partner'].create({'name': 'Namur Work Address'})
        cls.env['hr.work.location'].create([{
            'company_id': cls.env.company.id,
            'bce_code': '8888888473',
            'location_type': 'dmfa_unit',
            'address_id': cls.partner_brussels.id,
            'competence': 'br',
        }, {
            'company_id': cls.env.company.id,
            'bce_code': '8888888176',
            'location_type': 'dmfa_unit',
            'address_id': cls.partner_namur.id,
            'competence': 'wa',
        }])

    @classmethod
    def _create_calendar(cls, hours_per_week, full_time_hours_per_week=40.0, hours_per_day=None):
        hours_per_day = hours_per_day or (hours_per_week / 5.0)

        return cls.env['resource.calendar'].sudo().create({
            'name': f"{hours_per_week} Hours/Week",
            'company_id': cls.env.company.id,
            'hours_per_day': hours_per_day,
            'hours_per_week': hours_per_week,
            'full_time_required_hours': full_time_hours_per_week,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {
                    'dayofweek': str(day),
                    'hour_from': 8.0,
                    'hour_to': 8.0 + hours_per_day,
                    'work_entry_type_id': cls.env.ref(
                        'hr_work_entry.generic_work_entry_type_attendance'
                    ).id
                })
                for day in range(5)
            ],
        }).sudo(False)

    @classmethod
    def _generate_departure_data(cls, european_leave=False):
        cls.version_2019 = cls.version
        cls.version_2019.write({
            'wage': 3000,
            'commission_on_target': 1500,
            'date_version': datetime.date(2019, 1, 1),
            'contract_date_start': datetime.date(2019, 1, 1),
            'contract_date_end': datetime.date(2019, 12, 31),
            'l10n_be_joint_committee_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
        })
        cls.version_2019.employee_id.write({
            'l10n_be_fictive_hire_date': datetime.date(2019, 1, 1),
        })

        cls.version_2020 = cls.version_2019.copy({
            'name': "Contract For Payslip Test",
            'date_version': datetime.date(2020, 1, 1),
            'contract_date_start': datetime.date(2020, 1, 1),
            'contract_date_end': False,
            'wage': 3200,
            'l10n_be_joint_committee_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
        })

        cls.allocation_2019 = cls.env['hr.leave.allocation'].create({
            'name': 'Paid Time Off - 2019',
            'work_entry_type_id': cls.paid_time_off_type.id,
            'number_of_days': 20,
            'employee_id': cls.employee.id,
            'date_from': datetime.date(2019, 1, 1),
            'date_to': datetime.date(2025, 12, 31),
        })

        cls.allocation_2019_european = cls.env['hr.leave.allocation'].create({
            'name': 'European Time Off - 2019',
            'work_entry_type_id': cls.env.ref('hr_work_entry.l10n_be_work_entry_type_european').id,
            'number_of_days': 20,
            'employee_id': cls.employee.id,
            'date_from': datetime.date(2019, 1, 1),
            'date_to': datetime.date(2025, 12, 31),
        })

        cls.allocation_2020 = cls.env['hr.leave.allocation'].create({
            'name': 'Paid Time Off - 2020',
            'work_entry_type_id': cls.paid_time_off_type.id,
            'number_of_days': 20,
            'employee_id': cls.employee.id,
            'date_from': datetime.date(2020, 1, 1),
            'date_to': datetime.date(2025, 12, 31),
        })

        (cls.allocation_2019 + cls.allocation_2019_european + cls.allocation_2020).action_approve()

        cls.leave_2019 = cls.env['hr.leave'].create({
            'name': 'Unpaid Time Off 2019',
            'work_entry_type_id': cls.env.ref('hr_work_entry.l10n_be_work_entry_type_european').id if european_leave else cls.unpaid_time_off_type.id,
            'date_from': datetime.datetime(2019, 3, 4, 1, 0, 0),
            'date_to': datetime.datetime(2019, 3, 15, 23, 0, 0),
            'request_date_from': datetime.datetime(2019, 3, 4, 1, 0, 0),
            'request_date_to': datetime.datetime(2019, 3, 15, 23, 0, 0),
            'number_of_days': 10,
            'employee_id': cls.employee.id,
        })

        cls.legal_leave_2019 = cls.env['hr.leave'].create({
            'name': 'Legal Time Off 2019',
            'work_entry_type_id': cls.paid_time_off_type.id,
            'date_from': datetime.datetime(2019, 5, 6, 1, 0, 0),
            'date_to': datetime.datetime(2019, 5, 31, 23, 0, 0),
            'request_date_from': datetime.datetime(2019, 5, 6, 1, 0, 0),
            'request_date_to': datetime.datetime(2019, 5, 31, 23, 0, 0),
            'number_of_days': 20,
            'employee_id': cls.employee.id,
        })

        cls.legal_leave_2020 = cls.env['hr.leave'].create({
            'name': 'Legal Time Off 2020',
            'work_entry_type_id': cls.paid_time_off_type.id,
            'date_from': datetime.datetime(2020, 1, 13, 1, 0, 0),
            'date_to': datetime.datetime(2020, 1, 17, 23, 0, 0),
            'request_date_from': datetime.datetime(2020, 1, 13, 1, 0, 0),
            'request_date_to': datetime.datetime(2020, 1, 17, 23, 0, 0),
            'number_of_days': 5,
            'employee_id': cls.employee.id,
        })

        cls.batch = cls.env['hr.payslip.run'].create({
            'name': 'History Batch',
            'date_start': datetime.date(2019, 1, 1),
            'date_end': datetime.date(2020, 3, 31),
            'company_id': cls.env.company.id,
            'structure_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
        })

        # Janvier 2019: Salary + Commissions
        # Février 2019: Salary
        # Mars 2019: Salary (10 unpaid days)
        # Avril 2019: Salary + Warrants (2 payslips)
        # Mai 2019: Salary (20 legal days)
        # Juin 2019: Salary + Double Holiday Pay (2 payslips)
        # Juillet 2019: Salary + Commissions
        # Aout 2019: Salary
        # Septembre 2019: Salary
        # Octobre 2019: Salary + Commissions
        # Novembre 2019: Salary
        # Décembre 2019: Salary + 13eme mois (2 payslips)
        # Janvier 2020: Salary + Commissions (5 legal days)
        # Février 2020: Salary
        # Mars 2020: Salary
        # Avril: Fired Without notice period on the 15th of April (4 payslips):
        # - Termination Fees
        # - April Payslip
        # - Holiday Pay N
        # - Holiday Pay N-1
        cls.journal = cls.env['account.journal'].search([('type', '=', 'general')], limit=1)

        # Janvier 2019: Salary + Commissions
        cls.january_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip Jan 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 1, 1),
            'date_to': datetime.datetime(2019, 1, 31),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })
        cls.january_2019._set_input_value('COMMISSION', 2000)

        # Février 2019: Salary
        cls.february_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip Feb 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 2, 1),
            'date_to': datetime.datetime(2019, 2, 28),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })

        # Mars 2019: Salary (10 unpaid days)
        cls.march_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip Mar 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 3, 1),
            'date_to': datetime.datetime(2019, 3, 31),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })

        # Avril 2019: Salary + Warrants (2 payslips)
        cls.april_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip Apr 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 4, 1),
            'date_to': datetime.datetime(2019, 4, 30),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })

        cls.warrant_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip Warrant 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 4, 1),
            'date_to': datetime.datetime(2019, 4, 30),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_warrant').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })
        cls.warrant_2019._set_input_value('WARRANT_WITHOUT_ONSS', 1500)

        # Mai 2019: Salary (20 legal days)
        cls.may_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip May 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 5, 1),
            'date_to': datetime.datetime(2019, 5, 31),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })

        # Juin 2019: Salary + Double Holiday Pay (2 payslips)
        cls.june_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip Jun 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 6, 1),
            'date_to': datetime.datetime(2019, 6, 30),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })

        cls.double_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip Double 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 6, 1),
            'date_to': datetime.datetime(2019, 6, 30),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })

        # Juillet 2019: Salary + Commissions
        cls.july_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip Jul 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 7, 1),
            'date_to': datetime.datetime(2019, 7, 31),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })
        cls.july_2019._set_input_value('COMMISSION', 2000)

        # Aout 2019: Salary
        cls.august_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip Aug 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 8, 1),
            'date_to': datetime.datetime(2019, 8, 31),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })

        # Septembre 2019: Salary
        cls.september_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip Sep 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 9, 1),
            'date_to': datetime.datetime(2019, 9, 30),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })

        # Octobre 2019: Salary + Commissions
        cls.october_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip Oct 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 10, 1),
            'date_to': datetime.datetime(2019, 10, 31),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })
        cls.october_2019._set_input_value('COMMISSION', 2000)

        # Novembre 2019: Salary
        cls.november_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip Nov 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 11, 1),
            'date_to': datetime.datetime(2019, 11, 30),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })

        # Décembre 2019: Salary + 13eme mois (2 payslips)
        cls.december_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip Dec 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 12, 1),
            'date_to': datetime.datetime(2019, 12, 31),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })

        cls.thirteen_2019 = cls.env['hr.payslip'].create({
            'name': 'Payslip Thirteen Month 2019',
            'version_id': cls.version_2019.id,
            'date_from': datetime.datetime(2019, 12, 1),
            'date_to': datetime.datetime(2019, 12, 31),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })

        # Janvier 2020: Salary + Commissions (5 legal days)
        cls.january_2020 = cls.env['hr.payslip'].create({
            'name': 'Payslip Jan 2020',
            'version_id': cls.version_2020.id,
            'date_from': datetime.datetime(2020, 1, 1),
            'date_to': datetime.datetime(2020, 1, 31),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })
        cls.january_2020._set_input_value('COMMISSION', 2000)

        # Février 2020: Salary
        cls.february_2020 = cls.env['hr.payslip'].create({
            'name': 'Payslip Feb 2020',
            'version_id': cls.version_2020.id,
            'date_from': datetime.datetime(2020, 2, 1),
            'date_to': datetime.datetime(2020, 2, 28),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })

        # Mars 2020: Salary
        cls.march_2020 = cls.env['hr.payslip'].create({
            'name': 'Payslip Mar 2020',
            'version_id': cls.version_2020.id,
            'date_from': datetime.datetime(2020, 3, 1),
            'date_to': datetime.datetime(2020, 3, 31),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })

        # Avril: Fired Without notice period on the 15th of April (4 payslips):
        # - Termination Fees
        cls.departure_notice = cls.env['hr.employee.departure'].create({
            'employee_id': cls.employee.id,
            'departure_reason_id': cls.env.ref('hr.departure_fired').id,
            'dismissal_date': datetime.date(2020, 4, 15),
            'l10n_be_notice_respect': 'without',
            'departure_description': 'foo',
            'action_date': datetime.date(2020, 4, 16),
        })

        # - April Payslip
        cls.april_2020 = cls.env['hr.payslip'].create({
            'name': 'Payslip Mar 2020',
            'version_id': cls.version_2020.id,
            'date_from': datetime.datetime(2020, 3, 1),
            'date_to': datetime.datetime(2020, 3, 31),
            'employee_id': cls.employee.id,
            'struct_id': cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': cls.env.company.id,
            'journal_id': cls.journal.id,
            'payslip_run_id': cls.batch.id,
        })

        all_payslips = cls.january_2019 + cls.february_2019 + cls.march_2019 + cls.april_2019 + \
                       cls.warrant_2019 + cls.may_2019 + cls.june_2019 + cls.double_2019 + \
                       cls.july_2019 + cls.august_2019 + cls.september_2019 + cls.october_2019 + \
                       cls.november_2019 + cls.december_2019 + cls.thirteen_2019 + \
                       cls.january_2020 + cls.february_2020 + cls.march_2020 + cls.april_2020
        all_payslips.action_refresh_from_work_entries()
        # Clear review state before validation (simulates payroll officer approval)
        cls.employee.write({'review_state': '1_reviewed'})
        all_payslips.action_payslip_done()

        cls.departure_notice.action_register()
        cls.departure_payslips = cls.departure_notice._generate_termination_payslip()
        cls.departure_payslips += cls.departure_notice._generate_termination_holidays()
        struct_id = cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        cls.termination_fees = cls.departure_payslips.filtered(lambda pay: pay.struct_id == struct_id)
        cls.termination_fees.compute_sheet()
        cls.employee.write({'review_state': '1_reviewed'})
        cls.termination_fees.action_payslip_done()
        cls.termination_fees.payslip_run_id = cls.batch

    @classmethod
    def _create_researcher_employee(cls, name, certificate, rd_percentage, wage=None):
        employee = cls.env['hr.employee'].create({
            'name': name,
            'resource_calendar_id': cls.resource_calendar_38_hours_per_week.id,
            'company_id': cls.env.company.id,
            'country_id': cls.country.id,
            'structure_type_id': cls.employee.structure_type_id.id,
            'l10n_be_joint_committee_id': cls.version.l10n_be_joint_committee_id.id,
            'certificate': certificate,
            'date_version': datetime.date(2019, 1, 1),
            'contract_date_start': datetime.date(2019, 1, 1),
            'wage': wage or cls.version.wage,
            'lang': 'fr_BE',
        })
        employee.version_id.rd_percentage = rd_percentage
        return employee

    @classmethod
    def _create_researcher_payslips(cls, employees, date_from, date_to):
        payslips = cls.env['hr.payslip'].create([{
            'name': f'Payslip {employee.name}',
            'employee_id': employee.id,
            'version_id': employee.version_id.id,
            'company_id': cls.env.company.id,
            'struct_id': cls.structure.id,
            'date_from': date_from,
            'date_to': date_to,
        } for employee in employees])
        payslips.compute_sheet()
        return payslips

    def test_low_salary(self):
        self.version.wage = 1800
        self.version.ip_wage_rate = 0

        payslip = self._generate_payslip(self.date_from, self.date_to)

        self.assertEqual(len(payslip.worked_days_line_ids), 1)

        self._validate_worked_days(payslip, {'002.00': (22.0, 167.2, 1800.0)})

        self._validate_payslip(payslip)

    def test_end_of_contract(self):
        self.version.contract_date_end = datetime.date(2020, 9, 21)
        self.version.ip_wage_rate = 0
        self.version.write({
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })

        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 14, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 14, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_phc').id
        }])

        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True
        payslip = self._generate_payslip(self.date_from, self.date_to)

        self.assertEqual(len(payslip.worked_days_line_ids), 3)

        self._validate_worked_days(payslip, {
            '002.00': (14.0, 106.4, 1671.54),
            '006.15': (1.0, 7.6, 122.31),
            '000.00': (7.0, 53.2, 0.0),
        })

        self._validate_payslip(payslip)

    def test_out_of_contract_credit_time(self):
        # The employee is on 4/5 credit time (wednesday off) from the 16 of September 2020
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week,
            'work_time_rate': 1.0,
            'wage': 2120.0 * (5 / 4),
            'contract_date_start': datetime.date(2020, 9, 16),
            'contract_date_end': datetime.date(2020, 12, 31),
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True
        payslip = self._generate_payslip(self.date_from, self.date_to)

        self.assertEqual(len(payslip.worked_days_line_ids), 3)

        self._validate_worked_days(payslip, {
            '002.00': (8.0, 60.8, 978.46),
            '147.00': (3.0, 22.8, 0.0),
            '000.00': (11.0, 83.6, 0.0),
        })

        self._validate_payslip(payslip)

    # If there is a public holiday less than 30 days after the end of the
    # contract, the employee should be paid for that day too
    def test_out_of_contract_public_holiday(self):
        self.version.contract_date_end = datetime.date(2020, 9, 15)
        self.version.reference_calendar_id = self.resource_calendar_38_hours_per_week
        self.version.write({
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True

        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2020, 9, 22, 5, 0, 0),
            'date_to': datetime.datetime(2020, 9, 22, 16, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }])

        payslip = self._generate_payslip(self.date_from, self.date_to)

        payslip.with_context(number_of_public_holidays=1).add_upcoming_public_holiday_on_termination()
        payslip.compute_sheet()

        self.assertEqual(len(payslip.worked_days_line_ids), 3)

        self._validate_worked_days(payslip, {
            '002.00': (11.0, 83.6, 1304.62),
            '202.00': (1.0, 7.6, 122.31),
            '000.00': (11.0, 83.6, 0.0),
        })

        self._validate_payslip(payslip)

    def test_out_of_contract_public_holiday_hourly_wage(self):
        # Paid by the hour: the public holiday after the contract end is paid
        # as the hours of a normal day at the hourly wage
        self.version.write({
            'contract_date_end': datetime.date(2020, 9, 15),
            'wage_type': 'hourly',
            'hourly_wage': 20.0,
        })

        payslip = self._generate_payslip(self.date_from, self.date_to)
        payslip.with_context(number_of_public_holidays=1).add_upcoming_public_holiday_on_termination()

        self._validate_worked_days(payslip, {
            '202.00': (1.0, 7.6, 152.0),
        }, skip_lines=True)

    def test_end_of_contract_no_public_leave_right(self):
        # Check that only 1 day is taken into account (not 3) + Check it becomes 0 if another
        # contract is following
        self.version.contract_date_end = datetime.date(2020, 10, 13)
        self.version.ip_wage_rate = 0

        self.env['resource.calendar.leaves'].create([{
            'name': 'Armistice',
            'date_from': datetime.datetime.strptime('2020-11-11 07:00:00', '%Y-%m-%d %H:%M:%S'),
            'date_to': datetime.datetime.strptime('2020-11-11 18:00:00', '%Y-%m-%d %H:%M:%S'),
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id,
            'count_as': 'absence',
        }, {
            'name': 'Noel',
            'date_from': datetime.datetime.strptime('2020-12-25 07:00:00', '%Y-%m-%d %H:%M:%S'),
            'date_to': datetime.datetime.strptime('2020-12-25 18:00:00', '%Y-%m-%d %H:%M:%S'),
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id,
            'count_as': 'absence',
        }, {
            'name': 'Nouvel An',
            'date_from': datetime.datetime.strptime('2021-01-01 07:00:00', '%Y-%m-%d %H:%M:%S'),
            'date_to': datetime.datetime.strptime('2021-01-01 18:00:00', '%Y-%m-%d %H:%M:%S'),
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id,
            'count_as': 'absence',
        }])

        payslip = self._generate_payslip(datetime.date(2020, 10, 1), datetime.date(2020, 10, 31))

        # After contract public holiday is proposed

        new_version = self.env['hr.version'].create([{
            'name': "New Contract For Payslip Test",
            'employee_id': self.employee.id,
            'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'car_id': self.car.id,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'date_version': datetime.date(2020, 10, 14),
            'contract_date_start': datetime.date(2020, 10, 14),
            'contract_date_end': False,
            'wage': 2650.0,
            'transport_mode_car': True,
            'fuel_card': 150.0,
            'internet': 38.0,
            'mobile': 30.0,
            'meal_voucher_amount': 7.45,
            'ip_wage_rate': 0.25,
            'l10n_be_lsa_monthly_misc_base_amount': 150,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
        }])

        payslip.input_line_ids.unlink()
        payslip._compute_worked_days_line_ids()

        # After contract public holiday is not proposed anymore

    def test_one_day_contract(self):
        self.version.write({
            'contract_date_start': datetime.date(2020, 9, 1),
            'contract_date_end': datetime.date(2020, 9, 1),
            'ip_wage_rate': 0,
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True
        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (1.0, 7.6, 122.31),
            '000.00': (21.0, 159.6, 0.0),
        })

        self._validate_payslip(payslip)

    def test_bank_holidays(self):
        self.version.ip_wage_rate = 0
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 14, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 14, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }])
        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (21.0, 159.6, 2527.69),
            '006.00': (1.0, 7.6, 122.31),
        })

        self._validate_payslip(payslip)

    def test_public_holiday_compensation(self):
        self.version.ip_wage_rate = 0
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 14, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 14, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_phc').id
        }])

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (21.0, 159.6, 2527.69),
            '006.15': (1.0, 7.6, 122.31),
        })

        self._validate_payslip(payslip)

    def test_bank_holiday_half_days(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 14, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 15, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 16, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 16, 10, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self.assertEqual(sum(payslip.worked_days_line_ids.mapped('number_of_days')), 22)
        self.assertAlmostEqual(sum(payslip.worked_days_line_ids.mapped('number_of_hours')), 22 * 7.6)
        att_wdl = payslip.worked_days_line_ids.filtered(lambda wdl: wdl.work_entry_type_id.code == '002.00')
        self.assertEqual(att_wdl.number_of_days, 19.5)  # Attendance
        self.assertAlmostEqual(att_wdl.number_of_hours, 148)
        self.assertAlmostEqual(att_wdl.amount, 2341.01)
        leave_wdl = payslip.worked_days_line_ids.filtered(lambda wdl: wdl.work_entry_type_id.code == '016.00')
        self.assertEqual(leave_wdl.number_of_days, 2.5)  # leave
        self.assertAlmostEqual(leave_wdl.number_of_hours, 19.2)
        self.assertEqual(leave_wdl.amount, 308.99)
        self._validate_payslip(payslip)

    def test_classic_credit_time(self):
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 8, 1),
            'contract_date_end': datetime.date(2020, 11, 30),
            'wage': 2120.0 * (5 / 4),
            'work_time_rate': 1.0,
        })
        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (17.0, 129.2, 2120.0),
            '147.00': (5.0, 38.0, 0.0),
        })

        self._validate_payslip(payslip)

    def test_credit_time_employment_bonus_in_hours(self):
        # a time credit reduces the week of a full-time contract: the employment bonus counts hours, as for a part
        # time, against the full-time hours of the month
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 8, 1),
            'contract_date_end': datetime.date(2020, 11, 30),
            'wage': 2120.0 * (5 / 4),
            'work_time_rate': 1.0,
        })
        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))
        is_full_time, paid_hours, total_hours, _paid_days, _total_days = payslip._l10n_be_get_employment_bonus_fractions(payslip)
        self.assertFalse(is_full_time)
        self.assertEqual((paid_hours, total_hours), (129.2, 167.2))

    def test_horeca_employment_bonus_in_hours(self):
        # Horeca declares the hours of its full-time workers: their employment bonus counts hours, as for a part time,
        # and two unpaid hours lower the share of the month (165.2 of the 167.2 hours of April 2025), where the days
        # would not see them
        self.env['resource.calendar.leaves'].create({
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2025, 4, 8, 6, 0, 0),
            'date_to': datetime.datetime(2025, 4, 8, 8, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        })
        self.version.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302')
        payslip = self._generate_payslip(datetime.date(2025, 4, 1), datetime.date(2025, 4, 30))
        is_full_time, paid_hours, total_hours, _paid_days, _total_days = payslip._l10n_be_get_employment_bonus_fractions(payslip)
        self.assertFalse(is_full_time)
        self.assertEqual((paid_hours, total_hours), (165.2, 167.2))

    def test_credit_time_cafeteria_plan_shadow_wage(self):
        # the wage is the wage after the salary sacrifice of a cafeteria plan: the time credit prorates the wage
        # before it, the shadow wage (2,650 + 350) * 4/5 - 350
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 8, 1),
            'contract_date_end': datetime.date(2020, 11, 30),
            'wage': 2650.0,
            'work_time_rate': 1.0,
            'l10n_be_cafeteria_plan_salary_sacrifice': 350.0,
        })
        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self._validate_worked_days(payslip, {
            '002.00': (17.0, 129.2, 2050.0),
            '147.00': (5.0, 38.0, 0.0),
        })

    def test_variable_calendar_out_of_contract(self):
        # a schedule planned day by day plans nothing before the contract: the days out of the contract are those of
        # its regime, Thursday 1 to Saturday 3 January 2026 for Monday to Saturday, at 38 / 6 hours a day: the wage
        # less 19 hours at the hourly rate, 2,650 * (1 - 3 / (13 * 38) * 19)
        start = datetime.date(2026, 1, 5)
        calendar = self.env['resource.calendar'].create({
            'name': "Planned day by day",
            'company_id': self.env.company.id,
            'calendar_type': 'variable',
            'hours_per_week': 38,
            'days_per_week': 6,
            'full_time_required_hours': 38,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'date': start + datetime.timedelta(days=offset),
                'hour_from': 8.0,
                'hour_to': 14.0 + 1 / 3,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for offset in range(27) if (start + datetime.timedelta(days=offset)).weekday() < 6],
        })
        self.version.write({
            'resource_calendar_id': calendar.id,
            'date_version': start,
            'contract_date_start': start,
            'wage': 2650.0,
        })
        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        out_of_contract = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '000.00')
        self.assertEqual((out_of_contract.number_of_days, round(out_of_contract.number_of_hours, 2)), (3.0, 19.0))
        self.assertAlmostEqual(payslip._get_line_values(['BASIC'])['BASIC'][payslip.id]['total'], 2344.23, places=2)

    def test_cycle_employment_bonus_month(self):
        # a two-week cycle of four 9.5-hour days a week (Horeca): the month of the employment bonus is the cycle's
        # hours of the month (18 days in April 2026), not the full-time week spread over Monday to Friday (167.2 hours)
        start = datetime.date(2026, 3, 30)  # Monday, day 1 of the cycle
        cycle = self.env['resource.calendar'].create({
            'name': "Two-week cycle",
            'company_id': self.env.company.id,
            'calendar_type': 'variable',
            'hours_per_week': 38,
            'days_per_week': 4,
            'full_time_required_hours': 38,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'date': start + datetime.timedelta(days=day),
                'hour_from': hour_from,
                'hour_to': hour_to,
                'recurrency': True,
                'recurrency_type': 'weeks',
                'recurrency_interval': 2,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for day in (0, 2, 3, 6, 8, 9, 11, 12) for hour_from, hour_to in ((8.0, 13.0), (13.5, 18.0))],
        })
        self.version.write({
            'resource_calendar_id': cycle.id,
            'contract_date_start': datetime.date(2026, 1, 1),
        })
        payslip = self._generate_payslip(datetime.date(2026, 4, 1), datetime.date(2026, 4, 30))
        is_full_time, paid_hours, total_hours, _paid_days, total_days = payslip._l10n_be_get_employment_bonus_fractions(payslip)
        self.assertFalse(is_full_time)
        self.assertEqual((paid_hours, total_hours, total_days), (171.0, 171.0, 18))

    def test_variable_calendar_employment_bonus_reference_month(self):
        # a schedule planned day by day measures the month of the employment bonus on its reference calendar, the week
        # of the ONSS reference person: 7 hours on Tuesday and Wednesday and 6 hours from Thursday to Sunday plan 164
        # hours over the 26 Tuesdays to Sundays of March 2025, where their 38 hours spread over Monday to Saturday give
        # 164.67
        reference = self.env['resource.calendar'].create({
            'name': "Tuesday to Sunday",
            'company_id': self.env.company.id,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': 8.0,
                'hour_to': 8.0 + hours,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for dayofweek, hours in (('1', 7), ('2', 7), ('3', 6), ('4', 6), ('5', 6), ('6', 6))],
        })
        start = datetime.date(2025, 3, 1)
        calendar = self.env['resource.calendar'].create({
            'name': "Planned day by day",
            'company_id': self.env.company.id,
            'calendar_type': 'variable',
            'hours_per_week': 24,
            'days_per_week': 6,
            'reference_calendar_id': reference.id,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'date': start + datetime.timedelta(days=offset),
                'hour_from': 8.0,
                'hour_to': 12.0,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for offset in range(31) if (start + datetime.timedelta(days=offset)).weekday()],
        })
        self.version.write({
            'resource_calendar_id': calendar.id,
            'contract_date_start': datetime.date(2025, 1, 1),
        })
        payslip = self._generate_payslip(datetime.date(2025, 3, 1), datetime.date(2025, 3, 31))
        is_full_time, paid_hours, total_hours, _paid_days, total_days = payslip._l10n_be_get_employment_bonus_fractions(payslip)
        self.assertFalse(is_full_time)
        self.assertEqual((paid_hours, total_hours, total_days), (104.0, 164.0, 26))

    def test_employment_bonus_reference_wage_below_high_bound(self):
        # the bounds of the employment bonus apply to the reference wage: a Horeca schedule planned day by day pays 23
        # days of 7.6 hours in April 2025, a month of 22 days, so the reference wage S = 3,300 / 174.8 x 167.2 = 18.88 x
        # 167.2 is below the high bound (3,271.48) although the pay is above it: R = 120.59 - 0.2443 x (3,156.74 -
        # 2,777.83)
        start = datetime.date(2025, 4, 1)
        calendar = self.env['resource.calendar'].create({
            'name': "Planned day by day",
            'company_id': self.env.company.id,
            'calendar_type': 'variable',
            'hours_per_week': 38,
            'days_per_week': 5,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'date': day,
                'hour_from': 8.0,
                'hour_to': 15.6,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for day in (start + datetime.timedelta(days=offset) for offset in range(30))
                if day.weekday() < 5 or day == datetime.date(2025, 4, 12)],
        })
        self.version.write({
            'resource_calendar_id': calendar.id,
            'contract_date_start': datetime.date(2025, 1, 1),
            'wage': 3300.0,
            'fuel_card': 0,
            'internet': 0,
            'mobile': 0,
            'meal_voucher_amount': 0,
            'ip_wage_rate': 0,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
        })
        payslip = self._generate_payslip(start, datetime.date(2025, 4, 30))
        self._validate_payslip(payslip, {
            'SALARY': 3300.0,
            'EmpBonus.A': 28.02,
            'EmpBonus.B': 0.0,
            'EmpBonus.1': 28.02,
        }, skip_lines=True)

    def test_employment_bonus_planned_cycle_reference(self):
        # a Horeca schedule planned day by day whose reference regime is a two-week cycle of 36 hours (four 8-hour days,
        # then five): U is the hours the cycle plans in April 2025, 19 days of 8 hours = 152 hours, not its average week
        # spread over the 22 weekdays (36 / 5 x 22 = 158.4). Planned on the cycle's 19 days, H = U and S = W = 2,500:
        # volet A 120.59, volet B 162.62 - 0.2699 x (2,500 - 2,175.25) = 74.97. Over 158.4 hours S was 16.45 x 158.4 =
        # 2,605.68 and P = 0.96 x R: a bonus of 160.36 instead of 195.56
        pattern = (8, 8, 0, 8, 8, 0, 0, 8, 8, 8, 8, 8, 0, 0)
        reference = self.env['resource.calendar'].create({
            'name': "36 hours, two-week cycle",
            'company_id': self.env.company.id,
            'calendar_type': 'variable',
            'hours_per_week': 36,
            'days_per_week': 4.5,
            'full_time_required_hours': 36,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'date': datetime.date(1, 1, 1) + datetime.timedelta(days=offset),
                'hour_from': 8.0,
                'hour_to': 8.0 + hours,
                'recurrency': True,
                'recurrency_type': 'weeks',
                'recurrency_interval': 2,
                'recurrency_end_type': 'forever',
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for offset, hours in enumerate(pattern) if hours],
        })
        start = datetime.date(2025, 4, 1)
        planned = [day for day in (start + datetime.timedelta(days=offset) for offset in range(30))
                   if pattern[(day - datetime.date(1, 1, 1)).days % 14]]
        calendar = self.env['resource.calendar'].create({
            'name': "Planned day by day",
            'company_id': self.env.company.id,
            'calendar_type': 'variable',
            'hours_per_week': 36,
            'days_per_week': 4.5,
            'reference_calendar_id': reference.id,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'date': day,
                'hour_from': 8.0,
                'hour_to': 16.0,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for day in planned],
        })
        self.version.write({
            'resource_calendar_id': calendar.id,
            'contract_date_start': datetime.date(2025, 1, 1),
            'wage': 2500.0,
            'fuel_card': 0,
            'internet': 0,
            'mobile': 0,
            'meal_voucher_amount': 0,
            'ip_wage_rate': 0,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
        })
        payslip = self._generate_payslip(start, datetime.date(2025, 4, 30))
        is_full_time, paid_hours, total_hours, _paid_days, total_days = payslip._l10n_be_get_employment_bonus_fractions(payslip)
        self.assertFalse(is_full_time)
        self.assertEqual((paid_hours, total_hours, total_days), (152.0, 152.0, 19))
        self._validate_payslip(payslip)

    def test_employment_bonus_carry_over_partially_used_is_lost(self):
        # January: bonus A 123.00, bonus B 165.87, ONSS 105.74
        # - Paid A = min(105.74 ONSS, 123.00) = 105.74, carried over A = 123.00 - 105.74 = 17.26
        # - Paid B = min(0.00 ONSS left after A, 165.87) = 0.00, carried over B = 165.87
        self.version.write({
            'contract_date_start': datetime.date(2026, 1, 1),
            'wage': 800.0,
        })
        january = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        self._validate_payslip(january)
        explanations = {line.code: line.explanation for line in january.line_ids}
        self.assertEqual(
            explanations['EmpBonus.A.CO'],
            "Result (17.26) = Max(0, Bonus (123.0) - Already paid (0.0) - ONSS (105.74)) - Already carried over (0.0)")
        self.assertEqual(
            explanations['EmpBonus.B.CO'],
            "Result (165.87) = Max(0, Bonus (165.87) - Already paid (0.0) - Remaining ONSS after Volet A (0.0))"
            " - Already carried over (0.0)")
        january.action_payslip_done()

        # February: bonus A 123.00, bonus B 60.54, ONSS 341.00
        # - Paid A = min(341.00 ONSS, 123.00 + 17.26 carried over) = 140.26
        # - Paid B = min(200.74 ONSS left after A, 60.54 + 165.87 carried over) = 200.74
        # Only the bonus of the month not covered by its ONSS is carried over, not the unused carry over: carried over A
        # = max(0, 123.00 - 341.00) = 0 and carried over B = max(0, 60.54 - 200.74) = 0, so no EmpBonus.*.CO line and
        # the 25.67 left of the January carry over B (226.41 - 200.74) is lost
        self.version.wage = 2600.0
        february = self._generate_payslip(datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))
        self._validate_payslip(february)
        february.action_payslip_done()

        # March: nothing carried over from February
        # - Paid A = min(341.00 ONSS, 123.00) = 123.00
        # - Paid B = min(218.00 ONSS left after A, 60.54) = 60.54
        march = self._generate_payslip(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))
        self._validate_payslip(march)

    def test_employment_bonus_carry_over_counted_once_per_month(self):
        # The carry over of a month is the unused bonus of the whole month: a second payslip of the month corrects the
        # carry over of the first one instead of adding its own
        # January: bonus A 123.00, bonus B 165.87, ONSS 105.74
        # - Paid A = 105.74, carried over A = 17.26
        # - Paid B = 0.00, carried over B = 165.87
        self.version.write({
            'contract_date_start': datetime.date(2026, 1, 1),
            'wage': 800.0,
        })
        january = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        self._validate_payslip(january)
        january.action_payslip_done()

        # January off-cycle: ONSS 105.74
        # - Paid A = min(105.74 ONSS, 123.00 - 105.74 already paid) = 17.26
        # - Paid B = min(88.48 ONSS left after A, 165.87) = 88.48
        # Unused bonus of January: A = 123.00 - 123.00 paid = 0, B = 165.87 - 88.48 paid = 77.39, the off-cycle carries
        # over the difference with the 17.26 and 165.87 already carried over: -17.26 for A and -88.48 for B
        january_off_cycle = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        self._validate_payslip(january_off_cycle)
        explanations = {line.code: line.explanation for line in january_off_cycle.line_ids}
        self.assertEqual(
            explanations['EmpBonus.A.CO'],
            "Result (-17.26) = Max(0, Bonus (123.0) - Already paid (105.74) - ONSS (105.74))"
            " - Already carried over (17.26)")
        self.assertEqual(
            explanations['EmpBonus.B.CO'],
            "Result (-88.48) = Max(0, Bonus (165.87) - Already paid (0.0) - Remaining ONSS after Volet A (88.48))"
            " - Already carried over (165.87)")
        january_off_cycle.action_payslip_done()

        # February: bonus A 123.00, bonus B 60.54, ONSS 341.00, carried over A 0.00 and B 77.39 (not 183.13 + 77.39)
        # - Paid A = min(341.00 ONSS, 123.00) = 123.00
        # - Paid B = min(218.00 ONSS left after A, 60.54 + 77.39 carried over) = 137.93
        self.version.wage = 2600.0
        february = self._generate_payslip(datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))
        self._validate_payslip(february)

    def _create_planned_full_time_calendar(self, planned):
        return self.env['resource.calendar'].create({
            'name': "Planned day by day",
            'company_id': self.env.company.id,
            'calendar_type': 'variable',
            'hours_per_week': 38,
            'days_per_week': 5,
            'full_time_required_hours': 38,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'date': day,
                'hour_from': 8.0,
                'hour_to': 15.6,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for day in planned],
        })

    def test_employment_bonus_planned_full_time_complete_month(self):
        # a full-time employee out of Horeca planned day by day declares days: paid for the 20 days its planning holds in
        # March 2025 (two Saturdays instead of three Wednesdays), the month is complete and S = W, although the 38-hour
        # reference week plans 21 days (159.6 hours): R = 120.59 - 0.2443 x (3,000 - 2,777.83) = 66.31, not the hours
        # formula's S = 3,000 / 152 x 159.6 = 19.74 x 159.6 = 3,150.50, R = 29.55 x 152 / 159.6
        start = datetime.date(2025, 3, 1)
        planned = [day for day in (start + datetime.timedelta(days=offset) for offset in range(31))
                   if (day.weekday() < 5 and day.day not in (5, 12, 19)) or day.day in (8, 15)]
        self.version.write({
            'resource_calendar_id': self._create_planned_full_time_calendar(planned).id,
            'contract_date_start': datetime.date(2025, 1, 1),
            'wage': 3000.0,
            'fuel_card': 0,
            'internet': 0,
            'mobile': 0,
            'meal_voucher_amount': 0,
            'ip_wage_rate': 0,
        })
        payslip = self._generate_payslip(start, datetime.date(2025, 3, 31))
        is_full_time, _paid_hours, _total_hours, paid_days, total_days = payslip._l10n_be_get_employment_bonus_fractions(payslip)
        self.assertTrue(is_full_time)
        self.assertEqual((paid_days, total_days), (20, 20))
        self._validate_payslip(payslip, {
            'SALARY': 3000.0,
            'EmpBonus.A': 66.31,
            'EmpBonus.B': 0.0,
            'EmpBonus.1': 66.31,
        }, skip_lines=True)

    def test_employment_bonus_planned_full_time_incomplete_month(self):
        # an unpaid day of the planning makes the month incomplete: S = (W / J) x D and P = (J / D) x R, D the 21 days
        # of the five-day regime in March 2025 (the reference week), whatever the planning holds
        start = datetime.date(2025, 3, 1)
        planned = [day for day in (start + datetime.timedelta(days=offset) for offset in range(31))
                   if (day.weekday() < 5 and day.day not in (5, 12, 19)) or day.day in (8, 15)]
        self.version.write({
            'resource_calendar_id': self._create_planned_full_time_calendar(planned).id,
            'contract_date_start': datetime.date(2025, 1, 1),
        })
        self.env['resource.calendar.leaves'].create({
            'name': "Unpaid",
            'calendar_id': self.version.resource_calendar_id.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2025, 3, 8, 6, 0, 0),
            'date_to': datetime.datetime(2025, 3, 8, 16, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        })
        payslip = self._generate_payslip(start, datetime.date(2025, 3, 31))
        is_full_time, _paid_hours, _total_hours, paid_days, total_days = payslip._l10n_be_get_employment_bonus_fractions(payslip)
        self.assertTrue(is_full_time)
        self.assertEqual((paid_days, total_days), (19, 21))

    def test_employment_bonus_short_day_complete_month(self):
        # a full-time week of four 9-hour days and a 4-hour Friday: paid for its 21 days of March 2025, the month is
        # complete (J = D = 21, the Fridays count as days of the regime as they count as worked days) and S = W = 3,000:
        # R = 120.59 - 0.2443 x (3,000 - 2,777.83) = 66.31, volet B 0. Counting the Fridays as half days (D = 19) made
        # J > D and S = 142.86 x 19 = 2,714.34: volet A 120.59 and volet B 162.62 - 0.2699 x (2,714.34 - 2,175.25) =
        # 17.12, a bonus of 137.71 instead of 66.31
        calendar = self.env['resource.calendar'].create({
            'name': "40 hours, short Friday",
            'company_id': self.env.company.id,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for dayofweek, hour_from, hour_to in [
                ("0", 8.0, 12.0), ("0", 13.0, 18.0),
                ("1", 8.0, 12.0), ("1", 13.0, 18.0),
                ("2", 8.0, 12.0), ("2", 13.0, 18.0),
                ("3", 8.0, 12.0), ("3", 13.0, 18.0),
                ("4", 8.0, 12.0),
            ]],
        })
        calendar.reference_calendar_id = calendar
        self.version.write({
            'resource_calendar_id': calendar.id,
            'contract_date_start': datetime.date(2025, 1, 1),
            'wage': 3000.0,
            'fuel_card': 0,
            'internet': 0,
            'mobile': 0,
            'meal_voucher_amount': 0,
            'ip_wage_rate': 0,
        })
        payslip = self._generate_payslip(datetime.date(2025, 3, 1), datetime.date(2025, 3, 31))
        is_full_time, _paid_hours, _total_hours, paid_days, total_days = payslip._l10n_be_get_employment_bonus_fractions(payslip)
        self.assertTrue(is_full_time)
        self.assertEqual((paid_days, total_days), (21, 21))
        self._validate_payslip(payslip)

    def test_employment_bonus_hours_without_recoverable_overtime(self):
        # overtime recovered later (026.00) pays its premium when worked, but its hours are declared when the rest is
        # taken: they are not hours H of the month for the employment bonus
        self.version.write({
            'contract_date_start': datetime.date(2025, 1, 1),
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
        })
        self.env['resource.calendar.leaves'].create({
            'name': "Recoverable overtime",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2025, 3, 12, 7, 0, 0),
            'date_to': datetime.datetime(2025, 3, 12, 9, 0, 0),
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_overtime_recoverable').id,
        })
        payslip = self._generate_payslip(datetime.date(2025, 3, 1), datetime.date(2025, 3, 31))
        overtime = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '026.00')
        self.assertAlmostEqual(overtime.number_of_hours, 2.0, places=2)
        self.assertGreater(overtime.amount, 0.0)
        is_full_time, paid_hours, total_hours, _paid_days, _total_days = payslip._l10n_be_get_employment_bonus_fractions(payslip)
        self.assertFalse(is_full_time)
        self.assertEqual((paid_hours, total_hours), (157.6, 159.6))

    def test_employment_bonus_hours_paid_later(self):
        # additional hours paid with a later payslip, on a work entry type of the employer's own at a rate of 0, carry
        # no pay in the month, but they are performed and declared with the performance code 1: they are hours H of the
        # month for the employment bonus, the 91.2 hours of the half-time schedule and the 3 hours paid later, of the
        # 167.2 hours of September 2025
        paid_later_type = self.env.ref('hr_work_entry.be_work_entry_type_additional_hours').copy({
            'name': "Additional hours paid later",
            'code': 'TEST.PAID_LATER',
            'amount_rate': 0.0,
        })
        self.assertEqual(paid_later_type.dmfa_code, '1')
        self.version.resource_calendar_id = self.resource_calendar_half_time
        self.version.wage_type = "hourly"
        self.version.hourly_wage = 20
        self.env['hr.leave'].create({
            'work_entry_type_id': paid_later_type.id,
            'request_date_from': datetime.datetime(2025, 9, 8, 17, 0),
            'request_date_to': datetime.datetime(2025, 9, 8, 20, 0),
            'request_hour_from': 17,
            'request_hour_to': 20,
            'employee_id': self.employee.id,
        })
        payslip = self._generate_payslip(datetime.date(2025, 9, 1), datetime.date(2025, 9, 30))
        paid_later = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == 'TEST.PAID_LATER')
        self.assertAlmostEqual(paid_later.number_of_hours, 3.0, places=2)
        self.assertEqual(paid_later.amount, 0.0)
        is_full_time, paid_hours, total_hours, _paid_days, _total_days = payslip._l10n_be_get_employment_bonus_fractions(payslip)
        self.assertFalse(is_full_time)
        self.assertEqual((paid_hours, total_hours), (94.2, 167.2))

    def test_employment_bonus_base_amount_rounded(self):
        # the base amount R of the employment bonus is rounded to the cent before the fraction of the month: paid by the
        # hour in Horeca, 152 of the 159.6 hours of March 2025, S = 15.05 x 159.6 = 2,401.98 and R = 162.62 - 0.2699 x
        # (2,401.98 - 2,175.25) = 101.4256, rounded to 101.43: P = 0.95 x 101.43 = 96.36 (96.35 with R unrounded)
        self.version.write({
            'contract_date_start': datetime.date(2025, 1, 1),
            'wage_type': 'hourly',
            'hourly_wage': 15.05,
            'fuel_card': 0,
            'internet': 0,
            'mobile': 0,
            'meal_voucher_amount': 0,
            'ip_wage_rate': 0,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
        })
        self.env['resource.calendar.leaves'].create({
            'name': "Unpaid",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2025, 3, 10, 6, 0, 0),
            'date_to': datetime.datetime(2025, 3, 10, 16, 0, 0),
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        })
        payslip = self._generate_payslip(datetime.date(2025, 3, 1), datetime.date(2025, 3, 31))
        _is_full_time, paid_hours, total_hours, _paid_days, _total_days = payslip._l10n_be_get_employment_bonus_fractions(payslip)
        self.assertEqual((paid_hours, total_hours), (152.0, 159.6))
        self._validate_payslip(payslip, {
            'SALARY': 2287.6,
            'EmpBonus.B': 96.36,
        }, skip_lines=True)

    def test_credit_time_paid_time_off(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 14, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 15, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 17, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 18, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 8, 1),
            'contract_date_end': datetime.date(2020, 11, 30),
            'wage': 2120.0 * (5 / 4),
            'work_time_rate': 1.0,
        })

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 3)

        self._validate_worked_days(payslip, {
            '002.00': (13.0, 98.8, 1630.77),
            '147.00': (5.0, 38.0, 0.0),
            '016.00': (4.0, 30.4, 489.23),
        })

        self._validate_payslip(payslip)

    def test_credit_time_unpaid(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 14, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 15, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id
        }])

        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 8, 1),
            'contract_date_end': datetime.date(2020, 11, 30),
            'wage': 2120.0 * (5 / 4),
            'work_time_rate': 1.0,
        })

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 3)

        self._validate_worked_days(payslip, {
            '002.00': (15.0, 114.0, 1875.38),
            '147.00': (5.0, 38.0, 0.0),
            '158.00': (2.0, 15.2, 0.0),
        })

        self._validate_payslip(payslip)

    def test_credit_time_sick(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 14, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 15, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id
        }])

        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 8, 1),
            'contract_date_end': datetime.date(2020, 11, 30),
            'wage': 2120.0 * (5 / 4),
            'work_time_rate': 1.0,
        })

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 3)

        self._validate_worked_days(payslip, {
            '002.00': (15.0, 114.0, 1875.38),
            '147.00': (5.0, 38.0, 0.0),
            '013.00': (2.0, 15.2, 244.62),
        })

        self._validate_payslip(payslip)

    def test_credit_time_full_time(self):
        self.version.write({
            'resource_calendar_id': self.resource_calendar_0_hours_per_week.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 8, 1),
            'contract_date_end': datetime.date(2020, 11, 27),
            'wage': 0.0,
            'ip_wage_rate': 0,
            'work_time_rate': 0,
        })

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 1)

        self._validate_worked_days(payslip, {'147.00': (22.0, 167.2, 0.0)})

        self._validate_payslip(payslip)

    def test_half_time(self):
        self.version.write({
            'resource_calendar_id': self.resource_calendar_half_time.id,
            'wage': 1325.0,
            'ip_wage_rate': 0,
        })

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 1)

        self.assertAlmostEqual(payslip.worked_days_line_ids[0].amount, 1325.0, places=2)

        self.assertAlmostEqual(payslip.worked_days_line_ids[0].number_of_days, 14, places=2)

        self.assertAlmostEqual(payslip.worked_days_line_ids[0].number_of_hours, 87.4, places=2)

        self._validate_payslip(payslip)

    def test_half_time_1_day_paid_time_off(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_half_time.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 14, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 14, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        self.version.write({
            'resource_calendar_id': self.resource_calendar_half_time.id,
            'wage': 1325.0,
            'ip_wage_rate': 0,
        })

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        # 0 016.00, 1-2 002.00
        self.assertAlmostEqual(payslip.worked_days_line_ids[0].amount, 122.31, places=2)
        self.assertAlmostEqual(payslip.worked_days_line_ids[1].amount, 1202.69, places=2)

        self.assertAlmostEqual(payslip.worked_days_line_ids[0].number_of_days, 1.0, places=2)
        self.assertAlmostEqual(payslip.worked_days_line_ids[1].number_of_days, 13, places=2)

        self.assertAlmostEqual(payslip.worked_days_line_ids[0].number_of_hours, 7.6, places=2)
        self.assertAlmostEqual(payslip.worked_days_line_ids[1].number_of_hours, 79.8, places=2)

        self._validate_payslip(payslip)

    def test_half_time_1_day_unpaid_time_off(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_half_time.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 16, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 16, 9, 48, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_half_time.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 21, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 21, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id
        }])

        self.version.write({
            'resource_calendar_id': self.resource_calendar_half_time.id,
            'wage': 1325.0,
            'ip_wage_rate': 0,
        })

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 3)

        leaves_data = payslip._get_worked_days_line_values(['158.00', '016.00'], ['amount', 'number_of_days', 'number_of_hours'], True)
        paid_leaves_data = leaves_data['016.00']['sum']
        unpaid_leaves_data = leaves_data['158.00']['sum']

        self.assertAlmostEqual(paid_leaves_data['amount'], 61.15, places=2)
        self.assertAlmostEqual(unpaid_leaves_data['amount'], 0.0, places=2)
        self.assertAlmostEqual(payslip.worked_days_line_ids[2].amount, 1141.54, places=2)

        self.assertAlmostEqual(paid_leaves_data['number_of_days'], 1, places=2)
        self.assertAlmostEqual(unpaid_leaves_data['number_of_days'], 1.0, places=2)
        self.assertAlmostEqual(payslip.worked_days_line_ids[2].number_of_days, 12.0, places=2)

        self.assertAlmostEqual(paid_leaves_data['number_of_hours'], 3.8, places=2)
        self.assertAlmostEqual(unpaid_leaves_data['number_of_hours'], 7.6, places=2)
        self.assertAlmostEqual(payslip.worked_days_line_ids[2].number_of_hours, 76.0, places=2)

        self._validate_payslip(payslip)

    def test_maternity_time_off(self):
        self.public_time_off = self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2020, 10, 6, 5, 0, 0),
            'date_to': datetime.datetime(2020, 10, 6, 16, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }])

        maternity_time_off = self.env['hr.leave'].new({
            'name': 'Maternity Time Off : 15 weeks',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_maternity').id,
            'request_date_from': datetime.date(2020, 9, 10),
            'request_date_to': datetime.date(2020, 12, 24),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 76,
        })
        maternity_time_off._compute_date_from_to()
        maternity_time_off = self.env['hr.leave'].create(maternity_time_off._convert_to_write(maternity_time_off._cache))

        self.version.write({
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True
        september_payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(september_payslip.worked_days_line_ids), 2)
        self.assertEqual(len(september_payslip.line_ids), 61)

        self._validate_worked_days(september_payslip, {
            '002.00': (7.0, 53.2, 856.15),
            '128.00': (15.0, 114.0, 0.0),
        })

        self._validate_payslip(september_payslip)

        october_payslip = self._generate_payslip(datetime.date(2020, 10, 1), datetime.date(2020, 10, 31))

        self.assertEqual(len(october_payslip.worked_days_line_ids), 2)

        self._validate_worked_days(october_payslip, {
            '128.00': (21.0, 159.6, 0.0),
            '006.00': (1.0, 7.6, 122.31),
        })

        self._validate_payslip(october_payslip)

        november_payslip = self._generate_payslip(datetime.date(2020, 11, 1), datetime.date(2020, 11, 30))

        self.assertEqual(len(november_payslip.worked_days_line_ids), 1)
        self.assertEqual(len(november_payslip.input_line_ids), 0)

        self._validate_worked_days(november_payslip, {'128.00': (21.0, 159.60, 0.0)})

        self._validate_payslip(november_payslip)

    def test_paid_time_off_payslip(self):
        self.version.ip_wage_rate = 0
        self.leaves = self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 8, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 8, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (21.0, 159.6, 2527.69),
            '016.00': (1.0, 7.6, 122.31),
        })

        self._validate_payslip(payslip)

    def test_unpaid_leaves_complete_days(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 8, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 9, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '158.00': (2.0, 15.2, 0.0),
            '002.00': (20.0, 152.0, 2405.38),
        })

        self.assertAlmostEqual(payslip.worked_days_line_ids[0].fte, 0.091, places=3)
        self.assertAlmostEqual(payslip.worked_days_line_ids[1].fte, 0.909, places=3)

        self._validate_payslip(payslip)

    def test_as_much_unpaid_leaves_complete_days(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 8, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 22, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (11.0, 83.6, 1325),
            '158.00': (11.0, 83.6, 0.0),
        })

        self.assertEqual(payslip.worked_days_line_ids[0].fte, 0.5)
        self.assertEqual(payslip.worked_days_line_ids[1].fte, 0.5)

        self._validate_payslip(payslip)

    def test_more_unpaid_leaves_complete_days(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 8, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 23, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (10.0, 76.0, 1223.08),
            '158.00': (12.0, 91.2, 0.0),
        })

        self.assertAlmostEqual(payslip.worked_days_line_ids[0].fte, 0.455, places=3)
        self.assertAlmostEqual(payslip.worked_days_line_ids[1].fte, 0.545, places=3)

        self._validate_payslip(payslip)

    def test_unpaid_leaves_half_days(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 14, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 15, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 16, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 16, 10, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)
        self.assertEqual(sum(payslip.worked_days_line_ids.mapped('number_of_days')), 22)
        self.assertAlmostEqual(sum(payslip.worked_days_line_ids.mapped('number_of_hours')), 22 * 7.6)
        att_wdl = payslip.worked_days_line_ids.filtered(lambda wdl: wdl.work_entry_type_id.code == '002.00')
        self.assertEqual(att_wdl.number_of_days, 19.5)  # Attendance
        self.assertAlmostEqual(att_wdl.number_of_hours, 148)
        self.assertEqual(att_wdl.amount, 2341.01)
        self.assertAlmostEqual(att_wdl.fte, 0.885, places=3)
        leave_wdl = payslip.worked_days_line_ids.filtered(lambda wdl: wdl.work_entry_type_id.code == '158.00')
        self.assertEqual(leave_wdl.number_of_days, 2.5)  # leave
        self.assertAlmostEqual(leave_wdl.number_of_hours, 19.2)
        self.assertEqual(leave_wdl.amount, 0.0)
        self.assertAlmostEqual(leave_wdl.fte, 0.115, places=3)

        self._validate_payslip(payslip)

    def test_as_much_unpaid_leaves_half_days(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 14, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 15, 10, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 16, 10, 0, 0),
            'date_to': datetime.datetime(2020, 9, 29, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self._validate_worked_days(payslip, {
            '002.00': (11.5, 83.6, 1325),
            '158.00': (10.5, 83.6, 0.0),
        })

        self.assertEqual(len(payslip.worked_days_line_ids), 2)
        self.assertEqual(sum(payslip.worked_days_line_ids.mapped('number_of_days')), 22)
        self.assertEqual(sum(payslip.worked_days_line_ids.mapped('number_of_hours')), 22 * 7.6)
        att_wdl = payslip.worked_days_line_ids.filtered(lambda wdl: wdl.work_entry_type_id.code == '002.00')
        self.assertEqual(att_wdl.number_of_days, 11.5)  # Attendance
        self.assertAlmostEqual(att_wdl.number_of_hours, 83.6)
        self.assertEqual(att_wdl.amount, 1325)
        self.assertEqual(att_wdl.fte, 0.5)
        leave_wdl = payslip.worked_days_line_ids.filtered(lambda wdl: wdl.work_entry_type_id.code == '158.00')
        self.assertEqual(leave_wdl.number_of_days, 10.5)  # leave
        self.assertAlmostEqual(leave_wdl.number_of_hours, 83.6)
        self.assertEqual(leave_wdl.amount, 0.0)
        self.assertEqual(leave_wdl.fte, 0.5)

        self._validate_payslip(payslip)

    def test_as_much_unpaid_leaves_with_public_holiday(self):
        # Maternity leave from January 16th: 88 unpaid hours, 88 paid hours (80 worked and the public holiday of
        # January 1st). The paid lines share half of the wage: 3000 / 2 = 1500, the public holiday is not added
        # at the hourly rate on top of the half wage of the work (1363.64 + 138.46 = 1502.10)
        self.version.write({
            'wage': 3000,
            'resource_calendar_id': self.resource_calendar_40_hours_per_week.id,
            'reference_calendar_id': self.resource_calendar_40_hours_per_week.id,
        })
        self.env['resource.calendar.leaves'].create([{
            'name': "New Year",
            'calendar_id': self.resource_calendar_40_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2026, 1, 1, 0, 0, 0),
            'date_to': datetime.datetime(2026, 1, 1, 23, 59, 59),
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id,
        }, {
            'name': "Maternity Leave",
            'calendar_id': self.resource_calendar_40_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 1, 16, 0, 0, 0),
            'date_to': datetime.datetime(2026, 1, 31, 23, 59, 59),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_maternity').id,
        }])

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        self._validate_worked_days(payslip, {
            '002.00': (10.0, 80.0, 1363.64),
            '006.00': (1.0, 8.0, 136.36),
            '128.00': (11.0, 88.0, 0.0),
        })
        self._validate_payslip(payslip, {'BASIC': 1500.0}, skip_lines=True)

    def test_more_unpaid_leaves_half_days(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 3, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 15, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 16, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 21, 10, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)
        self.assertEqual(sum(payslip.worked_days_line_ids.mapped('number_of_days')), 22)
        self.assertEqual(sum(payslip.worked_days_line_ids.mapped('number_of_hours')), 22 * 7.6)
        att_wdl = payslip.worked_days_line_ids.filtered(lambda wdl: wdl.work_entry_type_id.code == '002.00')
        self.assertEqual(att_wdl.number_of_days, 9.5)  # Attendance
        self.assertAlmostEqual(att_wdl.number_of_hours, 72)
        self.assertEqual(att_wdl.amount, 1158.7)
        self.assertAlmostEqual(att_wdl.fte, 0.431, places=3)
        leave_wdl = payslip.worked_days_line_ids.filtered(lambda wdl: wdl.work_entry_type_id.code == '158.00')
        self.assertEqual(leave_wdl.number_of_days, 12.5)  # leave
        self.assertAlmostEqual(leave_wdl.number_of_hours, 95.2)
        self.assertEqual(leave_wdl.amount, 0.0)
        self.assertAlmostEqual(leave_wdl.fte, 0.569, places=3)

        self._validate_payslip(payslip)

    def test_unjustified_reason(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 14, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 14, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_unpredictable').id
        }])

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (21.0, 159.6, 2527.69),
            '135.00': (1.0, 7.6, 0.0),
        })

        self._validate_payslip(payslip)

    def test_private_car(self):
        self.employee.distance_home_work = 41
        self.version.write({
            'wage': 3707.12,
            'holidays': 12.0,
            'transport_mode_car': False,
            'private_car_employee_kilometer': 41,
            'fuel_card': 0.0,
            'internet': 43.99,
            'ip_wage_rate': 0.2,
            'car_id': False,
            'l10n_be_lsa_monthly_misc_base_amount': 150
        })

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 1)

        self._validate_worked_days(payslip, {'002.00': (22.0, 167.2, 3707.12)})

        self._validate_payslip(payslip)

    def test_private_car_cp200_2026(self):
        self.version.l10n_be_joint_committee_id.egov3_code = '200'
        self.employee.distance_home_work = 41
        self.version.write({
            'wage': 3707.12,
            'private_car_employee_kilometer': 41,
            'car_id': False,
        })
        payslip = self._generate_payslip(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))
        payslip_results = {
            'BASIC': 3707.12,
            'CAR.PRIV': 90.42,  # 4.11 * 22.0 * 1.0
        }
        self._validate_payslip(payslip, payslip_results, skip_lines=True)

    def test_private_car_cp302_2026(self):
        self.version.l10n_be_joint_committee_id.egov3_code = '302'
        self.employee.distance_home_work = 41
        self.version.write({
            'wage': 3707.12,
            'private_car_employee_kilometer': 41,
            'car_id': False,
        })
        payslip = self._generate_payslip(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))
        payslip_results = {
            'BASIC': 3707.12,
            'CAR.PRIV': 253.00,  # 5.75 * 44.0 * 1.0
        }
        self._validate_payslip(payslip, payslip_results, skip_lines=True)

    def test_private_car_before_2026(self):
        self.version.l10n_be_joint_committee_id.egov3_code = '200'
        self.version.write({
            'wage': 3707.12,
            'private_car_employee_kilometer': 41,
            'car_id': False,
        })
        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        payslip_results = {
            'BASIC': 3707.12,
            'CAR.PRIV': 86.5,
        }
        self._validate_payslip(payslip, payslip_results, skip_lines=True)

    def test_private_car_jc_out_of_scope(self):
        self.version.l10n_be_joint_committee_id.egov3_code = '124'
        self.version.write({
            'wage': 3707.12,
            'private_car_employee_kilometer': 41,
            'car_id': False,
        })
        payslip = self._generate_payslip(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))
        payslip_results = {
            'BASIC': 3707.12,
            'CAR.PRIV': 124.6,
        }
        self._validate_payslip(payslip, payslip_results, skip_lines=True)

    def test_private_car_cp200_2026_brackets(self):
        # The value under the key n of the daily scale applies from n km to the next key excluded. CP 200 only
        # intervenes from 3 km: the 1 and 2 km rows of the scale don't apply.
        self.version.l10n_be_joint_committee_id.egov3_code = '200'
        self.version.write({
            'wage': 3707.12,
            'private_car_employee_kilometer': 2,
            'car_id': False,
        })
        payslip = self._generate_payslip(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))
        for kilometer, daily_amount in ((2, 0.0), (3, 1.10), (30, 3.37), (31, 3.48), (33, 3.48), (34, 3.69)):
            with self.subTest(kilometer=kilometer):
                self.version.private_car_employee_kilometer = kilometer
                payslip.compute_sheet()
                self._validate_payslip(payslip, {
                    'BASIC': 3707.12,
                    'CAR.PRIV': round(daily_amount * 22.0, 2),
                }, skip_lines=True)

    def test_private_car_max_km(self):
        self.version.l10n_be_joint_committee_id.egov3_code = '302'
        self.version.write({
            'wage': 3707.12,
            'private_car_employee_kilometer': 200,
            'car_id': False,
        })
        payslip = self._generate_payslip(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))
        payslip_results = {
            'BASIC': 3707.12,
            'CAR.PRIV': 581.68,
        }
        self._validate_payslip(payslip, payslip_results, skip_lines=True)

    def test_relapse_without_guaranteed_salary(self):
        # Sick 1 Week (1 - 7 september)
        # Back 1 week (8 - 14 september)
        # Sick 4 weeks (15 septembeer - 13 october)
        # Part time sick from the 31 calendar day since the first sick day

        sick_leave_1 = self.env['hr.leave'].new({
            'name': 'Sick Time Off 1 Week',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2020, 9, 1),
            'request_date_to': datetime.date(2020, 9, 7),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 5,
        })
        sick_leave_1._compute_date_from_to()
        sick_leave_1 = self.env['hr.leave'].create(sick_leave_1._convert_to_write(sick_leave_1._cache))

        sick_leave_2 = self.env['hr.leave'].new({
            'name': 'Sick Time Off 4 Weeks',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2020, 9, 15),
            'request_date_to': datetime.date(2020, 10, 13),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 24,
            'l10n_be_sickness_relapse': True,
            'l10n_be_sickness_relapse_origin_leave_id': sick_leave_1.id,
        })
        sick_leave_2._compute_date_from_to()
        sick_leave_2 = self.env['hr.leave'].create(sick_leave_2._convert_to_write(sick_leave_2._cache))

        work_entries_vals = self.employee.version_id.generate_work_entries(datetime.date(2020, 9, 1), datetime.date(2020, 10, 31))

        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        sick_work_entry_type = self.env.ref('hr_work_entry.be_work_entry_type_sick_leave')
        partial_sick_work_entry_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_common_law_illness_after_legal_period')

        work_entries_expected_results = {
            (1, 9): sick_work_entry_type,
            (2, 9): sick_work_entry_type,
            (3, 9): sick_work_entry_type,
            (4, 9): sick_work_entry_type,
            (7, 9): sick_work_entry_type,
            (8, 9): attendance,
            (9, 9): attendance,
            (10, 9): attendance,
            (11, 9): attendance,
            (14, 9): attendance,
            (15, 9): sick_work_entry_type,
            (16, 9): sick_work_entry_type,
            (17, 9): sick_work_entry_type,
            (18, 9): sick_work_entry_type,
            (20, 9): sick_work_entry_type,
            (21, 9): sick_work_entry_type,
            (22, 9): sick_work_entry_type,
            (23, 9): sick_work_entry_type,
            (24, 9): sick_work_entry_type,
            (25, 9): sick_work_entry_type,
            (28, 9): sick_work_entry_type,
            (29, 9): sick_work_entry_type,
            (30, 9): sick_work_entry_type,
            (1, 10): sick_work_entry_type,
            (2, 10): sick_work_entry_type,
            (5, 10): sick_work_entry_type,
            (6, 10): sick_work_entry_type,
            (7, 10): sick_work_entry_type,
            (8, 10): partial_sick_work_entry_type,
            (9, 10): partial_sick_work_entry_type,
            (12, 10): partial_sick_work_entry_type,
            (13, 10): partial_sick_work_entry_type,
            (14, 10): attendance,
            (15, 10): attendance,
            (16, 10): attendance,
            (19, 10): attendance,
            (20, 10): attendance,
            (21, 10): attendance,
            (22, 10): attendance,
            (23, 10): attendance,
            (26, 10): attendance,
            (27, 10): attendance,
            (28, 10): attendance,
            (29, 10): attendance,
            (30, 10): attendance,
            (31, 10): attendance,
        }

        for vals in work_entries_vals:
            self.assertEqual(vals['work_entry_type_id'], work_entries_expected_results.get((vals['date'].day, vals['date'].month)))

        september_payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(september_payslip.worked_days_line_ids), 2)
        self.assertEqual(len(september_payslip.input_line_ids), 0)

        self._validate_worked_days(september_payslip, {
            '002.00': (5.0, 38.0, 570.77),
            '013.00': (17.0, 129.2, 2079.23),
        })

        self._validate_payslip(september_payslip)

        october_payslip = self._generate_payslip(datetime.date(2020, 10, 1), datetime.date(2020, 10, 31))

        self.assertEqual(len(october_payslip.worked_days_line_ids), 3)
        self.assertEqual(len(october_payslip.input_line_ids), 0)

        self._validate_worked_days(october_payslip, {
            '002.00': (13.0, 98.8, 1549.22),
            '013.00': (5.0, 38.0, 611.54),
            '122.00': (4.0, 30.4, 0.0),
        })

        self._validate_payslip(october_payslip)

    def test_relapse_with_guaranteed_salary(self):
        # Sick 1 Week (1 - 2 september)
        # Back 1 week (3 - 18 september)
        # Sick 2.5 weeks (21 septembeer - 7 october)
        # No part time sick as there is at least 15 days between the 2 sick time offs

        sick_leave_1 = self.env['hr.leave'].new({
            'name': 'Sick Time Off 2 Days',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2020, 9, 1),
            'request_date_to': datetime.date(2020, 9, 2),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 2,
        })
        sick_leave_1._compute_date_from_to()
        sick_leave_1 = self.env['hr.leave'].create(sick_leave_1._convert_to_write(sick_leave_1._cache))

        sick_leave_2 = self.env['hr.leave'].new({
            'name': 'Sick Time Off 2.5 Weeks',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2020, 9, 21),
            'request_date_to': datetime.date(2020, 10, 7),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 13,
        })
        sick_leave_2._compute_date_from_to()
        sick_leave_2 = self.env['hr.leave'].create(sick_leave_2._convert_to_write(sick_leave_2._cache))

        work_entries_vals = self.employee.version_id.generate_work_entries(datetime.date(2020, 9, 1), datetime.date(2020, 10, 31))

        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        sick_work_entry_type = self.env.ref('hr_work_entry.be_work_entry_type_sick_leave')

        work_entries_expected_results = {
            (1, 9): sick_work_entry_type,
            (2, 9): sick_work_entry_type,
            (3, 9): attendance,
            (4, 9): attendance,
            (7, 9): attendance,
            (8, 9): attendance,
            (9, 9): attendance,
            (10, 9): attendance,
            (11, 9): attendance,
            (14, 9): attendance,
            (15, 9): attendance,
            (16, 9): attendance,
            (17, 9): attendance,
            (18, 9): attendance,
            (20, 9): attendance,
            (21, 9): sick_work_entry_type,
            (22, 9): sick_work_entry_type,
            (23, 9): sick_work_entry_type,
            (24, 9): sick_work_entry_type,
            (25, 9): sick_work_entry_type,
            (28, 9): sick_work_entry_type,
            (29, 9): sick_work_entry_type,
            (30, 9): sick_work_entry_type,
            (1, 10): sick_work_entry_type,
            (2, 10): sick_work_entry_type,
            (5, 10): sick_work_entry_type,
            (6, 10): sick_work_entry_type,
            (7, 10): sick_work_entry_type,
            (8, 10): attendance,
            (9, 10): attendance,
            (12, 10): attendance,
            (13, 10): attendance,
            (14, 10): attendance,
            (15, 10): attendance,
            (16, 10): attendance,
            (19, 10): attendance,
            (20, 10): attendance,
            (21, 10): attendance,
            (22, 10): attendance,
            (23, 10): attendance,
            (26, 10): attendance,
            (27, 10): attendance,
            (28, 10): attendance,
            (29, 10): attendance,
            (30, 10): attendance,
            (31, 10): attendance,
        }

        for vals in work_entries_vals:
            self.assertEqual(vals['work_entry_type_id'], work_entries_expected_results.get((vals['date'].day, vals['date'].month)))

        september_payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(september_payslip.worked_days_line_ids), 2)
        self.assertEqual(len(september_payslip.input_line_ids), 0)

        self._validate_worked_days(september_payslip, {
            '002.00': (12.0, 91.2, 1426.92),
            '013.00': (10.0, 76.0, 1223.08),
        })

        self._validate_payslip(september_payslip)

        october_payslip = self._generate_payslip(datetime.date(2020, 10, 1), datetime.date(2020, 10, 31))

        self.assertEqual(len(october_payslip.worked_days_line_ids), 2)
        self.assertEqual(len(october_payslip.input_line_ids), 0)

        self._validate_worked_days(october_payslip, {
            '002.00': (17.0, 129.2, 2038.46),
            '013.00': (5.0, 38.0, 611.54),
        })

        self._validate_payslip(october_payslip)

    def test_sick_more_than_30_days(self):
        # Sick 1 september - 15 october
        # Part time sick from the 31th day
        self.version.write({
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True
        sick_leave = self.env['hr.leave'].new({
            'name': 'Sick Time Off 33 Days',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2020, 9, 1),
            'request_date_to': datetime.date(2020, 10, 15),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 33,
        })
        sick_leave._compute_date_from_to()
        sick_leave = self.env['hr.leave'].create(sick_leave._convert_to_write(sick_leave._cache))

        work_entries_vals = self.employee.version_id.generate_work_entries(datetime.date(2020, 9, 1), datetime.date(2020, 10, 31))

        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        sick_work_entry_type = self.env.ref('hr_work_entry.be_work_entry_type_sick_leave')
        partial_sick_work_entry_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_common_law_illness_after_legal_period')

        work_entries_expected_results = {
            (1, 9): sick_work_entry_type,
            (2, 9): sick_work_entry_type,
            (3, 9): sick_work_entry_type,
            (4, 9): sick_work_entry_type,
            (7, 9): sick_work_entry_type,
            (8, 9): sick_work_entry_type,
            (9, 9): sick_work_entry_type,
            (10, 9): sick_work_entry_type,
            (11, 9): sick_work_entry_type,
            (14, 9): sick_work_entry_type,
            (15, 9): sick_work_entry_type,
            (16, 9): sick_work_entry_type,
            (17, 9): sick_work_entry_type,
            (18, 9): sick_work_entry_type,
            (20, 9): sick_work_entry_type,
            (21, 9): sick_work_entry_type,
            (22, 9): sick_work_entry_type,
            (23, 9): sick_work_entry_type,
            (24, 9): sick_work_entry_type,
            (25, 9): sick_work_entry_type,
            (28, 9): sick_work_entry_type,
            (29, 9): sick_work_entry_type,
            (30, 9): sick_work_entry_type,
            (1, 10): partial_sick_work_entry_type,
            (2, 10): partial_sick_work_entry_type,
            (5, 10): partial_sick_work_entry_type,
            (6, 10): partial_sick_work_entry_type,
            (7, 10): partial_sick_work_entry_type,
            (8, 10): partial_sick_work_entry_type,
            (9, 10): partial_sick_work_entry_type,
            (12, 10): partial_sick_work_entry_type,
            (13, 10): partial_sick_work_entry_type,
            (14, 10): partial_sick_work_entry_type,
            (15, 10): partial_sick_work_entry_type,
            (16, 10): attendance,
            (19, 10): attendance,
            (20, 10): attendance,
            (21, 10): attendance,
            (22, 10): attendance,
            (23, 10): attendance,
            (26, 10): attendance,
            (27, 10): attendance,
            (28, 10): attendance,
            (29, 10): attendance,
            (30, 10): attendance,
            (31, 10): attendance,
        }

        for vals in work_entries_vals:
            self.assertEqual(vals['work_entry_type_id'], work_entries_expected_results.get((vals['date'].day, vals['date'].month)))

        september_payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(september_payslip.worked_days_line_ids), 1)
        self.assertEqual(len(september_payslip.input_line_ids), 0)

        self._validate_worked_days(september_payslip, {'013.00': (22.0, 167.2, 2650.0)})

        self._validate_payslip(september_payslip)

        october_payslip = self._generate_payslip(datetime.date(2020, 10, 1), datetime.date(2020, 10, 31))

        self.assertEqual(len(october_payslip.worked_days_line_ids), 2)
        self.assertEqual(len(october_payslip.input_line_ids), 0)

        self._validate_worked_days(october_payslip, {
            '002.00': (11.0, 83.6, 1325),
            '122.00': (11.0, 83.6, 0.0),
        })

        self._validate_payslip(october_payslip)

    def test_relapse_without_guaranteed_salary_credit_time(self):
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 1, 1),
            'contract_date_end': datetime.date(2021, 9, 30),
            'wage': 2120.0 * (5 / 4),
            'work_time_rate': 1.0,
        })

        sick_leave_1 = self.env['hr.leave'].new({
            'name': 'Sick Time Off 1 Week',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2020, 9, 1),
            'request_date_to': datetime.date(2020, 9, 7),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 5,
        })
        sick_leave_1._compute_date_from_to()
        sick_leave_1 = self.env['hr.leave'].create(sick_leave_1._convert_to_write(sick_leave_1._cache))

        sick_leave_2 = self.env['hr.leave'].new({
            'name': 'Sick Time Off 4 Weeks',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2020, 9, 15),
            'request_date_to': datetime.date(2020, 10, 13),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 24,
            'l10n_be_sickness_relapse': True,
            'l10n_be_sickness_relapse_origin_leave_id': sick_leave_1.id,
        })
        sick_leave_2._compute_date_from_to()
        sick_leave_2 = self.env['hr.leave'].create(sick_leave_2._convert_to_write(sick_leave_2._cache))

        work_entries_vals = self.employee.version_id.generate_work_entries(datetime.date(2020, 9, 1), datetime.date(2020, 10, 31))

        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        sick_work_entry_type = self.env.ref('hr_work_entry.be_work_entry_type_sick_leave')
        partial_sick_work_entry_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_common_law_illness_after_legal_period')
        credit_time_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_credit_time')

        work_entries_expected_results = {
            (1, 9): sick_work_entry_type,
            (2, 9): credit_time_type,
            (3, 9): sick_work_entry_type,
            (4, 9): sick_work_entry_type,
            (7, 9): sick_work_entry_type,
            (8, 9): attendance,
            (9, 9): credit_time_type,
            (10, 9): attendance,
            (11, 9): attendance,
            (14, 9): attendance,
            (15, 9): sick_work_entry_type,
            (16, 9): credit_time_type,
            (17, 9): sick_work_entry_type,
            (18, 9): sick_work_entry_type,
            (20, 9): sick_work_entry_type,
            (21, 9): sick_work_entry_type,
            (22, 9): sick_work_entry_type,
            (23, 9): credit_time_type,
            (24, 9): sick_work_entry_type,
            (25, 9): sick_work_entry_type,
            (28, 9): sick_work_entry_type,
            (29, 9): sick_work_entry_type,
            (30, 9): credit_time_type,
            (1, 10): sick_work_entry_type,
            (2, 10): sick_work_entry_type,
            (5, 10): sick_work_entry_type,
            (6, 10): sick_work_entry_type,
            (7, 10): credit_time_type,
            (8, 10): partial_sick_work_entry_type,
            (9, 10): partial_sick_work_entry_type,
            (12, 10): partial_sick_work_entry_type,
            (13, 10): partial_sick_work_entry_type,
            (14, 10): credit_time_type,
            (15, 10): attendance,
            (16, 10): attendance,
            (19, 10): attendance,
            (20, 10): attendance,
            (21, 10): credit_time_type,
            (22, 10): attendance,
            (23, 10): attendance,
            (26, 10): attendance,
            (27, 10): attendance,
            (28, 10): credit_time_type,
            (29, 10): attendance,
            (30, 10): attendance,
            (31, 10): attendance,
        }
        for vals in work_entries_vals:
            self.assertEqual(vals['work_entry_type_id'], work_entries_expected_results.get((vals['date'].day, vals['date'].month)))

        september_payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(september_payslip.worked_days_line_ids), 3)
        self.assertEqual(len(september_payslip.input_line_ids), 0)

        self._validate_worked_days(september_payslip, {
            '002.00': (4.0, 30.4, 530.0),
            '013.00': (13.0, 98.8, 1590.0),
            '147.00': (5.0, 38.0, 0.0),
        })

        self._validate_payslip(september_payslip)

        october_payslip = self._generate_payslip(datetime.date(2020, 10, 1), datetime.date(2020, 10, 31))

        self.assertEqual(len(october_payslip.worked_days_line_ids), 4)
        self.assertEqual(len(october_payslip.input_line_ids), 0)

        self._validate_worked_days(october_payslip, {
            '002.00': (10.0, 76.0, 1141.53),
            '013.00': (4.0, 30.4, 489.23),
            '122.00': (4.0, 30.4, 0.0),
            '147.00': (4.0, 30.4, 0.0),
        })

        self._validate_payslip(october_payslip)

    def test_relapse_with_guaranteed_salary_credit_time(self):
        # Sick 2 days (1 - 2 september)
        # Back 1 week (3 - 18 september)
        # Sick 2.5 weeks (21 septembeer - 7 october)
        # No part time sick as there is at least 15 days between the 2 sick time offs
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 1, 1),
            'contract_date_end': datetime.date(2021, 9, 30),
            'wage': 2120.0 * (5 / 4),
            'work_time_rate': 1.0,
        })

        sick_leave_1 = self.env['hr.leave'].new({
            'name': 'Sick Time Off 2 Days',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2020, 9, 1),
            'request_date_to': datetime.date(2020, 9, 2),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 2,
        })
        sick_leave_1._compute_date_from_to()
        sick_leave_1 = self.env['hr.leave'].create(sick_leave_1._convert_to_write(sick_leave_1._cache))

        sick_leave_2 = self.env['hr.leave'].new({
            'name': 'Sick Time Off 2.5 Weeks',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2020, 9, 21),
            'request_date_to': datetime.date(2020, 10, 7),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 13,
        })
        sick_leave_2._compute_date_from_to()
        sick_leave_2 = self.env['hr.leave'].create(sick_leave_2._convert_to_write(sick_leave_2._cache))

        work_entries_vals = self.employee.version_id.generate_work_entries(datetime.date(2020, 9, 1), datetime.date(2020, 10, 31))

        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        sick_work_entry_type = self.env.ref('hr_work_entry.be_work_entry_type_sick_leave')
        credit_time_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_credit_time')

        work_entries_expected_results = {
            (1, 9): sick_work_entry_type,
            (2, 9): credit_time_type,
            (3, 9): attendance,
            (4, 9): attendance,
            (7, 9): attendance,
            (8, 9): attendance,
            (9, 9): credit_time_type,
            (10, 9): attendance,
            (11, 9): attendance,
            (14, 9): attendance,
            (15, 9): attendance,
            (16, 9): credit_time_type,
            (17, 9): attendance,
            (18, 9): attendance,
            (20, 9): attendance,
            (21, 9): sick_work_entry_type,
            (22, 9): sick_work_entry_type,
            (23, 9): credit_time_type,
            (24, 9): sick_work_entry_type,
            (25, 9): sick_work_entry_type,
            (28, 9): sick_work_entry_type,
            (29, 9): sick_work_entry_type,
            (30, 9): credit_time_type,
            (1, 10): sick_work_entry_type,
            (2, 10): sick_work_entry_type,
            (5, 10): sick_work_entry_type,
            (6, 10): sick_work_entry_type,
            (7, 10): credit_time_type,
            (8, 10): attendance,
            (9, 10): attendance,
            (12, 10): attendance,
            (13, 10): attendance,
            (14, 10): credit_time_type,
            (15, 10): attendance,
            (16, 10): attendance,
            (19, 10): attendance,
            (20, 10): attendance,
            (21, 10): credit_time_type,
            (22, 10): attendance,
            (23, 10): attendance,
            (26, 10): attendance,
            (27, 10): attendance,
            (28, 10): credit_time_type,
            (29, 10): attendance,
            (30, 10): attendance,
            (31, 10): attendance,
        }

        for vals in work_entries_vals:
            self.assertEqual(vals['work_entry_type_id'], work_entries_expected_results.get((vals['date'].day, vals['date'].month)))

        september_payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(september_payslip.worked_days_line_ids), 3)
        self.assertEqual(len(september_payslip.input_line_ids), 0)

        self._validate_worked_days(september_payslip, {
            '002.00': (10.0, 76.0, 1263.85),
            '013.00': (7.0, 53.2, 856.15),
            '147.00': (5.0, 38.0, 0.0),
        })

        self._validate_payslip(september_payslip)

        october_payslip = self._generate_payslip(datetime.date(2020, 10, 1), datetime.date(2020, 10, 31))

        self.assertEqual(len(october_payslip.worked_days_line_ids), 3)
        self.assertEqual(len(october_payslip.input_line_ids), 0)

        self._validate_worked_days(october_payslip, {
            '002.00': (14.0, 106.4, 1630.77),
            '013.00': (4.0, 30.4, 489.23),
            '147.00': (4.0, 30.4, 0.0),
        })

        self._validate_payslip(october_payslip)

    def test_sick_more_than_30_days_credit_time(self):
        # Sick 1 september - 15 october
        # Part time sick from the 31th day
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 1, 1),
            'contract_date_end': datetime.date(2021, 9, 30),
            'wage': 2120.0 * (5 / 4),
            'work_time_rate': 1.0,
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True

        sick_leave = self.env['hr.leave'].new({
            'name': 'Sick Time Off 33 Days',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2020, 9, 1),
            'request_date_to': datetime.date(2020, 10, 15),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 33,
        })
        sick_leave._compute_date_from_to()
        sick_leave = self.env['hr.leave'].create(sick_leave._convert_to_write(sick_leave._cache))

        work_entries_vals = self.employee.version_id.generate_work_entries(datetime.date(2020, 9, 1), datetime.date(2020, 10, 31))

        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        sick_work_entry_type = self.env.ref('hr_work_entry.be_work_entry_type_sick_leave')
        partial_sick_work_entry_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_common_law_illness_after_legal_period')
        credit_time_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_credit_time')

        work_entries_expected_results = {
            (1, 9): sick_work_entry_type,
            (2, 9): credit_time_type,
            (3, 9): sick_work_entry_type,
            (4, 9): sick_work_entry_type,
            (7, 9): sick_work_entry_type,
            (8, 9): sick_work_entry_type,
            (9, 9): credit_time_type,
            (10, 9): sick_work_entry_type,
            (11, 9): sick_work_entry_type,
            (14, 9): sick_work_entry_type,
            (15, 9): sick_work_entry_type,
            (16, 9): credit_time_type,
            (17, 9): sick_work_entry_type,
            (18, 9): sick_work_entry_type,
            (20, 9): sick_work_entry_type,
            (21, 9): sick_work_entry_type,
            (22, 9): sick_work_entry_type,
            (23, 9): credit_time_type,
            (24, 9): sick_work_entry_type,
            (25, 9): sick_work_entry_type,
            (28, 9): sick_work_entry_type,
            (29, 9): sick_work_entry_type,
            (30, 9): credit_time_type,
            (1, 10): partial_sick_work_entry_type,
            (2, 10): partial_sick_work_entry_type,
            (5, 10): partial_sick_work_entry_type,
            (6, 10): partial_sick_work_entry_type,
            (7, 10): credit_time_type,
            (8, 10): partial_sick_work_entry_type,
            (9, 10): partial_sick_work_entry_type,
            (12, 10): partial_sick_work_entry_type,
            (13, 10): partial_sick_work_entry_type,
            (14, 10): credit_time_type,
            (15, 10): partial_sick_work_entry_type,
            (16, 10): attendance,
            (19, 10): attendance,
            (20, 10): attendance,
            (21, 10): credit_time_type,
            (22, 10): attendance,
            (23, 10): attendance,
            (26, 10): attendance,
            (27, 10): attendance,
            (28, 10): credit_time_type,
            (29, 10): attendance,
            (30, 10): attendance,
            (31, 10): attendance,
        }

        for vals in work_entries_vals:
            self.assertEqual(vals['work_entry_type_id'], work_entries_expected_results.get((vals['date'].day, vals['date'].month)))

        september_payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(september_payslip.worked_days_line_ids), 2)
        self.assertEqual(len(september_payslip.input_line_ids), 0)

        self._validate_worked_days(september_payslip, {
            '013.00': (17.0, 129.2, 2120.0),
            '147.00': (5.0, 38.0, 0.0),
        })

        self._validate_payslip(september_payslip)

        october_payslip = self._generate_payslip(datetime.date(2020, 10, 1), datetime.date(2020, 10, 31))

        self.assertEqual(len(october_payslip.worked_days_line_ids), 3)
        self.assertEqual(len(october_payslip.input_line_ids), 0)

        self._validate_worked_days(october_payslip, {
            '002.00': (9.0, 68.4, 1019.21),
            '122.00': (9.0, 68.4, 0.0),
            '147.00': (4.0, 30.4, 0.0),
        })

        self._validate_payslip(october_payslip)

    def test_small_unemployment(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 14, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 14, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_small_unemployment').id
        }])

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (21.0, 159.6, 2527.69),
            '007.00': (1.0, 7.6, 122.31),
        })

        self._validate_payslip(payslip)

    def test_small_unemployment_1_week(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 14, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 18, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_small_unemployment').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 9, 21, 6, 0, 0),
            'date_to': datetime.datetime(2020, 9, 22, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_small_unemployment').id
        }])

        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (15.0, 114.0, 1793.85),
            '007.00': (7.0, 53.2, 856.15),
        })

        self._validate_payslip(payslip)

    def test_full_time_credit_time_atn_negative_net(self):
        self.version.write({
            'resource_calendar_id': self.resource_calendar_0_hours_per_week.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 8, 1),
            'contract_date_end': datetime.date(2020, 11, 30),
            'wage': 0.0,
            'work_time_rate': 0,
        })
        payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 1)

        self._validate_worked_days(payslip, {'147.00': (22.0, 167.2, 0.0)})

        self._validate_payslip(payslip)

    def test_training_time_off_above_threshold(self):
        self.leaves = self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_4_5_thurday_off.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2020, 5, 4, 5, 0, 0),
            'date_to': datetime.datetime(2020, 5, 4, 16, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_4_5_thurday_off.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2020, 5, 5, 5, 0, 0),
            'date_to': datetime.datetime(2020, 5, 5, 16, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_4_5_thurday_off.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 5, 6, 6, 0, 0),
            'date_to': datetime.datetime(2020, 5, 6, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_training_time_off').id
        }])

        self.car.write({
            'contract_date_start': datetime.date(2014, 6, 10),
            'co2': 98.0,
            'car_value': 25686.82,
            'acquisition_date': datetime.date(2014, 6, 10)
        })

        self.vehicle_contract.write({
            'name': "Test Contract",
            'vehicle_id': self.car.id,
            'company_id': self.env.company.id,
            'start_date': datetime.date(2020, 11, 30),
            'expiration_date': datetime.date(2021, 11, 30),
            'state': "open",
            'cost_generated': 0.0,
            'cost_frequency': "monthly",
            'recurring_cost_amount_depreciated': 405.315
        })

        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_thurday_off.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 4, 1),
            'contract_date_end': datetime.date(2020, 11, 30),
            'wage': 3608.66 * (5 / 4),
            'fuel_card': 200.0,
            'mobile': 0.0,
            'ip_wage_rate': 0.25,
            'work_time_rate': 1.0,
        })

        payslip = self._generate_payslip(datetime.date(2020, 5, 1), datetime.date(2020, 5, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 4)

        self._validate_worked_days(payslip, {
            '002.00': (14.0, 106.4, 2984.09),
            '024.00': (1.0, 7.6, 135.14),
            '147.00': (4.0, 30.4, 0.0),
            '006.00': (2.0, 15.2, 416.38),
        })

        self._validate_payslip(payslip)

    def test_training_time_off_below_threshold(self):
        self.leaves = self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_4_5_thurday_off.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2020, 5, 4, 5, 0, 0),
            'date_to': datetime.datetime(2020, 5, 4, 16, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_4_5_thurday_off.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2020, 5, 5, 5, 0, 0),
            'date_to': datetime.datetime(2020, 5, 5, 16, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_4_5_thurday_off.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2020, 5, 6, 6, 0, 0),
            'date_to': datetime.datetime(2020, 5, 6, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_training_time_off').id
        }])

        self.car.write({
            'contract_date_start': datetime.date(2014, 6, 10),
            'co2': 98.0,
            'car_value': 25686.82,
            'acquisition_date': datetime.date(2014, 6, 10)
        })

        self.vehicle_contract.write({
            'name': "Test Contract",
            'vehicle_id': self.car.id,
            'company_id': self.env.company.id,
            'start_date': datetime.date(2020, 11, 30),
            'expiration_date': datetime.date(2021, 11, 30),
            'state': "open",
            'cost_generated': 0.0,
            'cost_frequency': "monthly",
            'recurring_cost_amount_depreciated': 405.315
        })

        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_thurday_off.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 4, 1),
            'contract_date_end': datetime.date(2020, 11, 30),
            'wage': 2120 * (5 / 4),
            'fuel_card': 200.0,
            'mobile': 0.0,
            'ip_wage_rate': 0.25,
            'work_time_rate': 1.0,
        })

        payslip = self._generate_payslip(datetime.date(2020, 5, 1), datetime.date(2020, 5, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 4)

        self._validate_worked_days(payslip, {
            '002.00': (14.0, 106.4, 1753.07),
            '024.00': (1.0, 7.6, 122.31),
            '147.00': (4.0, 30.4, 0.0),
            '006.00': (2.0, 15.2, 244.62),
        })

        self._validate_payslip(payslip)

    def test_variable_revenues(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2020, 9, 23, 5, 0, 0),
            'date_to': datetime.datetime(2020, 9, 23, 16, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }])

        self.version.commission_on_target = 1000
        self.version.contract_date_start = datetime.date(2019, 1, 1)

        commission_payslip = self._generate_payslip(datetime.date(2019, 12, 1), datetime.date(2019, 12, 31), input_values={'COMMISSION': 8484})
        self.employee.write({'review_state': '1_reviewed'})
        commission_payslip.action_payslip_done()

        self.assertEqual(len(commission_payslip.worked_days_line_ids), 1)

        self._validate_payslip(commission_payslip)

        classic_payslip = self._generate_payslip(datetime.date(2020, 9, 1), datetime.date(2020, 9, 30))

        self._validate_worked_days(classic_payslip, {
            '002.00': (21.0, 159.6, 2527.69),
            '006.00': (1.0, 7.6, 122.31),
        })

        payslip_results = {
            'BASIC': 2650.0,
            'DH_BASIC': 0.0,
            'COM_LOSS_PH': 33.94,
            'ATN.INT': 5.0,
            'ATN.MOB': 4.0,
            'SALARY': 2692.94,
            'DH_SALARY': 0.0,
            'ONSS_BASE_TOTAL': 2692.94,
            'ONSS': -351.97,
            'ONSS_DOUBLE_HOLIDAY': 0.0,
            'ONSSTOTAL': 351.97,
            'ATN.CAR': 130.5,
            'GROSSIP': 2471.47,
            'IP.PART': -662.5,
            'ONSS.NO.WT': 86.59,
            'WITHHOLDING_BASE_TOTAL': 1895.56,
            'GROSS': 1895.56,
            'DH_GROSS': 0.0,
            'GROSS.M': 1895.56,
            'GROSS.Y': 22680.0,
            'F_PROFESSIONAL_FEES': -4890.0,
            'TRANSPORT_TAX_DED': -410.4,
            'GROSS.NET.Y': 17379.6,
            'Y.P.P': 5343.95,
            'P.P.MARITAL.DED': -2097.2,
            'P.P.FAMILY.DED': 0.0,
            'P.P': -270.56,
            'DH_PP': 0.0,
            'PPTOTAL': 270.56,
            'ATN_DED': -139.5,
            'M.ONSS': 0.0,
            'MEAL_V_EMP': -22.89,
            'MEAL_VOUCHER_EMPLOYER': 133.56,
            'REP.FEES': 150.0,
            'IP': 662.5,
            'IP.DED': -36.7,
            'NET_TO_RECOVER': 0.0,
            'NET': 2151.82,
            'REMUNERATION': 2021.44,
            'CO2FEE': 27.24,
            'ONSSEMPLOYERBASIC': 673.23,
            'ONSSEMPLOYER_255': 0.54,
            'ONSSEMPLOYER_809': 10.5,
            'ONSSEMPLOYER_810': 2.69,
            'ONSSEMPLOYER_831': 6.19,
            'ONSSEMPLOYER_855': 45.51,
            'ONSSEMPLOYER_859': 2.69,
            'ONSSEMPLOYER': 596.46,
            'HOLIDAY_TAX_PROV_BASE': 2692.94,
            'HOLIDAY_TAX_PROV': 490.12,
        }
        self._validate_payslip(classic_payslip, payslip_results, skip_lines=True)

    def test_credit_time_keep_old_time_off(self):
        # Test Case: When setting a credit time, we change the calendar
        # and thus it could be possible to loose the time off that were planned
        # and validated before the contract change.
        # Ensure that the time off are not lost.

        sick_time_off = self.env['hr.leave'].new({
            'name': 'Maternity Time Off : 15 weeks',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2020, 11, 9),
            'request_date_to': datetime.date(2020, 11, 10),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 2,
        })
        sick_time_off._compute_date_from_to()
        sick_time_off = self.env['hr.leave'].create(sick_time_off._convert_to_write(sick_time_off._cache))

        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week,
            'work_time_rate': 0.8,
            'wage': 2120.0,
            'contract_date_start': datetime.date(2020, 9, 16),
            'contract_date_end': datetime.date(2020, 12, 31),
        })

        work_entries_vals = self.version.generate_work_entries(datetime.date(2020, 11, 1), datetime.date(2020, 11, 30))
        sick_work_entries = [vals for vals in work_entries_vals if vals['work_entry_type_id'] == self.sick_time_off_type]
        self.assertEqual(len(sick_work_entries), 2)

    def test_accounting_entries(self):
        # Test case: Create 2 payslips (1 classic / 1 low salary)
        # Generate and validate the accounting entries
        # 1rst contract
        self.version.write({
            'private_car_employee_kilometer': self.version.distance_home_work,
        })

        # Second contract
        second_employee = self.env['hr.employee'].sudo().create([{
            'name': "Test Employee",
            'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'marital': "single",
            'distance_home_work': 75,
            'car_id': False,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'contract_date_start': datetime.date(2018, 12, 31),
            'date_version': datetime.date(2018, 12, 31),
            'wage': 2000.0,
            'private_car_employee_kilometer': 75,
            'fuel_card': 150.0,
            'internet': 38.0,
            'mobile': 30.0,
            'meal_voucher_amount': 7.45,
            'ip_wage_rate': 0.25,
            'l10n_be_lsa_monthly_misc_base_amount': 150,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        }])

        payslip_run = self.env["hr.payslip.run"].create({
            "date_start": '2020-12-01',
            "date_end": '2020-12-31',
            "structure_id": self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            "version_ids": [self.version.id, second_employee.version_id.id],
        })

        payslip_run._generate_payslips()

        payslips = payslip_run.slip_ids
        self.assertEqual(len(payslips), 2)

        payslip_1 = payslips.filtered(lambda p: p.employee_id == self.employee)
        self.assertEqual(len(payslip_1.worked_days_line_ids), 1)
        self.assertEqual(len(payslip_1.input_line_ids), 1)

        self._validate_worked_days(payslip_1, {'002.00': (23.0, 174.8, 2650.0)})

        self._validate_payslip(payslip_1)

        payslip_2 = payslips.filtered(lambda p: p.employee_id == second_employee)
        self.assertEqual(len(payslip_2.worked_days_line_ids), 1)
        self.assertEqual(len(payslip_2.input_line_ids), 1)

        self._validate_worked_days(payslip_2, {'002.00': (23.0, 174.8, 2000.0)})

        self._validate_payslip(payslip_2)

        # Generate accounting entries
        payslip_run.action_validate()

        balance = 10017.62
        expected_move_lines = [
            {'account_id.code': '620200', 'debit': 7782.06, 'credit':    0.00},  # remuneration
            {'account_id.code': '453000', 'debit':    0.00, 'credit': 1722.22},  # PP
            {'account_id.code': '643000', 'debit': 1162.50, 'credit':    0.00},  # IP
            {'account_id.code': '453000', 'debit':    0.00, 'credit':   64.40},  # IP DED
            {'account_id.code': '454000', 'debit':    0.00, 'credit':  996.44},  # ONSS - Emp Bonus
            {'account_id.code': '620200', 'debit':  191.44, 'credit':    0.00},  # Private Car
            {'account_id.code': '620200', 'debit':  300.0, 'credit':    0.00},  # Representation Fees
            {'account_id.code': '743000', 'debit':    0.00, 'credit':   50.14},  # Meal vouchers
            {'account_id.code': '455000', 'debit':    0.00, 'credit': 6602.80},  # NET
            {'account_id.code': '454000', 'debit':    0.00, 'credit':  581.62},  # ONSS Employer
            {'account_id.code': '621000', 'debit':  581.62, 'credit':    0.00},  # ONSS Employer
        ]
        move_lines = [
            {'account_id.code': line.account_id.code, 'debit': line.debit, 'credit': line.credit}
            for line in payslip_1.move_id.line_ids
        ]

        self.assertEqual(len(move_lines), len(expected_move_lines), f"The payslip generated {len(move_lines)} account move lines instead of {len(expected_move_lines)}")
        self.assertAlmostEqual(sum(l['debit'] for l in move_lines), balance, places=2, msg=f"The sum of all debit operations of the payslip move line should have been {balance}")
        self.assertAlmostEqual(sum(l['credit'] for l in move_lines), balance, places=2, msg=f"The sum of all credit operations of the payslip move line should have been {balance}")

        expected_move_lines.sort(key=lambda l: [*l.values()])
        move_lines.sort(key=lambda l: [*l.values()])
        for line, expected_line in zip(move_lines, expected_move_lines):
            self.assertEqual(
                expected_line['account_id.code'], line['account_id.code'],
                f"Missing account line {expected_line['account_id.code']} from payslip"
            )
            self.assertEqual(
                expected_line['debit'], line['debit'],
                f"Expected debit of {expected_line['debit']} for account line {line['account_id.code']} but instead got {line['debit']}"
            )
            self.assertEqual(
                expected_line['credit'], line['credit'],
                f"Expected credit of {expected_line['credit']} for account line {line['account_id.code']} but instead got {line['credit']}"
            )

    def test_long_term_sick_leave(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2020, 3, 17, 6, 0, 0),
            'date_to': datetime.datetime(2020, 3, 17, 18, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }])

        long_term_sick = self.env['hr.leave'].new({  # long sick leave type is unassimilated so it doesn't contribute to holiday pay
            'name': 'Long Term Sick',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.long_term_sick_time_off_type.id,
            'request_date_from': datetime.date(2020, 3, 1),
            'request_date_to': datetime.date(2020, 3, 31),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 22,
        })
        long_term_sick._compute_date_from_to()
        long_term_sick = self.env['hr.leave'].create(long_term_sick._convert_to_write(long_term_sick._cache))

        payslip = self._generate_payslip(datetime.date(2020, 3, 1), datetime.date(2020, 3, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 1)

        self._validate_worked_days(payslip, {'123.00': (22.0, 167.2, 0.0)})

        self._validate_payslip(payslip)

    def test_commissions_with_low_salary_no_employment_bonus(self):
        self.version.write({
            'wage': 2300,
            'ip_wage_rate': 0,
        })

        payslip = self._generate_payslip(datetime.date(2021, 1, 1), datetime.date(2021, 1, 31), input_values={'COMMISSION': 3000})

        self.assertEqual(len(payslip.worked_days_line_ids), 1)

        self._validate_worked_days(payslip, {'002.00': (21.0, 159.6, 2300.0)})

        self._validate_payslip(payslip)

    def test_private_car_capping_part_time(self):
        # Private car reimbursement should be 10 intead of 50 for employees working 1 day per week
        self.employee.distance_home_work = 25

        self.version.write({
            'transport_mode_car': False,
            'private_car_employee_kilometer': 25,
            'resource_calendar_id': self.resource_calendar_1_5_monday_on.id,
            'ip_wage_rate': 0,
        })

        payslip = self._generate_payslip(datetime.date(2021, 1, 1), datetime.date(2021, 1, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 1)

        self._validate_worked_days(payslip, {'002.00': (4.0, 30.4, 2650.0)})

        self._validate_payslip(payslip)

    def test_private_car_capping_part_time_1_time_off(self):
        # Private car reimbursement should be 10 intead of 50 for employees working 1 day per week
        self.employee.distance_home_work = 25

        self.version.write({
            'transport_mode_car': False,
            'resource_calendar_id': self.resource_calendar_1_5_monday_on.id,
            'ip_wage_rate': 0,
            'private_car_employee_kilometer': 25,
        })

        self.leaves = self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_1_5_monday_on.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2021, 1, 11, 7, 0, 0),
            'date_to': datetime.datetime(2021, 1, 11, 15, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id
        }])
        payslip = self._generate_payslip(datetime.date(2021, 1, 1), datetime.date(2021, 1, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (3.0, 22.8, 2038.46),
            '013.00': (1.0, 7.6, 611.54),
        })

        self._validate_payslip(payslip)

    def test_private_car_reimbursement(self):
        self.employee.distance_home_work = 25
        self.version.write({
            'private_car_employee_kilometer': 25,
            'transport_mode_car': False,
            'l10n_be_mobility_budget': False,
        })

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        self._validate_payslip(payslip)

    def test_private_car_reimbursement_with_low_salary_and_other_benefits(self):
        self.employee.distance_home_work = 25
        self.version.write({
            'wage': 1000,
            'private_car_employee_kilometer': 25,
            'transport_mode_car': False,
        })

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        self._validate_payslip(payslip)

    def test_private_car_reimbursement_with_high_salary_and_other_benefits(self):
        self.employee.distance_home_work = 25
        self.version.write({
            'wage': 9000,
            'private_car_employee_kilometer': 25,
            'transport_mode_car': False,
            'l10n_be_mobility_budget': True,
        })
        self.assertEqual(self.version.l10n_be_mobility_budget_amount, 17244.0)

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        self._validate_payslip(payslip)

    def test_maternity_time_off_bank_holidays(self):
        # Maternity time off > bank holiday after 30 days
        # Means that the time off isn't paid by the employer after 30 days
        # but is paid in this case

        maternity_time_off = self.env['hr.leave'].new({
            'name': 'Maternity Time Off : 2 days',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_maternity').id,
            'request_date_from': datetime.date(2020, 12, 31),
            'request_date_to': datetime.date(2021, 1, 1),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 2,
        })
        maternity_time_off._compute_date_from_to()
        maternity_time_off = self.env['hr.leave'].create(maternity_time_off._convert_to_write(maternity_time_off._cache))

        self.env['resource.calendar.leaves'].create({
            'name': "Bank Holiday",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2021, 1, 1, 5, 0, 0),
            'date_to': datetime.datetime(2021, 1, 1, 18, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        })

        payslip = self._generate_payslip(datetime.date(2021, 1, 1), datetime.date(2021, 1, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (20.0, 152.0, 2527.69),
            '006.00': (1.0, 7.6, 122.31),
        })

    def test_extra_legal_representation_fees(self):
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_misc_base_amount')]).write({'active': True})
        self.version.write({
            'l10n_be_lsa_monthly_misc_base_amount': 150,
        })
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2021, 1, 4, 7, 0, 0),
            'date_to': datetime.datetime(2021, 1, 4, 15, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_extra_legal').id,
        }])

        payslip = self._generate_payslip(datetime.date(2021, 1, 1), datetime.date(2021, 1, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (20.0, 152.0, 2527.69),
            '011.00': (1.0, 7.6, 122.31),
        })

        self.assertAlmostEqual(payslip._get_line_values(['REP.FEES'])['REP.FEES'][payslip.id]['total'], 150, places=2)
        self.assertAlmostEqual(payslip._get_line_values(['REP.FEES.VOLATILE'])['REP.FEES.VOLATILE'][payslip.id]['total'], 0.0, places=2)

    def test_credit_time_representation_fees(self):
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_misc_base_amount')]).write({'active': True})
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 12, 1),
            'contract_date_end': datetime.date(2021, 2, 28),
            'wage': 2650.0 * (5 / 4),
            'work_time_rate': 1.0,
            'l10n_be_lsa_monthly_misc_base_amount': 150,
        })

        payslip = self._generate_payslip(datetime.date(2021, 1, 1), datetime.date(2021, 1, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (17.0, 129.2, 2650.0),
            '147.00': (4.0, 30.4, 0.0),
        })

        self.assertAlmostEqual(payslip._get_line_values(['REP.FEES'])['REP.FEES'][payslip.id]['total'], 150, places=2)
        self.assertAlmostEqual(payslip._get_line_values(['REP.FEES.VOLATILE'])['REP.FEES.VOLATILE'][payslip.id]['total'], 0.0, places=2)

    def test_credit_time_representation_fees_prorated(self):
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_misc_base_amount')]).write({'active': True})
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2020, 12, 1),
            'contract_date_end': datetime.date(2021, 2, 28),
            'wage': 2650.0 * (5 / 4),
            'work_time_rate': 1.0,
            'l10n_be_lsa_monthly_misc_base_amount': 279.31,  # At the time of this payslip the threshold was 279.31
            'l10n_be_lsa_monthly_pro_other_amount': 120.69,
        })

        payslip = self._generate_payslip(datetime.date(2021, 1, 1), datetime.date(2021, 1, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (17.0, 129.2, 2650.0),
            '147.00': (4.0, 30.4, 0.0),
        })

        self.assertAlmostEqual(payslip._get_line_values(['REP.FEES'])['REP.FEES'][payslip.id]['total'], 279.31, places=2)
        self.assertAlmostEqual(payslip._get_line_values(['REP.FEES.VOLATILE'])['REP.FEES.VOLATILE'][payslip.id]['total'], 97.7, places=2)

    def test_contractual_part_time_representation_fees(self):
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_misc_base_amount')]).write({'active': True})
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off.id,
            'l10n_be_lsa_monthly_misc_base_amount': 150,
        })

        payslip = self._generate_payslip(datetime.date(2021, 1, 1), datetime.date(2021, 1, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 1)

        self._validate_worked_days(payslip, {'002.00': (17.0, 129.2, 2650.0)})

        self.assertAlmostEqual(payslip._get_line_values(['REP.FEES'])['REP.FEES'][payslip.id]['total'], 150, places=2)
        self.assertAlmostEqual(payslip._get_line_values(['REP.FEES.VOLATILE'])['REP.FEES.VOLATILE'][payslip.id]['total'], 0.0, places=2)

    def test_replacement_amount_worked_days_computation(self):
        """
        Test replacement amount logic for a single month payslip:
        - Out Of Contract '000.00' -> replacement_amount = 0
        - Regular work (002.00) -> amount > 0, replacement_amount = 0
        - Unpaid and non-assimilated work entry -> replacement_amount = 0
        """

        # UNPAID_AND_UNASSIMILATED Category
        be_work_entry_type_unjustified_reason_leave = self.env.ref('hr_work_entry.l10n_be_work_entry_type_unjustified_reason')

        self.version.write({
            'contract_date_start': datetime.date(2026, 1, 10),
            'contract_date_end': datetime.date(2026, 1, 31),
        })

        self.env['hr.leave.allocation'].create({
            "employee_id": self.employee.id,
            "work_entry_type_id": be_work_entry_type_unjustified_reason_leave.id,
            "number_of_days": 10,
            "date_from": datetime.date(2026, 1, 11),
        }).action_approve()

        self.env['hr.leave'].create({
            "name": 'unpaid leave non-assimilated',
            "employee_id": self.employee.id,
            "work_entry_type_id": be_work_entry_type_unjustified_reason_leave.id,
            "request_date_from": datetime.date(2026, 1, 11),
            "request_date_to": datetime.date(2026, 1, 15)
        })

        payslip = self.env['hr.payslip'].create({
            'name': 'Jan 2026 Test Payslip',
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'date_from': datetime.date(2026, 1, 1),
            'date_to': datetime.date(2026, 1, 31),
            'company_id': self.env.company.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
        })

        payslip.compute_sheet()
        payslip.action_payslip_done()

        self.assertEqual(len(payslip.worked_days_line_ids), 3)

        self.assertEqual(payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '000.00').l10n_be_replacement_amount, 0.0,
                        "Out of contract must calculate replacement_amount = 0")
        self.assertEqual(payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '002.00').l10n_be_replacement_amount, 0.0,
                         "Work lines with regular wage must have replacement_amount = 0")
        self.assertEqual(payslip.worked_days_line_ids.filtered(lambda wd: wd.code == 'LEAVE_UNPAID_NON_ASSIMILATED').l10n_be_replacement_amount, 0.0,
                         "Unpaid non-assimilated lines must have replacement_amount = 0")

    def test_employment_bonus_half_days(self):
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2021, 3, 1, 7, 0, 0),
            'date_to': datetime.datetime(2021, 3, 1, 11, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id
        }])

        self.version.write({
            'wage': 2500.0,
        })

        payslip = self._generate_payslip(datetime.date(2021, 3, 1), datetime.date(2021, 3, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)
        self.assertEqual(sum(payslip.worked_days_line_ids.mapped('number_of_days')), 23)
        self.assertAlmostEqual(sum(payslip.worked_days_line_ids.mapped('number_of_hours')), 23 * 7.6)
        att_wdl = payslip.worked_days_line_ids.filtered(lambda wdl: wdl.work_entry_type_id.code == '002.00')
        self.assertEqual(att_wdl.number_of_days, 22.5)  # Attendance
        self.assertAlmostEqual(att_wdl.number_of_hours, 170.8)
        self.assertEqual(att_wdl.amount, 2439.27)
        leave_wdl = payslip.worked_days_line_ids.filtered(lambda wdl: wdl.work_entry_type_id.code == '013.00')
        self.assertEqual(leave_wdl.number_of_days, 0.5)  # leave
        self.assertAlmostEqual(leave_wdl.number_of_hours, 4)
        self.assertEqual(leave_wdl.amount, 60.73)

        self._validate_payslip(payslip)

    def test_employee_departure(self):
        self._generate_departure_data()
        # - Holiday Pay N
        # - Holiday Pay N-1
        struct_n1_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n1_holidays')
        struct_n_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays')

        self.holiday_pay_2019 = self.departure_payslips.filtered(lambda p: p.struct_id == struct_n1_id)
        self.holiday_pay_2020 = self.departure_payslips.filtered(lambda p: p.struct_id == struct_n_id)

        self.assertEqual(len(self.termination_fees.worked_days_line_ids), 0)
        self._validate_payslip(self.termination_fees)

        self.holiday_pay_2020.compute_sheet()

        self.assertEqual(len(self.holiday_pay_2020.worked_days_line_ids), 0)
        self._validate_payslip(self.holiday_pay_2020)

        self.holiday_pay_2019.compute_sheet()

        self.assertEqual(len(self.holiday_pay_2019.worked_days_line_ids), 0)
        self._validate_payslip(self.holiday_pay_2019)

    def test_employee_departure_european_time_off(self):
        self._generate_departure_data(european_leave=True)
        # - Holiday Pay N
        # - Holiday Pay N-1
        struct_n1_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n1_holidays')
        struct_n_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays')

        self.holiday_pay_2019 = self.departure_payslips.filtered(lambda p: p.struct_id == struct_n1_id)
        self.holiday_pay_2020 = self.departure_payslips.filtered(lambda p: p.struct_id == struct_n_id)

        self.assertEqual(len(self.termination_fees.worked_days_line_ids), 0)
        self._validate_payslip(self.termination_fees)

        self.assertEqual(len(self.holiday_pay_2020.worked_days_line_ids), 0)
        self._validate_payslip(self.holiday_pay_2020)

        self.assertEqual(len(self.holiday_pay_2019.worked_days_line_ids), 0)
        self._validate_payslip(self.holiday_pay_2019)

    def test_work_incapacity_due_to_illness(self):
        self.version.write({
            'wage': 1774.3 * 2,
            'resource_calendar_id': self.resource_calendar_19_part_time_sick.id,
            'contract_date_start': datetime.date(2021, 3, 27),
            'contract_date_end': datetime.date(2021, 4, 30),
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True

        payslip = self._generate_payslip(datetime.date(2021, 3, 1), datetime.date(2021, 3, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 3)

        self._validate_worked_days(payslip, {
            '002.00': (1.5, 11.4, 245.67),
            '122.04': (1.5, 11.4, 0.0),
            '000.00': (20.0, 152.0, 0.0),
        })

        self._validate_payslip(payslip)

    def test_work_incapacity_due_to_illness_full_salary(self):
        self.version.write({
            'wage': 1358.55 / 0.4,
            'resource_calendar_id': self.resource_calendar_15_2_part_time_sick.id,
            'contract_date_start': datetime.date(2026, 1, 1),
            'contract_date_end': False,
        })

        payslip = self._generate_payslip(datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        # Total should sum to the employee salary
        self._validate_worked_days(payslip, {
            '002.00': (8.0, 60.8, 1358.55),
            '122.04': (14.0, 106.4, 0.0),
        })

    def test_work_incapacity_due_to_illness_full_month(self):
        self.employee.write({
            'distance_home_work': 53,
        })

        self.version.write({
            'resource_calendar_id': self.resource_calendar_19_part_time_sick.id,
            'wage': 887.15 * 2,
            'holidays': 5.0,
            'fuel_card': 0.0,
            'internet': 0.0,
            'mobile': 0.0,
            'ip_wage_rate': 0.2,
            'l10n_be_lsa_monthly_misc_base_amount': 283.73,
            'l10n_be_lsa_monthly_pro_other_amount': 115.27,
            'private_car_employee_kilometer': 53
        })

        # Public Holiday
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_19_part_time_sick.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2021, 4, 5, 4, 0, 0),
            'date_to': datetime.datetime(2021, 4, 5, 17, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }])

        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_19_part_time_sick.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2021, 4, 12, 7, 0, 0),
            'date_to': datetime.datetime(2021, 4, 12, 10, 48, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_extra_legal').id
        }])

        payslip = self._generate_payslip(datetime.date(2021, 4, 1), datetime.date(2021, 4, 30))

        self.assertEqual(len(payslip.worked_days_line_ids), 4)

        self._validate_worked_days(payslip, {
            '002.00': (10.0, 76.0, 805.25),
            '011.00': (0.5, 3.8, 40.95),
            '122.04': (11.0, 83.6, 0.0),
            '006.00': (0.5, 3.8, 40.95),
        })

        self._validate_payslip(payslip)

    def test_withholding_tax_reduction_extra_hours(self):
        extra_hours_entry_type = self.env['hr.work.entry.type'].create({
            'name': 'Extra Hours 200%',
            'code': 'EXTRA_HOURS200',
            'amount_rate': 2,
            'category_ids': [(6, 0, [self.env.ref('hr_payroll.EXTRA_HOURS').id, self.env.ref('l10n_be_hr_payroll.OVERTIME_TAX_RELIEF').id])],
        })

        self.leaves = self.env['resource.calendar.leaves'].create([{
            'name': "14th JAN Extra Hours",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 1, 14, 7, 0, 0),
            'date_to': datetime.datetime(2026, 1, 14, 16, 36, 0),
            'work_entry_type_id': extra_hours_entry_type.id
        },
        {
            'name': "15th JAN Extra Hours",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 1, 15, 7, 0, 0),
            'date_to': datetime.datetime(2026, 1, 15, 16, 36, 0),
            'work_entry_type_id': extra_hours_entry_type.id
        }])

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 2, "Payslip should contain exactly 2 worked day lines.")

        overtime_line = payslip.worked_days_line_ids.filtered(lambda l: l.work_entry_type_id == extra_hours_entry_type)
        self.assertTrue(overtime_line, "Worked days lines must include the overtime line (EXTRA_HOURS200).")
        self.assertAlmostEqual(overtime_line.number_of_hours, 15.2, places=2)

        # Calculation verification for Rule P.P.DEDEH:
        # Contract Wage = 2650.0 €
        # Basic Hourly Rate = 2650.0 * 3 / (13 * 38) ≈ 16.09312 €/h
        # Base Amount = 15.2 hours * 16.09312 ≈ 244.61538 €
        # Overtime premium rate = 100% (>= 50%) -> Deduction Rate = 57.75%
        # Expected Reduction = 244.61538 * 0.5775 ≈ 141.265 €
        deduction_line = payslip.line_ids.filtered(lambda l: l.code == 'P.P.DEDEH')
        self.assertTrue(deduction_line, "Rule P.P.DEDEH must be computed on the payslip.")
        self.assertAlmostEqual(deduction_line.total, 141.27, places=2)

        self._validate_payslip(payslip)

    def test_withholding_tax_reduction_extra_hours_category(self):
        # The overtime giving right to the withholding tax reduction is the one of the category of the overtime tax
        # relief, as for the 274.44/274.55 exemptions and the box 18 of the 281.10: an extra hours type without it
        # is paid, but neither reduces the withholding tax nor is declared as overtime
        extra_hours_entry_type = self.env['hr.work.entry.type'].create({
            'name': 'Extra Hours 200%',
            'code': 'EXTRA_HOURS200',
            'amount_rate': 2,
            'category_ids': [(6, 0, [self.env.ref('hr_payroll.EXTRA_HOURS').id])],
        })
        self.env['resource.calendar.leaves'].create({
            'name': "14th JAN Extra Hours",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 1, 14, 7, 0, 0),
            'date_to': datetime.datetime(2026, 1, 14, 16, 36, 0),
            'work_entry_type_id': extra_hours_entry_type.id,
        })
        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        self.assertTrue(payslip.worked_days_line_ids.filtered(lambda l: l.work_entry_type_id == extra_hours_entry_type))
        self.assertFalse(payslip.line_ids.filtered(lambda l: l.code == 'P.P.DEDEH'))

    def test_withholding_tax_reduction_extra_hours_with_different_rates(self):
        extra_hours_25_type = self.env['hr.work.entry.type'].create({
            'name': 'Extra Hours 125%',
            'code': 'EXTRA_HOURS125',
            'amount_rate': 1.25,
            'category_ids': [(6, 0, [self.env.ref('hr_payroll.EXTRA_HOURS').id, self.env.ref('l10n_be_hr_payroll.OVERTIME_TAX_RELIEF').id])],
        })

        extra_hours_100_type = self.env['hr.work.entry.type'].create({
            'name': 'Extra Hours 200%',
            'code': 'EXTRA_HOURS200',
            'amount_rate': 2.0,
            'category_ids': [(6, 0, [self.env.ref('hr_payroll.EXTRA_HOURS').id, self.env.ref('l10n_be_hr_payroll.OVERTIME_TAX_RELIEF').id])],
        })

        self.env['resource.calendar.leaves'].create([
            {
                'name': "14th JAN Extra Hours 125%",
                'calendar_id': self.resource_calendar_38_hours_per_week.id,
                'company_id': self.env.company.id,
                'resource_id': self.employee.resource_id.id,
                'date_from': datetime.datetime(2026, 1, 14, 7, 0, 0),
                'date_to': datetime.datetime(2026, 1, 14, 16, 36, 0),
                'work_entry_type_id': extra_hours_25_type.id,
            },
            {
                'name': "15th JAN Extra Hours 200%",
                'calendar_id': self.resource_calendar_38_hours_per_week.id,
                'company_id': self.env.company.id,
                'resource_id': self.employee.resource_id.id,
                'date_from': datetime.datetime(2026, 1, 15, 7, 0, 0),
                'date_to': datetime.datetime(2026, 1, 15, 16, 36, 0),
                'work_entry_type_id': extra_hours_100_type.id,
            },
        ])

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        # Basic hourly rate = 2650.0 * 3 / (13 * 38) ≈ 16.09312 €/h
        # Base amount per line (7.6h) = 7.6 * 16.09312 ≈ 122.30769 €
        # Deduction_1 (66.81%) = 122.30769 * 0.6681 ≈ 81.71377 €
        # Deduction_2 (57.75%) = 122.30769 * 0.5775 ≈ 70.63269 €
        # Total Expected Reduction = -(81.71377 + 70.63269) ≈ 152.35 €
        self.assertAlmostEqual(payslip._get_withholding_extra_hours_reduction(), 152.35, places=2)
        # It exceeds the withholding tax of the scale (P.P = -144.33 €): the reduction stops at that tax, the
        # withholding tax is 0, not a refund
        deduction_line = payslip.line_ids.filtered(lambda l: l.code == 'P.P.DEDEH')
        self.assertTrue(deduction_line, "Rule P.P.DEDEH must be computed for multiple rates.")
        self.assertAlmostEqual(deduction_line.total, 144.33, places=2)

        self._validate_payslip(payslip)

    def test_withholding_tax_reduction_extra_hours_student(self):
        # A student has no withholding tax: the overtime reduction has no tax to reduce, it is not paid with the net
        self.version.l10n_be_dimona_category = 'stu'
        self.env['resource.calendar.leaves'].create({
            'name': "14th JAN Extra Hours 150%",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 1, 14, 7, 0, 0),
            'date_to': datetime.datetime(2026, 1, 14, 16, 36, 0),
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_overtime').id,
        })

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        overtime_line = payslip.worked_days_line_ids.filtered(lambda l: l.code == '040.00')
        self.assertAlmostEqual(overtime_line.number_of_hours, 7.6, places=2)
        # Without the limit: 7.6h x 2650.0 * 3 / (13 * 38) €/h x 57.75% ≈ 70.63 €
        self.assertAlmostEqual(payslip._get_withholding_extra_hours_reduction(), 70.63, places=2)
        self.assertFalse(payslip.line_ids.filtered(lambda l: l.code == 'P.P'))
        self._validate_payslip(payslip, {'P.P.DEDEH': 0.0}, skip_lines=True)

    def test_withholding_tax_reduction_extra_hours_annual_cap_reached(self):
        """
        Test that withholding tax reduction (P.P.DEDEH) is capped at the yearly limit of hours of the joint
        committee: 180 hours for CP200 (cp200_overtime_threshold, as in the 274.XX), the 360 hours of the hotel
        industry (CP302) only apply to that joint committee, whatever the cash register.

        Accumulation Breakdown:
          - Jan 2026: 22 days * 7.6h = 167.2h
          - Remaining annual cap for February = 180.0h - 167.2h = 12.8h
          - Feb 2026: 20 days * 7.6h = 152.0h (Exceeds remaining cap!)
          - Eligible hours capped at min(152.0h, 12.8h) = 12.8h
          - March: the cap is reached, no reduction
        """

        self.env.company.l10n_be_has_white_cash_register = False
        extra_hours_entry_type = self.env['hr.work.entry.type'].create({
            'name': 'Extra Hours 200%',
            'code': 'EXTRA_HOURS200',
            'amount_rate': 2.0,
            'category_ids': [(6, 0, [self.env.ref('hr_payroll.EXTRA_HOURS').id, self.env.ref('l10n_be_hr_payroll.OVERTIME_TAX_RELIEF').id])],
        })

        # January 2026: 22 extra working days * 7.6h = 167.2 extra hours
        self.env['resource.calendar.leaves'].create([{
            'name': "JAN Extratime Cap Reach",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 1, 1, 7, 0, 0),
            'date_to': datetime.datetime(2026, 1, 31, 16, 36, 0),
            'work_entry_type_id': extra_hours_entry_type.id,
        }])

        jan_payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        jan_payslip.action_payslip_done()

        # February 2026: 20 extra working days * 7.6h = 152.0 extra hours
        self.env['resource.calendar.leaves'].create([{
            'name': "FEB Extratime",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 2, 1, 7, 0, 0),
            'date_to': datetime.datetime(2026, 2, 28, 16, 36, 0),
            'work_entry_type_id': extra_hours_entry_type.id,
        }])
        feb_payslip = self._generate_payslip(datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))

        # Calculation verification for Rule P.P.DEDEH in February:
        # Basic Hourly Rate = 2650.0 * 3 / (13 * 38) ≈ 16.09312 €/h
        # Eligible Extra Hours = min(152.0h registered, 12.8h remaining cap) = 12.8h
        # Capped Base Amount = 12.8 hours * 16.09312 ≈ 205.99190 €
        # Premium rate = 100% (>= 50%) -> Deduction Rate = 57.75%
        # Expected Reduction = 205.99190 * 0.5775 ≈ 118.96 €
        self.assertAlmostEqual(feb_payslip._get_withholding_extra_hours_reduction(), 118.96, places=2)
        withholding_tax = -feb_payslip._get_line_values(['P.P'])['P.P'][feb_payslip.id]['total']
        deduction_line = feb_payslip.line_ids.filtered(lambda l: l.code == 'P.P.DEDEH')
        self.assertTrue(deduction_line, "Rule P.P.DEDEH should be computed on the February payslip up to the remaining annual cap.")
        self.assertAlmostEqual(deduction_line.total, min(118.96, withholding_tax), places=2)
        feb_payslip.action_payslip_done()

        # MAR -> 6 days * 7.6h = 45.6 extra hours, the yearly cap is reached
        self.env['resource.calendar.leaves'].create([{
            'name': "MAR Extratime Cap Exceeded",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 3, 2, 7, 0, 0),
            'date_to': datetime.datetime(2026, 3, 9, 16, 36, 0),
            'work_entry_type_id': extra_hours_entry_type.id,
        }])
        mar_payslip = self._generate_payslip(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))
        self.assertEqual(mar_payslip._get_withholding_extra_hours_reduction(), 0)
        self.assertFalse(mar_payslip.line_ids.filtered(lambda l: l.code == 'P.P.DEDEH').total)

    def test_withholding_tax_reduction_extra_hours_child_premium_pay_category(self):
        """
        Test that withholding tax reduction (P.P.DEDEH) is correctly triggered when
        a work entry type has a base amount_rate of 1.0 but it has a parent category
        whose child category is a premium pay rate with premium_percentage_hourly_rate > 0.
        Even though amount_rate = 1.0 on the work entry type:
          - Base rate = 1.0
          - Child category premium rate = +0.50 (50%)
          - Total effective rate = 1.0 + 0.50 = 1.50 (> 1.0)
          - Effective rate = 150%
        """
        parent_category = self.env['hr.salary.rule.category'].create({
            'name': 'Overtime Parent Category',
            'code': 'OVERTIME_PARENT',
        })

        self.env['hr.salary.rule.category'].create({
            'name': 'Overtime Child Premium Pay',
            'code': 'OVERTIME_CHILD_PREMIUM',
            'parent_id': parent_category.id,
            'is_premium_pay': True,
            'premium_percentage_hourly_rate': 0.50,
        })

        extra_hours_entry_type = self.env['hr.work.entry.type'].create({
            'name': 'Extra Hours 100%',
            'code': 'EXTRA_HOURS100',
            'amount_rate': 1.0,
            'category_ids': [(6, 0, [
                self.env.ref('hr_payroll.EXTRA_HOURS').id,
                self.env.ref('l10n_be_hr_payroll.OVERTIME_TAX_RELIEF').id,
                parent_category.id
            ])],
        })

        # Add 2 days (15.2 hours) of overtime in January 2026
        self.env['resource.calendar.leaves'].create([
            {
                'name': "14th JAN Child Premium Extra Hours",
                'calendar_id': self.resource_calendar_38_hours_per_week.id,
                'company_id': self.env.company.id,
                'resource_id': self.employee.resource_id.id,
                'date_from': datetime.datetime(2026, 1, 14, 7, 0, 0),
                'date_to': datetime.datetime(2026, 1, 14, 16, 36, 0),
                'work_entry_type_id': extra_hours_entry_type.id,
            },
            {
                'name': "15th JAN Child Premium Extra Hours",
                'calendar_id': self.resource_calendar_38_hours_per_week.id,
                'company_id': self.env.company.id,
                'resource_id': self.employee.resource_id.id,
                'date_from': datetime.datetime(2026, 1, 15, 7, 0, 0),
                'date_to': datetime.datetime(2026, 1, 15, 16, 36, 0),
                'work_entry_type_id': extra_hours_entry_type.id,
            },
        ])

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        # 4. Calculation verification for Rule P.P.DEDEH:
        # Contract Wage = 2650.0 €
        # Basic Hourly Rate = 2650.0 * 3 / (13 * 38) ≈ 16.09312 €/h
        # Base Amount = 15.2 hours * 16.09312 ≈ 244.61538 €
        # Effective Rate = 1.0 (amount_rate) + 0.50 (child premium) = 1.50
        # Deduction Rate = 57.75%
        # Expected Reduction = 244.61538 * 0.5775 ≈ 141.265 €
        deduction_line = payslip.line_ids.filtered(lambda l: l.code == 'P.P.DEDEH')
        self.assertTrue(deduction_line, "Rule P.P.DEDEH must compute when qualification comes from child premium pay.")
        self.assertAlmostEqual(deduction_line.total, 141.27, places=2)

        self._validate_payslip(payslip)

    def test_withholding_tax_reduction_extra_hours_credit_time(self):
        """The overtime reduction of a 4/5 time credit is computed on the same base as the employer's exemption
        (art. 154bis and 275/1 CIR 92: the pay of the hours before the premium), at the hourly wage the overtime line
        is valued at (the wage prorated by the time credit), not the full-time wage over the part-time weekly hours."""
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2025, 1, 1),
            'contract_date_end': False,
            'wage': 2120.0 * (5 / 4),
            'work_time_rate': 1.0,
        })
        self.env['resource.calendar.leaves'].create({
            'name': "15th JAN Extra Hours 150%",
            'calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 1, 15, 7, 0, 0),
            'date_to': datetime.datetime(2026, 1, 15, 16, 36, 0),
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_overtime').id,
        })

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        overtime_line = payslip.worked_days_line_ids.filtered(lambda l: l.code == '040.00')
        self.assertAlmostEqual(overtime_line.number_of_hours, 7.6, places=2)
        # The overtime line: 7.6h x 2120.0 (the wage after the 4/5 time credit) * 3 / (13 * 30.4) €/h x 150%
        #   = 7.6 x 16.09312 x 1.5 ≈ 183.46 €; the base of the 274.44 and of the reduction: 183.46 / 1.5 ≈ 122.31 €
        # Before the fix: 7.6h x 2650.0 (the full-time wage) * 3 / (13 * 30.4) = 20.11640 €/h x 57.75% ≈ 88.29 €
        # After: 122.31 x 57.75% ≈ 70.63 € (the 274.44: 122.31 x 41.25% ≈ 50.45 €)
        base = overtime_line.amount / overtime_line.work_entry_type_id.amount_rate
        self.assertAlmostEqual(payslip._get_withholding_extra_hours_reduction(), base * 0.5775, places=2)
        self.assertAlmostEqual(payslip._get_withholding_extra_hours_reduction(), 70.63, places=2)

        self._validate_payslip(payslip)

    def test_termination_holidays_pp_exoneration_reduction(self):
        self.employee.children = 2
        self.employee.version_id.write({
            'wage': 1200.0,
        })
        termination_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2021, 5, 1),
            'date_to': datetime.datetime(2021, 5, 31),
            'vehicle_id': self.car.id,
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n1_holidays').id,
            'company_id': self.env.company.id,
        })
        termination_payslip._set_input_values({
            'EUROPEAN': 0,
            'EUROPEAN_DAYS': 0,
            'TIME_OFF_TAKEN': 5,
            'ALLOCATION': 20,
            'GROSS_REF': 43608.44,
        })
        termination_payslip.compute_sheet()

        self.assertEqual(len(termination_payslip.worked_days_line_ids), 0)

        # Annexe III: the yearly normal pay (14,302.91) is below the limit for 2 children (17,060): the holiday pay
        # (3,885.58) is exempted up to the difference (2,757.09), the rest is taxed at the rate of the yearly normal
        # pay (26.25%), reduced by 20% for 2 children: 1,128.49 x 26.25% x 80%
        self.assertAlmostEqual(termination_payslip.line_ids.filtered(lambda l: l.code == 'HOLIDAY_TERM_PP').amount, -236.98, places=2)
        self._validate_payslip(termination_payslip)

    def test_termination_holidays_pp_no_exoneration_reduction(self):
        self.employee.children = 2
        self.employee.version_id.write({
            'wage': 1500.0,
        })
        termination_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2021, 5, 1),
            'date_to': datetime.datetime(2021, 5, 31),
            'vehicle_id': self.car.id,
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n1_holidays').id,
            'company_id': self.env.company.id,
        })
        termination_payslip._set_input_values({
            'EUROPEAN': 0,
            'EUROPEAN_DAYS': 0,
            'TIME_OFF_TAKEN': 5,
            'ALLOCATION': 20,
            'GROSS_REF': 43608.44,
        })
        termination_payslip.compute_sheet()

        self.assertEqual(len(termination_payslip.worked_days_line_ids), 0)

        self.assertAlmostEqual(termination_payslip.line_ids.filtered(lambda l: l.code == 'HOLIDAY_TERM_PP').amount, -1033.71, places=2)
        self._validate_payslip(termination_payslip)

    def test_termination_holidays_december_payslip(self):
        termination_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2021, 5, 1),
            'date_to': datetime.datetime(2021, 5, 31),
            'vehicle_id': self.car.id,
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n1_holidays').id,
            'company_id': self.env.company.id,
        })
        termination_payslip._set_input_values({
            'EUROPEAN': 0,
            'EUROPEAN_DAYS': 0,
            'TIME_OFF_TAKEN': 5,
            'ALLOCATION': 20,
            'GROSS_REF': 43608.44,
        })
        termination_payslip.compute_sheet()

        self.assertEqual(len(termination_payslip.worked_days_line_ids), 0)

        self._validate_payslip(termination_payslip)

    def test_termination_holidays_pp_no_exoneration_no_reduction(self):
        self.employee.children = 2

        termination_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2021, 5, 1),
            'date_to': datetime.datetime(2021, 5, 31),
            'vehicle_id': self.car.id,
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n1_holidays').id,
            'company_id': self.env.company.id,
        })
        termination_payslip._set_input_values({
            'EUROPEAN': 0,
            'EUROPEAN_DAYS': 0,
            'TIME_OFF_TAKEN': 5,
            'ALLOCATION': 20,
            'GROSS_REF': 43608.44,
        })
        termination_payslip.compute_sheet()

        self.assertEqual(len(termination_payslip.worked_days_line_ids), 0)

        self.assertAlmostEqual(termination_payslip.line_ids.filtered(lambda l: l.code == 'HOLIDAY_TERM_PP').amount, -2144.29, places=2)
        self._validate_payslip(termination_payslip)

    def test_taxable_salary_without_onss(self):
        # Taxed at the scale and paid with the net, never in the ONSS base: one input adds, the other deducts
        for inputs in [{'TAXABLE_NO_ONSS': 500}, {'TAXABLE_NO_ONSS_DED': 100}]:
            payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31), input_values=inputs)
            self._validate_payslip(payslip)

    def test_seized_amounts_are_deducted_from_the_net(self):
        amount_by_code = {
            'DEDUCTION': 100.0,
            'CHILD_SUPPORT': 110.0,
            'ASSIG_SALARY_PRIOR': 120.0,
            'ASSIG_SALARY': 130.0,
            'ATTACH_SALARY': 140.0,
            'SALARYADVREC': 160.0,
        }

        self.employee.version_id.wage = 10000

        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Seizure',
            'employee_id': self.employee.id,
            'company_id': self.employee.company_id.id,
            'version_id': self.employee.version_id.id,
            'date_from': datetime.date(2025, 3, 1),
            'date_to': datetime.date(2025, 3, 31),
        })

        payslip._set_input_values(amount_by_code)
        payslip.compute_sheet()
        self._validate_payslip(payslip)

    def test_seizable_amount_meal_voucher_contribution(self):
        # The employee contribution to the meal vouchers is not deducted from the net remuneration
        self.version.write({
            'wage': 3000.0,
            'meal_voucher_amount': 10.0,
        })
        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        payslip._set_input_values({
            'HIRINGBONUS': 1000.0,
            'ATTACH_SALARY': 10000.0,
        })
        payslip.compute_sheet()
        self._validate_payslip(payslip)

    def test_traffic_fines_paid_by_the_employer(self):
        # A taxable benefit in kind subject to the contribution 889 instead of the ONSS. The light fines are exempt up
        # to 150 EUR a year (January 100, February 50 of 100, March none), the serious ones never.
        for date_from, date_to, inputs in [
            (datetime.date(2026, 1, 1), datetime.date(2026, 1, 31), {'TRAFFIC_FINES_LIGHT': 100}),
            (datetime.date(2026, 2, 1), datetime.date(2026, 2, 28), {'TRAFFIC_FINES_LIGHT': 100}),
            (datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), {'TRAFFIC_FINES_LIGHT': 30, 'TRAFFIC_FINES': 200}),
        ]:
            payslip = self._generate_payslip(date_from, date_to, input_values=inputs)
            self._validate_payslip(payslip)
            payslip.action_payslip_done()

    def test_public_holiday_right_unemployment(self):
        # Note: The public holidays are paid the first 14 days of unemployment

        self.version.ip_wage_rate = 0
        self.version.write({
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True

        # Public time offs
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2026, 5, 12, 4, 0, 0),
            'date_to': datetime.datetime(2026, 5, 12, 21, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2026, 5, 26, 4, 0, 0),
            'date_to': datetime.datetime(2026, 5, 26, 21, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }])

        self.env['hr.leave'].create({
            'name': 'Legal Time Off 2026',
            'work_entry_type_id': self.economic_unemployment_for_employee_time_off_type.id,
            'request_date_from': datetime.date(2026, 5, 1),
            'request_date_to': datetime.date(2026, 5, 31),
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2026, 5, 1),
            'date_to': datetime.date(2026, 5, 31)
        })
        payslip.compute_sheet()

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '006.11': (1.0, 7.6, 122.31),
            '137.20': (20.0, 152, 0.0),
        })

        self._validate_payslip(payslip)

    def test_public_holiday_right_maternity(self):
        # Note: The public holidays are paid the first 30 days of maternity/partial incapacity, ...

        self.version.ip_wage_rate = 0
        self.version.write({
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True

        # Public time offs
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2021, 5, 12, 4, 0, 0),
            'date_to': datetime.datetime(2021, 5, 12, 21, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2021, 5, 17, 4, 0, 0),
            'date_to': datetime.datetime(2021, 5, 17, 21, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }])

        self.env['hr.leave'].create({
            'name': 'Legal Time Off 2020',
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_maternity').id,
            'request_date_from': datetime.date(2021, 4, 17),
            'request_date_to': datetime.date(2021, 5, 31),
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2021, 5, 1),
            'date_to': datetime.date(2021, 5, 31)
        })
        payslip.compute_sheet()

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '128.00': (20.0, 152.0, 0.0),
            '006.00': (1.0, 7.6, 122.31),
        })

        self._validate_payslip(payslip)

    def test_public_holiday_right_sick_leaves(self):
        # Note: The public holidays are paid the first 30 days of sick leaves, ...

        self.version.ip_wage_rate = False
        self.version.write({
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True

        # Public time offs
        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2021, 5, 12, 6, 0, 0),
            'date_to': datetime.datetime(2021, 5, 12, 21, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2021, 5, 17, 6, 0, 0),
            'date_to': datetime.datetime(2021, 5, 17, 21, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }])

        sick_leaves = self.env['hr.leave'].create({
            'name': 'Sick Leaves',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2021, 4, 17),
            'request_date_to': datetime.date(2021, 5, 31),
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2021, 5, 1),
            'date_to': datetime.date(2021, 5, 31)
        })
        payslip.compute_sheet()

        self._validate_worked_days(payslip, {
            '013.00': (9.0, 68.4, 1100.77),
            '122.00': (11.0, 83.6, 0.0),
            '006.00': (1.0, 7.6, 122.31),
        })

        self._validate_payslip(payslip)

    def test_public_holiday_right_maternity_full_time_credit_time(self):
        # Note: Always unpaid
        self.version.write({
            'resource_calendar_id': self.resource_calendar_0_hours_per_week.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2021, 5, 1),
            'wage': 0.0,
            'ip_wage_rate': 0,
            'work_time_rate': 0,
        })

        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_0_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2021, 5, 4, 4, 0, 0),
            'date_to': datetime.datetime(2021, 5, 4, 21, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }])

        self.env['hr.leave'].create({
            'name': 'Legal Time Off 2020',
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_maternity').id,
            'request_date_from': '2021-05-01',
            'request_date_to': '2021-05-31',
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2021, 5, 1),
            'date_to': datetime.date(2021, 5, 31)
        })
        payslip.compute_sheet()

        self.assertEqual(len(payslip.worked_days_line_ids), 1)

        self._validate_worked_days(payslip, {'147.00': (21.0, 159.6, 0.0)})

    def test_public_holiday_right_maternity_credit_time_less_1_month(self):
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2021, 5, 1),
            'wage': 2120 * (5 / 4),
            'ip_wage_rate': 0,
            'work_time_rate': 0.8,
        })

        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2021, 5, 4, 4, 0, 0),
            'date_to': datetime.datetime(2021, 5, 4, 21, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }])

        self.env['hr.leave'].create({
            'name': 'Legal Time Off 2020',
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_maternity').id,
            'request_date_from': datetime.date(2021, 5, 1),
            'request_date_to': datetime.date(2021, 5, 31),
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2021, 5, 1),
            'date_to': datetime.date(2021, 5, 31)
        })
        payslip.compute_sheet()

        self._validate_worked_days(payslip, {
            '128.00': (16.0, 121.6, 0.0),
            '147.00': (4.0, 30.4, 0.0),
            '006.00': (1.0, 7.6, 122.31),
        })

    def test_public_holiday_right_maternity_credit_time_less_3_month(self):
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'contract_date_start': datetime.date(2021, 4, 1),
            'wage': 2120 * (5 / 4),
            'ip_wage_rate': 0,
            'work_time_rate': 1.0,
        })

        self.env['resource.calendar.leaves'].create([{
            'name': "Absence",
            'calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2021, 5, 4, 4, 0, 0),
            'date_to': datetime.datetime(2021, 5, 4, 21, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2021, 5, 13, 4, 0, 0),
            'date_to': datetime.datetime(2021, 5, 13, 21, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }, {
            'name': "Absence",
            'calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2021, 5, 17, 4, 0, 0),
            'date_to': datetime.datetime(2021, 5, 17, 21, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }])

        self.env['hr.leave'].create({
            'name': 'Legal Time Off 2020',
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_maternity').id,
            'request_date_from': datetime.date(2021, 5, 1),
            'request_date_to': datetime.date(2021, 5, 31),
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2021, 5, 1),
            'date_to': datetime.date(2021, 5, 31)
        })
        payslip.compute_sheet()

        self.assertEqual(len(payslip.worked_days_line_ids), 3)

        self._validate_worked_days(payslip, {
            '128.00': (14.0, 106.4, 0.0),
            '147.00': (4.0, 30.4, 0.0),
            '006.00': (3.0, 22.8, 366.92),
        })

    def test_double_remuneration_line_2_contracts(self):
        self.employee.distance_home_work = 41

        version_1 = self.version
        version_1.write({
            'date_version': datetime.date(2022, 2, 1),
            'contract_date_start': datetime.date(2022, 2, 1),
            'contract_date_end': datetime.date(2022, 2, 15),
            'private_car_employee_kilometer': 41,
            'train_transport_employee_kilometer': 12,
            'l10n_be_canteen_cost': 42,
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })

        version_2 = version_1.copy({
            'date_version': datetime.date(2022, 2, 16),
            'contract_date_start': datetime.date(2022, 2, 16),
            'contract_date_end': False,
            'l10n_be_dimona_category': 'alt',
        })

        payslip_1 = self.env['hr.payslip'].create([{
            'name': "Test Payslip 1",
            'employee_id': self.employee.id,
            'version_id': version_1.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2022, 2, 1),
            'date_to': datetime.date(2022, 2, 28),
        }])
        payslip_2 = self.env['hr.payslip'].create([{
            'name': "Test Payslip 2",
            'employee_id': self.employee.id,
            'version_id': version_2.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2022, 2, 1),
            'date_to': datetime.date(2022, 2, 28),
        }])

        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True
        payslip_1.compute_sheet()
        payslip_1.action_payslip_done()
        payslip_2.compute_sheet()

        self._validate_payslip(payslip_1)
        self._validate_payslip(payslip_2)

    def test_canteen_cost_2_contracts(self):
        version_1 = self.version
        version_1.write({
            'date_version': datetime.date(2026, 8, 1),
            'contract_date_start': datetime.date(2026, 8, 1),
            'contract_date_end': datetime.date(2026, 8, 14),
            'l10n_be_canteen_cost': 42
        })

        version_1.copy({
            'date_version': datetime.date(2026, 8, 15),
            'contract_date_start': datetime.date(2026, 8, 15),
            'contract_date_end': False,
            'l10n_be_canteen_cost': 42
        })

        self.env['hr.leave'].create({
            'name': 'Unpaid Leave Half Month',
            'work_entry_type_id': self.unpaid_time_off_type.id,
            'request_date_from': '2026-08-01',
            'request_date_to': '2026-08-14',
            'request_date_from_period': 'am',
            'request_date_to_period': 'pm',
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
                'name': "Test Payslip 1",
                'employee_id': self.employee.id,
                'version_id': version_1.id,
                'company_id': self.env.company.id,
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
                'date_from': datetime.date(2026, 8, 1),
                'date_to': datetime.date(2026, 8, 31),
            })
        payslip.compute_sheet()
        payslip.action_payslip_done()

        canteen_costs = payslip._get_line_values(['CANTEEN'])['CANTEEN']
        self.assertEqual(canteen_costs[payslip.id]['total'], -42.0)

    def test_double_remuneration_line_1_contract(self):
        # In case only one of both contracts has an advantage
        # Ensure we don't set it to 0
        self.employee.distance_home_work = 41

        version_1 = self.version
        version_1.write({
            'date_version': datetime.date(2022, 2, 1),
            'contract_date_start': datetime.date(2022, 2, 1),
            'contract_date_end': datetime.date(2022, 2, 15),
            'transport_mode_car': False,
            'private_car_employee_kilometer': 0,
            'mobile': False,
            'internet': False,
            'train_transport_employee_kilometer': 0,
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })

        version_2 = version_1.copy({
            'date_version': datetime.date(2022, 2, 16),
            'contract_date_start': datetime.date(2022, 2, 16),
            'contract_date_end': False,
            'mobile': 30,
            'internet': 38.0,
            'transport_mode_car': True,
            'train_transport_employee_kilometer': 4,
            'private_car_employee_kilometer': 41,
            'l10n_be_dimona_category': 'alt',
        })

        payslip_1 = self.env['hr.payslip'].create([{
            'name': "Test Payslip 1",
            'employee_id': self.employee.id,
            'version_id': version_1.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2022, 2, 1),
            'date_to': datetime.date(2022, 2, 28),
        }])
        payslip_2 = self.env['hr.payslip'].create([{
            'name': "Test Payslip 2",
            'employee_id': self.employee.id,
            'version_id': version_2.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2022, 2, 1),
            'date_to': datetime.date(2022, 2, 28),
        }])

        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True
        (payslip_1 + payslip_2).compute_sheet()

        self._validate_payslip(payslip_1)
        self._validate_payslip(payslip_2)

    def test_holiday_attest_n_before_june(self):
        self._generate_departure_data()
        struct_n_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays')

        holiday_pay_2020 = self.departure_payslips.filtered(lambda p: p.struct_id == struct_n_id)
        holiday_pay_2020.write({
            'date_from': datetime.date(2020, 4, 1),
            'date_to': datetime.date(2020, 4, 30),
        })
        holiday_pay_2020.compute_sheet()

        self._validate_payslip(holiday_pay_2020)

    def test_holiday_attest_n_after_june(self):
        # Compensate the loss on commission on PTO with the double holiday pay (SIMPLE_VARIABLE) instead of monthly (COM_LOSS_PTO)
        self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_double_holiday').active = True
        self._generate_departure_data()

        double_pay_payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version_2020.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2020, 3, 1),
            'date_to': datetime.date(2020, 3, 31),
            'journal_id': self.journal.id,
            'payslip_run_id': self.batch.id,
        })
        double_pay_payslip.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        double_pay_payslip.action_payslip_done()

        self._validate_payslip(double_pay_payslip)

        struct_n_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays')

        holiday_pay_2020 = self.departure_payslips.filtered(lambda p: p.struct_id == struct_n_id)
        holiday_pay_2020.write({
            'date_from': datetime.date(2020, 4, 1),
            'date_to': datetime.date(2020, 4, 30),
        })
        holiday_pay_2020.compute_sheet()

        self._validate_payslip(holiday_pay_2020)

        struct_n1_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n1_holidays')

        holiday_pay_2019 = self.departure_payslips.filtered(lambda p: p.struct_id == struct_n1_id)
        holiday_pay_2019.write({
            'date_from': datetime.date(2020, 4, 1),
            'date_to': datetime.date(2020, 4, 30),
        })
        holiday_pay_2019.compute_sheet()

        self._validate_payslip(holiday_pay_2019)

    def test_double_remuneration_refunds_partial_contracts(self):
        # 1 full time parental time off at the start of the month
        # 1 4/5 over the rest of the month
        # 1 refund + 1 correction
        self.employee.write({
            'distance_home_work': 40.0,
            'private_car_employee_kilometer': 40.0,
            'marital': 'cohabitant',
            'spouse_fiscal_status': 'high_income',
            'children': 0,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'work_time_rate': 0,
            'wage': 2821.00,
            'resource_calendar_id': self.resource_calendar_0_hours_per_week.id,
            'date_version': datetime.date(2022, 1, 3),
            'contract_date_start': datetime.date(2022, 1, 3),
            'contract_date_end': datetime.date(2022, 4, 2),
            'car_id': False,
            'transport_mode_car': False,
            'fuel_card': 0,
            'internet': 0,
            'mobile': 0,
            'meal_voucher_amount': 8.0,
            'ip_wage_rate': 0.12,
            'commission_on_target': 1533.0,
            'bus_transport_employee_amount': 49.0,
            'bus_transport_employee_kilometer': 5,
            'l10n_be_lsa_monthly_misc_base_amount': 279.31,
            'l10n_be_lsa_monthly_pro_other_amount': 119.69,
        })

        partial_contract = self.employee.create_version({
            'name': "Partial Contract For Payslip Test",
            'distance_home_work': 40.0,
            'private_car_employee_kilometer': 40.0,
            'marital': 'cohabitant',
            'spouse_fiscal_status': 'high_income',
            'employee_id': self.employee.id,
            'resource_calendar_id': self.resource_calendar_4_5_friday_off.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'work_time_rate': 1.0,
            'company_id': self.env.company.id,
            'car_id': False,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'date_version': datetime.date(2022, 4, 3),
            'contract_date_start': datetime.date(2022, 4, 3),
            'contract_date_end': datetime.date(2022, 9, 2),
            'wage': 2851.71 * (5 / 4),
            'transport_mode_car': False,
            'fuel_card': 0,
            'internet': 0,
            'mobile': 0,
            'meal_voucher_amount': 8.0,
            'ip_wage_rate': 0.12,
            'commission_on_target': 1433.33,
            'bus_transport_employee_amount': 49.0,
            'bus_transport_employee_kilometer': 5,
            'l10n_be_lsa_monthly_misc_base_amount': 279.31,
            'l10n_be_lsa_monthly_pro_other_amount': 119.69,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
        })

        payslip_1 = self.env['hr.payslip'].create([{
            'name': "Test Payslip 1",
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2022, 3, 1),
            'date_to': datetime.date(2022, 3, 31),
        }])
        payslip_2 = self.env['hr.payslip'].create([{
            'name': "Test Payslip 2",
            'employee_id': self.employee.id,
            'version_id': partial_contract.id,
            'company_id': self.env.company.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2022, 4, 1),
            'date_to': datetime.date(2022, 4, 30),
        }])
        (payslip_1 + payslip_2).compute_sheet()

        self._validate_payslip(payslip_1)
        self._validate_payslip(payslip_2)
        payslip_2.action_payslip_done()

        refund_payslip = payslip_2._action_refund_payslips()

        self._validate_payslip(refund_payslip)
        refund_payslip.action_payslip_draft()
        payslip_2.action_payslip_draft()

        new_payslip_2 = self.env['hr.payslip'].create([{
            'name': "New Test Payslip 2",
            'employee_id': self.employee.id,
            'version_id': partial_contract.id,
            'company_id': self.env.company.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2022, 4, 1),
            'date_to': datetime.date(2022, 4, 30),
        }])
        new_payslip_2.compute_sheet()

        self._validate_payslip(new_payslip_2)

    def test_company_car_pp_exemption_2021(self):
        payslip = self._generate_payslip(datetime.date(2022, 5, 1), datetime.date(2022, 5, 31))

        self._validate_payslip(payslip)

    def test_company_car_cycle_capped(self):
        self.employee.write({
            'bike_transport_employee_kilometer': 1
        })
        payslip = self._generate_payslip(datetime.date(2022, 5, 1), datetime.date(2022, 5, 31))
        self.assertEqual(len(payslip.worked_days_line_ids), 1)

        self._validate_payslip(payslip)

    def test_company_car_cycle_uncapped(self):
        self.employee.write({
            'distance_home_work': 5,
            'bike_transport_employee_kilometer': 1
        })
        payslip = self._generate_payslip(datetime.date(2022, 5, 1), datetime.date(2022, 5, 31))
        self.assertEqual(len(payslip.worked_days_line_ids), 1)

        self._validate_payslip(payslip)

    def test_representation_fees_two_weeks_calendar(self):
        self.version.resource_calendar_id = self.resource_calendar_9_10_monday_off
        self.version.write({
            'l10n_be_lsa_monthly_misc_base_amount': 283.73,
            'l10n_be_lsa_monthly_pro_other_amount': 115.27,
        })
        payslip = self._generate_payslip(datetime.date(2022, 5, 1), datetime.date(2022, 5, 31))
        self.assertEqual(len(payslip.worked_days_line_ids), 1)
        self.assertEqual(payslip.worked_days_line_ids.number_of_days, 20)  # Instead of 22

        self._validate_payslip(payslip)

    def test_representation_fees_two_weeks_calendar_credit_time(self):
        self.version.write({
            'resource_calendar_id': self.resource_calendar_9_10_monday_off_credit_time.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week,
            'wage': 2650.0 * (167.2 / 152.0),
            'work_time_rate': 1.0,
            'l10n_be_lsa_monthly_misc_base_amount': 283.73,
            'l10n_be_lsa_monthly_pro_other_amount': 115.27,
        })
        payslip = self._generate_payslip(datetime.date(2022, 5, 1), datetime.date(2022, 5, 31))
        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_payslip(payslip)

    def test_representation_fees_strange_two_weeks_calendar_credit_time(self):
        self.version.write({
            'resource_calendar_id': self.resource_calendar_9_10_strange.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week,
            'wage': 2650.0 * (165.6 / 151.6),
            'work_time_rate': 1.0,
            'l10n_be_lsa_monthly_misc_base_amount': 283.73,
            'l10n_be_lsa_monthly_pro_other_amount': 115.27,
        })
        payslip = self._generate_payslip(datetime.date(2022, 5, 1), datetime.date(2022, 5, 31))
        self.assertEqual(len(payslip.worked_days_line_ids), 2)  # Work entries are overlapping
        credit_time = payslip.worked_days_line_ids.filtered(lambda w: w.code == '147.00')
        self.assertTrue(credit_time)
        self.assertEqual(credit_time.number_of_days, 0)
        self.assertEqual(credit_time.number_of_hours, 14)
        self.assertEqual(len(payslip.input_line_ids), 0)

        self._validate_payslip(payslip)

    def test_relapse_without_guaranteed_salary_split_time_off(self):
        # Check when the employee is always sick, but with split time off
        # Sick 3 days (27 - 29 April 2022)
        # Sick 1 week (2 - 6 May)
        # Sick 2 weeks (7 - 20 May)
        # Sick 4 week (21 May - 17 June)
        self.version.write({
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True

        bank_holiday = self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday')
        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        sick_work_entry_type = self.env.ref('hr_work_entry.be_work_entry_type_sick_leave')
        partial_sick_work_entry_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_common_law_illness_after_legal_period')

        self.env['resource.calendar.leaves'].create([{
            'name': "Easter Monday",
            'calendar_id': False,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2022, 4, 18, 5, 0, 0),
            'date_to': datetime.datetime(2022, 4, 18, 18, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': bank_holiday.id
        }, {
            'name': "Ascension Day",
            'calendar_id': False,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2022, 5, 26, 5, 0, 0),
            'date_to': datetime.datetime(2022, 5, 26, 18, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': bank_holiday.id
        }])

        sick_leave_1 = self.env['hr.leave'].new({
            'name': 'Sick Time Off 3 days',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2022, 4, 27),
            'request_date_to': datetime.date(2022, 4, 29),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 3,
        })

        sick_leave_1._compute_date_from_to()
        sick_leave_1 = self.env['hr.leave'].create(sick_leave_1._convert_to_write(sick_leave_1._cache))

        sick_leave_2 = self.env['hr.leave'].new({
            'name': 'Sick Time Off 1 Week',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2022, 5, 2),
            'request_date_to': datetime.date(2022, 5, 6),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 5,
            'l10n_be_sickness_relapse': True,
            'l10n_be_sickness_relapse_origin_leave_id': sick_leave_1.id,
        })
        sick_leave_2._compute_date_from_to()
        sick_leave_2 = self.env['hr.leave'].create(sick_leave_2._convert_to_write(sick_leave_2._cache))

        sick_leave_3 = self.env['hr.leave'].new({
            'name': 'Sick Time Off 2 Week',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2022, 5, 7),
            'request_date_to': datetime.date(2022, 5, 20),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 10,
            'l10n_be_sickness_relapse': True,
            'l10n_be_sickness_relapse_origin_leave_id': sick_leave_2.id,
        })
        sick_leave_3._compute_date_from_to()
        sick_leave_3 = self.env['hr.leave'].create(sick_leave_3._convert_to_write(sick_leave_3._cache))

        sick_leave_4 = self.env['hr.leave'].new({
            'name': 'Sick Time Off 4 Week',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2022, 5, 21),
            'request_date_to': datetime.date(2022, 6, 17),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 20,
            'l10n_be_sickness_relapse': True,
            'l10n_be_sickness_relapse_origin_leave_id': sick_leave_3.id,
        })
        sick_leave_4._compute_date_from_to()
        sick_leave_4 = self.env['hr.leave'].create(sick_leave_4._convert_to_write(sick_leave_4._cache))

        work_entries_vals = self.employee.version_id.generate_work_entries(datetime.date(2022, 4, 1), datetime.date(2022, 6, 30))

        work_entries_expected_results = {
            # Attendances
            (1, 4): attendance,

            (4, 4): attendance,
            (5, 4): attendance,
            (6, 4): attendance,
            (7, 4): attendance,
            (8, 4): attendance,

            (11, 4): attendance,
            (12, 4): attendance,
            (13, 4): attendance,
            (14, 4): attendance,
            (15, 4): attendance,

            (18, 4): bank_holiday,
            (19, 4): attendance,
            (20, 4): attendance,
            (21, 4): attendance,
            (22, 4): attendance,

            # 1rs time off
            (25, 4): attendance,
            (26, 4): attendance,
            (27, 4): sick_work_entry_type,
            (28, 4): sick_work_entry_type,
            (29, 4): sick_work_entry_type,
            # 2nd time off
            (2, 5): sick_work_entry_type,
            (3, 5): sick_work_entry_type,
            (4, 5): sick_work_entry_type,
            (5, 5): sick_work_entry_type,
            (6, 5): sick_work_entry_type,
            # 3rd time off
            (9, 5): sick_work_entry_type,
            (10, 5): sick_work_entry_type,
            (11, 5): sick_work_entry_type,
            (12, 5): sick_work_entry_type,
            (13, 5): sick_work_entry_type,

            (16, 5): sick_work_entry_type,
            (17, 5): sick_work_entry_type,
            (18, 5): sick_work_entry_type,
            (19, 5): sick_work_entry_type,
            (20, 5): sick_work_entry_type,
            # 4th time off
            (23, 5): sick_work_entry_type,
            (24, 5): sick_work_entry_type,
            (25, 5): sick_work_entry_type,
            (26, 5): bank_holiday,
            (27, 5): sick_work_entry_type,

            (30, 5): partial_sick_work_entry_type,
            (31, 5): partial_sick_work_entry_type,
            (1, 6): partial_sick_work_entry_type,
            (2, 6): partial_sick_work_entry_type,
            (3, 6): partial_sick_work_entry_type,

            (6, 6): partial_sick_work_entry_type,
            (7, 6): partial_sick_work_entry_type,
            (8, 6): partial_sick_work_entry_type,
            (9, 6): partial_sick_work_entry_type,
            (10, 6): partial_sick_work_entry_type,

            (13, 6): partial_sick_work_entry_type,
            (14, 6): partial_sick_work_entry_type,
            (15, 6): partial_sick_work_entry_type,
            (16, 6): partial_sick_work_entry_type,
            (17, 6): partial_sick_work_entry_type,

            # Come back
            (20, 6): attendance,
            (21, 6): attendance,
            (22, 6): attendance,
            (23, 6): attendance,
            (24, 6): attendance,

            (27, 6): attendance,
            (28, 6): attendance,
            (29, 6): attendance,
            (30, 6): attendance,
        }

        for vals in work_entries_vals:
            self.assertEqual(vals['work_entry_type_id'], work_entries_expected_results.get((vals['date'].day, vals['date'].month)), msg=str(vals['date'].day) + ", " + str(vals['date'].month))

        april_payslip = self._generate_payslip(datetime.date(2022, 4, 1), datetime.date(2022, 4, 30))

        self.assertEqual(len(april_payslip.worked_days_line_ids), 3)

        self._validate_payslip(april_payslip)

        may_payslip = self._generate_payslip(datetime.date(2022, 5, 1), datetime.date(2022, 5, 31))

        self.assertEqual(len(may_payslip.worked_days_line_ids), 3)

        self._validate_payslip(may_payslip)

        june_payslip = self._generate_payslip(datetime.date(2022, 6, 1), datetime.date(2022, 6, 30))

        self.assertEqual(len(june_payslip.worked_days_line_ids), 2)

        self._validate_payslip(june_payslip)

    def test_strike_days(self):
        strike_leave = self.env['hr.leave'].new({
            'name': 'Strike Day',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_strike').id,
            'request_date_from': datetime.date(2022, 5, 17),
            'request_date_to': datetime.date(2022, 5, 17),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 1,
        })
        strike_leave._compute_date_from_to()
        strike_leave = self.env['hr.leave'].create(strike_leave._convert_to_write(strike_leave._cache))

        payslip = self._generate_payslip(datetime.date(2022, 5, 1), datetime.date(2022, 5, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (21.0, 159.6, 2527.69),
            '132.00': (1.0, 7.6, 0.0),
        })

        self._validate_payslip(payslip)

    def test_cycle_private_car(self):
        # Test that cycle days are removed from private car reimbursement
        self.version.write({
            'transport_mode_car': False,
            'private_car_employee_kilometer': 75,
            'bike_transport_employee_kilometer': 1
        })

        payslip = self._generate_payslip(datetime.date(2022, 7, 1), datetime.date(2022, 7, 31))

        self._validate_payslip(payslip)

    def test_simple_n1_holiday_pay_recovery_half_days(self):
        """
        Check that half days AND full days are taken into account
        """
        CONTRACT_START = datetime.date(2026, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                "date_from": CONTRACT_START + relativedelta(years=-1),
                "date_to": datetime.date(CONTRACT_START.year - 1, 12, 31),
                "prev_work_days_per_week": 5,
                "prev_days_earned": 5,
                "prev_simple_holiday_pay_paid": 1000,
                "prev_double_holiday_pay_paid": 0,
            }),
        ]

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave Half Day",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 7, 22, 6, 0, 0),  # utc + 2
            'date_to': datetime.datetime(2026, 7, 22, 10, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }, {
            'name': "Legal Leave Whole Day",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 7, 20, 6, 0, 0),
            'date_to': datetime.datetime(2026, 7, 20, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2026, 7, 1), datetime.date(2026, 7, 31))
        paid_leaves_data = payslip._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 + 4)
        self.assertEqual(paid_leaves_data['amount'], 122.31 + 64.37)

        # HolPayRecN1 should be -186.68 * 0.9 = -168.01
        self._validate_payslip(payslip)

        payslip.action_payslip_done()

        payslip_dec = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))

        # Target (11.6 hours): 11.6 * min(16.09 [current hourly cost], 1000 [total amount] / 38 [total hours]) = 186.68.
        # Recovered: 168.01
        # HolPayRegN1 = -(186.68 - 168.01) = -18.67
        self._validate_payslip(payslip_dec)

    def test_simple_n1_holiday_pay_recovery_higher_salary(self):
        """
        Check that half days AND full days are taken into account
        Employee received 10€ for 5 days of holidays from previous employer
        The salary being higher in his current company, the HolidayPayRecN1 will be 90% of the holiday pay. Regularization happens in December.
        """
        CONTRACT_START = datetime.date(2026, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                "date_from": CONTRACT_START + relativedelta(years=-1),
                "date_to": datetime.date(CONTRACT_START.year - 1, 12, 31),
                "prev_work_hours_per_week": 38,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 5,
                "prev_simple_holiday_pay_paid": 10,
                "prev_double_holiday_pay_paid": 0,
            }),
        ]

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave Half Day",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 7, 22, 6, 0, 0),  # utc + 2
            'date_to': datetime.datetime(2026, 7, 22, 10, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }, {
            'name': "Legal Leave Whole Day",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 7, 20, 6, 0, 0),
            'date_to': datetime.datetime(2026, 7, 20, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2026, 7, 1), datetime.date(2026, 7, 31))
        paid_leaves_data = payslip._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 + 4)
        self.assertEqual(paid_leaves_data['amount'], 122.31 + 64.37)

        # HolPayRecN1 should be -186.68 * 0.9 = -168.01
        self._validate_payslip(payslip)

        payslip.action_payslip_done()

        payslip_dec = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))

        # Recomputed 100% Wage Base (11.6 hours): 11.6h * 16.0931 €/h = 186.68 €
        # Max Recoverable: min(100% Wage Base [186.68 €], Cap [10.00 € * 11.6 / 38 hours taken = 3.05 €]) = 3.05 €
        # Actual Recovered in July: 168.01 €
        # HolPayReg = -(3.05 - 168.01) = 164.96 € (Reimbursement)
        self._validate_payslip(payslip_dec)

    def test_simple_n1_holiday_pay_recovery_lower_salary(self):
        """
        Employee received 10 000€ for 2 days of holidays from the previous employer
        The salary being lower in his current company, the HolidayPayRecN1 will be 90% of the holiday pay. Regularization happens in December.
        """
        CONTRACT_START = datetime.date(2026, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                "date_from": CONTRACT_START + relativedelta(years=-1),
                "date_to": datetime.date(CONTRACT_START.year - 1, 12, 31),
                "prev_work_hours_per_week": 38,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 2,
                "prev_simple_holiday_pay_paid": 10000,
                "prev_double_holiday_pay_paid": 0,
            }),
        ]

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave Full Week",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 7, 20, 6, 0, 0),
            'date_to': datetime.datetime(2026, 7, 24, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2026, 7, 1), datetime.date(2026, 7, 31))
        paid_leaves_data = payslip._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 * 5)
        self.assertEqual(paid_leaves_data['amount'], 611.54)

        # HolPayRecN1 should be -244.62 * 0.9 = -220.15
        self._validate_payslip(payslip)

        payslip.action_payslip_done()

        payslip_dec = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))

        # Target (15.2 hours): 15.2 * min(16.09 [current cost], 10000 [total amount] / 15.2 [total hours]) = 244.62.
        # Recovered: 220.15
        # HolPayRegN1 = -(244.62 - 220.15) = -24.47
        self._validate_payslip(payslip_dec)

    def test_simple_n1_holiday_pay_recovery_lower_salary_2_payslips(self):
        """
        Employee received 10 000€ for 3 days of holidays from the previous employer
        Employee took 2 days on september (so the HolidayPayRecN1 should be equal to 90% of the holiday pay for 2 days)
        Employee took 2 days on october (so the HolidayPayRecN1 should be equal to 90% of the holiday pay for the 1 remaining day to recover)
        Employee took 4 days on november (so the HolidayPayRecN1 should be 0 as all days are already recovered)
        """
        CONTRACT_START = datetime.date(2026, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                "date_from": CONTRACT_START + relativedelta(years=-1),
                "date_to": datetime.date(CONTRACT_START.year - 1, 12, 31),
                "prev_work_hours_per_week": 38,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 3,
                "prev_simple_holiday_pay_paid": 10000,
                "prev_double_holiday_pay_paid": 0,
            }),
        ]

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal leave 2 days september",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 9, 21, 6, 0, 0),
            'date_to': datetime.datetime(2026, 9, 22, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal leave 2 days october",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 10, 12, 6, 0, 0),
            'date_to': datetime.datetime(2026, 10, 13, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal leave 4 days november",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 11, 9, 6, 0, 0),
            'date_to': datetime.datetime(2026, 11, 12, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        paid_leaves_data = payslip._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 * 2)
        self.assertEqual(paid_leaves_data['amount'], 244.62)

        # HolPayRecN1 should be -244.62 * 0.9 = -220.15
        self._validate_payslip(payslip)

        payslip2 = self._generate_payslip(datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
        self.employee.write({'review_state': '1_reviewed'})
        payslip2.action_payslip_done()
        paid_leaves_data = payslip2._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 * 2)
        self.assertEqual(paid_leaves_data['amount'], 244.62)

        # HolPayRecN1 should be -122.31 * 0.9 = -110.08
        self._validate_payslip(payslip2)

        payslip3 = self._generate_payslip(datetime.date(2026, 11, 1), datetime.date(2026, 11, 30))
        paid_leaves_data = payslip3._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 * 4)
        self.assertEqual(paid_leaves_data['amount'], 489.23)

        self._validate_payslip(payslip3)

        payslip3.action_payslip_done()
        payslip_dec = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))

        # Target (22.8 hours): 22.8 * min(16.09 [current cost], 10000 [total amount] / 22.8 [total hours]) = 366.92.
        # Recovered: 220.15 + 110.08 = 330.23
        # HolPayReg = -(366.92 - 330.23) = -36.69

        self._validate_payslip(payslip_dec)

    def test_simple_n_holiday_pay_recovery_half_days(self):
        """
        Check that half days AND full days are taken into account
        """
        CONTRACT_START = datetime.date(2025, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                "date_from": CONTRACT_START,
                "date_to": datetime.date(CONTRACT_START.year, 12, 31),
                "prev_work_hours_per_week": 38,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 5,
                "prev_simple_holiday_pay_paid": 1000,
                "prev_double_holiday_pay_paid": 0,
            }),
        ]

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave Half Day",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 7, 22, 6, 0, 0),  # utc + 2
            'date_to': datetime.datetime(2026, 7, 22, 10, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }, {
            'name': "Legal Leave Whole Day",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 7, 20, 6, 0, 0),
            'date_to': datetime.datetime(2026, 7, 20, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2026, 7, 1), datetime.date(2026, 7, 31))

        paid_leaves_data = payslip._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 + 4)
        self.assertEqual(paid_leaves_data['amount'], 122.31 + 64.37)

        # HolPayRecN should be -186.68 * 0.9 = -168.01
        self._validate_payslip(payslip)

        payslip.action_payslip_done()

        payslip_dec = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))

        # Target (11.6 hours): 11.6 * min(16.09 [current hourly cost], 1000 [total amount] / 38 [total hours]) = 186.68.
        # Recovered: 168.01
        # HolPayReg = -(186.68 - 168.01) = -18.67
        self._validate_payslip(payslip_dec)

    def test_simple_n_holiday_pay_recovery_higher_salary(self):
        # Check that half days AND full days are taken into account
        CONTRACT_START = datetime.date(2025, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        # Employee received 10€ for 5 days of holidays from previous employer
        # The salary being higher in his current company, the HolPayRec will be 90% of the holiday pay. Regularization happens in December.
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                "date_from": CONTRACT_START,
                "date_to": datetime.date(CONTRACT_START.year, 12, 31),
                "prev_work_hours_per_week": 38,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 5,
                "prev_simple_holiday_pay_paid": 10,
                "prev_double_holiday_pay_paid": 0,
            }),
        ]

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave Half Day",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 7, 22, 6, 0, 0),  # utc + 2
            'date_to': datetime.datetime(2026, 7, 22, 10, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }, {
            'name': "Legal Leave Whole Day",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 7, 20, 6, 0, 0),
            'date_to': datetime.datetime(2026, 7, 20, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2026, 7, 1), datetime.date(2026, 7, 31))
        paid_leaves_data = payslip._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 + 4)
        self.assertEqual(paid_leaves_data['amount'], 122.31 + 64.37)

        # HolPayRecN should be -186.68 * 0.9 = -168.01
        self._validate_payslip(payslip)

        payslip.action_payslip_done()

        payslip_dec = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))

        # Recomputed 100% Wage Base (11.6 hours): 11.6h * 16.0931 €/h = 186.68 €
        # Max Recoverable: min(100% Wage Base [186.68 €], Cap [10.00 € * 11.6 / 38 hours taken = 3.05 €]) = 3.05 €
        # Actual Recovered in July: 168.01 €
        # HolPayRegN = -(3.05 - 168.01) = 164.96 € (Reimbursement)
        self._validate_payslip(payslip_dec)

    def test_simple_n_holiday_pay_recovery_lower_salary(self):
        CONTRACT_START = datetime.date(2025, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        # Employee received 10 000€ for 2 days of holidays from the previous employer
        # The salary being lower in his current company, the HolPayRec will be 90% of the holiday pay. Regularization happens in December.
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                "date_from": CONTRACT_START,
                "date_to": datetime.date(CONTRACT_START.year, 12, 31),
                "prev_work_hours_per_week": 38,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 2,
                "prev_simple_holiday_pay_paid": 10000,
                "prev_double_holiday_pay_paid": 0,
            }),
        ]

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave Full Week",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 7, 20, 6, 0, 0),
            'date_to': datetime.datetime(2026, 7, 24, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2026, 7, 1), datetime.date(2026, 7, 31))
        paid_leaves_data = payslip._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 * 5)
        self.assertEqual(paid_leaves_data['amount'], 611.54)

        # HolPayRecN should be -244.62 * 0.9 = -220.15
        self._validate_payslip(payslip)

        payslip.action_payslip_done()

        payslip_dec = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))

        # Target (15.2 hours): 15.2 * min(16.09 [current cost], 10000 [total amount] / 15.2 [total hours]) = 244.62.
        # Recovered: 220.15
        # HolPayRegN = -(244.62 - 220.15) = -24.47
        self._validate_payslip(payslip_dec)

    def test_simple_n_holiday_pay_recovery_lower_salary_2_payslips(self):
        CONTRACT_START = datetime.date(2025, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        # Employee received 10 000€ for 3 days of holidays from the previous employer
        # Employee took 2 days in September (HolPayRec = 90% of the holiday pay for 2 days)
        # Employee took 2 days in October (HolPayRec = 90% of the holiday pay for the 1 remaining day to recover)
        # Employee took 4 days in November (HolPayRec = 0 as all days are already recovered)
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                "date_from": CONTRACT_START,
                "date_to": datetime.date(CONTRACT_START.year, 12, 31),
                "prev_work_hours_per_week": 38,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 3,
                "prev_simple_holiday_pay_paid": 10000,
                "prev_double_holiday_pay_paid": 0,
            }),
        ]

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal leave 2 days september",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 9, 21, 6, 0, 0),
            'date_to': datetime.datetime(2026, 9, 22, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal leave 2 days october",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 10, 12, 6, 0, 0),
            'date_to': datetime.datetime(2026, 10, 13, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal leave 4 days november",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 11, 9, 6, 0, 0),
            'date_to': datetime.datetime(2026, 11, 12, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        paid_leaves_data = payslip._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 * 2)
        self.assertEqual(paid_leaves_data['amount'], 244.62)

        # HolPayRecN should be -244.62 * 0.9 = -220.15
        self._validate_payslip(payslip)

        payslip2 = self._generate_payslip(datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
        self.employee.write({'review_state': '1_reviewed'})
        payslip2.action_payslip_done()
        paid_leaves_data = payslip2._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 * 2)
        self.assertEqual(paid_leaves_data['amount'], 244.62)

        # HolPayRecN should be -122.31 * 0.9 = -110.08
        self._validate_payslip(payslip2)

        payslip3 = self._generate_payslip(datetime.date(2026, 11, 1), datetime.date(2026, 11, 30))
        paid_leaves_data = payslip3._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 * 4)
        self.assertEqual(paid_leaves_data['amount'], 489.23)

        self._validate_payslip(payslip3)

        payslip3.action_payslip_done()
        payslip_dec = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))

        # Target (22.8 hours): 22.8 * min(16.09 [current cost], 10000 [total amount] / 22.8 [total hours]) = 366.92
        # Recovered: 220.15 + 110.08 = 330.23
        # HolPayRegN = -(366.92 - 330.23) = -36.69
        self._validate_payslip(payslip_dec)

    def test_refund_accounting_entries(self):
        payslip = self._generate_payslip(datetime.date(2022, 8, 1), datetime.date(2022, 8, 31))
        self._validate_payslip(payslip)
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()

        net_account_move_line = payslip.move_id.line_ids.filtered(lambda l: l.name == 'Net Salary')
        self.assertAlmostEqual(net_account_move_line.debit, 0.0, places=2)
        self.assertAlmostEqual(net_account_move_line.credit, 2199.64, places=2)

        refund = payslip._action_refund_payslips()
        self._validate_payslip(refund)
        self.employee.write({'review_state': '1_reviewed'})

        net_account_move_line = refund.move_id.line_ids.filtered(lambda l: l.name == 'Net Salary')
        self.assertAlmostEqual(net_account_move_line.debit, 2199.64, places=2)
        self.assertAlmostEqual(net_account_move_line.credit, 0.0, places=2)

    def _correct_august_payslip_with_lower_wage(self, paid):
        payslip = self._generate_payslip(datetime.date(2022, 8, 1), datetime.date(2022, 8, 31))
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        if paid:
            payslip.action_payslip_paid()
        payslip._action_refund_payslips()
        self.version.wage -= 1000
        self.employee.write({'review_state': '1_reviewed'})
        correction = payslip._action_correct_payslips()
        correction.action_payslip_done()
        return payslip, correction

    def test_negative_correction_delta_is_recovered(self):
        """ The correction of a paid payslip pays the difference of net with the original payslip:
        when it is negative, the employee owes it and it is recovered on the next payslips. """
        payslip, correction = self._correct_august_payslip_with_lower_wage(paid=True)
        debt = payslip.net_wage - correction.net_wage
        self.assertGreater(debt, 0)
        self.assertAlmostEqual(correction.correction_net_delta, -debt, places=2)
        self.assertEqual(correction._get_line_values(['NET_TO_RECOVER'])['NET_TO_RECOVER'][correction.id]['total'], 0)

        september = self._generate_payslip(datetime.date(2022, 9, 1), datetime.date(2022, 9, 30))
        line_values = september._get_line_values(['NET_TO_RECOVER', 'NET'])
        self.assertAlmostEqual(line_values['NET_TO_RECOVER'][september.id]['total'], -debt, places=2)
        self.assertGreater(line_values['NET'][september.id]['total'], 0)

        self.employee.write({'review_state': '1_reviewed'})
        september.action_payslip_done()
        move_lines = september.move_id.line_ids
        recovery_line = move_lines.filtered(lambda l: l.name == 'Net Amount to Recover')
        self.assertAlmostEqual(recovery_line.credit, debt, places=2)
        self.assertEqual(recovery_line.account_id, move_lines.filtered(lambda l: l.name == 'Net Salary').account_id)
        self.assertFalse(move_lines.filtered(lambda l: l.name == 'Adjustment Entry'))

        # the debt is recovered once
        october = self._generate_payslip(datetime.date(2022, 10, 1), datetime.date(2022, 10, 31))
        self.assertEqual(october._get_line_values(['NET_TO_RECOVER'])['NET_TO_RECOVER'][october.id]['total'], 0)

    def test_negative_correction_delta_of_unpaid_payslip(self):
        """ Nothing was paid to the employee: a negative correction delta isn't owed. """
        dummy, correction = self._correct_august_payslip_with_lower_wage(paid=False)
        self.assertLess(correction.correction_net_delta, 0)

        september = self._generate_payslip(datetime.date(2022, 9, 1), datetime.date(2022, 9, 30))
        self.assertEqual(september._get_line_values(['NET_TO_RECOVER'])['NET_TO_RECOVER'][september.id]['total'], 0)

    def test_sick_time_off_without_guaranteed_salary_half_days_no_attendances(self):
        # Check the sick time off is not counted twice on half/full days
        # if only sick time off without attendances (and without guaranteed salary)

        self.version.write({
            'wage': 3846.00,
            'resource_calendar_id': self.resource_calendar_4_5_monday_off_equal_morning_afternoon.id,
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True

        sick_leave_1 = self.env['hr.leave'].new({
            'name': 'Sick Time Off 16 days',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2022, 9, 26),
            'request_date_to': datetime.date(2022, 10, 17),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 16,
        })
        sick_leave_1._compute_date_from_to()
        sick_leave_1 = self.env['hr.leave'].create(sick_leave_1._convert_to_write(sick_leave_1._cache))

        sick_leave_2 = self.env['hr.leave'].new({
            'name': 'Sick Time Off 20 days',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2022, 10, 18),
            'request_date_to': datetime.date(2022, 11, 14),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 20,
            'l10n_be_sickness_relapse': True,
            'l10n_be_sickness_relapse_origin_leave_id': sick_leave_1.id,
        })
        sick_leave_2._compute_date_from_to()
        sick_leave_2 = self.env['hr.leave'].create(sick_leave_2._convert_to_write(sick_leave_2._cache))

        payslip = self._generate_payslip(datetime.date(2022, 10, 1), datetime.date(2022, 10, 31))

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        # Without guaranteed salary
        wds = payslip.worked_days_line_ids
        sick = wds.filtered(lambda wd: wd.code == "122.00" and math.isclose(wd.number_of_hours, 22.8, abs_tol=1e-9))
        self.assertAlmostEqual(sick.amount, 0, places=2)
        # Sick time off
        sick = wds.filtered(lambda wd: wd.code == "013.00")
        self.assertAlmostEqual(sick.amount, 3180.36, places=2)

        self._validate_payslip(payslip)

    def test_example(self):
        self.version.write({
            'wage': 2500,
            'internet': 0,
            'mobile': 0,
            'transport_mode_car': False,
            'ip_wage_rate': 0,
            'contract_date_start': datetime.date(2019, 1, 1),
        })
        payslip = self._generate_payslip(datetime.date(2019, 10, 1), datetime.date(2019, 10, 31))

        self._validate_payslip(payslip)

    def test_holiday_attest_occupation(self):
        emp = self.env['hr.employee'].create({
            'name': "Holiday attest test emp",
            'lang': 'fr_BE',
        })
        versions = self.env['hr.version'].create([
            {
                'employee_id': emp.id,
                'date_version': datetime.date(2024, 2, 19),
                'contract_date_start': datetime.date(2024, 2, 19),
                'contract_date_end': datetime.date(2025, 1, 19),
            },
            {
                'employee_id': emp.id,
                'date_version': datetime.date(2025, 1, 20),
                'contract_date_start': datetime.date(2025, 1, 20),
                'contract_date_end': datetime.date(2025, 12, 31),
                'resource_calendar_id': self.resource_calendar_4_5_friday_off.id,
            },
        ])
        payslips = self.env['hr.payslip'].create([
            {
                'name': 'Payslip',
                'employee_id': versions.employee_id.id,
                'version_id': versions[0].id,
                'date_from': datetime.date(2025, 1, 1),
                'date_to': datetime.date(2025, 1, 31),
            }
        ])
        payslips |= self.env['hr.payslip'].create([
            {
                'name': f'Payslip {month}',
                'employee_id': versions.employee_id.id,
                'version_id': versions[1].id,
                'date_from': datetime.date(2025, month, 1),
                'date_to': datetime.date(2025, month, 1) + relativedelta(day=31),
            } for month in range(1, 13)
        ])
        payslips.action_payslip_done()
        attest_occupations = versions.employee_id.get_l10n_be_holiday_attest_occupations(2025)
        self.assertEqual(len(attest_occupations), 2)
        occ1, occ2 = attest_occupations

        self.assertEqual({
            'date_start': datetime.date(2025, 1, 1),
            'date_end': datetime.date(2025, 1, 19),
            'hours_per_week': 38.0,
            'days_per_week': 5.0,
            'equivalent_days': 21.0,
            'european_leaves': 0,
            'european_leaves_amount': 0,
            'non_equivalent_days': 2,
            'paid_leaves': 0,
            'postponed_leaves': 0,
            'attest_paid_leaves': 0,
            'reference_hours_per_week': 38.0,
            'senior_youth_leaves': 0,
        }, occ1)

        self.assertEqual({
            'date_start': datetime.date(2025, 1, 20),
            'date_end': datetime.date(2025, 12, 31),
            'hours_per_week': 30.4,
            'days_per_week': 4.0,
            'equivalent_days': 199.0,
            'non_equivalent_days': 49.0,
            'european_leaves': 0,
            'european_leaves_amount': 0,
            'paid_leaves': 0,
            'postponed_leaves': 0,
            'attest_paid_leaves': 0,
            'reference_hours_per_week': 38.0,
            'senior_youth_leaves': 0,
        }, occ2)

    def test_cdi_laurie_poiret(self):
        self.version.ip_wage_rate = 0
        payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))
        self._validate_payslip(payslip)

    def test_without_car_without_atn(self):
        # 4 hours unpaid, 2 days leave, no atn and no car
        # Note: The IP is not the same as in the reference payslip, as it
        # was incorrectly computed by SDWorx during 2018
        self.version.write({
            'date_version': datetime.date(2018, 1, 1),
            'contract_date_start': datetime.date(2018, 1, 1),
            'wage': 3746.33,
            'internet': 0,
            'mobile': 0,
            'transport_mode_car': False,
        })
        self.unpaid_time_off_type.request_unit = 'half_day'
        unpaid_time_off = self.env['hr.leave'].create({
            'name': 'Unpaid Leave 4 hours',
            'work_entry_type_id': self.unpaid_time_off_type.id,
            'request_date_from': '2018-11-06',
            'request_date_to': '2018-11-06',
            'request_date_from_period': 'am',
            'request_date_to_period': 'am',
            'employee_id': self.employee.id,
        })

        self.env['resource.calendar.leaves'].create({
            'name': "Bank Holiday",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2018, 11, 9, 7),
            'date_to': datetime.datetime(2018, 11, 9, 18),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        })

        payslip = self._generate_payslip(datetime.date(2018, 11, 1), datetime.date(2018, 11, 30))
        self._validate_payslip(payslip)

    def test_with_car_with_atn_with_child(self):
        # 2 unpaid days + 2 bank holidays + IP + Mobile + 1 child + extra leaves
        # IP should be correct as we are in 2019,
        self.version.employee_id.write({
            'marital': 'cohabitant',
            'spouse_fiscal_status': 'high_income',
            'children': 1,
        })
        self.version.car_id.write({
            'acquisition_date': datetime.date(2018, 1, 15),
            'contract_date_start': datetime.date(2018, 1, 15),
            'car_value': 29235.15,
            'fuel_type': 'diesel',
            'co2': 89,
        })
        vehicle = self.version.car_id
        self.env['fleet.vehicle.log.contract'].create({
            'vehicle_id': vehicle.id,
            'recurring_cost_amount_depreciated': vehicle.model_id.default_recurring_cost_amount_depreciated,
            'purchaser_id': vehicle.driver_id.id,
            'company_id': vehicle.company_id.id,
            'user_id': vehicle.manager_id.id if vehicle.manager_id else self.env.user.id,
            'start_date': datetime.date.today(),
        })
        self.version.car_id.log_contracts.recurring_cost_amount_depreciated = 562.52
        self.version.write({
            'wage': 3542.63,
            'holidays': 1,
            'mobile': 0,
        })

        unpaid_times_off = self.env['hr.leave'].create([{
            'name': 'Unpaid Leave Day 1',
            'work_entry_type_id': self.unpaid_time_off_type.id,
            'date_from': datetime.datetime(2019, 5, 1, 5),
            'date_to': datetime.datetime(2019, 5, 1, 20),
            'request_date_from': datetime.datetime(2019, 5, 1, 5),
            'request_date_to': datetime.datetime(2019, 5, 1, 20),
            'number_of_days': 1,
            'employee_id': self.employee.id,
        }, {
            'name': 'Unpaid Leave Day 2',
            'work_entry_type_id': self.unpaid_time_off_type.id,
            'date_from': datetime.datetime(2019, 5, 2, 5),
            'date_to': datetime.datetime(2019, 5, 2, 20),
            'request_date_from': datetime.datetime(2019, 5, 2, 5),
            'request_date_to': datetime.datetime(2019, 5, 2, 20),
            'number_of_days': 1,
            'employee_id': self.employee.id,
        }])

        self.env['resource.calendar.leaves'].create([{
            'name': "Bank Holiday Day 1",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2019, 5, 7, 5),
            'date_to': datetime.datetime(2019, 5, 7, 20),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }, {
            'name': "Bank Holiday Day 2",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2019, 5, 6, 5),
            'date_to': datetime.datetime(2019, 5, 6, 20),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }])

        payslip = self._generate_payslip(datetime.date(2019, 5, 1), datetime.date(2019, 5, 31))
        self._validate_payslip(payslip)

    def test_with_car_with_atn_with_car(self):
        # ATN + No leave + IP (2019) + car
        self.version.employee_id.write({
            'marital': 'cohabitant',
            'spouse_fiscal_status': 'high_income',
        })
        self.version.car_id.write({
            'acquisition_date': datetime.date(2014, 12, 10),
            'contract_date_start': datetime.date(2014, 12, 10),
            'car_value': 28138.86,
            'fuel_type': 'diesel',
            'co2': 88.00,
        })
        vehicle = self.version.car_id
        self.env['fleet.vehicle.log.contract'].create({
            'vehicle_id': vehicle.id,
            'recurring_cost_amount_depreciated': vehicle.model_id.default_recurring_cost_amount_depreciated,
            'purchaser_id': vehicle.driver_id.id,
            'company_id': vehicle.company_id.id,
            'user_id': vehicle.manager_id.id if vehicle.manager_id else self.env.user.id,
            'start_date': datetime.date.today(),
        })
        self.version.car_id.log_contracts.recurring_cost_amount_depreciated = 503.12
        self.version.write({
            'wage': 3470.36,
            'holidays': 1,
            'mobile': 0,
            'ip_wage_rate': 0.25,
        })

        payslip = self._generate_payslip(datetime.date(2019, 3, 1), datetime.date(2019, 3, 31))
        self._validate_payslip(payslip)

    def test_with_car_with_atn_with_car_based_on_yearly_cost(self):
        # ATN + No leave + IP (2019) + car
        self.version.employee_id.write({
            'marital': 'cohabitant',
            'spouse_fiscal_status': 'high_income',
        })
        self.version.car_id.write({
            'acquisition_date': datetime.date(2014, 12, 10),
            'contract_date_start': datetime.date(2014, 12, 10),
            'car_value': 28138.86,
            'fuel_type': 'diesel',
            'co2': 88.00,
        })
        vehicle = self.version.car_id
        self.env['fleet.vehicle.log.contract'].create({
            'vehicle_id': vehicle.id,
            'recurring_cost_amount_depreciated': vehicle.model_id.default_recurring_cost_amount_depreciated,
            'purchaser_id': vehicle.driver_id.id,
            'company_id': vehicle.company_id.id,
            'user_id': vehicle.manager_id.id if vehicle.manager_id else self.env.user.id
        })
        self.version.car_id.log_contracts.recurring_cost_amount_depreciated = 503.12
        self.version.write({
            'wage': 3450.89,
            'holidays': 1,
            'mobile': 0,
            'ip_wage_rate': 0.25,
        })

        cost_before = self.version.final_yearly_costs
        the_car = self.version.car_id
        self.version.car_id = False
        self.version.car_id = the_car
        self.assertEqual(self.version.final_yearly_costs, cost_before)

    def test_car_co2_greening_fee_2026(self):
        # After July 1st 2023
        self.car.write({
            'contract_date_start': datetime.date(2023, 7, 15),
            'co2': 105.0,
            'fuel_type': 'diesel',
        })

        # Calculation Logic for CO2 FEE:
        # Base: [(CO2 * 9) - 600] / 12 * Indexation * Greening_Multiplier
        # Greening Multiplier Factor for 2026: 4.00
        # ((105 * 9 - 600) / 12) * (185.85/114.08) * (4)
        # High fee due to Greening factor
        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        self._validate_payslip(payslip)

    def test_car_co2_greening_min_fee_2026(self):
        # After July 1st 2023
        # Electric cars are also affected by greening but stay at the MINIMUM fee
        self.car.write({
            'contract_date_start': datetime.date(2023, 7, 15),
            'fuel_type': 'electric',  # min_fee
            'co2': 0,
        })

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        # Calculation: Min Greening Fee * Indexation
        # Min greening Fee for 2026: 25.99
        # 25.99 * (185.85/114.08) = 42.34
        self._validate_payslip(payslip)

    def test_no_ip_emp_bonus(self):
        # No IP, with employment bonus
        self.version.write({
            'wage': 2075.44,
            'internet': False,
            'mobile': False,
            'transport_mode_car': False,
            'ip_wage_rate': 0,
        })
        payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))
        self._validate_payslip(payslip)

    def test_small_unemployment_leave(self):
        # Small unemployment leave, spouse without income
        self.version.employee_id.write({
            'marital': 'married',
            'children': 1,
            'spouse_fiscal_status': 'without_income',
        })
        self.version.write({
            'wage': 2706.14,
        })

        brief_holidays = self.env['hr.leave'].create([{
            'name': 'Small Unemployment - Day 1',
            'work_entry_type_id': self.work_entry_type_small_unemployment.id,
            'date_from': datetime.datetime(2019, 2, 27, 5),
            'date_to': datetime.datetime(2019, 2, 27, 20),
            'request_date_from': datetime.datetime(2019, 2, 27, 5),
            'request_date_to': datetime.datetime(2019, 2, 27, 20),
            'number_of_days': 1,
            'employee_id': self.employee.id,
        }, {
            'name': 'Small Unemployment - Day 2',
            'work_entry_type_id': self.work_entry_type_small_unemployment.id,
            'date_from': datetime.datetime(2019, 2, 28, 5),
            'date_to': datetime.datetime(2019, 2, 28, 20),
            'request_date_from': datetime.datetime(2019, 2, 28, 5),
            'request_date_to': datetime.datetime(2019, 2, 28, 20),
            'number_of_days': 1,
            'employee_id': self.employee.id,
        }])

        payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))
        self._validate_payslip(payslip)

    def test_pfi_with_benefits_pay(self):
        self.version.write({
            'wage': 1572.8,
            'l10n_be_dimona_category': 'ivt',
            'ip_wage_rate': 0,
        })
        payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))
        self._validate_payslip(payslip)

    def test_repartition_few_half_days(self):
        calendar = self.env['resource.calendar'].create([{
            'name': "Test Calendar : 26 Hours/Week",
            'company_id': self.env.company.id,
            'hours_per_day': 6.67,
            'full_time_required_hours': 38.0,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id

            }) for dayofweek, hour_from, hour_to in [
                ("0", 9.0, 12.0),
                ("0", 12.75, 17),
                ("1", 9.0, 12.0),
                ("1", 12.75, 17.0),
                ("2", 9.0, 14.75),
                ("3", 9.0, 12.0),
                ("3", 12.75, 17),
            ]],
        }])
        self.employee.resource_calendar_id = calendar
        self.version.write({
            'wage': 908.33,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'resource_calendar_id': calendar.id,
            'contract_date_start': datetime.date(2023, 3, 27),
            'internet': 0,
            'mobile': 0,
            'ip_wage_rate': 0,
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True

        sick_leave = self.env['hr.leave'].new({
            'name': 'Sick Time Off 3 Days',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_time_off_type.id,
            'request_date_from': datetime.date(2023, 3, 27),
            'request_date_to': datetime.date(2023, 3, 29),
            'request_hour_from': 7,
            'request_hour_to': 18,
            'number_of_days': 3,
        })
        sick_leave._compute_date_from_to()
        sick_leave = self.env['hr.leave'].create(sick_leave._convert_to_write(sick_leave._cache))
        payslip = self._generate_payslip(datetime.date(2023, 3, 1), datetime.date(2023, 3, 31))

        wds = payslip.worked_days_line_ids.sorted("number_of_hours")
        self.assertAlmostEqual(wds[0].number_of_days, 1, places=2)
        self.assertAlmostEqual(wds[0].number_of_hours, 7.25, places=2)
        self.assertAlmostEqual(wds[0].amount, 55.26, places=2)
        self.assertEqual(wds[0].work_entry_type_id.code, "002.00")

        self.assertAlmostEqual(wds[1].number_of_days, 3, places=2)
        self.assertAlmostEqual(wds[1].number_of_hours, 20.25, places=2)
        self.assertAlmostEqual(wds[1].amount, 154.35, places=2)
        self.assertEqual(wds[1].work_entry_type_id.code, "013.00")

        self.assertAlmostEqual(wds[2].number_of_days, 14, places=2)
        self.assertAlmostEqual(wds[2].number_of_hours, 95.5, places=2)
        self.assertAlmostEqual(wds[2].amount, 0, places=2)
        self.assertEqual(wds[2].work_entry_type_id.code, "000.00")

        self._validate_payslip(payslip)

    def test_thirteen_month(self):
        payslip = self._generate_payslip(datetime.date(2023, 6, 1), datetime.date(2023, 6, 30), struct_id=self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month').id)
        self._validate_payslip(payslip)

    def _get_move_balances(self, payslip):
        """ Balance (credit - debit) of the journal entry of the payslip, by account code. """
        balances = defaultdict(float)
        for line in payslip.move_id.line_ids:
            balances[line.account_id.code] += line.credit - line.debit
        return balances

    def test_accounting_entries_thirteen_month(self):
        payslip = self._generate_payslip(
            datetime.date(2023, 12, 1), datetime.date(2023, 12, 31),
            struct_id=self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month').id)
        totals = {code: values[payslip.id]['total'] for code, values in payslip._get_line_values(
            ['BONUS_BASIC', 'NET', 'ONSSTOTAL', 'ONSSEMPLOYER', 'M.ONSS', 'PPTOTAL']).items()}
        self.assertTrue(all(totals.values()))
        payslip.action_payslip_done()

        self.assertFalse(payslip.move_id.line_ids.filtered(lambda line: line.name == 'Adjustment Entry'))
        balances = self._get_move_balances(payslip)
        self.assertAlmostEqual(balances['620200'], -totals['BONUS_BASIC'], places=2)
        self.assertAlmostEqual(balances['455000'], totals['NET'], places=2)
        self.assertAlmostEqual(balances['454000'], totals['ONSSTOTAL'] + totals['ONSSEMPLOYER'] - totals['M.ONSS'], places=2)
        self.assertAlmostEqual(balances['453000'], totals['PPTOTAL'], places=2)

    def test_accounting_entries_cct90(self):
        payslip = self._generate_payslip(
            datetime.date(2025, 1, 1), datetime.date(2025, 1, 31),
            struct_id=self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_cct90').id)
        payslip._set_input_value('CCT90BONUSPLAN', 10000)
        payslip.compute_sheet()
        totals = {code: values[payslip.id]['total'] for code, values in payslip._get_line_values(
            ['ONSS_BONUS', 'ONSS_SOLIDARITY_BONUS', 'ONSSEMPLOYER', 'BONUS_PP']).items()}
        self.assertTrue(totals['ONSS_BONUS'] and totals['BONUS_PP'])
        payslip.action_payslip_done()

        # The worker contributions on the bonus and the employer contributions are owed to the ONSS
        balances = self._get_move_balances(payslip)
        self.assertAlmostEqual(
            balances['454000'],
            -totals['ONSS_BONUS'] - totals['ONSS_SOLIDARITY_BONUS'] + totals['ONSSEMPLOYER'], places=2)
        self.assertAlmostEqual(balances['453000'], -totals['BONUS_PP'], places=2)

    def test_accounting_entries_mobility_budget_special_contribution(self):
        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        payslip._set_input_value('MOBILITY_PAYMENT', 1000.0)
        payslip.compute_sheet()
        contribution = payslip._get_line_values(['ONSSEMPLOYER_869'])['ONSSEMPLOYER_869'][payslip.id]['total']
        self.assertLess(contribution, 0)
        payslip.action_payslip_done()

        move_line = payslip.move_id.line_ids.filtered(lambda line: line.name == 'Mobility Budget Special Contribution')
        self.assertEqual(move_line.account_id.code, '454000')
        self.assertAlmostEqual(move_line.credit, -contribution, places=2)
        self.assertAlmostEqual(move_line.debit, 0.0, places=2)

    def test_accounting_entries_onss_partner(self):
        # Every amount owed to the ONSS is booked with the ONSS as partner, for the reconciliation
        # with its payments and its partner ledger
        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        payslip._set_input_value('MOBILITY_PAYMENT', 1000.0)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        onss_lines = payslip.move_id.line_ids.filtered(lambda line: line.account_id.code == '454000')
        self.assertTrue(onss_lines)
        onss_partner = self.env.ref('l10n_be_hr_payroll.res_partner_onss')
        for line in onss_lines:
            self.assertEqual(line.partner_id, onss_partner, f"No ONSS partner on the line {line.name}")

    def test_simple_n_holiday_pay_recovery_2024(self):
        CONTRACT_START = datetime.date(2023, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        # Check that the same amount if recovered on 2 diffent months (July / February)
        # Employee received 10000€ for 2 days of holidays from previous employer
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                "date_from": CONTRACT_START,
                "date_to": datetime.date(CONTRACT_START.year, 12, 31),
                "prev_work_hours_per_week": 38,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 2,
                "prev_simple_holiday_pay_paid": 100000,
                "prev_double_holiday_pay_paid": 0,
            }),
        ]

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave Whole Day",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2024, 2, 11, 6, 0, 0),
            'date_to': datetime.datetime(2024, 2, 15, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2024, 2, 1), datetime.date(2024, 2, 29))
        paid_leaves_data = payslip._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 * 4)
        self.assertEqual(paid_leaves_data['amount'], 489.23)
        # Should be 122.31 * 2 * 0.90 = 220.15
        self._validate_payslip(payslip)

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave Whole Day",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2024, 7, 14, 6, 0, 0),
            'date_to': datetime.datetime(2024, 7, 18, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2024, 7, 1), datetime.date(2024, 7, 31))
        paid_leaves_data = payslip._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 * 4)
        self.assertEqual(paid_leaves_data['amount'], 489.23)

        # Should be 122.31 * 2 * 0.90 = 220.15
        self._validate_payslip(payslip)

    # same function for simple_n1 or simple_n so only one test.
    def test_simple_n_holiday_pay_recovery_lower_salary_2_payslips_2024(self):
        CONTRACT_START = datetime.date(2023, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        # Check that the same amount if recovered on 2 diffent months (July / February)
        # Employee received 1000€ for 5 days of holidays from previous employer
        # Employee took 2 days on january (so the HolPayRec should be equal to 90% of the holiday pay for 2 days)
        # Employee took 2 days on february (so the HolPayRec should be equal to 90% of the holiday pay for the 1 remaining day to recover)
        # Employee took 4 days on march (so the HolPayRec should be equal to 0 as all days are recovered)
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                "date_from": CONTRACT_START,
                "date_to": datetime.date(CONTRACT_START.year, 12, 31),
                "prev_work_hours_per_week": 38,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 3,
                "prev_simple_holiday_pay_paid": 100000,
                "prev_double_holiday_pay_paid": 0,
            }),
        ]

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2024, 1, 11, 6, 0, 0),
            'date_to': datetime.datetime(2024, 1, 12, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2024, 1, 1), datetime.date(2024, 1, 31))
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        paid_leaves_data = payslip._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 * 2)
        self.assertEqual(paid_leaves_data['amount'], 244.62)
        # HolPayRecN is 90% of the 2 day (122.31 * 2 * 0.90 = -220.15)
        self._validate_payslip(payslip)

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2024, 2, 6, 6, 0, 0),
            'date_to': datetime.datetime(2024, 2, 7, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2024, 2, 1), datetime.date(2024, 2, 29))
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        paid_leaves_data = payslip._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 * 2)
        self.assertEqual(paid_leaves_data['amount'], 244.62)
        # HolPayRecN is 90% of the remaining 1 day (122.31 * 0.90 = -110.08)
        self._validate_payslip(payslip)

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2024, 3, 18, 6, 0, 0),
            'date_to': datetime.datetime(2024, 3, 21, 19, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2024, 3, 1), datetime.date(2024, 3, 31))
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()
        paid_leaves_data = payslip._get_worked_days_line_values(['016.00'], ['amount', 'number_of_hours'], True)['016.00']['sum']
        self.assertEqual(paid_leaves_data['number_of_hours'], 7.6 * 4)
        self.assertEqual(paid_leaves_data['amount'], 489.23)
        # HolPayRecN should be equal to 0
        self._validate_payslip(payslip)

        payslip.action_payslip_done()

        payslip_dec = self._generate_payslip(datetime.date(2024, 12, 1), datetime.date(2024, 12, 31))

        # Target (22.8 hours): 22.8 * min(16.09 [current cost], 100000 [total amount] / 22.8 [total hours]) = 366.92
        # Recovered: 220.15 + 110.08 = 330.23
        # HolPayRegN = -(366.92 - 330.23) = -36.69
        self._validate_payslip(payslip_dec)

    def test_multiple_public_holidays_variable_salary(self):
        self.version.commission_on_target = 1000
        self.env['resource.calendar.leaves'].create([{
            'name': 'Public Time Off 1',
            'date_from': datetime.datetime(2023, 8, 7, 2),
            'date_to': datetime.datetime(2023, 8, 7, 22),
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id,
            'count_as': 'absence',
        }, {
            'name': 'Public Time Off 2',
            'date_from': datetime.datetime(2023, 8, 8, 2),
            'date_to': datetime.datetime(2023, 8, 8, 22),
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id,
            'count_as': 'absence',
        }, {
            'name': 'Public Time Off 3',
            'date_from': datetime.datetime(2023, 8, 9, 2),
            'date_to': datetime.datetime(2023, 8, 9, 22),
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id,
            'count_as': 'absence',
        }])

        commission_payslip = self._generate_payslip(datetime.date(2022, 12, 1), datetime.date(2022, 12, 31), input_values={'COMMISSION': 10000})
        self.employee.write({'review_state': '1_reviewed'})
        commission_payslip.action_payslip_done()

        payslip = self._generate_payslip(datetime.date(2023, 8, 1), datetime.date(2023, 8, 31))
        self._validate_payslip(payslip)

    def test_parental_time_off_out_of_contract(self):
        self.version.write({
            'name': "4/5 Parental Time Off",
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'resource_calendar_id': self.resource_calendar_4_5_friday_off.id,
            'date_version': datetime.date(2023, 4, 1),
            'contract_date_start': datetime.date(2023, 4, 1),
            'contract_date_end': datetime.date(2023, 8, 13),
            'wage': 2562.78 * (5 / 4),
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True

        extra_legal_time_off = self.env['hr.leave'].create({
            'name': 'Extra Legal Time Off',
            'work_entry_type_id': self.extra_legal_time_off_type.id,
            'date_from': datetime.datetime(2023, 8, 1, 6, 0, 0),
            'date_to': datetime.datetime(2023, 8, 10, 20, 0, 0),
            'request_date_from': datetime.datetime(2023, 8, 1, 6, 0, 0),
            'request_date_to': datetime.datetime(2023, 8, 10, 20, 0, 0),
            'number_of_days': 7,
            'employee_id': self.employee.id,
        })

        payslip = self._generate_payslip(datetime.date(2023, 8, 1), datetime.date(2023, 8, 31))

        self._validate_worked_days(payslip, {
            '000.00': (14.0, 106.4, 0.0),
            '011.00': (7.0, 53.2, 1034.97),
            '147.00': (2.0, 15.2, 0.0),
        })

        self._validate_payslip(payslip)

        version_2 = self.version.copy({
            'date_version': datetime.date(2023, 8, 14),
            'contract_date_start': datetime.date(2023, 8, 14),
            'contract_date_end': datetime.date(2023, 12, 21),
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
        })

        # Public Holiday
        self.env['resource.calendar.leaves'].create([{
            'name': "15 Aout",
            'calendar_id': False,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2023, 8, 15, 5, 0, 0),
            'date_to': datetime.datetime(2023, 8, 15, 20, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id
        }])

        # Paid Time Off
        self.env['resource.calendar.leaves'].create([{
            'name': "Paid Time Off",
            'calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2023, 8, 14, 6, 0, 0),
            'date_to': datetime.datetime(2023, 8, 14, 14, 36, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2023, 8, 1), datetime.date(2023, 8, 31), version_id=version_2.id)

        self._validate_worked_days(payslip, {
            '002.00': (9.0, 68.4, 1202.54),
            '000.00': (9.0, 68.4, 0.0),
            '016.00': (1.0, 7.6, 147.85),
            '147.00': (3.0, 22.8, 0.0),
            '006.00': (1.0, 7.6, 147.85),
        })

        self._validate_payslip(payslip)

    def test_onss_and_tax_regularisation_01(self):
        periodic_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        periodic_payslip_results = self._validate_payslip(periodic_payslip)
        periodic_payslip.action_payslip_done()

        non_periodic_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'HIRINGBONUS': 10000})
        non_periodic_payslip.ignore_worked_day_lines = True
        non_periodic_payslip_results = self._validate_payslip(non_periodic_payslip)

        (periodic_payslip | non_periodic_payslip).action_payslip_draft()
        (periodic_payslip | non_periodic_payslip).unlink()

        verification_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'HIRINGBONUS': 10000})

        codes_to_check = ['BASIC', 'ONSSTOTAL', 'P.P', 'P.P.DED', 'PPTOTAL', 'M.ONSS', 'NET']
        verification_results = verification_payslip._get_line_values(codes_to_check)
        for code in codes_to_check:
            sum_result = non_periodic_payslip_results.get(code, 0) + periodic_payslip_results.get(code, 0)
            self.assertAlmostEqual(verification_results[code][verification_payslip.id]['total'], sum_result, 2)

    def test_onss_and_tax_regularisation_02(self):
        non_periodic_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'HIRINGBONUS': 10000})
        non_periodic_payslip.ignore_worked_day_lines = True
        non_periodic_payslip_results = self._validate_payslip(non_periodic_payslip)
        non_periodic_payslip.action_payslip_done()

        periodic_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        periodic_payslip_results = self._validate_payslip(periodic_payslip)

        (periodic_payslip | non_periodic_payslip).action_payslip_draft()
        (periodic_payslip | non_periodic_payslip).unlink()

        verification_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'HIRINGBONUS': 10000})

        codes_to_check = ['BASIC', 'ONSSTOTAL', 'P.P', 'P.P.DED', 'PPTOTAL', 'M.ONSS', 'NET']
        verification_results = verification_payslip._get_line_values(codes_to_check)
        for code in codes_to_check:
            sum_result = non_periodic_payslip_results.get(code, 0) + periodic_payslip_results.get(code, 0)
            self.assertAlmostEqual(verification_results[code][verification_payslip.id]['total'], sum_result, 2)

    def test_onss_and_tax_regularisation_03(self):
        periodic_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        periodic_payslip_results = self._validate_payslip(periodic_payslip)
        periodic_payslip.action_payslip_done()

        non_periodic_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'COMMISSION': 350})
        non_periodic_payslip.ignore_worked_day_lines = True
        non_periodic_payslip_results = self._validate_payslip(non_periodic_payslip)

        (periodic_payslip | non_periodic_payslip).action_payslip_draft()
        (periodic_payslip | non_periodic_payslip).unlink()

        verification_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'COMMISSION': 350})

        codes_to_check = ['BASIC', 'ONSSTOTAL', 'P.P', 'P.P.DED', 'PPTOTAL', 'M.ONSS', 'NET']
        verification_results = verification_payslip._get_line_values(codes_to_check)
        for code in codes_to_check:
            sum_result = non_periodic_payslip_results.get(code, 0) + periodic_payslip_results.get(code, 0)
            self.assertAlmostEqual(verification_results[code][verification_payslip.id]['total'], sum_result, 2)

    def test_onss_and_tax_regularisation_04(self):
        non_periodic_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'COMMISSION': 350})
        non_periodic_payslip.ignore_worked_day_lines = True
        non_periodic_payslip_results = self._validate_payslip(non_periodic_payslip)
        non_periodic_payslip.action_payslip_done()

        periodic_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        periodic_payslip_results = self._validate_payslip(periodic_payslip)

        (periodic_payslip | non_periodic_payslip).action_payslip_draft()
        (periodic_payslip | non_periodic_payslip).unlink()

        verification_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'COMMISSION': 350})

        codes_to_check = ['BASIC', 'ONSSTOTAL', 'P.P', 'P.P.DED', 'PPTOTAL', 'M.ONSS', 'NET']
        verification_results = verification_payslip._get_line_values(codes_to_check)
        for code in codes_to_check:
            sum_result = non_periodic_payslip_results.get(code, 0) + periodic_payslip_results.get(code, 0)
            self.assertAlmostEqual(verification_results[code][verification_payslip.id]['total'], sum_result, 2)

    def test_onss_and_tax_regularisation_05(self):
        self.version.write({
            'wage': 1500,
        })
        periodic_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        periodic_payslip_results = self._validate_payslip(periodic_payslip)
        periodic_payslip.action_payslip_done()

        non_periodic_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'COMMISSION': 5000})
        non_periodic_payslip.ignore_worked_day_lines = True
        non_periodic_payslip_results = self._validate_payslip(non_periodic_payslip)

        (periodic_payslip | non_periodic_payslip).action_payslip_draft()
        (periodic_payslip | non_periodic_payslip).unlink()

        verification_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'COMMISSION': 5000})

        codes_to_check = ['BASIC', 'ONSSTOTAL', 'P.P', 'P.P.DED', 'PPTOTAL', 'M.ONSS', 'NET']
        verification_results = verification_payslip._get_line_values(codes_to_check)
        for code in codes_to_check:
            sum_result = non_periodic_payslip_results.get(code, 0) + periodic_payslip_results.get(code, 0)
            self.assertAlmostEqual(verification_results[code][verification_payslip.id]['total'], sum_result, 2)

    def test_onss_and_tax_regularisation_06(self):
        self.version.write({
            'wage': 1500,
        })
        non_periodic_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'COMMISSION': 5000})
        non_periodic_payslip.ignore_worked_day_lines = True
        non_periodic_payslip_results = self._validate_payslip(non_periodic_payslip)
        non_periodic_payslip.action_payslip_done()

        periodic_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        periodic_payslip_results = self._validate_payslip(periodic_payslip)
        periodic_payslip.action_payslip_done()

        (periodic_payslip | non_periodic_payslip).action_payslip_draft()
        (periodic_payslip | non_periodic_payslip).unlink()

        verification_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'COMMISSION': 5000})

        codes_to_check = ['BASIC', 'ONSSTOTAL', 'P.P', 'P.P.DED', 'PPTOTAL', 'M.ONSS', 'NET']
        verification_results = verification_payslip._get_line_values(codes_to_check)
        for code in codes_to_check:
            sum_result = non_periodic_payslip_results.get(code, 0) + periodic_payslip_results.get(code, 0)
            self.assertAlmostEqual(verification_results[code][verification_payslip.id]['total'], sum_result, 2)

    def test_onss_and_tax_regularisation_07(self):
        self.version.write({
            'wage': 1500,
        })
        periodic_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        periodic_payslip_results = self._validate_payslip(periodic_payslip)
        periodic_payslip.action_payslip_done()

        non_periodic_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        non_periodic_payslip.ignore_worked_day_lines = True
        non_periodic_payslip_results = self._validate_payslip(non_periodic_payslip)

        (periodic_payslip | non_periodic_payslip).action_payslip_draft()
        (periodic_payslip | non_periodic_payslip).unlink()

        verification_payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))

        codes_to_check = ['BASIC', 'ONSSTOTAL', 'P.P', 'P.P.DED', 'PPTOTAL', 'M.ONSS', 'NET']
        verification_results = verification_payslip._get_line_values(codes_to_check)
        for code in codes_to_check:
            sum_result = non_periodic_payslip_results.get(code, 0) + periodic_payslip_results.get(code, 0)
            self.assertAlmostEqual(verification_results[code][verification_payslip.id]['total'], sum_result, 2)

    def test_bik_first_payslip_unpaid(self):
        self.version.write({
            'name': "Full Time Parental Time Off",
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'work_time_rate': 0,
            'resource_calendar_id': self.resource_calendar_0_hours_per_week.id,
            'date_version': datetime.date(2023, 10, 1),
            'contract_date_start': datetime.date(2023, 10, 1),
            'contract_date_end': datetime.date(2023, 10, 10),
            'wage': 0,
        })

        version_2 = self.version.copy({
            'name': '4/5 Parental Time Off',
            'date_version': datetime.date(2023, 10, 11),
            'contract_date_start': datetime.date(2023, 10, 11),
            'contract_date_end': False,
            'work_time_rate': 1.0,
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'l10n_be_lsa_monthly_misc_base_amount': 0,
            'l10n_be_lsa_monthly_pro_base_amount': 150,
            'wage': 3000 * (5 / 4),
            'l10n_be_dimona_category': 'alt',
        })

        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True
        payslip_1 = self._generate_payslip(datetime.date(2023, 10, 1), datetime.date(2023, 10, 31), version_id=self.version.id)
        payslip_2 = self._generate_payslip(datetime.date(2023, 10, 1), datetime.date(2023, 10, 31), version_id=version_2.id)

        self._validate_payslip(payslip_1)

        self._validate_payslip(payslip_2)

    def test_bik_for_short_contract(self):
        self.version.write({
            'contract_date_start': datetime.date(2026, 1, 1),
            'contract_date_end': datetime.date(2026, 1, 10),
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 283.73,
        })

        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True
        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 30))

        self._validate_worked_days(payslip, {
            '002.00': (7.0, 53.2, 856.15),
            '000.00': (15.0, 114.0, 0.0),
        })

        # Calculation for CAR.BIK:
        #  Version_1: 1st -> 10th January
        #   car_atn * (10/30)
        #  ∴ final_car_atn = 159.29 * (10/30)
        #                  = 53.1

        self._validate_payslip(payslip)

    def test_bik_across_multiple_versions(self):
        new_car = self.env['fleet.vehicle'].sudo().create([{
                'name': "New Test Car",
                'license_plate': "New TEST",
                'driver_id': self.work_contact.id,
                'company_id': self.env.company.id,
                'model_id': self.model.id,
                'contract_date_start': datetime.date(2026, 1, 1),
                'co2': 50.0,
                'car_value': 44000.0,
                'fuel_type': "lpg",
                'acquisition_date': datetime.date(2026, 1, 1)
            }]).sudo(False)

        self.version.copy({
            'name': 'New Version',
            'date_version': datetime.date(2026, 4, 15),
            'car_id': new_car.id
        })

        # Calculation for CAR.BIK:
        #  Version_1: 1st -> 14th April
        #   car_atn * (14/30)
        #  Version_2: 15th -> 30th April
        #   car_atn * (16/30)
        #  ∴ final_car_atn = 159.29 * (14/30) * 138.90 * (19/30)
        #               = 148.42
        payslip = self._generate_payslip(datetime.date(2026, 4, 1), datetime.date(2026, 4, 30))

        self._validate_payslip(payslip)

    def test_student_benefits_in_kind(self):
        self.version.write({
            'l10n_be_dimona_category': 'stu',
            'ip_wage_rate': 0,
            'internet': 40,
            'mobile': 20,
            'laptop': 100,
            'mobile_amount': 30,
            'tablet': 50,
        })
        payslip = self._generate_payslip(datetime.date(2025, 4, 1), datetime.date(2025, 4, 30))
        values = payslip._get_line_values(['ATN.INT', 'ATN.MOB', 'ATN.LAP', 'ATN.PHONE_AMT', 'ATN.TAB', 'ATN.CAR', 'ATN_DED', 'CO2FEE'])
        for code, amount in [('ATN.INT', 5), ('ATN.MOB', 4), ('ATN.LAP', 6), ('ATN.PHONE_AMT', 3), ('ATN.TAB', 3)]:
            self.assertAlmostEqual(values[code][payslip.id]['total'], amount, places=2)
        car_benefit = values['ATN.CAR'][payslip.id]['total']
        self.assertGreater(car_benefit, 0)
        self.assertGreater(values['CO2FEE'][payslip.id]['total'], 0)
        self.assertAlmostEqual(values['ATN_DED'][payslip.id]['total'], -21 - car_benefit, places=2)

    def test_mobility_budget_combustion_car(self):
        # Before 2026, pillar 1 also admits low-emission combustion cars. The
        # same CO2 contribution is owed, but declared under worker code 868.
        self.version.l10n_be_mobility_budget = True
        self.car.write({
            'fuel_type': 'plug_in_hybrid_gasoline',
            'co2': 40,
            'acquisition_date': datetime.date(2021, 1, 1),
        })
        payslip = self._generate_payslip(datetime.date(2025, 4, 1), datetime.date(2025, 4, 30))
        self.assertFalse(payslip.line_ids.filtered(lambda line: line.code == 'CO2FEE'))
        fee = payslip.line_ids.filtered(lambda line: line.code == 'ONSSEMPLOYER_868')
        self.assertAlmostEqual(fee.total, 33.22, places=2)
        self.car.fuel_type = 'electric'
        self.car.co2 = 0
        payslip.compute_sheet()
        self.assertFalse(payslip.line_ids.filtered(lambda line: line.code == 'CO2FEE'))
        self.assertAlmostEqual(payslip.line_ids.filtered(lambda line: line.code == 'ONSSEMPLOYER_868').total, 33.22, places=2)

    def test_benefits_after_unworked_first_version(self):
        # The month starts on a weekend. The target version with paid hours is
        # therefore the second version, although the payslip keeps the first.
        self.version.write({'internet': 40, 'mobile': 20, 'laptop': 100, 'mobile_amount': 30, 'tablet': 50})
        later_version = self.version.copy({'date_version': datetime.date(2025, 2, 3)})
        for mobility_budget in (False, True):
            with self.subTest(mobility_budget=mobility_budget):
                (self.version | later_version).l10n_be_mobility_budget = mobility_budget
                payslip = self._generate_payslip(datetime.date(2025, 2, 1), datetime.date(2025, 2, 28))
                self.assertEqual(payslip.version_id, self.version)
                self.assertIn(later_version, payslip.worked_days_line_ids.version_id)
                values = payslip._get_line_values(['ATN.INT', 'ATN.MOB', 'ATN.LAP', 'ATN.PHONE_AMT', 'ATN.TAB', 'CO2FEE', 'ONSSEMPLOYER_868'])
                for code, amount in [('ATN.INT', 5), ('ATN.MOB', 4), ('ATN.LAP', 6), ('ATN.PHONE_AMT', 3), ('ATN.TAB', 3)]:
                    self.assertAlmostEqual(values[code][payslip.id]['total'], amount, places=2)
                code = 'ONSSEMPLOYER_868' if mobility_budget else 'CO2FEE'
                expected_fee = self.car.with_context(co2_fee_date=payslip.date_from)._get_co2_fee(
                    self.car.co2, self.car.co2_emission_unit, self.car.fuel_type)
                self.assertAlmostEqual(values[code][payslip.id]['total'], expected_fee, places=2)

    def test_company_car_only_on_later_version(self):
        self.version.write({'car_id': False, 'transport_mode_car': False})
        self.version.copy({
            'date_version': datetime.date(2025, 4, 11),
            'car_id': self.car.id,
            'transport_mode_car': True,
        })
        payslip = self._generate_payslip(datetime.date(2025, 4, 1), datetime.date(2025, 4, 30))
        self.assertEqual(payslip.vehicle_id, self.car)
        expected_fee = self.car.with_context(co2_fee_date=payslip.date_from)._get_co2_fee(
            self.car.co2, self.car.co2_emission_unit, self.car.fuel_type)
        self.assertAlmostEqual(payslip.line_ids.filtered(lambda line: line.code == 'CO2FEE').total, expected_fee, places=2)
        self.assertAlmostEqual(
            payslip.line_ids.filtered(lambda line: line.code == 'ATN.CAR').total,
            self.car._get_monthly_car_atn(date=payslip.date_from) * 20 / 30, places=2)

    def test_co2_fee_car_of_most_days(self):
        # a car changed during the month owes the CO2 contribution of the car with the most calendar days in the
        # month, the new one on a tie
        second_car, third_car = self.env['fleet.vehicle'].sudo().create([{
            'name': name,
            'license_plate': name,
            'driver_id': self.work_contact.id,
            'company_id': self.env.company.id,
            'model_id': self.model.id,
            'co2': co2,
            'car_value': 30000.0,
            'fuel_type': "gasoline",
            'acquisition_date': datetime.date(2026, 1, 1),
        } for name, co2 in (("Second Car", 115.0), ("Third Car", 140.0))]).sudo(False)
        second_version = self.version.copy({'date_version': datetime.date(2026, 4, 10), 'car_id': second_car.id})
        third_version = self.version.copy({'date_version': datetime.date(2026, 6, 16), 'car_id': third_car.id})
        self.version.copy({'date_version': datetime.date(2026, 7, 25), 'car_id': self.car.id})

        for version, month, car in [
            (self.version, 4, second_car),  # 9 days of the first car, 21 of the second one
            (second_version, 6, third_car),  # 15 days each
            (third_version, 7, third_car),  # 24 days of the third car, 7 of the first one
        ]:
            date_from = datetime.date(2026, month, 1)
            payslip = self.env['hr.payslip'].create({
                'name': "Car change",
                'employee_id': self.employee.id,
                'version_id': version.id,
                'struct_id': self.structure.id,
                'date_from': date_from,
                'date_to': date_from + relativedelta(day=31),
            })
            payslip.compute_sheet()
            self.assertEqual(payslip.vehicle_id, car)
            co2_fee = car.with_context(co2_fee_date=date_from)._get_co2_fee(
                car.co2, car.co2_emission_unit, car.fuel_type)
            co2_line = payslip.line_ids.filtered(lambda line: line.code == 'CO2FEE')
            self.assertAlmostEqual(co2_line.total, co2_fee, delta=0.01)

    def test_two_versions_with_the_same_hours(self):
        # March 2026 cut in two versions of 11 working days each: the two work lines have the same hours, and the
        # month pays the wage once
        self.version.copy({'name': 'New Version', 'date_version': datetime.date(2026, 3, 17)})
        payslip = self._generate_payslip(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))

        work_lines = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '002.00')
        self.assertEqual(work_lines.mapped('number_of_hours'), [83.6, 83.6])
        self.assertAlmostEqual(sum(work_lines.mapped('amount')), 2650.0, places=2)

    def test_bik_across_multiple_versions_with_different_benefits(self):
        self.version.copy({
            'name': 'New Version',
            'date_version': datetime.date(2026, 4, 15),
            'transport_mode_car': False,
            'car_id': False,
        })

        # Calculation for CAR.BIK:
        #  Version_1: 1st -> 14th April
        #   car_atn * (14/30)
        #  Version_2: 15th -> 30th April "No Company Car"
        #  ∴ final_car_atn = 159.29 * (14/30)
        #                  = 74.33
        payslip = self._generate_payslip(datetime.date(2026, 4, 1), datetime.date(2026, 4, 30))
        self._validate_payslip(payslip)

    def test_employment_bonuses(self):
        self.version.write({
            'wage': 2923.82,
            'fuel_card': 0,
            'internet': 0,
            'mobile': 0,
            'meal_voucher_amount': 0,
            'ip_wage_rate': 0,
            'l10n_be_lsa_monthly_pro_other_amount': 0,
        })
        # Full-time J=D case (Focus is bonus A)
        self.version.resource_calendar_id = self.resource_calendar_40_hours_per_week.id
        self.version.reference_calendar_id = self.resource_calendar_38_hours_per_week.id
        payslip = self._generate_payslip(datetime.date(2026, 5, 1), datetime.date(2026, 5, 31))
        payslip_result = {
            'BASIC': 2923.82,
            'SALARY': 2923.82,
            'EmpBonus.A': 113.13,
            'EmpBonus.B': 0,
            'EmpBonus.1': 113.13,
        }
        self._validate_payslip(payslip, payslip_result, skip_lines=True)

        # Part-time case (Focus is bonus A): half the wage for half the full-time hours, the reference salary is the
        # full-time one (S = W / H * U) and the bonus is halved (P = H / U * R)
        self.version.reference_calendar_id = self.resource_calendar_80_hours_per_week.id
        self.version.wage = 1461.91
        payslip = self._generate_payslip(datetime.date(2026, 5, 1), datetime.date(2026, 5, 31))
        payslip_result = {
            'BASIC': 1461.91,
            'SALARY': 1461.91,
            'EmpBonus.A': 56.65,
            'EmpBonus.B': 0,
            'EmpBonus.1': 56.65,
        }
        self._validate_payslip(payslip, payslip_result, skip_lines=True)
        self.version.wage = 2923.82

        # Full-time but (J = 6) < (D = 21) case, it has a full-time calendar but its contract finishes early (Focus is bonus A)
        self.version.reference_calendar_id = self.resource_calendar_38_hours_per_week.id
        self.version.date_end = datetime.date(2026, 5, 10)
        payslip = self._generate_payslip(datetime.datetime(2026, 5, 1), datetime.datetime(2026, 5, 31))
        payslip_result = {
            'BASIC': 809.67,
            'DH_BASIC': 0.0,
            'SALARY': 809.67,
            'DH_SALARY': 0.0,
            'ONSS_BASE_TOTAL': 809.67,
            'ONSS': -105.82,
            'EmpBonus.A': 36.26,
            'EmpBonus.B': 3.63,
            'EmpBonus.1': 39.89,
            'ONSS_DOUBLE_HOLIDAY': 0.0,
            'ONSSTOTAL': 65.93,
            'ATN.CAR': 53.1,
            'WITHHOLDING_BASE_TOTAL': 796.84,
            'GROSS': 796.84,
            'DH_GROSS': 0.0,
            'GROSS.M': 796.84,
            'GROSS.Y': 9562.08,
            'F_PROFESSIONAL_FEES': -2718.5,
            'TRANSPORT_TAX_DED': -500.4,
            'GROSS.NET.Y': 6343.18,
            'Y.P.P': 1696.8,
            'P.P.MARITAL.DED': -2987.98,
            'P.P.FAMILY.DED': 0.0,
            'P.P': 0.0,
            'DH_PP': 0.0,
            'P.P.DED': 0.0,
            'PPTOTAL': 0.0,
            'ATN_DED': -53.1,
            'M.ONSS': 0.0,
            'LSA_MONTHLY_MISC_SERIOUS': 150.0,
            'REP.FEES': 150.0,
            'REP.FEES.VOLATILE': 0.0,
            'NET_TO_RECOVER': 0.0,
            'NET': 893.74,
            'REMUNERATION': 809.67,
            'CO2FEE': 33.93,
            'ONSSEMPLOYERBASIC': 202.42,
            'ONSSEMPLOYER_255': 0.16,
            'ONSSEMPLOYER_256': 0.08,
            'ONSSEMPLOYER_809': 3.16,
            'ONSSEMPLOYER_810': 0.81,
            'ONSSEMPLOYER_831': 1.86,
            'ONSSEMPLOYER_855': 13.68,
            'ONSSEMPLOYER_859': 0.81,
            'ONSSEMPLOYER': 203.69,
            'HOLIDAY_TAX_PROV_BASE': 809.67,
            'HOLIDAY_TAX_PROV': 147.36,
        }
        self._validate_payslip(payslip, payslip_result, skip_lines=True)

        self.version.wage = 2420.83
        # Full-time J=D case (Focus is bonus B)
        payslip = self._generate_payslip(datetime.date(2026, 5, 1), datetime.date(2026, 5, 31))
        payslip_result = {
            'BASIC': 2420.83,
            'SALARY': 2420.83,
            'EmpBonus.A': 125.04,
            'EmpBonus.B': 124.00,
            'EmpBonus.1': 249.04,
        }
        self._validate_payslip(payslip, payslip_result, skip_lines=True)

        # Part-time case (Focus is bonus B): half the wage for half the full-time hours
        self.version.reference_calendar_id = self.resource_calendar_80_hours_per_week.id
        self.version.wage = 1210.42
        payslip = self._generate_payslip(datetime.date(2026, 5, 1), datetime.date(2026, 5, 31))
        payslip_result = {
            'BASIC': 1210.42,
            'SALARY': 1210.42,
            'EmpBonus.A': 62.52,
            'EmpBonus.B': 62.22,
            'EmpBonus.1': 124.74,
        }
        self._validate_payslip(payslip, payslip_result, skip_lines=True)
        self.version.wage = 2420.83

        # Full-time but (J = 6) < (D = 21) case, it has a full-time calendar but its contract finishes early (Focus is bonus B)
        self.version.reference_calendar_id = self.resource_calendar_38_hours_per_week.id
        self.version.date_end = datetime.date(2026, 5, 10)
        payslip = self._generate_payslip(datetime.datetime(2026, 5, 1), datetime.datetime(2026, 5, 31))
        payslip_result = {
            'BASIC': 670.38,
            'DH_BASIC': 0.0,
            'SALARY': 670.38,
            'DH_SALARY': 0.0,
            'ONSS_BASE_TOTAL': 670.38,
            'ONSS': -87.62,
            'EmpBonus.A': 36.26,
            'EmpBonus.B': 41.79,
            'EmpBonus.1': 78.05,
            'ONSS_DOUBLE_HOLIDAY': 0.0,
            'ONSSTOTAL': 9.57,
            'ATN.CAR': 53.1,
            'WITHHOLDING_BASE_TOTAL': 713.91,
            'GROSS': 713.91,
            'DH_GROSS': 0.0,
            'GROSS.M': 713.91,
            'GROSS.Y': 8566.92,
            'F_PROFESSIONAL_FEES': -2419.96,
            'TRANSPORT_TAX_DED': -500.4,
            'GROSS.NET.Y': 5646.56,
            'Y.P.P': 1510.45,
            'P.P.MARITAL.DED': -2987.98,
            'P.P.FAMILY.DED': 0.0,
            'P.P': 0.0,
            'DH_PP': 0.0,
            'P.P.DED': 0.0,
            'PPTOTAL': 0.0,
            'ATN_DED': -53.1,
            'M.ONSS': 0.0,
            'LSA_MONTHLY_MISC_SERIOUS': 150.0,
            'REP.FEES': 150.0,
            'REP.FEES.VOLATILE': 0.0,
            'NET_TO_RECOVER': 0.0,
            'NET': 810.81,
            'REMUNERATION': 670.38,
            'CO2FEE': 33.93,
            'ONSSEMPLOYERBASIC': 167.59,
            'ONSSEMPLOYER_255': 0.13,
            'ONSSEMPLOYER_256': 0.07,
            'ONSSEMPLOYER_809': 2.61,
            'ONSSEMPLOYER_810': 0.67,
            'ONSSEMPLOYER_831': 1.54,
            'ONSSEMPLOYER_855': 11.33,
            'ONSSEMPLOYER_859': 0.67,
            'ONSSEMPLOYER': 117.26,
            'HOLIDAY_TAX_PROV_BASE': 670.38,
            'HOLIDAY_TAX_PROV': 122.01,
        }
        self._validate_payslip(payslip, payslip_result, skip_lines=True)

        # Full-time J=D case (Focus is Employee Bonus, before 2024 it is not the sum of bonus A + bonus B)
        payslip = self._generate_payslip(datetime.datetime(2022, 1, 1), datetime.datetime(2022, 1, 31))
        payslip_result = {
            'BASIC': 2420.83,
            'SALARY': 2420.83,
            'EmpBonus.1': 65.06,
        }
        self._validate_payslip(payslip, payslip_result, skip_lines=True)

        # Part-time case (Focus is Employee Bonus, before 2024 it is not the sum of bonus A + bonus B): half the wage for
        # half the full-time hours
        self.version.reference_calendar_id = self.resource_calendar_80_hours_per_week.id
        self.version.wage = 1210.42
        payslip = self._generate_payslip(datetime.datetime(2022, 1, 1), datetime.datetime(2022, 1, 31))
        payslip_result = {
            'BASIC': 1210.42,
            'SALARY': 1210.42,
            'EmpBonus.1': 32.71,
        }
        self._validate_payslip(payslip, payslip_result, skip_lines=True)
        self.version.wage = 2420.83

        # Full-time but (J = 6) < (D = 21) case, it has a full-time calendar but its contract finishes early
        # (Focus is Employee Bonus, before 2024 it is not the sum of bonus A + bonus B)
        self.version.reference_calendar_id = self.resource_calendar_38_hours_per_week.id
        self.version.date_end = datetime.date(2022, 1, 10)
        payslip = self._generate_payslip(datetime.datetime(2022, 1, 1), datetime.datetime(2022, 1, 31))
        payslip_result = {
            'BASIC': 670.38,
            'DH_BASIC': 0.0,
            'SALARY': 670.38,
            'DH_SALARY': 0.0,
            'ONSS_BASE_TOTAL': 670.38,
            'ONSS': -87.62,
            'EmpBonus.1': 23.61,
            'ONSS_DOUBLE_HOLIDAY': 0.0,
            'ONSSTOTAL': 64.01,
            'ATN.CAR': 49.76,
            'WITHHOLDING_BASE_TOTAL': 656.13,
            'GROSS': 656.13,
            'DH_GROSS': 0.0,
            'GROSS.M': 656.13,
            'GROSS.Y': 7740.0,
            'F_PROFESSIONAL_FEES': -2193.12,
            'TRANSPORT_TAX_DED': -429.6,
            'GROSS.NET.Y': 5117.28,
            'Y.P.P': 1368.87,
            'P.P.MARITAL.DED': -2222.93,
            'P.P.FAMILY.DED': 0.0,
            'P.P': 0.0,
            'DH_PP': 0.0,
            'P.P.DED': 0.0,
            'PPTOTAL': 0.0,
            'ATN_DED': -49.76,
            'M.ONSS': 0.0,
            'LSA_MONTHLY_MISC_SERIOUS': 150.0,
            'REP.FEES': 150.0,
            'REP.FEES.VOLATILE': 0.0,
            'NET_TO_RECOVER': 0.0,
            'NET': 756.37,
            'REMUNERATION': 670.38,
            'CO2FEE': 28.17,
            'ONSSEMPLOYERBASIC': 167.59,
            'ONSSEMPLOYER_255': 0.13,
            'ONSSEMPLOYER_256': 0.07,
            'ONSSEMPLOYER_809': 2.61,
            'ONSSEMPLOYER_810': 0.67,
            'ONSSEMPLOYER_831': 1.54,
            'ONSSEMPLOYER_855': 11.33,
            'ONSSEMPLOYER_859': 0.67,
            'ONSSEMPLOYER': 156.98,
            'HOLIDAY_TAX_PROV_BASE': 670.38,
            'HOLIDAY_TAX_PROV': 122.01,
        }
        self._validate_payslip(payslip, payslip_result, skip_lines=True)

    @freeze_time('2026-01-01')
    def test_multiple_cars_atn_regularization_1(self):
        """
            Use a car then change it to another car with lower ATN value.

            Min car ATN = 1,690€ / year at 2026
            Car 1 (VW Golf) Jan-Jun:
                Yearly Theoretical ATN = 1,938 €
                Yearly Paid ATN = 1,938 €
            Car 2 (Nissan)  Jul-Dec:
                Yearly Theoretical ATN = 1,371.43 €
                Yearly Paid ATN = 1,690 €

            Calculations:
            ∵ monthly_car_atn is calculated based on the month calendar days so need to get the car covered assignment on days

            ∵ min_legal_car_atn = 1,690 € in 2026
            ∵ car1 covered_days = 181 days
            ∵ car2 covered_days = 184 days
            ∴ Yearly Theoretical ATN through the whole Year = 1,938 * (181 / 365) + 1,371.43 * (184 / 365)
                                                            = 1,652.39 €

            ∴ Yearly ATN to pay = Max(min_legal_car_atn, yearly_theoretical_atn) , where it's the final ATN that should have been paid after applying the legal minimum.
                                = Max(1,690, 1,652.37) = 1,690 €

            ∵ Yearly ATN paid (payslips) =
                car1 -> (1,938/365) * (31 + 28 + 31 + 30 + 31 + 30) = 961.035616438 €
                car2 -> (1,690/365) * (31 + 31 + 30 + 31 + 30 + 31) = 851.945205479 €
                = 1,812.98 €

            ∴ Regularization amount = yearly_atn_to_pay - yearly_atn_paid
                                    = 1,690 - 1,812.97
                                    = -122.97 €

            ∴ Need to refund 122.97 € back to the employee
        """

        car2 = self.env['fleet.vehicle'].sudo().create([{
            'name': "Nissan Car",
            'license_plate': "NISSAN license",
            'driver_id': self.work_contact.id,
            'company_id': self.env.company.id,
            'model_id': self.model.id,
            'contract_date_start': datetime.date(2026, 7, 1),
            'co2': 95.0,
            'car_value': 20000.0,
            'fuel_type': "gasoline",
            'acquisition_date': datetime.date(2026, 7, 1),
        }]).sudo(False)

        version2 = self.version.copy({
            'name': 'New Version',
            'date_version': datetime.date(2026, 7, 1),
            'car_id': car2.id,
        })

        # Generate and Done Payslips from Jan to Nov
        for month in range(1, 12):
            date_from = datetime.date(2026, month, 1)
            date_to = date_from + relativedelta(day=31)
            v_id = self.version.id if month <= 6 else version2.id

            slip = self._generate_payslip(date_from, date_to, version_id=v_id)

            self.employee.write({'review_state': '1_reviewed'})
            slip.action_payslip_done()

        dec_slip = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31), version_id=version2.id)

        self._validate_payslip(dec_slip)

    @freeze_time('2026-01-01')
    def test_multiple_cars_atn_regularization_2(self):
        """
            Use a car then change it to another car with lower ATN value.

            Min car ATN = 1,690€ / year at 2026
            Car 1 (Corolla) Jan-Jun:
                Yearly Theoretical ATN = 1,748.57€
                Yearly Paid ATN = 1,748.57€
            Car 2 (Clio)  Jul-Dec:
                Yearly Theoretical ATN = 1,371.43€
                Yearly Paid ATN = 1,690€

            Calculations:
            ∵ monthly_car_atn is calculated based on the month calendar days so need to get the car covered assignment on days

            ∵ min_legal_car_atn = 1,690 € in 2026
            ∵ car1 covered_days = 181 days
            ∵ car2 covered_days = 184 days
            ∴ Yearly Theoretical ATN through the whole Year = 1,748.57 * (181 / 365) + 1,371.43 * (184 / 365)
                                                            = 1,558.45 €

            ∴ Yearly ATN to pay = Max(min_legal_car_atn, yearly_theoretical_atn) , where it's the final ATN that should have been paid after applying the legal minimum.
                                = Max(1,690, 1,558.45) = 1,690 €

            ∵ Yearly ATN paid (payslips) =
                car1 -> (1,748.57/365) * (31 + 28 + 31 + 30 + 31 + 30) = 867.11 €
                car2 -> (1,690/365) * (31 + 31 + 30 + 31 + 30 + 31) = 851.92 €
                = 1,719.03 €

            ∴ Regularization amount = yearly_atn_to_pay - yearly_atn_paid
                                    = 1,690 - 1,719.03
                                    = -29.03 €

            ∴ Need to refund 29.03 € back to the employee
        """

        car1 = self.env['fleet.vehicle'].sudo().create([{
            'name': "Corolla Car",
            'license_plate': "COROLLA License",
            'driver_id': self.work_contact.id,
            'company_id': self.env.company.id,
            'model_id': self.model.id,
            'contract_date_start': datetime.date(2026, 1, 1),
            'co2': 88.0,
            'car_value': 24000.0,
            'fuel_type': "diesel",
            'acquisition_date': datetime.date(2026, 1, 1),
        }]).sudo(False)

        self.version.write({
            'car_id': car1.id,
        })

        car2 = self.env['fleet.vehicle'].sudo().create([{
            'name': "Clio Car",
            'license_plate': "CLIO License",
            'driver_id': self.work_contact.id,
            'company_id': self.env.company.id,
            'model_id': self.model.id,
            'contract_date_start': datetime.date(2026, 7, 1),
            'co2': 95.0,
            'car_value': 20000.0,
            'fuel_type': "gasoline",
            'acquisition_date': datetime.date(2026, 7, 1),
        }]).sudo(False)

        version2 = self.version.copy({
            'name': 'New Version',
            'date_version': datetime.date(2026, 7, 1),
            'car_id': car2.id,
        })

        # Generate and Done Payslips from Jan to Nov
        for month in range(1, 12):
            date_from = datetime.date(2026, month, 1)
            date_to = date_from + relativedelta(day=31)
            v_id = self.version.id if month <= 6 else version2.id

            slip = self._generate_payslip(date_from, date_to, version_id=v_id)

            self.employee.write({'review_state': '1_reviewed'})
            slip.action_payslip_done()

        dec_slip = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31), version_id=version2.id)

        self._validate_payslip(dec_slip)

    @freeze_time('2026-01-01')
    def test_multiple_cars_atn_regularization_3(self):
        """
            Use a car then change it to another car with higher ATN value.

            Min car ATN = 1,690€ / year at 2026
            Car 1 (Clio)  Jan-Mar:
                Yearly Theoretical ATN = 1,371.43€
                Yearly Paid ATN = 1,690€
            Car2 (Corolla) Apr-Jun:
                Yearly Theoretical ATN = 1,748.57€
                Yearly Paid ATN = 1,748.57€

            Calculations:
            ∵ monthly_car_atn is calculated based on the month calendar days so need to get the car covered assignment on days

            ∵ min_legal_car_atn = 1,690 € in 2026
            ∵ car1 covered_days = 90 days
            ∵ car2 covered_days = 275 days
            ∴ Yearly Theoretical ATN through the whole Year = 1,371.43 * (90 / 365) + 1,748.57 * (275 / 365)
                                     = 1,655.58 €

            ∴ Yearly ATN to pay = Max(min_legal_car_atn, yearly_theoretical_atn) , where it's the final ATN that should have been paid after applying the legal minimum.
                                = Max(1,690, 1,655.58) = 1,690 €

            ∵ Yearly ATN paid (payslips) =
                car1 -> (1,690/365) * (31 + 28 + 31) = 416.71 €
                car2 -> (1,748.57/365) * (30 + 31 + 30 + 31 + 31 + 30 + 31 + 30 + 31) = 1,317.42 €
                = 1,734.13 €

            ∴ Regularization amount = yearly_atn_to_pay - yearly_atn_paid
                                    = 1,690 - 1,734.13
                                    = -44.13 €

            ∴ Need to refund 44.13 € back to the employee
        """

        car1 = self.env['fleet.vehicle'].sudo().create([{
            'name': "Clio Car",
            'license_plate': "CLIO License",
            'driver_id': self.work_contact.id,
            'company_id': self.env.company.id,
            'model_id': self.model.id,
            'contract_date_start': datetime.date(2026, 1, 1),
            'co2': 95.0,
            'car_value': 20000.0,
            'fuel_type': "gasoline",
            'acquisition_date': datetime.date(2026, 1, 1),
        }]).sudo(False)

        self.version.write({
            'car_id': car1.id,
        })

        car2 = self.env['fleet.vehicle'].sudo().create([{
            'name': "Corolla Car",
            'license_plate': "COROLLA License",
            'driver_id': self.work_contact.id,
            'company_id': self.env.company.id,
            'model_id': self.model.id,
            'contract_date_start': datetime.date(2026, 4, 1),
            'co2': 88.0,
            'car_value': 24000.0,
            'fuel_type': "diesel",
            'acquisition_date': datetime.date(2026, 4, 1),
        }]).sudo(False)

        version2 = self.version.copy({
            'name': 'New Version',
            'date_version': datetime.date(2026, 4, 1),
            'car_id': car2.id,
        })

        # Generate and Done Payslips from Jan to Nov
        for month in range(1, 12):
            date_from = datetime.date(2026, month, 1)
            date_to = date_from + relativedelta(day=31)
            v_id = self.version.id if month <= 3 else version2.id

            slip = self._generate_payslip(date_from, date_to, version_id=v_id)

            self.employee.write({'review_state': '1_reviewed'})
            slip.action_payslip_done()

        dec_slip = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31), version_id=version2.id)

        self._validate_payslip(dec_slip)

    @freeze_time('2026-01-01')
    def test_multiple_cars_atn_regularization_end_of_contract(self):
        """
            Use a car then change it to another car with lower ATN value.

            Min car ATN = 1,690€ / year at 2026
            Car 1 (Corolla) Jan-Jun:
                Yearly Theoretical ATN = 1,748.57€
                Yearly Paid ATN = 1,748.57€
            Car 2 (Clio)  Jul-Nov:
                Yearly Theoretical ATN = 1,371.43€
                Yearly Paid ATN = 1,690€

            The contract end at 30th November

            Calculations:
            ∵ monthly_car_atn is calculated based on the month calendar days so need to get the car covered assignment on days

            ∵ car1 covered_days = 181 days
            ∵ car2 covered_days = 152 days
            ∴ Yearly Theoretical ATN = 1,748.57 * (181 / 365) + 1,371.43 * (152 / 365)
                                     = 1,438.215 €

            ∵ The regularization will be applied till the contract end not the full year, so the min_legal_car_atn will be prorated
            ∴ min_atn_prorated = 1,690 * ((181 + 152) / 365)
                               = 1,541.8356 €

            ∴ Yearly ATN to pay = Max(1,541.8356, 1,438.215) = 1,541.8356 €

            ∵ Yearly ATN paid (payslips) =
                car1 -> (1,748.57/365) * (31 + 28 + 31 + 30 + 31 + 30) = 867.11 €
                car2 -> (1,690/365) * (31 + 31 + 30 + 31 + 30 + 29) = 571.12 €
                = 1,570.87 €

            ∴ Regularization amount = 1,541.8356 - 1,570.87
                                    = -29.03 €

            ∴ Need to refund 29.03 € back to the employee
        """

        car1 = self.env['fleet.vehicle'].sudo().create([{
            'name': "Corolla Car",
            'license_plate': "COROLLA License",
            'driver_id': self.work_contact.id,
            'company_id': self.env.company.id,
            'model_id': self.model.id,
            'contract_date_start': datetime.date(2026, 1, 1),
            'co2': 88.0,
            'car_value': 24000.0,
            'fuel_type': "diesel",
            'acquisition_date': datetime.date(2026, 1, 1),
        }]).sudo(False)

        self.version.write({
            'car_id': car1.id,
        })

        car2 = self.env['fleet.vehicle'].sudo().create([{
            'name': "Clio Car",
            'license_plate': "CLIO License",
            'driver_id': self.work_contact.id,
            'company_id': self.env.company.id,
            'model_id': self.model.id,
            'contract_date_start': datetime.date(2026, 7, 1),
            'co2': 95.0,
            'car_value': 20000.0,
            'fuel_type': "gasoline",
            'acquisition_date': datetime.date(2026, 7, 1),
        }]).sudo(False)

        version2 = self.version.copy({
            'name': 'New Version',
            'date_version': datetime.date(2026, 7, 1),
            'car_id': car2.id,
        })

        # fully compensated: this test doesn't test the annual sectorial bonus
        (self.version | version2).l10n_be_sectorial_bonus_compensatory_amount = 1000.0

        # Generate and Done Payslips from Jan to Oct
        for month in range(1, 11):
            date_from = datetime.date(2026, month, 1)
            date_to = date_from + relativedelta(day=31)
            v_id = self.version.id if month <= 6 else version2.id

            slip = self._generate_payslip(date_from, date_to, version_id=v_id)

            self.employee.write({'review_state': '1_reviewed'})
            slip.action_payslip_done()

        departures_reasons = {
            'dead': self.env.ref('hr.departure_dead'),
            'resigned_retired': self.env.ref('hr.departure_retired'),
            'resigned_anitcipated_retirement': self.env.ref('l10n_be_hr_payroll.departure_resigned_anticipated_retirement'),
            'fired_early_retirement': self.env.ref('l10n_be_hr_payroll.departure_fired_early_retirement'),
            'fired': self.env.ref('hr.departure_fired'),
        }

        self.version.employee_id.departure_reason_id = departures_reasons['fired']
        self.version.employee_id.departure_date = datetime.date(2026, 11, 29)

        nov_slip = self._generate_payslip(datetime.date(2026, 11, 1), datetime.date(2026, 11, 30), version_id=version2.id)

        self._validate_payslip(nov_slip)

    @freeze_time('2026-01-01')
    def test_no_atn_regularization(self):
        """
            Min car ATN = 1,690€ / year at 2026
            Car 1 (VW Golf) Jan-Dec:
                Yearly Theoretical ATN = 1,938€
                Yearly Paid ATN Paid = 1,938€
        """

        # Generate and Done Payslips from Jan to Nov
        history = self.env['hr.payslip'].create([{
            'name': f'Payslip {month}/2026',
            'employee_id': self.employee.id,
            'struct_id': self.structure.id,
            'date_from': datetime.date(2026, month, 1),
            'date_to': datetime.date(2026, month, 1) + relativedelta(day=31),
        } for month in range(1, 12)])
        history.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        history.action_payslip_done()

        dec_slip = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31), version_id=self.version.id)

        self._validate_payslip(dec_slip)

    def test_employment_bonus_split_volet_A_B(self):
        payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        self._validate_payslip(payslip)

    def test_employment_bonus_cap_volet_A_B(self):
        self.version.wage = 2000
        payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        self._validate_payslip(payslip)

    def test_employment_bonus_worker_coefficient_may_2024(self):
        # from May 2024 to January 2025, the volet B of a worker decreases by 0.2915 per euro of reference wage above
        # 2,132.59 (0.2914 in April 2024 only): a complete month paid 2,500 gives
        # R = 172.18 - 0.2915 x (2,500 - 2,132.59) = 65.08
        self.version.write({
            'wage': 2500.0,
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
            'fuel_card': 0,
            'internet': 0,
            'mobile': 0,
            'meal_voucher_amount': 0,
            'ip_wage_rate': 0,
            'l10n_be_lsa_monthly_misc_base_amount': 0,
        })
        payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        self._validate_payslip(payslip, {
            'SALARY': 2500.0,
            'EmpBonus.A': 127.68,
            'EmpBonus.B': 65.08,
            'EmpBonus.1': 192.76,
        }, skip_lines=True)

    def test_min_withholding_tax(self):
        payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'P_P_ADJ': 400})
        self._validate_payslip(payslip)

    def test_fiscal_voluntarism(self):
        self.version.write({
            'fiscal_voluntarism_type': 'fixed',
            'fiscal_voluntarism_amount': 850
        })
        payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        self._validate_payslip(payslip)

        self.version.write({
            'fiscal_voluntarism_type': 'percentage',
            'fiscal_voluntarism_percentage': 0.5,
        })
        payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        self._validate_payslip(payslip)

    def test_fiscal_voluntarism_accounting(self):
        # The voluntary withholding tax is owed to the tax administration with the other withholding taxes
        self.version.write({
            'fiscal_voluntarism_type': 'fixed',
            'fiscal_voluntarism_amount': 100,
        })
        payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31))
        payslip.action_payslip_done()

        self.assertAlmostEqual(payslip._get_line_values(['FISC_VOL'])['FISC_VOL'][payslip.id]['total'], -100, 2)
        move_lines = payslip.move_id.line_ids
        self.assertTrue(move_lines)
        self.assertFalse(move_lines.filtered(lambda line: line.name == 'Adjustment Entry'))
        withholding_lines = move_lines.filtered(lambda line: line.account_id.code == '453000')
        self.assertIn(100, withholding_lines.mapped('credit'))

    def test_hiring_bonus(self):
        payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'HIRINGBONUS': 10000})
        self._validate_payslip(payslip)

    def test_bonus(self):
        payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), input_values={'BONUS': 10000})
        self._validate_payslip(payslip)

    def test_atn_miscellaneous_cp200_employee(self):
        with freeze_time('2026-01-01'):
            self.employee.version_id.write({
                'internet': 0,
                'mobile': 0,
                'car_atn': 0.0,
                'transport_mode_car': False,
                'ip_wage_rate': 0,
                'meal_voucher_amount': 0,
                'eco_checks': 0,
                'l10n_be_lsa_monthly_misc_base_amount': 0,
            })
            payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31), version_id=self.employee.version_id.id, input_values={'ATN_MISC': 100})
            self._validate_payslip(payslip)

    def test_all_onss_rules_01(self):
        employee = self.env['hr.employee'].create([{
            'name': 'Flash McQueen',
            'date_version': datetime.date(2026, 2, 1),
            'contract_date_start': datetime.date(2026, 2, 1),
            'wage': 2555.73,
            'lang': 'fr_BE',
        }])
        payslip = self._generate_payslip(datetime.date(2026, 2, 1), datetime.date(2026, 2, 28), employee_id=employee.id, version_id=employee.version_ids.id)
        self._validate_payslip(payslip)

    def test_all_onss_rules_02(self):
        employee = self.env['hr.employee'].create([{
            'name': 'Flash McQueen',
            'date_version': datetime.date(2026, 2, 10),
            'contract_date_start': datetime.date(2026, 2, 10),
            'wage': 2555.73,
            'children': 1,
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00495').id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        }])
        self.car.write({
            'driver_id': employee.work_contact_id.id,
            'company_id': employee.company_id.id,
            'contract_date_start': datetime.date(2026, 2, 10),
            'co2': 155.0,
            'car_value': 52000.0,
            'fuel_type': "gasoline",
            'acquisition_date': datetime.date(2026, 2, 10),
        })
        employee.write({
            'transport_mode_car': True,
            'car_id': self.car.id,
        })
        payslip = self._generate_payslip(datetime.date(2026, 2, 1), datetime.date(2026, 2, 28), employee_id=employee.id, version_id=employee.version_ids.id)
        self._validate_payslip(payslip)

    def test_sales_rep_commission_advance(self):
        sales_rep_employee = self.env['hr.employee'].create({
            'name': 'Sales Rep',
            'date_version': '2025-01-01',
            'contract_date_start': '2025-01-01',
            'wage': 2000,
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_d').id,
            'l10n_be_is_sale_representative': True,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        })

        # Min wage for category D and 0 year seniority in 2025 is 2500.47€
        # January slip: 2000€ + 300€ COM -> 200.47€ of advance
        jan_payslip = self._generate_payslip(
            datetime.date(2025, 1, 1),
            datetime.date(2025, 1, 31),
            employee_id=sales_rep_employee.id,
            version_id=sales_rep_employee.version_ids.id,
            input_values={'COMMISSION': 300},
        )
        self._validate_payslip(jan_payslip)
        jan_payslip.action_payslip_done()

        # Feb slip: 2000€ + 600€ COM -> we substract 99.53€ (max to get to min wage)
        feb_payslip = self._generate_payslip(
            datetime.date(2025, 2, 1),
            datetime.date(2025, 2, 28),
            employee_id=sales_rep_employee.id,
            version_id=sales_rep_employee.version_ids.id,
            input_values={'COMMISSION': 600},
        )
        self._validate_payslip(feb_payslip)
        feb_payslip.action_payslip_done()

        # March slip: 2000€ + 800 COM -> still (200.47 - 99.53) to recover
        mar_payslip = self._generate_payslip(
            datetime.date(2025, 3, 1),
            datetime.date(2025, 3, 31),
            employee_id=sales_rep_employee.id,
            version_id=sales_rep_employee.version_ids.id,
            input_values={'COMMISSION': 800},
        )
        self._validate_payslip(mar_payslip)
        mar_payslip.action_payslip_done()

        # December slip: 2000€ + 300€ COM -> 200.47€ of advance
        dec_payslip = self._generate_payslip(
            datetime.date(2025, 12, 1),
            datetime.date(2025, 12, 31),
            employee_id=sales_rep_employee.id,
            version_id=sales_rep_employee.version_ids.id,
            input_values={'COMMISSION': 300},
        )
        self._validate_payslip(dec_payslip)
        dec_payslip.action_payslip_done()

        # January next year slip: 2000€ + 800€ COM -> no advance because new year reset
        jan_next_payslip = self._generate_payslip(
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 31),
            employee_id=sales_rep_employee.id,
            version_id=sales_rep_employee.version_ids.id,
            input_values={'COMMISSION': 800},
        )
        self._validate_payslip(jan_next_payslip)

    def test_sales_rep_commission_advance_part_time(self):
        """ The minimum guaranteed to a part-time sales representative is the part-time scale. """
        sales_rep_employee = self.env['hr.employee'].create({
            'name': 'Part-Time Sales Rep',
            'date_version': '2025-01-01',
            'contract_date_start': '2025-01-01',
            'wage': 1300,
            'resource_calendar_id': self.resource_calendar_half_time.id,
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_d').id,
            'l10n_be_is_sale_representative': True,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'lang': 'fr_BE',
        })
        version = sales_rep_employee.version_ids
        self.assertAlmostEqual(version.work_time_rate, 0.5, places=2)
        # Min wage for category D and 0 year seniority in 2025 is 2500.47€, 1250.24€ at half-time
        payslip = self._generate_payslip(
            datetime.date(2025, 1, 1),
            datetime.date(2025, 1, 31),
            employee_id=sales_rep_employee.id,
            version_id=version.id,
        )
        self.assertFalse(payslip.line_ids.filtered(lambda line: line.code == 'COMMISSION_ADV'))

        version.wage = 1200
        payslip.compute_sheet()
        self.assertAlmostEqual(
            payslip.line_ids.filtered(lambda line: line.code == 'COMMISSION_ADV').total, 2500.47 * 0.5 - 1200, places=2)

    def test_company_executive_01(self):
        payslip = self._generate_payslip(
            datetime.date(2025, 4, 1),
            datetime.date(2025, 4, 30),
            employee_id=self.company_executive_employee.id,
            version_id=self.company_executive_employee.version_ids.id,
            input_values={'ATN_SOCIAL_CONTRIB': 807.84},
        )
        self._validate_payslip(payslip)

    def test_company_executive_02(self):
        self.company_executive_employee.write({
            'transport_mode_car': True,
            'car_id': self.car.id,
            'wage': 2875.46,
            'children': 1,
        })

        self.car.co2 = 110.295
        payslip = self._generate_payslip(
            datetime.date(2025, 4, 1),
            datetime.date(2025, 4, 30),
            employee_id=self.company_executive_employee.id,
            version_id=self.company_executive_employee.version_ids.id,
            input_values={'ATN_SOCIAL_CONTRIB': 264.14},
        )
        self._validate_payslip(payslip)

    def test_company_executive_03(self):
        self.company_executive_employee.write({
            'wage': 5949.34,
            'children': 1,
            'laptop': 0,
            'meal_voucher_amount': 0,
        })
        payslip = self._generate_payslip(
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 31),
            employee_id=self.company_executive_employee.id,
            version_id=self.company_executive_employee.version_ids.id,
            input_values={
                'ATN_SOCIAL_CONTRIB': 1384.06,
                'N_P_BASIC': 5949.34,
            },
        )
        self._validate_payslip(payslip)

    def test_company_executive_04(self):
        self.company_executive_employee.write({
            'transport_mode_car': True,
            'car_id': self.car.id,
            'wage': 3634.44,
            'children': 1,
        })
        self.car.co2 = 40
        payslip = self._generate_payslip(
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 31),
            employee_id=self.company_executive_employee.id,
            version_id=self.company_executive_employee.version_ids.id,
            input_values={'N_P_BASIC': 11052.16},
        )
        self._validate_payslip(payslip)

    def test_company_executive_05(self):
        self.company_executive_employee.write({
            'wage': 0,
            'children': 1,
            'laptop': 0,
            'meal_voucher_amount': 0,
        })
        payslip = self._generate_payslip(
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 31),
            employee_id=self.company_executive_employee.id,
            version_id=self.company_executive_employee.version_ids.id,
            input_values={
                'ATN_SOCIAL_CONTRIB': 1384.06,
                'N_P_BASIC': 77341.42,
            },
        )
        self._validate_payslip(payslip)

    def test_company_executive_06(self):
        self.company_executive_employee.write({
            'fixed_meal_voucher_days': 20,
            'wage': 3750,
        })
        payslip = self._generate_payslip(
            datetime.date(2025, 4, 1),
            datetime.date(2025, 4, 30),
            employee_id=self.company_executive_employee.id,
            version_id=self.company_executive_employee.version_ids.id,
            input_values={'ATN_SOCIAL_CONTRIB': 807.84},
        )
        self._validate_payslip(payslip)

    def test_company_executive_07(self):
        self.company_executive_employee.write({
            'l10n_be_withholding_tax_type': 'percentage',
            'l10n_be_withholding_tax_percentage': 0.3,
        })
        payslip = self._generate_payslip(
            datetime.date(2025, 4, 1),
            datetime.date(2025, 4, 30),
            employee_id=self.company_executive_employee.id,
            version_id=self.company_executive_employee.version_ids.id,
            input_values={'ATN_SOCIAL_CONTRIB': 807.84},
        )
        self._validate_payslip(payslip)

    def test_company_executive_08(self):
        self.company_executive_employee.write({
            'l10n_be_withholding_tax_type': 'fixed',
            'l10n_be_withholding_tax_amount': 500,
        })
        payslip = self._generate_payslip(
            datetime.date(2025, 4, 1),
            datetime.date(2025, 4, 30),
            employee_id=self.company_executive_employee.id,
            version_id=self.company_executive_employee.version_ids.id,
            input_values={'ATN_SOCIAL_CONTRIB': 807.84},
        )
        self._validate_payslip(payslip)

    def test_n1_holiday_pay_recovery_40_hours_working_schedule(self):
        CONTRACT_START = datetime.date(2026, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        # Employee received 2000€ for 10 days of holidays from previous employer
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                "date_from": CONTRACT_START + relativedelta(years=-1),
                "date_to": datetime.date(CONTRACT_START.year - 1, 12, 31),
                "prev_work_hours_per_week": 38,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 10,
                "prev_simple_holiday_pay_paid": 2000,
                "prev_double_holiday_pay_paid": 0,
            }),
        ]

        self.version.wage_type = 'hourly'
        self.version.hourly_wage = 20.62

        calendar_40h = self.resource_calendar_40_hours_per_week
        self.version.resource_calendar_id = calendar_40h

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave Feb",
            'calendar_id': calendar_40h.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.date(2026, 2, 9),
            'date_to': datetime.date(2026, 2, 14),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }, {
            'name': "Legal Leave Dec",
            'calendar_id': calendar_40h.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.date(2026, 12, 7),
            'date_to': datetime.date(2026, 12, 12),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip_feb = self._generate_payslip(datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))

        # HolPayRec is 90% of the 5 days/40 hours (40 * 20.62 * 0.90 = -742.32)
        self.assertAlmostEqual(
            payslip_feb._get_line_values(['HolPayRec'], compute_sum=True)['HolPayRec']['sum']['total'], -742.32, places=2)

        self._validate_payslip(payslip_feb)

        payslip_feb.action_payslip_done()

        payslip_dec = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))

        # HolPayRec is 90% of the remaining 5 days/40 hours (40 * 20.62 * 0.90 = -742.32)
        self.assertAlmostEqual(
            payslip_dec._get_line_values(['HolPayRec'], compute_sum=True)['HolPayRec']['sum']['total'], -742.32, places=2)

        self._validate_payslip(payslip_dec)

    def test_group_insurance_fixed_amount(self):
        self.version.ip_wage_rate = 0
        self.version.l10n_be_group_insurance_company_contribution = 150.0
        self.version.l10n_be_group_insurance_company_contribution_unit = 'amount'
        self.version.l10n_be_group_insurance_employee_contribution = 80.0
        self.version.l10n_be_group_insurance_employee_contribution_unit = 'amount'
        self.version.l10n_be_group_insurance_employee_voluntary = 50.0

        payslip = self._generate_payslip(self.date_from, self.date_to)
        self._validate_payslip(payslip)

    def test_group_insurance_percentage(self):
        self.version.ip_wage_rate = 0
        self.version.l10n_be_group_insurance_company_contribution = 0.05
        self.version.l10n_be_group_insurance_company_contribution_unit = 'percentage'
        self.version.l10n_be_group_insurance_employee_contribution = 0.03
        self.version.l10n_be_group_insurance_employee_contribution_unit = 'percentage'
        self.version.l10n_be_group_insurance_employee_voluntary = 0.0

        payslip = self._generate_payslip(self.date_from, self.date_to)
        self._validate_payslip(payslip)

    def test_holiday_pay_regularization_n1_preconditions(self):
        CONTRACT_START = datetime.date(2026, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        holiday_attestation = self.env["l10n.be.holiday.attest"].create([
            {
                "date_from": CONTRACT_START + relativedelta(years=-1),
                "date_to": datetime.date(CONTRACT_START.year - 1, 12, 31),
                "employee_id": self.employee.id,
                "prev_work_hours_per_week": 38,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 2,
                "prev_simple_holiday_pay_paid": 1000,
                "prev_double_holiday_pay_paid": 0,
            },
        ])

        payslip_nov = self._generate_payslip(datetime.date(2026, 11, 1), datetime.date(2026, 11, 30))
        self.assertNotIn('HolPayReg', payslip_nov.line_ids.mapped('code'))

        holiday_attestation.prev_simple_holiday_pay_paid = 0
        payslip_dec_empty = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))
        self.assertNotIn('HolPayReg', payslip_dec_empty.line_ids.mapped('code'))

        holiday_attestation.prev_simple_holiday_pay_paid = 1000
        payslip_dec_success = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))
        self.assertIn('HolPayReg', payslip_dec_success.line_ids.mapped('code'))

    def test_holiday_pay_regularization_n_preconditions(self):
        CONTRACT_START = datetime.date(2025, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        holiday_attestation = self.env["l10n.be.holiday.attest"].create([
            {
                "date_from": CONTRACT_START,
                "date_to": datetime.date(CONTRACT_START.year, 12, 31),
                "employee_id": self.employee.id,
                "prev_work_hours_per_week": 38,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 2,
                "prev_simple_holiday_pay_paid": 1000,
                "prev_double_holiday_pay_paid": 0,
            },
        ])

        payslip_nov = self._generate_payslip(datetime.date(2026, 11, 1), datetime.date(2026, 11, 30))
        self.assertNotIn('HolPayReg', payslip_nov.line_ids.mapped('code'))

        holiday_attestation.prev_simple_holiday_pay_paid = 0
        payslip_dec_empty = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))
        self.assertNotIn('HolPayReg', payslip_dec_empty.line_ids.mapped('code'))

        holiday_attestation.prev_simple_holiday_pay_paid = 1000
        payslip_dec_success = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))
        self.assertIn('HolPayReg', payslip_dec_success.line_ids.mapped('code'))

    def test_simple_n_holiday_pay_recovery_december_leave(self):
        """
        Check corner case where leave is taken in December (recovery + regularization in same slip)
        """
        CONTRACT_START = datetime.date(2025, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                'date_from': CONTRACT_START,
                'date_to': datetime.date(CONTRACT_START.year, 12, 31),
                'prev_work_hours_per_week': 38,
                'prev_reference_work_hours_per_week': 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 2,
                "prev_simple_holiday_pay_paid": 1000,
                "prev_double_holiday_pay_paid": 0,
            }),
        ]

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave Dec",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 12, 7, 6, 0, 0),
            'date_to': datetime.datetime(2026, 12, 7, 19, 0, 0),
            'count_as': 'absence',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))
        self._validate_payslip(payslip)

    def test_holiday_pay_regularization_negative_deduction(self):
        """
        Monthly Wage = 2650.00 € (1 day leave = 122.31 € base, 90% HolPayRec = -110.08 €).
        Cap = 1000.00 € (> 122.31 €).
        Result: HolPayReg = -(122.31 - 110.08) = -12.23 € (Deduction).
        """
        CONTRACT_START = datetime.date(2025, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                'date_from': CONTRACT_START,
                'date_to': datetime.date(CONTRACT_START.year, 12, 31),
                'prev_work_hours_per_week': 38,
                'prev_reference_work_hours_per_week': 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 2,
                "prev_simple_holiday_pay_paid": 1000.0,  # Cap > 122.31 € -> triggers deduction
                "prev_double_holiday_pay_paid": 0.0,
            }),
        ]

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave Dec (1 day)",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 12, 7, 6, 0, 0),
            'date_to': datetime.datetime(2026, 12, 7, 19, 0, 0),
            'count_as': 'absence',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))

        rec_line = payslip.line_ids.filtered(lambda l: l.code == 'HolPayRec')
        reg_line = payslip.line_ids.filtered(lambda l: l.code == 'HolPayReg')

        self.assertAlmostEqual(rec_line.total, -110.08, places=2)
        self.assertAlmostEqual(reg_line.total, -12.23, places=2)

    def test_holiday_pay_regularization_positive_refund(self):
        """
        Monthly Wage = 2650.00 € (1 day leave = 122.31 € base, 90% HolPayRec = -110.08 €).
        Cap = 50.00 € for the 2 days of the attest, 25.00 € for the day taken (< 110.08 €).
        Result: HolPayReg = -(25.00 - 110.08) = +85.08 € (Refund).
        """
        CONTRACT_START = datetime.date(2025, 1, 1)
        self.version.contract_date_start = CONTRACT_START
        self.employee.l10n_be_holiday_attest_ids = [
            Command.create({
                'date_from': CONTRACT_START,
                'date_to': datetime.date(CONTRACT_START.year, 12, 31),
                'prev_work_hours_per_week': 38,
                'prev_reference_work_hours_per_week': 38,
                "prev_work_days_per_week": 5,
                "prev_days_earned": 2,
                "prev_simple_holiday_pay_paid": 50.0,  # Cap < 110.08 € -> triggers refund
                "prev_double_holiday_pay_paid": 0.0,
            }),
        ]

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave Dec (1 day)",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 12, 7, 6, 0, 0),
            'date_to': datetime.datetime(2026, 12, 7, 19, 0, 0),
            'count_as': 'absence',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id
        }])

        payslip = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))

        rec_line = payslip.line_ids.filtered(lambda l: l.code == 'HolPayRec')
        reg_line = payslip.line_ids.filtered(lambda l: l.code == 'HolPayReg')

        self.assertAlmostEqual(rec_line.total, -110.08, places=2)
        self.assertAlmostEqual(reg_line.total, 85.08, places=2)

    def test_worker_sick_time_off_worked_days(self):
        self.employee.write({
            'wage': 4000,
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
        })

        self.env['hr.leave'].create({
            'name': 'Sick Time Off',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2026, 1, 1),
            'request_date_to': datetime.date(2026, 1, 31),
            'employee_id': self.employee.id,
        })
        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        self._validate_worked_days(payslip, {
            '010.00': (5.0, 38.0, 861.54),
            '082.00': (5.0, 38.0, 792.74),
            '072.00': (12.0, 91.2, 751.32),
        })

    def test_worker_work_accident_time_off_worked_days(self):
        self.employee.write({
            'wage': 4000,
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
        })

        self.env['hr.leave'].create({
            'name': 'Sick Time Off',
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_work_accident_first_week').id,
            'request_date_from': datetime.date(2026, 1, 1),
            'request_date_to': datetime.date(2026, 1, 31),
            'employee_id': self.employee.id,
        })
        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        self._validate_worked_days(payslip, {
            '009.00': (5.0, 38.0, 861.54),
            '070.00': (17.0, 129.2, 2695.31),
        })

    def test_worker_sick_and_work_accident_no_onss(self):
        self.company.current_payroll_config_id.l10n_be_employer_category_id = self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00017')
        self.employee.write({
            'wage': 4000,
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
        })
        self.env['hr.leave'].create([
            {
                'name': 'Work Accident Time Off',
                'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_work_accident_first_week').id,
                'request_date_from': datetime.date(2026, 1, 1),
                'request_date_to': datetime.date(2026, 1, 31),
                'employee_id': self.employee.id,
            },
            {
                'name': 'Sick Time Off',
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
                'request_date_from': datetime.date(2026, 2, 1),
                'request_date_to': datetime.date(2026, 2, 28),
                'employee_id': self.employee.id,
            }
        ])

        payslip_jan = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        payslip_feb = self._generate_payslip(datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))

        self._validate_payslip(payslip_jan)

        self._validate_payslip(payslip_feb)

    def test_student_worker_guaranteed_salary_no_withholding_tax(self):
        # Days 8 to 14 of a student manual worker's illness (082.00): the guaranteed salary is replacement revenue,
        # without withholding tax as the rest of a student's pay
        self.employee.write({
            'wage': 2000,
            'ip_wage_rate': 0,
            'l10n_be_dimona_category': 'stu',
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00840').id,
        })
        self.env['hr.leave'].create({
            'name': 'Sick Time Off',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2026, 1, 5),
            'request_date_to': datetime.date(2026, 1, 16),
            'employee_id': self.employee.id,
        })
        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        self._validate_payslip(payslip)

    def test_no_onss_dimona_dwd(self):
        # A worker declared without ONSS (Dimona DWD) owes neither the worker's nor the employer's contributions and gets
        # no employer reduction: the pay is taxed at the scale, the company car's CO2 contribution stays due
        self.employee.write({
            'wage': 750,
            'ip_wage_rate': 0,
            'l10n_be_dimona_category': 'dwd',
        })
        payslip = self._generate_payslip(datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
        self.assertTrue(payslip.version_id.no_onss)

        self._validate_payslip(payslip)

    def test_worker_work_accident_taxed_at_scale(self):
        # Days 8 to 30 of a worker's work accident (070.00): the employer's guaranteed salary at 85.88 % of the pay,
        # outside the ONSS base and taxed with the salary at the scale, also in a month with few paid hours
        self.employee.write({
            'wage': 3000,
            'ip_wage_rate': 0,
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
        })
        self.env['hr.leave'].create({
            'name': 'Work Accident Time Off',
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_work_accident_first_week').id,
            'request_date_from': datetime.date(2026, 1, 12),
            'request_date_to': datetime.date(2026, 2, 27),
            'employee_id': self.employee.id,
        })
        payslip_jan = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        payslip_feb = self._generate_payslip(datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))
        hourly_rate = 3000 * 3 / (13 * 38)

        for payslip in payslip_jan | payslip_feb:
            accident = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '070.00')
            values = payslip._get_line_values(['WORK_ACCIDENT', 'REPLACEMENT_REVENUE', 'REPLACEMENT_REVENUE.P.P'])
            self.assertAlmostEqual(values['WORK_ACCIDENT'][payslip.id]['total'], accident.amount, places=2)
            self.assertFalse(values['REPLACEMENT_REVENUE'][payslip.id]['total'])
            self.assertFalse(values['REPLACEMENT_REVENUE.P.P'][payslip.id]['total'])
        # February: 7 paid days out of 20, the hours at the hourly rate, at 85.88 % as well
        accident_feb = payslip_feb.worked_days_line_ids.filtered(lambda wd: wd.code == '070.00')
        self.assertAlmostEqual(accident_feb.amount, hourly_rate * accident_feb.number_of_hours * 0.8588, places=2)

        self._validate_payslip(payslip_jan)
        self._validate_payslip(payslip_feb)

    def test_withholding_reduction_capped_at_scale_tax(self):
        # The tax reduction of the employment bonus reduces the tax of the scale only, never the exceptional
        # rate on the complement of the guaranteed salary of an illness (082.00)
        self.employee.write({
            'wage': 2100,
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
        })
        self.env['hr.leave'].create({
            'name': 'Sick Time Off',
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_work_incapacity_worker_second_week').id,
            'request_date_from': datetime.date(2026, 2, 2),
            'request_date_to': datetime.date(2026, 2, 13),
            'employee_id': self.employee.id,
        })

        payslip = self._generate_payslip(datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))

        self._validate_payslip(payslip, {
            'EmpBonus.1': 147.12,
            'P.P': 0.0,
            'REPLACEMENT_REVENUE.P.P': -319.3,
            'P.P.DED': 0.0,
            'PPTOTAL': 319.3,
        }, skip_lines=True)

    def test_loss_on_commission_public_holiday_employee_joined_current_year(self):
        # If employee joined in current year, loss on variable during public holiday is the daily average since employee arrived.
        self.version.write({
            'contract_date_start': datetime.date(2026, 1, 1),
            'commission_on_target': 1000,
        })
        self.version.employee_id.write({
            'l10n_be_fictive_hire_date': datetime.date(2026, 1, 1),
        })

        self.env['resource.calendar.leaves'].create([{
            'name': "Public Holiday",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2026, 2, 2, 5, 0, 0),
            'date_to': datetime.datetime(2026, 2, 3, 16, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id,
        }])

        com_payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31), input_values={'COMMISSION': 1000})
        com_payslip.action_payslip_done()

        public_holiday_payslip = self._generate_payslip(datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))
        # number_of_month = 1 (only Jan 2026), daily variable revenue = 1000 / (25 * 5/6) = 48.0, for 2 days
        self._validate_payslip(public_holiday_payslip, {'COM_LOSS_PH': 96.0}, skip_lines=True)
        loss_line = public_holiday_payslip.line_ids.filtered(lambda l: l.code == 'COM_LOSS_PH')
        self.assertEqual((loss_line.quantity, loss_line.amount), (2, 48.0))

    def test_loss_on_commission_public_holiday_employee_joined_current_month(self):
        # If employee joined in current month, loss on variable during public holiday is the month commissions / number of days worked
        self.version.write({
            'contract_date_start': datetime.date(2026, 1, 1),
            'commission_on_target': 1000,
        })
        self.version.employee_id.write({
            'l10n_be_fictive_hire_date': datetime.date(2026, 1, 1),
        })

        self.env['resource.calendar.leaves'].create([{
            'name': "Public Holiday",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2026, 1, 2, 5, 0, 0),
            'date_to': datetime.datetime(2026, 1, 2, 16, 0, 0),
            'resource_id': False,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id,
        }])

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31), input_values={'COMMISSION': 1000})
        payslip.action_payslip_done()

        # 1000€ / 21 days = 47.62€
        self._validate_payslip(payslip, {'COM_LOSS_PH': 47.62}, skip_lines=True)

    def test_loss_on_commission_sickness(self):
        self.version.write({
            'contract_date_start': datetime.date(2025, 1, 1),
            'commission_on_target': 0,
        })
        self.version.employee_id.write({
            'l10n_be_fictive_hire_date': datetime.date(2025, 1, 1),
        })

        com_payslip = self._generate_payslip(datetime.date(2025, 12, 1), datetime.date(2025, 12, 31))
        com_payslip._set_input_value('COMMISSION', 1000)
        com_payslip.compute_sheet()
        com_payslip.action_payslip_done()

        self.env['resource.calendar.leaves'].create([{
            'name': "Sickness",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2026, 1, 5, 6, 0, 0),
            'date_to': datetime.datetime(2026, 1, 5, 18, 0, 0),
            'resource_id': False,
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
        }])

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        # 1000€ / 12 months = 83.33€/month; daily rate = 83.33 / (25 * 5/6) = 4.0€
        self._validate_payslip(payslip, {'COM_LOSS_SICK': 4.0}, skip_lines=True)

    def test_loss_on_commission_reference_periods(self):
        # The variable revenue of a suspension is the average of the previous civil year (small unemployment), except
        # for the sickness of the employees and the extra-legal holidays: the 12 months before the month
        self.version.write({
            'contract_date_start': datetime.date(2025, 1, 1),
            'commission_on_target': 0,
        })
        self.version.employee_id.write({
            'l10n_be_fictive_hire_date': datetime.date(2025, 1, 1),
        })
        for year, commission in ((2025, 1200), (2026, 600)):
            com_payslip = self._generate_payslip(datetime.date(year, 2, 1), datetime.date(year, 2, 28), input_values={'COMMISSION': commission})
            com_payslip.action_payslip_done()

        self.env['resource.calendar.leaves'].create([{
            'name': name,
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2026, 6, day, 6, 0, 0),
            'date_to': datetime.datetime(2026, 6, day, 18, 0, 0),
            'resource_id': False,
            'work_entry_type_id': self.env.ref(work_entry_type).id,
        } for name, day, work_entry_type in (
            ('Sickness', 2, 'hr_work_entry.be_work_entry_type_sick_leave'),
            ('Small Unemployment', 3, 'hr_work_entry.l10n_be_work_entry_type_small_unemployment'),
        )])

        payslip = self._generate_payslip(datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))
        # sickness: 600 / 12 months = 50/month, daily rate = 50 / (25 * 5/6) = 2.4
        # small unemployment: 1200 / 12 months of 2025 = 100/month, daily rate = 100 / (25 * 5/6) = 4.8
        self._validate_payslip(payslip, {'COM_LOSS_SICK': 7.2}, skip_lines=True)

    def test_loss_on_commission_absences_paid_by_employer(self):
        # The variable revenue is only due on the absences paid by the employer: the 3 first days of the birth leave
        # (007.05), not the next ones paid by the mutual insurance (128.05)
        self.version.write({
            'contract_date_start': datetime.date(2025, 1, 1),
            'commission_on_target': 0,
        })
        self.version.employee_id.write({
            'l10n_be_fictive_hire_date': datetime.date(2025, 1, 1),
        })
        com_payslip = self._generate_payslip(datetime.date(2025, 2, 1), datetime.date(2025, 2, 28), input_values={'COMMISSION': 1200})
        com_payslip.action_payslip_done()

        self.env['resource.calendar.leaves'].create([{
            'name': 'Birth Leave',
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2026, 6, day, 6, 0, 0),
            'date_to': datetime.datetime(2026, 6, day, 18, 0, 0),
            'resource_id': False,
            'work_entry_type_id': self.env.ref(work_entry_type).id,
        } for day, work_entry_type in (
            (2, 'hr_work_entry.l10n_be_work_entry_type_paternity_company'),
            (3, 'hr_work_entry.l10n_be_work_entry_type_paternity_company'),
            (4, 'hr_work_entry.l10n_be_work_entry_type_paternity_legal'),
        )])

        payslip = self._generate_payslip(datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))
        # 1200 / 12 months of 2025 = 100/month, daily rate = 100 / (25 * 5/6) = 4.8, for the 2 days of 007.05
        self._validate_payslip(payslip, {'COM_LOSS_SICK': 9.6}, skip_lines=True)

    def test_loss_on_commission_pto(self):
        self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_monthly').active = True
        self.version.write({
            'contract_date_start': datetime.date(2025, 1, 1),
            'commission_on_target': 0,
        })
        self.version.employee_id.write({
            'l10n_be_fictive_hire_date': datetime.date(2025, 1, 1),
        })

        com_payslip = self._generate_payslip(datetime.date(2025, 12, 1), datetime.date(2025, 12, 31))
        com_payslip._set_input_value('COMMISSION', 1000)
        com_payslip.compute_sheet()
        com_payslip.action_payslip_done()

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2026, 1, 5, 6, 0, 0),
            'date_to': datetime.datetime(2026, 1, 5, 18, 0, 0),
            'resource_id': False,
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id,
        }])

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        # 1000€ / 12 months = 83.33€/month; daily rate = 83.33 / (25 * 5/6) = 4.0€
        # Booked as remuneration: BASIC 2650 + COM_LOSS_PTO 4 - IP 662.5
        self._validate_payslip(payslip, {'COM_LOSS_PTO': 4.0, 'REMUNERATION': 1991.5}, skip_lines=True)

        # When compensated with the double holiday pay, COM_LOSS_PTO should not be applied
        monthly_benefit = self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_monthly')
        double_holiday_benefit = self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_double_holiday')
        double_holiday_benefit.active = True
        payslip_annual = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        self.assertNotIn('COM_LOSS_PTO', payslip_annual.line_ids.mapped('code'))
        monthly_benefit.active = True

        # The December settlement must deduct the PTO commission already paid.
        payslip.action_payslip_done()
        december_payslip = self._generate_payslip(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))
        self._validate_payslip(december_payslip, {'SIMPLE_DECEMBER': 154.34}, skip_lines=True)

    def test_loss_on_commission_pto_without_variable_revenues(self):
        # Without variable revenues in the past, there is no loss on commission
        self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_monthly').active = True
        self.version.write({
            'contract_date_start': datetime.date(2025, 1, 1),
            'commission_on_target': 0,
        })
        self.version.employee_id.write({
            'l10n_be_fictive_hire_date': datetime.date(2025, 1, 1),
        })

        self.env['resource.calendar.leaves'].create([{
            'name': "Legal Leave",
            'calendar_id': self.resource_calendar_38_hours_per_week.id,
            'company_id': self.env.company.id,
            'date_from': datetime.datetime(2026, 1, 5, 6, 0, 0),
            'date_to': datetime.datetime(2026, 1, 5, 18, 0, 0),
            'resource_id': False,
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_legal_leave').id,
        }])

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        self.assertIn('016.00', payslip.worked_days_line_ids.mapped('code'))
        self.assertNotIn('COM_LOSS_PTO', payslip.line_ids.mapped('code'))

    def test_loss_on_commission_pto_benefits_exclusive(self):
        monthly_benefit = self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_monthly')
        double_holiday_benefit = self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_double_holiday')
        monthly_rule = self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_loss_on_commissions_pto')
        double_holiday_rule = self.env.ref('l10n_be_hr_payroll.cp200_employees_double_holiday_single_holiday_variable_revenues')
        # Monthly by default on a new database (post init hook), with the double holiday pay on the updated ones
        monthly_benefit.active = True
        self.assertTrue(monthly_benefit.active)
        self.assertFalse(double_holiday_benefit.active)
        self.assertTrue(monthly_rule.active)
        # SIMPLE_VARIABLE also pays the other joint committees: never archived by the choice
        self.assertTrue(double_holiday_rule.active)

        double_holiday_benefit.active = True
        self.assertFalse(monthly_benefit.active)
        self.assertFalse(monthly_rule.active)
        self.assertTrue(double_holiday_rule.active)

        with self.assertRaises(UserError):
            double_holiday_benefit.active = False
        with self.assertRaises(UserError):
            (monthly_benefit | double_holiday_benefit).active = True

        monthly_benefit.active = True
        self.assertFalse(double_holiday_benefit.active)
        self.assertTrue(monthly_rule.active)
        self.assertTrue(double_holiday_rule.active)

        with self.assertRaises(UserError):
            monthly_benefit.unlink()

    def test_loss_on_commission_pto_benefits_data_update(self):
        # The choice is kept when the module is updated
        monthly_benefit = self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_monthly')
        double_holiday_benefit = self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_double_holiday')
        monthly_rule = self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_loss_on_commissions_pto')
        for chosen_benefit, other_benefit in [(double_holiday_benefit, monthly_benefit), (monthly_benefit, double_holiday_benefit)]:
            chosen_benefit.active = True
            convert_file(self.env, 'l10n_be_hr_payroll', 'data/hr_contract_salary_benefit_data.xml', idref={}, mode='update')
            self.assertTrue(chosen_benefit.active)
            self.assertFalse(other_benefit.active)
            self.assertEqual(monthly_rule.active, chosen_benefit == monthly_benefit)

    def test_loss_on_commission_pto_monthly_other_joint_committee(self):
        # Compensated monthly in JC 200 only (COM_LOSS_PTO): the double holiday pay of the other joint committees
        # keeps the single holiday pay on the variable salary
        self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_monthly').active = True
        self._generate_departure_data()
        for joint_committee, simple_variable in [('l10n_be_joint_committee_200', 0.0), ('l10n_be_joint_committee_302', 480.08)]:
            self.version_2020.l10n_be_joint_committee_id = self.env.ref(f'l10n_be_hr_payroll.{joint_committee}')
            double_pay_payslip = self.env['hr.payslip'].create({
                'employee_id': self.employee.id,
                'version_id': self.version_2020.id,
                'company_id': self.env.company.id,
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
                'date_from': datetime.date(2020, 3, 1),
                'date_to': datetime.date(2020, 3, 31),
            })
            double_pay_payslip.compute_sheet()
            self.assertEqual(
                double_pay_payslip._get_line_values(['SIMPLE_VARIABLE'])['SIMPLE_VARIABLE'][double_pay_payslip.id]['total'],
                simple_variable, joint_committee)

    def test_cct90_payslip(self):
        cct90_struct = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_cct90')
        payslip = self._generate_payslip(datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), struct_id=cct90_struct.id, input_values={'CCT90BONUSPLAN': 10000})
        self._validate_payslip(payslip)

    def test_worker_payslip(self):
        self.version.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_100').id
        self.version.l10n_be_worker_code_id = self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 30))
        self._validate_payslip(payslip)

    def test_hospital_insurance_employee_contribution(self):
        self.version.ip_wage_rate = 0
        self.version.has_hospital_insurance = True
        self.version.insurance_amount = 200
        self.version.hospital_insurance_employee_contribution = 100.0
        payslip = self._generate_payslip(self.date_from, self.date_to)
        self._validate_payslip(payslip)

    def test_journalist_pension_fund_contribution(self):
        self.version.l10n_be_worker_status = 'PJ'
        payslip = self._generate_payslip(self.date_from, self.date_to)
        self._validate_payslip(payslip)

    @freeze_time("2026-01-01")
    def test_economic_unemployment_bonus_full(self):
        self.version.resource_calendar_id = self.resource_calendar_eco_unemployment_full
        self.employee.write({'wage': 5000})
        # as wage is higher than threshold, employee will start taking bonus from the 27th day of economic unemployment.
        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        payslip.action_payslip_done()
        self._validate_worked_days(payslip, {
            '137.00': (22.0, 167.2, 0.0),
        })
        self._validate_payslip(payslip)

        payslip = self._generate_payslip(datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))

        self._validate_worked_days(payslip, {
            '137.00': (20.0, 152.0, 0.0),
        })
        self._validate_payslip(payslip)

    @freeze_time("2026-01-01")
    def test_economic_unemployment_bonus_partial(self):
        self.version.resource_calendar_id = self.resource_calendar_eco_unemployment_partial

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        self._validate_worked_days(payslip, {
            '002.00': (10.0, 76.0, 1223.08),
            '137.00': (12.0, 91.2, 0.0),
        })

        self._validate_payslip(payslip)

    @freeze_time("2026-01-01")
    def test_economic_unemployment_compensation_302(self):
        employee = self.env['hr.employee'].create({
            'name': 'Economic Unemployment worker',
            'company_id': self.env.company.id,
            'resource_calendar_id': self.resource_calendar_eco_unemployment_partial.id,
            'date_version': datetime.date(2026, 1, 1),
            'contract_date_start': datetime.date(2026, 1, 1),
            'wage': 5000,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
            'lang': 'fr_BE',
        })

        payslip = []
        for month in range(12):
            last_day = calendar.monthrange(2026, month + 1)[1]
            payslip.append(self._generate_payslip(
                datetime.date(2026, month + 1, 1),
                datetime.date(2026, month + 1, last_day),
                employee_id=employee.id,
                version_id=employee.current_version_id.id,
            ))
            payslip[month].action_payslip_done()

        self._validate_worked_days(payslip[0], {
            '137.00': (12.0, 91.2, 0.0),
            '002.00': (10.0, 76.0, 2307.69),
        })

        # less than 6 months -> 2 €/ day
        self._validate_payslip(payslip[0])

        # after 6 months and less than 111 days -> 0.5187 / hour
        self._validate_payslip(payslip[7])

        # after 6 months and more than 110 days ->  2 €/ day
        self._validate_payslip(payslip[10])

    @freeze_time("2026-01-01")
    def test_economic_unemployment_compensation_200(self):
        self.version.resource_calendar_id = self.resource_calendar_eco_unemployment_partial

        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        self._validate_worked_days(payslip, {
            '002.00': (10.0, 76.0, 1223.08),
            '137.00': (12.0, 91.2, 0.0),
        })

        payslip.with_context(hr_payroll_force_compute_issue=True)._compute_issues()
        issues = list((payslip.issues or {}).values())
        messages = [issue.get('message') for issue in issues]
        self.assertTrue(any(message and message.startswith("Temporary unemployment detected for CP200: compensation amount must be entered manually.") for message in messages))

        payslip._set_input_value('EUC_CP200', 5)
        payslip.compute_sheet()

        payslip.with_context(hr_payroll_force_compute_issue=True)._compute_issues()
        issues = list((payslip.issues or {}).values())
        messages = [issue.get('message') for issue in issues]
        self.assertFalse(any(message and message.startswith("Temporary unemployment detected for CP200: compensation amount must be entered manually.") for message in messages))

        self._validate_payslip(payslip[0])

    def test_out_of_contract_multi_version(self):
        self.version.write({
            'date_version': datetime.date(2026, 6, 1),
            'contract_date_start': datetime.date(2026, 6, 1),
            'contract_date_end': datetime.date(2026, 6, 7),
            'wage': 2500.0,
            'ip_wage_rate': 0,
            'l10n_be_lsa_monthly_misc_base_amount': 0.0,
            'l10n_be_lsa_monthly_pro_base_amount': 150.0,
        })
        self.env['hr.contract.salary.benefit'].with_context(active_test=False).search([('res_field_id.name', '=', 'l10n_be_lsa_monthly_pro_base_amount')]).active = True
        self.version.copy({
            'date_version': datetime.date(2026, 6, 8),
            'contract_date_start': datetime.date(2026, 6, 8),
            'contract_date_end': False,
            'wage': 3000.0,
            'l10n_be_dimona_category': False,
        })
        version_3 = self.version.copy({
            'date_version': datetime.date(2026, 6, 15),
            'contract_date_start': datetime.date(2026, 6, 8),
            'contract_date_end': False,
            'wage': 3500.0,
            'l10n_be_dimona_category': False,
        })

        # Payslip for Contract 1
        payslip_1 = self._generate_payslip(datetime.date(2026, 6, 1), datetime.date(2026, 6, 30), version_id=self.version.id)
        self.assertEqual(len(payslip_1.worked_days_line_ids), 2)

        # 000.00: 17 days (129.2h). Unpaid = 0.00
        # 002.00: 5 days (38h). 2500 * (1 - (129.2 [000.00 hours] * (3 / 13 / 38))) = 538.46
        self._validate_worked_days(payslip_1, {'002.00': (5.0, 38.0, 576.92), '000.00': (17.0, 129.2, 0.0)})
        self._validate_payslip(payslip_1)

        # Payslip for Contract 2
        payslip_2 = self._generate_payslip(datetime.date(2026, 6, 1), datetime.date(2026, 6, 30), version_id=version_3.id)
        self.assertEqual(len(payslip_2.worked_days_line_ids), 3)

        # 000.00: 5 days (38h). Unpaid = 0.00
        # 002.00:
        #   - Version 2: 5 days (38h). 3000 * (3 / 13 / 38) * 38 = 692.31
        #   - Version 3: 12 days (91.2h).
        #      The longest period uses the deduction method:
        #           - version 2 theoretical hours = actual hours * version 3 weekly hours / version 2 weekly hours = 38 * 38 / 38 = 38
        #           - version 3 amount = wage - shoter periods theoretical hours * hourly rate = 3500.0 - (76) * (3500.0 * 3 / (38 * 13)) = 1884.62
        #   - Aggregated 002.00 = 692.31 (V2) + 1884.62 (V3) = 2576.93
        self._validate_worked_days(payslip_2, {'002.00': (17.0, 129.2, 2576.93), '000.00': (5.0, 38.0, 0.0)})
        self._validate_payslip(payslip_2)

    def test_part_time_additional_hours(self):

        def _create_additional_hours_leave(work_entry_type, datetime_from, datetime_to):
            leave = self.env['hr.leave'].create({
                'work_entry_type_id': work_entry_type.id,
                'request_date_from': datetime_from,
                'request_date_to': datetime_to,
                'request_hour_from': datetime_from.hour,
                'request_hour_to': datetime_to.hour,
                'employee_id': self.employee.id,
            })
            return leave

        self.version.resource_calendar_id = self.resource_calendar_half_time
        self.version.wage_type = "hourly"
        self.version.hourly_wage = 20

        _create_additional_hours_leave(
            self.additional_hours_type,
            datetime.datetime(2025, 9, 8, 17, 0),
            datetime.datetime(2025, 9, 8, 23, 0),
        )
        _create_additional_hours_leave(
            self.additional_hours_type,
            datetime.datetime(2025, 9, 9, 14, 0),
            datetime.datetime(2025, 9, 9, 22, 0),
        )
        _create_additional_hours_leave(
            self.additional_hours_type,
            datetime.datetime(2025, 9, 10, 14, 0),
            datetime.datetime(2025, 9, 10, 20, 0),
        )
        _create_additional_hours_leave(
            self.additional_hours_type,
            datetime.datetime(2025, 9, 11, 13, 0),
            datetime.datetime(2025, 9, 11, 20, 0),
        )
        _create_additional_hours_leave(
            self.additional_hours_50_type,
            datetime.datetime(2025, 9, 14, 13, 0),  # Sunday
            datetime.datetime(2025, 9, 14, 15, 0),
        )
        _create_additional_hours_leave(
            self.additional_hours_100_type,
            datetime.datetime(2025, 9, 21, 10, 0),  # Sunday
            datetime.datetime(2025, 9, 21, 15, 0),
        )
        payslip = self._generate_payslip(datetime.date(2025, 9, 1), datetime.date(2025, 9, 30))
        payslip.with_context(hr_payroll_force_compute_issue=True)._compute_issues()
        issues = list((payslip.issues or {}).values())
        messages = [issue.get('message') for issue in issues]
        warning_messages = (
                "Daily hours exceed 9h limit convert excess to Extra-hours.",
                "Max 12 additional hours/month pay excess at +50% or +100%.",
                "Sunday additional hours must be paid.",
                "Weekly hours exceed schedule limit convert excess to Extra-hours.",
                "Cannot encode additional hours during regular working time."
        )
        for message_start in warning_messages:
            self.assertTrue(
                any(message and message.startswith(message_start) for message in messages),
                f"Expected issue starting with {message_start!r}, got:\n{messages}",
            )

        with self.assertRaises(ValidationError):
            payslip.action_payslip_done()

    def test_part_time_additional_hours_on_sundays(self):
        """Within the monthly credit, additional hours carry no supplement, even on a Sunday: plain hours on a
        Sunday are accepted. Beyond the credit, the supplement on a Sunday is +100%: hours paid +50% on a Sunday
        block the payslip."""
        self.version.resource_calendar_id = self.resource_calendar_half_time
        self.version.wage_type = "hourly"
        self.version.hourly_wage = 20
        for work_entry_type, datetime_from, datetime_to in [
            (self.additional_hours_type, datetime.datetime(2025, 9, 14, 10, 0), datetime.datetime(2025, 9, 14, 13, 0)),
            (self.additional_hours_100_type, datetime.datetime(2025, 9, 21, 10, 0), datetime.datetime(2025, 9, 21, 12, 0)),
            (self.additional_hours_type, datetime.datetime(2025, 10, 5, 10, 0), datetime.datetime(2025, 10, 5, 12, 0)),
            (self.additional_hours_50_type, datetime.datetime(2025, 10, 12, 10, 0), datetime.datetime(2025, 10, 12, 12, 0)),
        ]:
            self.env['hr.leave'].create({
                'work_entry_type_id': work_entry_type.id,
                'request_date_from': datetime_from,
                'request_date_to': datetime_to,
                'request_hour_from': datetime_from.hour,
                'request_hour_to': datetime_to.hour,
                'employee_id': self.employee.id,
            })

        payslip = self._generate_payslip(datetime.date(2025, 9, 1), datetime.date(2025, 9, 30))
        self.assertEqual(payslip.l10n_be_sum_additional_hours, 3.0)
        self.assertFalse(payslip.l10n_be_wrong_additional_hours_on_sundays_or_public_holidays)
        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')

        payslip = self._generate_payslip(datetime.date(2025, 10, 1), datetime.date(2025, 10, 31))
        self.assertTrue(payslip.l10n_be_wrong_additional_hours_on_sundays_or_public_holidays)
        with self.assertRaises(ValidationError):
            payslip.action_payslip_done()

    def test_part_time_additional_hours_batch(self):
        """Payslips computed together: those without additional hours are reset, those with some
        are checked as when computed alone."""
        self.version.resource_calendar_id = self.resource_calendar_half_time
        self.version.wage_type = "hourly"
        self.version.hourly_wage = 20
        self.env['hr.leave'].create({
            'work_entry_type_id': self.additional_hours_50_type.id,
            'request_date_from': datetime.datetime(2025, 10, 12, 10, 0),  # Sunday
            'request_date_to': datetime.datetime(2025, 10, 12, 12, 0),
            'request_hour_from': 10,
            'request_hour_to': 12,
            'employee_id': self.employee.id,
        })
        payslips = self.env['hr.payslip'].create([{
            'name': "Test Payslip",
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'struct_id': self.structure.id,
            'date_from': date_from,
            'date_to': date_to,
        } for date_from, date_to in [
            (datetime.date(2025, 9, 1), datetime.date(2025, 9, 30)),
            (datetime.date(2025, 10, 1), datetime.date(2025, 10, 31)),
        ]])
        if self.car:
            payslips.write({'vehicle_id': self.car.id})
        payslips.compute_sheet()
        september, october = payslips
        self.assertEqual(september.l10n_be_sum_additional_hours, 0.0)
        self.assertFalse(september.l10n_be_wrong_additional_hours_on_sundays_or_public_holidays)
        self.assertTrue(october.l10n_be_wrong_additional_hours_on_sundays_or_public_holidays)
        self.assertFalse(october.l10n_be_additional_hours_during_working_time)

    def test_part_time_additional_hours_daily_and_weekly_limits(self):
        """The 9 hours a day and the full time week are checked on the days and weeks that carry additional hours,
        not on long planned days or weeks without any. Variable part time schedule over two weeks: week A Monday to
        Thursday 8 hours and Friday 9.5 hours (41.5 hours), week B Monday 4 hours."""
        self.version.resource_calendar_id = self.env['resource.calendar'].sudo().create({
            'name': "Test Calendar: variable part time, long week A",
            'company_id': self.env.company.id,
            'calendar_type': 'variable',
            'hours_per_day': 7.7,
            'days_per_week': 3.0,
            'hours_per_week': 22.75,
            'full_time_required_hours': 38.0,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'date': datetime.date(1, 1, 1) + datetime.timedelta(days=day, weeks=week),
                'hour_from': hour_from,
                'hour_to': hour_to,
                'recurrency': True,
                'recurrency_type': 'weeks',
                'recurrency_interval': 2,
                'recurrency_end_type': 'forever',
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for day, week, hour_from, hour_to in [
                (0, 0, 8.0, 16.0),
                (1, 0, 8.0, 16.0),
                (2, 0, 8.0, 16.0),
                (3, 0, 8.0, 16.0),
                (4, 0, 8.0, 12.0),
                (4, 0, 12.5, 18.0),
                (0, 1, 8.0, 12.0),
            ]],
        })
        self.version.wage_type = "hourly"
        self.version.hourly_wage = 20
        for datetime_from, datetime_to in [
            (datetime.datetime(2025, 9, 9, 9, 0), datetime.datetime(2025, 9, 9, 11, 0)),  # Tuesday, week B
            (datetime.datetime(2025, 10, 17, 18, 0), datetime.datetime(2025, 10, 17, 19, 0)),  # Friday, week A
        ]:
            self.env['hr.leave'].create({
                'work_entry_type_id': self.additional_hours_type.id,
                'request_date_from': datetime_from,
                'request_date_to': datetime_to,
                'request_hour_from': datetime_from.hour,
                'request_hour_to': datetime_to.hour,
                'employee_id': self.employee.id,
            })

        payslip = self._generate_payslip(datetime.date(2025, 9, 1), datetime.date(2025, 9, 30))
        self.assertEqual(payslip.l10n_be_sum_additional_hours, 2.0)
        self.assertFalse(payslip.l10n_be_working_hours_limit_per_day_exceeded)
        self.assertFalse(payslip.l10n_be_working_hours_limit_per_week_exceeded)
        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')

        payslip = self._generate_payslip(datetime.date(2025, 10, 1), datetime.date(2025, 10, 31))
        self.assertEqual(payslip.l10n_be_sum_additional_hours, 1.0)
        self.assertTrue(payslip.l10n_be_working_hours_limit_per_day_exceeded)
        self.assertTrue(payslip.l10n_be_working_hours_limit_per_week_exceeded)
        # The too many additional hours per day / week warnings do not block the payslips
        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')

    def test_part_time_additional_hours_exact_daily_limit(self):
        """A day of exactly 9 hours is within the daily limit, even when its pieces do not add up exactly in
        floats: 4 h + 4 h 40 + 20 min of additional hours = 9.000000000000002."""
        self.version.resource_calendar_id = self.env['resource.calendar'].sudo().create({
            'name': "Test Calendar: part time, 8 hours 40 on Monday",
            'company_id': self.env.company.id,
            'full_time_required_hours': 38.0,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for dayofweek, hour_from, hour_to in [
                ('0', 8.0, 12.0),
                ('0', 12.5, 17 + 10 / 60),
                ('1', 8.0, 12.0),
            ]],
        })
        self.version.wage_type = "hourly"
        self.version.hourly_wage = 20
        self.env['hr.leave'].create({
            'work_entry_type_id': self.additional_hours_type.id,
            'request_date_from': datetime.date(2025, 9, 8),
            'request_date_to': datetime.date(2025, 9, 8),
            'request_hour_from': 17 + 10 / 60,
            'request_hour_to': 17.5,
            'employee_id': self.employee.id,
        })

        payslip = self._generate_payslip(datetime.date(2025, 9, 1), datetime.date(2025, 9, 30))
        self.assertAlmostEqual(payslip.l10n_be_sum_additional_hours, 1 / 3, places=2)
        self.assertFalse(payslip.l10n_be_additional_hours_during_working_time)
        self.assertFalse(payslip.l10n_be_working_hours_limit_per_day_exceeded)
        self.assertFalse(payslip.l10n_be_working_hours_limit_per_week_exceeded)

    def test_part_time_additional_hours_exact_monthly_limit(self):
        """12 additional hours in the month are within the monthly limit, even when their pieces do not add up exactly
        in floats: 2 h 50 + 2 h 50 + 40 min + 2 h 50 + 2 h 50 = 12.000000000000002."""
        self.version.resource_calendar_id = self.env['resource.calendar'].sudo().create({
            'name': "Test Calendar: part time, mornings",
            'company_id': self.env.company.id,
            'full_time_required_hours': 38.0,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': 8.0,
                'hour_to': 12.0,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for dayofweek in '01234'],
        })
        self.version.wage_type = "hourly"
        self.version.hourly_wage = 20
        for day, minutes in [(8, 170), (9, 170), (10, 40), (11, 170), (12, 170)]:
            self.env['hr.leave'].create({
                'work_entry_type_id': self.additional_hours_type.id,
                'request_date_from': datetime.date(2025, 9, day),
                'request_date_to': datetime.date(2025, 9, day),
                'request_hour_from': 12.5,
                'request_hour_to': 12.5 + minutes / 60,
                'employee_id': self.employee.id,
            })

        payslip = self._generate_payslip(datetime.date(2025, 9, 1), datetime.date(2025, 9, 30))
        self.assertAlmostEqual(payslip.l10n_be_sum_additional_hours, 12.0, places=2)
        self.assertFalse(payslip.l10n_be_sum_additional_hours > 12)

    def test_reference_working_schedule_issue_blocks_validation(self):
        # Putting itself as a reference calendar makes full_time_required_hours 19 from 38
        self.version.write({
            'resource_calendar_id': self.resource_calendar_half_time.id,
            'reference_calendar_id': self.resource_calendar_half_time.id,
        })
        # Fix the full_time_required_hours so that the work time rate < 1
        self.resource_calendar_half_time.full_time_required_hours = 38.0
        # An employee who only had a past version on that schedule is not blocked
        other_employee = self.env['hr.employee'].create({
            'name': 'Former Half Time Employee',
            'company_id': self.employee.company_id.id,
            'date_version': datetime.date(2018, 1, 1),
            'resource_calendar_id': self.resource_calendar_half_time.id,
        })
        other_employee.create_version({
            'date_version': datetime.date(2019, 1, 1),
            'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
        })
        blocked_employees = self.env['hr.payslip']._get_employees_from_records(self.resource_calendar_half_time)
        self.assertIn(self.employee, blocked_employees)
        self.assertNotIn(other_employee, blocked_employees)

        payslip = self._generate_payslip(self.date_from, self.date_to)

        with self.assertRaisesRegex(ValidationError, "Reference working schedule issue"):
            payslip.action_payslip_done()

    def test_employee_under_15_blocks_validation(self):
        """The legal minimum working age applies to every employee under contract, not only to the students."""
        warning = self.env.ref('l10n_be_hr_payroll.hr_payroll_warning_less_than_15_student')
        today = datetime.date.today()
        self.assertNotEqual(self.version.employee_type_id.l10n_be_dimona_category, 'stu')
        no_contract_employee = self.env['hr.employee'].create({
            'name': 'Young Employee Without Contract',
            'company_id': self.employee.company_id.id,
            'birthday': today - relativedelta(years=14),
        })

        def flagged_employees():
            return warning._get_warning_domain_records(self.env.companies)

        # No birthday: not flagged
        self.employee.birthday = False
        self.assertNotIn(self.employee, flagged_employees())
        # 15 years old today: not flagged
        self.employee.birthday = today - relativedelta(years=15)
        self.assertNotIn(self.employee, flagged_employees())
        # Under 15 without contract: not flagged
        self.assertNotIn(no_contract_employee, flagged_employees())

        # Under 15 with a contract (not a student): flagged and the payslip validation is blocked
        self.employee.birthday = today - relativedelta(years=14)
        self.assertIn(self.employee, flagged_employees())
        payslip = self._generate_payslip(self.date_from, self.date_to)
        with self.assertRaisesRegex(ValidationError, "Employees under 15 years old"):
            payslip.action_payslip_done()

        # Back to 15 years old: the payslip can be validated
        self.employee.birthday = today - relativedelta(years=15)
        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')

    def test_marital_status_separated(self):
        """Test separated marital status fallback to single parent reductions."""
        self.employee.write({
            'marital': 'separated',
            'children': 2,
            'wage': 2650.0,
            'ip_wage_rate': 0,
        })

        payslip = self._generate_payslip(self.date_from, self.date_to)
        self._validate_worked_days(payslip, {'002.00': (22.0, 167.2, 2650.0)})

        self._validate_payslip(payslip)

    def _assert_withholding_deductions(self, payslip, marital, family):
        values = payslip._get_line_values(['P.P.MARITAL.DED', 'P.P.FAMILY.DED'])
        self.assertAlmostEqual(values['P.P.MARITAL.DED'][payslip.id]['total'], -marital, places=2)
        self.assertAlmostEqual(values['P.P.FAMILY.DED'][payslip.id]['total'], -family, places=2)

    def test_withholding_taxes_2026_nov_dependents(self):
        # IPP reform: new yearly amounts for the income paid from November 2026
        self.employee.write({
            'marital': 'single',
            'children': 2,
            'disabled': True,
            'other_juniors_dependent': 1,
            'wage': 5500.0,
            'ip_wage_rate': 0,
        })

        # single parent 624 + disabled worker 624 + other dependent 624 + 2 children 1656
        payslip_oct = self._generate_payslip(datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
        self._assert_withholding_deductions(payslip_oct, 2987.98, 3528.0)
        self._validate_payslip(payslip_oct)

        # single parent 636 + disabled worker 648 + other dependent 636 + 2 children 1644
        payslip_nov = self._generate_payslip(datetime.date(2026, 11, 1), datetime.date(2026, 11, 30))
        self._assert_withholding_deductions(payslip_nov, 3089.63, 3564.0)
        self._validate_payslip(payslip_nov)

    def test_withholding_taxes_2026_nov_dependents_with_disabled(self):
        # From November 2026, the disabled worker has a deduction of its own, the disabled spouse and the other
        # dependent people keep the shared one
        self.employee.write({
            'marital': 'married',
            'spouse_fiscal_status': 'without_income',
            'birthday': datetime.date(1980, 5, 10),
            'spouse_birthdate': datetime.date(1982, 7, 20),
            'children': 1,
            'disabled': True,
            'disabled_spouse_bool': True,
            'other_juniors_dependent': 1,
            'wage': 5500.0,
            'ip_wage_rate': 0,
        })

        # scale II: 2 x 2987.98; disabled worker 624 + other dependent 624 + disabled spouse 624 + 1 child 624
        payslip_oct = self._generate_payslip(datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
        self._assert_withholding_deductions(payslip_oct, 2 * 2987.98, 2496.0)
        self._validate_payslip(payslip_oct)

        # scale II: 2 x 3089.63; disabled worker 648 + other dependent 636 + disabled spouse 636 + 1 child 684
        payslip_nov = self._generate_payslip(datetime.date(2026, 11, 1), datetime.date(2026, 11, 30))
        self._assert_withholding_deductions(payslip_nov, 2 * 3089.63, 2604.0)
        self._validate_payslip(payslip_nov)

    def test_withholding_taxes_2026_nov_more_than_8_children(self):
        self.employee.write({
            'marital': 'single',
            'children': 10,
            'wage': 10000.0,
            'ip_wage_rate': 0,
        })

        # single parent 624 + 8 children 21996 + 2 x 3864
        payslip_oct = self._generate_payslip(datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
        self._assert_withholding_deductions(payslip_oct, 2987.98, 30348.0)
        self._validate_payslip(payslip_oct)

        # single parent 636 + 8 children 21492 + 2 x 3780
        payslip_nov = self._generate_payslip(datetime.date(2026, 11, 1), datetime.date(2026, 11, 30))
        self._assert_withholding_deductions(payslip_nov, 3089.63, 29688.0)
        self._validate_payslip(payslip_nov)

    def test_withholding_taxes_2026_nov_spouse_maximum(self):
        # Scale II: from November 2026, the income allotted to the spouse without income is at most 12790 for the
        # whole year when both spouses are 66 years old on January 1st of the next year, 11780 otherwise (13790 before)
        self.employee.write({
            'marital': 'married',
            'spouse_fiscal_status': 'without_income',
            'birthday': datetime.date(1955, 3, 1),
            'wage': 5500.0,
            'ip_wage_rate': 0,
        })

        def max_spouse_income(date_from, date_to):
            payslip = self._generate_payslip(date_from, date_to)
            amount = payslip._get_be_max_spouse_income()
            self._validate_payslip(payslip)
            payslip.unlink()
            return amount

        november = (datetime.date(2026, 11, 1), datetime.date(2026, 11, 30))
        # spouse 44 years old on January 1st, 2027
        self.employee.spouse_birthdate = datetime.date(1982, 7, 20)
        self.assertEqual(max_spouse_income(*november), 11780.0)
        # spouse birthdate unknown
        self.employee.spouse_birthdate = False
        self.assertEqual(max_spouse_income(*november), 11780.0)
        # both spouses 66 years old on January 1st, 2027 (the spouse turns 66 on December 15th, 2026)
        self.employee.spouse_birthdate = datetime.date(1960, 12, 15)
        self.assertEqual(max_spouse_income(datetime.date(2026, 10, 1), datetime.date(2026, 10, 31)), 13790.0)
        self.assertEqual(max_spouse_income(*november), 12790.0)
        # the spouse turns 66 on March 10th, 2027: 11780 in 2026, 12790 from January 2027
        self.employee.spouse_birthdate = datetime.date(1961, 3, 10)
        self.assertEqual(max_spouse_income(datetime.date(2026, 12, 1), datetime.date(2026, 12, 31)), 11780.0)
        self.assertEqual(max_spouse_income(datetime.date(2027, 1, 1), datetime.date(2027, 1, 31)), 12790.0)

    def test_fixed_wage_under_50_percent(self):
        self.version.write({
            'wage': 3000.0,
            'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
        })

        date_from = datetime.date(2026, 7, 1)
        date_to = datetime.date(2026, 7, 31)

        self.env['hr.leave'].create({
            'name': 'Unpaid Leave (Under 50%)',
            'work_entry_type_id': self.unpaid_time_off_type.id,
            'date_from': datetime.datetime(2026, 7, 15, 0, 0, 0),
            'date_to': datetime.datetime(2026, 7, 31, 23, 59, 59),
            'request_date_from': datetime.datetime(2026, 7, 15, 0, 0, 0),
            'request_date_to': datetime.datetime(2026, 7, 31, 23, 59, 59),
            'number_of_days': 13,
            'employee_id': self.employee.id,
        })

        payslip = self._generate_payslip(date_from, date_to)

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (10.0, 76.0, 1384.62),
            '158.00': (13.0, 98.8, 0.0),
        })

        self._validate_payslip(payslip)

    def test_fixed_wage_over_50_percent(self):
        self.version.write({
            'wage': 3000.0,
            'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
        })

        date_from = datetime.date(2026, 7, 1)
        date_to = datetime.date(2026, 7, 31)

        self.env['hr.leave'].create({
            'name': 'Unpaid Leave (Over 50%)',
            'work_entry_type_id': self.unpaid_time_off_type.id,
            'date_from': datetime.datetime(2026, 7, 16, 0, 0, 0),
            'date_to': datetime.datetime(2026, 7, 31, 23, 59, 59),
            'request_date_from': datetime.datetime(2026, 7, 18, 0, 0, 0),
            'request_date_to': datetime.datetime(2026, 7, 31, 23, 59, 59),
            'number_of_days': 13,
            'employee_id': self.employee.id,
        })

        payslip = self._generate_payslip(date_from, date_to)

        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (13.0, 98.8, 1615.40),
            '158.00': (10.0, 76.0, 0),
        })

        self._validate_payslip(payslip)

    def test_paid_by_hours_wage(self):
        self.version.write({
            'wage_type': 'hourly',
            'hourly_wage': 15.0,
            'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
        })

        date_from = datetime.date(2024, 7, 1)
        date_to = datetime.date(2024, 7, 31)

        self.env['hr.leave'].create({
            'name': 'Unpaid Leave (Hourly Test)',
            'work_entry_type_id': self.unpaid_time_off_type.id,
            'date_from': datetime.datetime(2024, 7, 15, 0, 0, 0),
            'date_to': datetime.datetime(2024, 7, 31, 23, 59, 59),
            'request_date_from': datetime.datetime(2024, 7, 15, 0, 0, 0),
            'request_date_to': datetime.datetime(2024, 7, 31, 23, 59, 59),
            'number_of_days': 13,
            'employee_id': self.employee.id,
        })

        payslip = self._generate_payslip(date_from, date_to)
        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        self._validate_worked_days(payslip, {
            '002.00': (10.0, 76.0, 1140.0),
            '158.00': (13.0, 98.8, 0.0),
        })
        self._validate_payslip(payslip)

    @freeze_time("2026-01-01")
    def test_holiday_pay_provision_employee_departure(self):
        """ Ensure the employee holiday pay provision accrues at 18.2% every month and is emptied on the last payslip when the employee leaves. """
        # Clean base: no benefits so that the gross equals the monthly wage.
        self.version.write({
            'wage': 1778.84,  # Gross chosen so that the monthly provision is around 323.75.
            'internet': 0,
            'mobile': 0,
            'ip_wage_rate': 0,
            'contract_date_end': datetime.date(2026, 7, 13),  # the employee leaves on the 13th of July
        })

        # January to June: 18.2% provision on the 1,778.84 gross.
        for month in range(1, 7):
            first_day = datetime.date(2026, month, 1)
            last_day = first_day + relativedelta(day=31)
            payslip = self._generate_payslip(first_day, last_day)
            self._validate_payslip(payslip, {'HOLIDAY_TAX_PROV': 323.75}, skip_lines=True)
            payslip.action_payslip_done()

        # July: last payslip, the whole provision accrued during the year is released.
        july_payslip = self._generate_payslip(datetime.date(2026, 7, 1), datetime.date(2026, 7, 31))
        # Check that the provision equals to 6 months * 18.2% * 1,778.84 = 1,942.49.
        self._validate_payslip(july_payslip, {'HOLIDAY_TAX_PROV': -1942.49}, skip_lines=True)

    @freeze_time("2026-01-01")
    def test_holiday_pay_provision_worker_assimilated_and_departure(self):
        """
        Ensure the worker holiday pay provision accrues at 10.27% of the 108% gross, keeps accruing on
        assimilated but unpaid time off, and is emptied on the last payslip when the worker leaves.
        """
        self.version.write({
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
            'wage': 2465.04,  # Gross chosen so that the monthly provision is around 273.41.
            'internet': 0,
            'mobile': 0,
            'ip_wage_rate': 0,
            'contract_date_end': datetime.date(2026, 3, 13),  # The worker leaves on the 13th of March.
        })

        # January: regular full month. Ensure that the provision equals to 10.27% * 1.08 * 2,465.04 = 273.41.
        january_payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        self._validate_payslip(january_payslip, {'HOLIDAY_TAX_PROV': 273.41}, skip_lines=True)
        january_payslip.action_payslip_done()

        # February: a few strike days. They are unpaid on the payslip but assimilated for the double holiday pay
        # (like a legal holiday), so the provision base is topped up and the provision stays a full 273.41.
        self.env['resource.calendar.leaves'].create([{
            'name': "Strike",
            'calendar_id': self.version.resource_calendar_id.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime.datetime(2026, 2, 9, 6, 0, 0),
            'date_to': datetime.datetime(2026, 2, 11, 16, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_strike').id,
        }])
        february_payslip = self._generate_payslip(datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))
        self._validate_payslip(february_payslip, {'HOLIDAY_TAX_PROV': 273.41}, skip_lines=True)
        february_payslip.action_payslip_done()

        # March: last payslip, the whole provision accrued during the year is released.
        march_payslip = self._generate_payslip(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))
        # Ensure that the released provision equals the two monthly lines booked before, 2 * 273.41 = 546.82.
        self._validate_payslip(march_payslip, {'HOLIDAY_TAX_PROV': -546.82}, skip_lines=True)

    def test_withholding_tax_exemption_274_32_computed_for_doctor_researcher(self):
        # A PhD employee assigned 60% of their time to R&D is entitled to a
        # withholding tax exemption (form 274.32) capped at 80% of that share
        # of the total withholding tax, and never more than the withholding due.
        self.employee.certificate = 'doctor'
        self.version.rd_percentage = 0.6
        payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))

        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_32')
        line_values = payslip._get_line_values(['PPTOTAL', 'WITHHOLDING_TAX_EX_274_32'])
        pp_total = line_values['PPTOTAL'][payslip.id]['total']
        withholding_tax_exemption = line_values['WITHHOLDING_TAX_EX_274_32'][payslip.id]['total']

        self.assertGreater(pp_total, 0, "There should be a positive withholding tax to exempt from")
        expected_withholding_tax_exemption = min(pp_total * self.version.rd_percentage * 0.8, pp_total)
        self.assertAlmostEqual(withholding_tax_exemption, expected_withholding_tax_exemption, places=2)

    def test_withholding_tax_exemption_274_32_not_computed_without_rd_percentage(self):
        # Same certificate, but no R&D time allocated: the exemption doesn't apply.
        self.employee.certificate = 'doctor'
        self.version.rd_percentage = 0
        payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))
        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_32', expected=False)

    def test_withholding_tax_exemption_274_32_not_computed_for_other_certificate(self):
        # A master's degree doesn't qualify for the 274.32 (PhD/civil engineer) exemption,
        # it falls under 274.33 instead.
        self.employee.certificate = 'master'
        self.version.rd_percentage = 0.6
        payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))
        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_32', expected=False)
        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_33', expected=True)

    def test_withholding_tax_exemption_274_33_computed_for_master_researcher(self):
        # A master's degree employee assigned 60% of their time to R&D is entitled to a
        # withholding tax exemption (form 274.33) capped at 80% of that share
        # of the total withholding tax, and never more than the withholding due.
        self.employee.certificate = 'master'
        self.version.rd_percentage = 0.6
        payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))

        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_33')
        line_values = payslip._get_line_values(['PPTOTAL', 'WITHHOLDING_TAX_EX_274_33'])
        pp_total = line_values['PPTOTAL'][payslip.id]['total']
        withholding_tax_exemption = line_values['WITHHOLDING_TAX_EX_274_33'][payslip.id]['total']

        self.assertGreater(pp_total, 0, "There should be a positive withholding tax to exempt from")
        expected_withholding_tax_exemption = min(pp_total * self.version.rd_percentage * 0.8, pp_total)
        self.assertAlmostEqual(withholding_tax_exemption, expected_withholding_tax_exemption, places=2)

    def test_withholding_tax_exemption_274_33_not_computed_without_rd_percentage(self):
        # Same certificate, but no R&D time allocated: the exemption doesn't apply.
        self.employee.certificate = 'master'
        self.version.rd_percentage = 0
        payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))
        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_33', expected=False)

    def test_withholding_tax_exemption_274_33_not_computed_for_other_certificate(self):
        # A PhD/civil engineer doesn't qualify for the 274.33 (master) exemption,
        # it falls under 274.32 instead.
        self.employee.certificate = 'doctor'
        self.version.rd_percentage = 0.6
        payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))
        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_33', expected=False)
        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_32', expected=True)

    def test_withholding_tax_exemption_274_34_capped_at_quarter_of_doctor_master_total(self):
        # WITHHOLDING_TAX_EX_274_34 (bachelor exemption) only applies when at least one PhD/civil
        # engineer or master researcher is computed in the same payslip batch, and it is
        # capped at 25% of their combined WITHHOLDING_TAX_EX_274_32 + WITHHOLDING_TAX_EX_274_33 total, on
        # top of the usual 80%-of-own-withholding cap.
        doctor = self._create_researcher_employee('Researcher PhD', 'doctor', 1.0)
        bachelor = self._create_researcher_employee('Researcher Bachelor', 'bachelor', 1.0)
        doctor_payslip, bachelor_payslip = self._create_researcher_payslips(
            doctor + bachelor, datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))

        self._validate_rule_computed(doctor_payslip, 'WITHHOLDING_TAX_EX_274_32')
        self._validate_rule_computed(bachelor_payslip, 'WITHHOLDING_TAX_EX_274_34')

        doctor_withholding_tax_exemption = doctor_payslip._get_line_values(['WITHHOLDING_TAX_EX_274_32'])['WITHHOLDING_TAX_EX_274_32'][doctor_payslip.id]['total']
        bachelor_line_values = bachelor_payslip._get_line_values(['PPTOTAL', 'WITHHOLDING_TAX_EX_274_34'])
        bachelor_pp_total = bachelor_line_values['PPTOTAL'][bachelor_payslip.id]['total']
        bachelor_withholding_tax_exemption = bachelor_line_values['WITHHOLDING_TAX_EX_274_34'][bachelor_payslip.id]['total']

        expected_cap = doctor_withholding_tax_exemption / 4
        uncapped_theoretical = bachelor_pp_total * 0.8
        self.assertLess(expected_cap, uncapped_theoretical,
            "The quarter cap must be the binding constraint for this scenario")
        self.assertAlmostEqual(bachelor_withholding_tax_exemption, expected_cap, places=1,
            msg="The bachelor exemption must be capped at a quarter of the PhD/master total")

    def test_withholding_tax_exemption_274_34_not_computed_without_rd_percentage(self):
        # A bachelor with no R&D time doesn't qualify, even alongside a qualifying researcher.
        doctor = self._create_researcher_employee('Researcher PhD', 'doctor', 1.0)
        bachelor = self._create_researcher_employee('Researcher Bachelor', 'bachelor', 0)
        _, bachelor_payslip = self._create_researcher_payslips(
            doctor + bachelor, datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))
        self._validate_rule_computed(bachelor_payslip, 'WITHHOLDING_TAX_EX_274_34', expected=False)

    def test_withholding_tax_exemption_274_34_without_doctor_or_master_in_batch(self):
        # A bachelor computed on its own, without a PhD/civil engineer or master researcher
        # in the same batch, 274.34 exemption should be 0.
        bachelor = self._create_researcher_employee('Researcher Bachelor', 'bachelor', 1.0)
        bachelor_payslip, = self._create_researcher_payslips(
            bachelor, datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))
        bachelor_line_values = bachelor_payslip._get_line_values(['WITHHOLDING_TAX_EX_274_34'])
        bachelor_withholding_tax_exemption = bachelor_line_values['WITHHOLDING_TAX_EX_274_34'][bachelor_payslip.id]['total']
        self.assertAlmostEqual(bachelor_withholding_tax_exemption, 0, places=1,
            msg="The bachelor exemption must be capped at a quarter of the PhD/master total")

    def test_withholding_tax_exemption_274_34_capped_at_own_withholding_when_lower_than_quarter_cap(self):
        # With several high-earning PhD/master researchers, the quarter-of-total cap can be
        # very large. The bachelor's own exemption can never exceed 80% of their own
        # withholding tax (current_pp), regardless of how much room the quarter cap allows.
        researchers = self.env['hr.employee']
        for i in range(3):
            researchers += self._create_researcher_employee(f'Researcher {i}', 'doctor', 1.0, wage=8000)
        bachelor = self._create_researcher_employee('Researcher Bachelor', 'bachelor', 1.0, wage=1500)

        date_from, date_to = datetime.date(2019, 2, 1), datetime.date(2019, 2, 28)
        payslips = self._create_researcher_payslips(researchers + bachelor, date_from, date_to)
        doctor_payslips, bachelor_payslip = payslips[:-1], payslips[-1]

        self._validate_rule_computed(bachelor_payslip, 'WITHHOLDING_TAX_EX_274_34')

        doctor_withholding_tax_exemptions = sum(
            payslip._get_line_values(['WITHHOLDING_TAX_EX_274_32'])['WITHHOLDING_TAX_EX_274_32'][payslip.id]['total']
            for payslip in doctor_payslips
        )
        bachelor_line_values = bachelor_payslip._get_line_values(['PPTOTAL', 'WITHHOLDING_TAX_EX_274_34'])
        bachelor_pp_total = bachelor_line_values['PPTOTAL'][bachelor_payslip.id]['total']
        bachelor_withholding_tax_exemption = bachelor_line_values['WITHHOLDING_TAX_EX_274_34'][bachelor_payslip.id]['total']

        quarter_cap = doctor_withholding_tax_exemptions / 4
        own_withholding_cap = bachelor_pp_total * 0.8

        self.assertLess(own_withholding_cap, quarter_cap,
            "The bachelor's own withholding cap must be the binding constraint for this scenario")
        self.assertAlmostEqual(bachelor_withholding_tax_exemption, own_withholding_cap, places=2,
            msg="The bachelor exemption is capped at 80% of their own withholding tax, not the quarter cap")

    def test_withholding_tax_exemption_274_34_multiple_batches(self):
        doctor = self._create_researcher_employee('Researcher PhD', 'doctor', 1.0, wage=10000)
        bachelor_1 = self._create_researcher_employee('Researcher Bachelor 1', 'bachelor', 1.0, wage=3500)
        bachelor_2 = self._create_researcher_employee('Researcher Bachelor 2', 'bachelor', 1.0, wage=3500)

        date_from, date_to = datetime.date(2019, 2, 1), datetime.date(2019, 2, 28)
        doctor_payslip, bachelor_1_payslip = self._create_researcher_payslips((doctor | bachelor_1), date_from, date_to)

        doctor_withholding_tax_exemptions = doctor_payslip._get_line_values(['WITHHOLDING_TAX_EX_274_32'])['WITHHOLDING_TAX_EX_274_32'][doctor_payslip.id]['total']
        bachelor_withholding_tax_exemption = bachelor_1_payslip._get_line_values(['WITHHOLDING_TAX_EX_274_34'])['WITHHOLDING_TAX_EX_274_34'][bachelor_1_payslip.id]['total']

        self.assertAlmostEqual(doctor_withholding_tax_exemptions, 3055.99, places=2)
        self.assertAlmostEqual(bachelor_withholding_tax_exemption, 667.46, places=2)

        (doctor_payslip | bachelor_1_payslip).action_payslip_done()
        bachelor_2_payslip = self._create_researcher_payslips(bachelor_2, date_from, date_to)
        bachelor_withholding_tax_exemption = bachelor_2_payslip._get_line_values(['WITHHOLDING_TAX_EX_274_34'])['WITHHOLDING_TAX_EX_274_34'][bachelor_2_payslip.id]['total']
        self.assertAlmostEqual(bachelor_withholding_tax_exemption, 96.54, places=2)

    def test_withholding_tax_exemption_274_3x_not_computed_for_ineligible_certificate(self):
        # WITHHOLDING_TAX_EX_274_32/33/34 only apply to Bachelor/Master/Doctor/Civil Engineer degrees.
        # rd_percentage is set once while the certificate is still eligible (required by the
        # rd_percentage constraint), then the certificate alone is changed afterwards: that
        # doesn't retrigger the constraint, so it reproduces a real state where an employee
        # keeps a stale rd_percentage after losing/lacking an eligible certificate. No 274.32,
        # 274.33 or 274.34 withholding_tax_exemption should ever appear in that state, whatever the value.
        self.employee.certificate = 'doctor'
        self.version.rd_percentage = 0.6
        for certificate in [False, 'graduate', 'other']:
            with self.subTest(certificate=certificate):
                self.employee.certificate = certificate
                payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))
                self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_32', expected=False)
                self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_33', expected=False)
                self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_34', expected=False)

    def test_withholding_tax_exemption_274_74_computed_from_team_shift_premium(self):
        # All attendance hours are tagged as Team premium pay, well above the 1/3 threshold
        # of hours paid at 100%, and the legal team premium rate (2%) is met by default.
        self.employee.resource_calendar_id.attendance_ids.write({
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            'category_options_ids': [Command.set([self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_TEAM').id])],
        })
        payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))

        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_74')

        is_eligible, theoretical_exemption = self.env['l10n_be.274_xx']._get_team_shift_exemption_vals(payslip)
        self.assertTrue(is_eligible, "The employee must be eligible to the team-shift exemption")
        self.assertGreater(theoretical_exemption, 0, "The team-shift theoretical exemption must be positive")

        line_values = payslip._get_line_values(['PPTOTAL', 'WITHHOLDING_TAX_EX_274_74'])
        pp_total = line_values['PPTOTAL'][payslip.id]['total']
        withholding_tax_exemption = line_values['WITHHOLDING_TAX_EX_274_74'][payslip.id]['total']

        self.assertAlmostEqual(withholding_tax_exemption, min(pp_total, theoretical_exemption), places=2,
            msg="WITHHOLDING_TAX_EX_274_74 must equal the theoretical exemption capped at the withholding tax due")

    @freeze_time("2026-01-01")
    def test_withholding_tax_exemption_274_74_capped_without_flat_rate_tax(self):
        # The team exemption is capped at the withholding tax on the remuneration: the flat-rate tax on the
        # economic unemployment supplements is not part of that cap. Without scale tax, no exemption.
        calendar = self.resource_calendar_eco_unemployment_partial
        calendar.attendance_ids.filtered(
            lambda a: a.work_entry_type_id == self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        ).category_options_ids = [Command.set([self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_TEAM').id])]
        self.version.resource_calendar_id = calendar
        payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

        is_eligible, theoretical_exemption = self.env['l10n_be.274_xx']._get_team_shift_exemption_vals(payslip)
        self.assertTrue(is_eligible)
        self.assertGreater(theoretical_exemption, 0.0)
        line_values = payslip._get_line_values(['P.P', 'PPTOTAL', 'ECONOMIC_UNEMPLOYMENT.P.P', 'WITHHOLDING_TAX_EX_274_74'])
        self.assertEqual(line_values['P.P'][payslip.id]['total'], 0.0)
        self.assertGreater(line_values['PPTOTAL'][payslip.id]['total'], 0.0)
        self.assertAlmostEqual(
            line_values['PPTOTAL'][payslip.id]['total'], -line_values['ECONOMIC_UNEMPLOYMENT.P.P'][payslip.id]['total'], 2)
        self.assertEqual(line_values['WITHHOLDING_TAX_EX_274_74'][payslip.id]['total'], 0.0)
        self._validate_payslip(payslip)

    def _set_night_premium(self, amount):
        self.env['hr.rule.parameter.value'].create({
            'rule_parameter_id': self.env.ref('l10n_be_hr_payroll.rule_parameter_cp_200_premium_pay_night_hourly_rate').id,
            'date_from': datetime.date(2019, 1, 1),
            'parameter_value': str(amount),
        })

    def test_withholding_tax_exemption_274_75_computed_from_night_shift_premium(self):
        # All attendance hours are tagged as Night premium pay, well above the 1/3 threshold
        # of hours paid at 100%, with a night premium of 5 EUR an hour, above 12% of the
        # hourly wage of the employee.
        self._set_night_premium(5.0)
        self.employee.resource_calendar_id.attendance_ids.write({
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            'category_options_ids': [Command.set([self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_NIGHT').id])],
        })
        payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))

        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_75')

        is_eligible, theoretical_exemption = self.env['l10n_be.274_xx']._get_night_shift_exemption_vals(payslip)
        self.assertTrue(is_eligible, "The employee must be eligible to the night-shift exemption")
        self.assertGreater(theoretical_exemption, 0, "The night-shift theoretical exemption must be positive")

        line_values = payslip._get_line_values(['PPTOTAL', 'WITHHOLDING_TAX_EX_274_75'])
        pp_total = line_values['PPTOTAL'][payslip.id]['total']
        withholding_tax_exemption = line_values['WITHHOLDING_TAX_EX_274_75'][payslip.id]['total']

        self.assertAlmostEqual(withholding_tax_exemption, min(pp_total, theoretical_exemption), places=2,
            msg="WITHHOLDING_TAX_EX_274_75 must equal the theoretical exemption capped at the withholding tax due")

    def test_withholding_tax_exemption_274_74_not_computed_below_hours_threshold(self):
        # Only a quarter of the attendance hours are tagged as Team premium pay: below the
        # 1/3 threshold of hours paid at 100%, so no exemption is granted.
        attendances = self.employee.resource_calendar_id.attendance_ids
        attendances.write({'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id})
        attendances[:max(len(attendances) // 4, 1)].category_options_ids = [
            Command.set([self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_TEAM').id])
        ]
        payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))
        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_74', expected=False)

    def test_withholding_tax_exemption_274_74_excludes_274_75_on_same_payslip(self):
        # Remark from the spec: an employee eligible to the team-shift exemption cannot
        # also claim the night-shift exemption on the same payslip, even when also tagged
        # as night work.
        self.employee.resource_calendar_id.attendance_ids.write({
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            'category_options_ids': [Command.set([
                self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_TEAM').id,
                self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_NIGHT').id,
            ])],
        })
        payslip = self._generate_payslip(datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))

        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_74')
        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_75', expected=False)

    def test_withholding_tax_exemption_274_74_75_on_taxable_remuneration(self):
        # Once the premium hours reach a third of the hours paid at 100%, the team and night exemptions are 22.8% of
        # the worker's taxable remuneration (CIR 92, art. 275/5), not of the pay of the premium hours alone: two days a
        # week out of five carry the premium here.
        attendances = self.employee.resource_calendar_id.attendance_ids
        attendances.write({'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id})
        tagged = attendances.filtered(lambda attendance: attendance.dayofweek in ('0', '1'))
        declaration = self.env['l10n_be.274_xx']
        # a night premium of 5 EUR an hour, above 12% of the hourly wage of the employee
        self._set_night_premium(5.0)
        for option, month in (('PREMIUM_PAY_TEAM', 2), ('PREMIUM_PAY_NIGHT', 3)):
            with self.subTest(option=option):
                tagged.category_options_ids = [Command.set([self.env.ref(f'l10n_be_hr_payroll.{option}').id])]
                date_from = datetime.date(2019, month, 1)
                payslip = self._generate_payslip(date_from, date_from + relativedelta(day=31))
                if option == 'PREMIUM_PAY_TEAM':
                    eligible, theoretical = declaration._get_team_shift_exemption_vals(payslip)
                else:
                    eligible, theoretical = declaration._get_night_shift_exemption_vals(payslip)
                gross = payslip._get_line_values(['GROSS'])['GROSS'][payslip.id]['total']
                self.assertTrue(eligible)
                self.assertAlmostEqual(theoretical, gross * 0.228, places=2,
                    msg="The exemption applies to the whole taxable remuneration of the payslip")

    def _create_team_shift_employee(self, name, wage):
        employee = self._create_researcher_employee(name, False, 0, wage=wage)
        employee.resource_calendar_id.attendance_ids.write({
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            'category_options_ids': [Command.set([self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_TEAM').id])],
        })
        return employee

    def test_withholding_tax_exemption_274_74_mutualized_pool_capped_across_batch(self):
        # Reproduces the mechanism from the spec's example: several employees eligible to
        # the same mutualized dispensation, whose combined theoretical exemption exceeds
        # the combined withholding tax cap. The dispensation is capped on the sum of the
        # eligible employees' withholding tax, and no single employee is granted more
        # than their own withholding tax.
        # Low wages are used on purpose: at this wage level the withholding tax (the cap)
        # is proportionally lower than the flat 22.8% exemption rate (the theoretical
        # amount), so the cap - not the theoretical amount - ends up being the binding
        # constraint, as in the spec's example.
        employees = self.env['hr.employee']
        for i, wage in enumerate((1500, 1600, 1700)):
            employees += self._create_team_shift_employee(f'Team Worker {i}', wage)

        payslips = self._create_researcher_payslips(employees, datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))

        line_values = payslips._get_line_values(['PPTOTAL', 'WITHHOLDING_TAX_EX_274_74'], compute_sum=True)
        total_theoretical = sum(
            self.env['l10n_be.274_xx']._get_team_shift_exemption_vals(payslip)[1]
            for payslip in payslips
        )
        total_cap = line_values['PPTOTAL']['sum']['total']
        total_granted = line_values['WITHHOLDING_TAX_EX_274_74']['sum']['total']

        self.assertLess(total_cap, total_theoretical,
            "The withholding tax cap must be the binding constraint for this scenario")
        self.assertAlmostEqual(total_granted, total_cap, places=2,
            msg="The mutualized dispensation must be capped on the sum of the eligible employees' withholding tax")
        for payslip in payslips:
            granted = line_values['WITHHOLDING_TAX_EX_274_74'][payslip.id]['total']
            self.assertLessEqual(granted, line_values['PPTOTAL'][payslip.id]['total'] + 0.01,
                "No single employee can be granted more than their own withholding tax")

    def test_withholding_tax_exemption_274_74_multiple_batches(self):
        # Reproduces the spec's second part: a later payrun/payslip within the same month
        # must take into account the mutualized dispensation already granted on previously
        # validated payslips, and only distribute what's left in the pool.
        low_wage_employee = self._create_team_shift_employee('Team Worker 1', 1500)
        high_wage_employee = self._create_team_shift_employee('Team Worker 2', 8000)

        date_from, date_to = datetime.date(2019, 2, 1), datetime.date(2019, 2, 28)
        first_payslip, = self._create_researcher_payslips(low_wage_employee, date_from, date_to)
        first_payslip.action_payslip_done()

        first_line_values = first_payslip._get_line_values(['PPTOTAL', 'WITHHOLDING_TAX_EX_274_74'])
        first_pp_total = first_line_values['PPTOTAL'][first_payslip.id]['total']
        first_withholding_tax_exemption = first_line_values['WITHHOLDING_TAX_EX_274_74'][first_payslip.id]['total']
        self.assertAlmostEqual(first_withholding_tax_exemption, first_pp_total, places=2,
            msg="Alone in the pool, the first employee's dispensation is only capped by their own withholding tax")

        second_payslip, = self._create_researcher_payslips(high_wage_employee, date_from, date_to)
        second_line_values = second_payslip._get_line_values(['PPTOTAL', 'WITHHOLDING_TAX_EX_274_74'])
        second_pp_total = second_line_values['PPTOTAL'][second_payslip.id]['total']
        second_withholding_tax_exemption = second_line_values['WITHHOLDING_TAX_EX_274_74'][second_payslip.id]['total']

        second_theoretical = self.env['l10n_be.274_xx']._get_team_shift_exemption_vals(second_payslip)[1]
        total_cap = first_pp_total + second_pp_total
        first_theoretical = self.env['l10n_be.274_xx']._get_team_shift_exemption_vals(first_payslip)[1]
        expected_group_dispensation = min(first_theoretical + second_theoretical, total_cap)
        expected_second_withholding_tax_exemption = min(second_pp_total, expected_group_dispensation - first_withholding_tax_exemption)

        self.assertAlmostEqual(second_withholding_tax_exemption, expected_second_withholding_tax_exemption, places=2,
            msg="The second payrun's dispensation is the remaining pool room, capped at its own withholding tax")

    def test_withholding_tax_exemption_274_33_and_274_74_combined_exemptions_capped_by_withholding(self):
        # An employee can be eligible to several withholding tax exemptions at once, e.g.
        # a Master researcher (274.33) also doing Team-shift work (274.74). 274.33 is
        # computed first (round 1) and already consumes part of the withholding tax, so
        # 274.74 (round 3) can only claim what's left of it, even though its own
        # theoretical amount (uncapped) would be higher on its own.
        # e.g. 1000 of withholding tax, 800 already granted by the master exemption:
        # only 200 is left for the team exemption, whatever its theoretical amount is.
        employee = self._create_researcher_employee('Researcher Master Team', 'master', 1.0, wage=8000)
        employee.resource_calendar_id.attendance_ids.write({
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            'category_options_ids': [Command.set([self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_TEAM').id])],
        })
        payslip, = self._create_researcher_payslips(employee, datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))

        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_33')
        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_74')

        line_values = payslip._get_line_values(['PPTOTAL', 'WITHHOLDING_TAX_EX_274_33', 'WITHHOLDING_TAX_EX_274_74'])
        pp_total = line_values['PPTOTAL'][payslip.id]['total']
        master_withholding_tax_exemption = line_values['WITHHOLDING_TAX_EX_274_33'][payslip.id]['total']
        team_withholding_tax_exemption = line_values['WITHHOLDING_TAX_EX_274_74'][payslip.id]['total']

        # Withholding tax due: 2961.31. The master exemption claims 80% of it (rd_percentage
        # is 100%): 2369.05. The team exemption's own theoretical amount (22.8% of the wage
        # tied to the team-tagged hours, i.e. 22.8% of 8000) is 1824.00, well above what's
        # left of the withholding tax (2961.31 - 2369.05 = 592.26), so it gets capped there
        # instead of granting the full 1824.00.
        self.assertAlmostEqual(pp_total, 2961.31, places=2)
        self.assertAlmostEqual(master_withholding_tax_exemption, 2369.05, places=2)
        self.assertAlmostEqual(team_withholding_tax_exemption, 592.26, places=2,
            msg="The team exemption must be capped at what's left of the withholding tax (592.26), not its own theoretical amount (1824.00)")
        self.assertLessEqual(master_withholding_tax_exemption + team_withholding_tax_exemption, pp_total + 0.01,
            "The combined exemptions on a single payslip can never exceed its withholding tax")

    def test_withholding_tax_exemption_274_34_and_274_74_combined_exemptions_capped_by_withholding(self):
        # 274.34 (bachelor, round 2) is computed before 274.74 (team, round 3): the bachelor's
        # own exemption must already be reflected in TAX_EXEMPTION_GRANTED before the team
        # exemption gets capped, not just the round-1 274.32/33 exemptions (unlike the
        # 274.33 + 274.74 case above, this exercises accumulation across two prior rounds).
        doctors = self.env['hr.employee']
        for i in range(3):
            doctors += self._create_researcher_employee(f'Researcher Doctor {i}', 'doctor', 1.0, wage=8000)
        bachelor = self._create_researcher_employee('Researcher Bachelor Team', 'bachelor', 1.0, wage=1500)
        # Give the bachelor their own calendar copy so tagging it doesn't also make the
        # doctors (who share the class-level calendar) eligible for the team exemption.
        bachelor_calendar = self.resource_calendar_38_hours_per_week.copy()
        bachelor.resource_calendar_id = bachelor_calendar
        bachelor_calendar.attendance_ids.write({
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            'category_options_ids': [Command.set([self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_TEAM').id])],
        })

        date_from, date_to = datetime.date(2019, 2, 1), datetime.date(2019, 2, 28)
        payslips = self._create_researcher_payslips(doctors + bachelor, date_from, date_to)
        bachelor_payslip = payslips[-1]

        self._validate_rule_computed(bachelor_payslip, 'WITHHOLDING_TAX_EX_274_34')
        self._validate_rule_computed(bachelor_payslip, 'WITHHOLDING_TAX_EX_274_74')

        line_values = bachelor_payslip._get_line_values(['PPTOTAL', 'WITHHOLDING_TAX_EX_274_34', 'WITHHOLDING_TAX_EX_274_74'])
        pp_total = line_values['PPTOTAL'][bachelor_payslip.id]['total']
        bachelor_withholding_tax_exemption = line_values['WITHHOLDING_TAX_EX_274_34'][bachelor_payslip.id]['total']
        team_withholding_tax_exemption = line_values['WITHHOLDING_TAX_EX_274_74'][bachelor_payslip.id]['total']

        # Withholding tax due: 72.92. The high-wage doctors make the quarter-of-32/33 cap
        # very large, so the bachelor's own 80%-of-withholding cap is what binds: 58.34.
        # The team exemption's own theoretical amount (22.8% of the wage tied to the
        # team-tagged hours, i.e. 22.8% of 1500 = 342.00) is far above what's left of the
        # withholding tax (72.92 - 58.34 = 14.58), so it gets capped there instead.
        self.assertAlmostEqual(pp_total, 72.92, places=2)
        self.assertAlmostEqual(bachelor_withholding_tax_exemption, 58.34, places=2)
        self.assertAlmostEqual(team_withholding_tax_exemption, 14.58, places=2,
            msg="The team exemption must be capped at what's left of the withholding tax (14.58) after the bachelor exemption, not its own theoretical amount (342.00)")
        self.assertLessEqual(bachelor_withholding_tax_exemption + team_withholding_tax_exemption, pp_total + 0.01,
            "The combined exemptions on a single payslip can never exceed its withholding tax")

    def test_withholding_tax_exemption_274_74_team_and_contteam_combined_hours_exclude_274_75(self):
        # Team and Continuous Team hours are pooled together to check the 1/3 threshold for
        # 274.74: neither category alone crosses it here, but combined they do. Once 274.74
        # is eligible, 274.75 (Night) is excluded on the same payslip even though the
        # Night-tagged hours alone would cross their own 1/3 threshold.
        employee = self._create_researcher_employee('Researcher Team Contteam Night', False, 0, wage=3000)
        calendar = self.resource_calendar_38_hours_per_week.copy()
        employee.resource_calendar_id = calendar
        attendances = calendar.attendance_ids.sorted(lambda a: (a.dayofweek, a.hour_from))
        attendances.write({'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id})
        attendances[0:2].category_options_ids = [Command.set([self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_TEAM').id])]
        attendances[2:4].category_options_ids = [Command.set([self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_CONTTEAM').id])]
        attendances[4:8].category_options_ids = [Command.set([self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_NIGHT').id])]

        payslip, = self._create_researcher_payslips(employee, datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))

        team_hours = payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_TEAM')
        contteam_hours = payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_CONTTEAM')
        night_hours = payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_NIGHT')
        full_pay_hours = payslip._get_l10n_be_full_pay_worked_hours()

        # 30.4h of Team and 30.4h of Continuous Team over 152h worked this month: each is
        # below the 1/3 (50.67h) eligibility threshold on its own, but pooled together
        # (60.8h) they cross it. The 60.8h of Night hours would cross that same threshold
        # on their own too, proving the exclusion below is really about 274.74 eligibility,
        # not a lack of Night hours.
        self.assertAlmostEqual(team_hours, 30.40, places=2)
        self.assertAlmostEqual(contteam_hours, 30.40, places=2)
        self.assertAlmostEqual(night_hours, 60.80, places=2)
        self.assertAlmostEqual(full_pay_hours, 152.00, places=2)
        self.assertLess(team_hours, full_pay_hours / 3, "Team hours alone must be below the 1/3 threshold")
        self.assertLess(contteam_hours, full_pay_hours / 3, "Continuous Team hours alone must be below the 1/3 threshold")
        self.assertGreaterEqual(team_hours + contteam_hours, full_pay_hours / 3,
            "Team and Continuous Team hours combined must reach the 1/3 threshold")
        self.assertGreaterEqual(night_hours, full_pay_hours / 3,
            "Night hours alone must also reach the 1/3 threshold, to prove exclusion below isn't just a lack of hours")

        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_74')
        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_75', expected=False)

        line_values = payslip._get_line_values(['PPTOTAL', 'WITHHOLDING_TAX_EX_274_74'])
        pp_total = line_values['PPTOTAL'][payslip.id]['total']
        team_withholding_tax_exemption = line_values['WITHHOLDING_TAX_EX_274_74'][payslip.id]['total']

        # Withholding tax due: 675.44, above the exemption, so it isn't the binding constraint
        # here. The granted amount is the taxable remuneration (2712.59) at the Continuous Team
        # rate (25%) in the share of its hours in all the hours of the month (30.4 / 152 = 20%),
        # at the Team rate (22.8%) on the rest: 2712.59 * (20% * 25% + 80% * 22.8%) = 630.41.
        self.assertAlmostEqual(pp_total, 675.44, places=2)
        self.assertAlmostEqual(team_withholding_tax_exemption, 630.41, places=2,
            msg="274.74 must grant the Continuous Team rate (25%) in the share of its hours in all the hours")

    def test_withholding_tax_exemption_274_74_third_time_without_public_holidays(self):
        # The third-time rule of the team exemption counts the paid hours of the period without the public holidays
        # (nor the working time reduction days, the recovered overtime and the guaranteed salary from the 2nd week of
        # sickness): the team hours (Mondays and Tuesday mornings) are below a third of the paid hours of the month,
        # but reach a third of them without its three public holidays.
        employee = self._create_researcher_employee('Team Worker With Public Holidays', False, 0, wage=3000)
        calendar = self.resource_calendar_38_hours_per_week.copy()
        employee.resource_calendar_id = calendar
        attendances = calendar.attendance_ids.sorted(lambda a: (a.dayofweek, a.hour_from))
        attendances.write({'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id})
        attendances[0:3].category_options_ids = [Command.set([self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_TEAM').id])]
        self.env['resource.calendar.leaves'].create({
            'name': "Public Holidays",
            'calendar_id': calendar.id,
            'company_id': self.env.company.id,
            'resource_id': employee.resource_id.id,
            'date_from': datetime.datetime(2019, 2, 6, 6, 0, 0),
            'date_to': datetime.datetime(2019, 2, 8, 17, 0, 0),
            'count_as': "absence",
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id,
        })

        payslip, = self._create_researcher_payslips(employee, datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))

        paid_hours = sum(payslip.worked_days_line_ids.mapped('number_of_hours'))
        public_holiday_hours = sum(
            payslip.worked_days_line_ids.filtered(lambda line: line.code == '006.00').mapped('number_of_hours'))
        team_hours = payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_TEAM')
        self.assertAlmostEqual(public_holiday_hours, 22.8, places=2)
        self.assertAlmostEqual(payslip._get_l10n_be_full_pay_worked_hours(), paid_hours - public_holiday_hours, places=2)
        self.assertLess(team_hours, paid_hours / 3)
        self.assertGreaterEqual(team_hours, (paid_hours - public_holiday_hours) / 3)
        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_74')

    def _create_team_worker_with_time_off(self, name, team_attendances_count, time_off_periods):
        """A worker of 38 hours a week whose first attendances of the week are in team, with time off over the given
        (date_from, date_to, work entry type xmlid) periods, and his payslip of February 2019."""
        employee = self._create_researcher_employee(name, False, 0, wage=3000)
        calendar = self.resource_calendar_38_hours_per_week.copy()
        employee.resource_calendar_id = calendar
        attendances = calendar.attendance_ids.sorted(lambda a: (a.dayofweek, a.hour_from))
        attendances.write({'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id})
        attendances[:team_attendances_count].category_options_ids = [
            Command.set([self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_TEAM').id])]
        self.env['resource.calendar.leaves'].create([{
            'name': "Time Off",
            'calendar_id': calendar.id,
            'company_id': self.env.company.id,
            'resource_id': employee.resource_id.id,
            'date_from': date_from,
            'date_to': date_to,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref(work_entry_type_xmlid).id,
        } for date_from, date_to, work_entry_type_xmlid in time_off_periods])
        payslip, = self._create_researcher_payslips(employee, datetime.date(2019, 2, 1), datetime.date(2019, 2, 28))
        return payslip

    def test_withholding_tax_exemption_274_74_third_time_with_time_off_on_team_days(self):
        # The paid time off counts as team hours in the third-time rule on the days the worker would have worked in
        # team, although the team premium isn't paid on it. Team on Mondays and Tuesdays (60.8 of the 152 hours of
        # February 2019), two weeks of holidays (11-22/02, 4 team days) and a public holiday on a team day (04/02,
        # neither in the team hours nor in the total): 22.8 worked team hours and 30.4 hours of holidays on team days
        # reach a third of the 144.4 hours, the 22.8 worked team hours alone don't.
        payslip = self._create_team_worker_with_time_off("Team Worker On Holidays", 4, [
            (datetime.datetime(2019, 2, 11, 6, 0, 0), datetime.datetime(2019, 2, 22, 17, 0, 0), 'hr_work_entry.be_work_entry_type_legal_leave'),
            (datetime.datetime(2019, 2, 4, 6, 0, 0), datetime.datetime(2019, 2, 4, 17, 0, 0), 'hr_work_entry.l10n_be_work_entry_type_bank_holiday'),
        ])

        worked_days = payslip.worked_days_line_ids
        team_premium = self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_TEAM')
        self.assertAlmostEqual(sum(worked_days.filtered(lambda line: line.code == '016.00').mapped('number_of_hours')), 76.0, places=2)
        self.assertAlmostEqual(sum(worked_days.filtered(lambda line: line.code == '006.00').mapped('number_of_hours')), 7.6, places=2)
        # The premium is only paid on the worked team hours
        self.assertAlmostEqual(
            sum(worked_days.filtered(lambda line: team_premium in line.category_options_ids).mapped('number_of_hours')), 22.8, places=2)
        self.assertAlmostEqual(payslip._get_l10n_be_category_option_leave_hours('PREMIUM_PAY_TEAM'), 30.4, places=2)
        self.assertAlmostEqual(payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_TEAM'), 53.2, places=2)
        self.assertAlmostEqual(payslip._get_l10n_be_full_pay_worked_hours(), 144.4, places=2)
        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_74')

    def test_withholding_tax_exemption_274_74_third_time_with_time_off_on_other_days(self):
        # The time off on the days the worker would not have worked in team doesn't count as team hours: team on
        # Mondays (30.4 of the 152 hours of February 2019), holidays on Wednesdays to Fridays of two weeks.
        payslip = self._create_team_worker_with_time_off("Team Worker On Holidays Other Days", 2, [
            (datetime.datetime(2019, 2, 13, 6, 0, 0), datetime.datetime(2019, 2, 15, 17, 0, 0), 'hr_work_entry.be_work_entry_type_legal_leave'),
            (datetime.datetime(2019, 2, 20, 6, 0, 0), datetime.datetime(2019, 2, 22, 17, 0, 0), 'hr_work_entry.be_work_entry_type_legal_leave'),
        ])

        self.assertAlmostEqual(sum(
            payslip.worked_days_line_ids.filtered(lambda line: line.code == '016.00').mapped('number_of_hours')), 45.6, places=2)
        self.assertAlmostEqual(payslip._get_l10n_be_category_option_leave_hours('PREMIUM_PAY_TEAM'), 0.0, places=2)
        self.assertAlmostEqual(payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_TEAM'), 30.4, places=2)
        self.assertAlmostEqual(payslip._get_l10n_be_full_pay_worked_hours(), 152.0, places=2)
        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_74', expected=False)

    def test_withholding_tax_exemption_274_74_third_time_and_split_rubrics(self):
        # The rubrics of the third-time rule (circular 11/2021) and of the split of the taxable remuneration (from
        # 2025) as Partena gives them: the recoverable overtime (026, the premium only, at a rate of 0) counts in
        # both, the public holiday during temporary unemployment (086.00) in both, the carried over workers' holidays
        # (142.24) and the paid rubrics from 108 (165.00) in neither, the guaranteed salary from the 2nd week of
        # sickness (072) in the third-time rule until 2024 only, the premium rubrics (042-045) in neither.
        payslip_2025 = self.env['hr.payslip'].new({'date_from': datetime.date(2025, 3, 1), 'date_to': datetime.date(2025, 3, 31)})
        payslip_2024 = self.env['hr.payslip'].new({'date_from': datetime.date(2024, 3, 1), 'date_to': datetime.date(2024, 3, 31)})
        for code, rate, third_time_2024, third_time_2025, split in [
            ('002.00', 1.0, True, True, True),
            ('026.00', 0.0, True, True, True),
            ('086.00', 0.8588, True, True, True),
            ('006.00', 1.0, False, False, True),
            ('006.48', 2.0, True, True, True),
            ('019.00', 1.0, False, False, True),
            ('046.00', 1.0, False, False, True),
            ('039.23', 1.0, True, True, False),
            ('072.00', 1.0, True, False, False),
            ('082.00', 0.8588, True, False, False),
            ('142.00', 0.0, True, True, False),
            ('142.20', 1.0, True, True, False),
            ('142.24', 0.0, False, False, False),
            ('165.00', 1.0, False, False, False),
            ('044.00', 1.0, False, False, False),
            ('158.00', 0.0, False, False, False),
        ]:
            work_entry_type = self.env['hr.work.entry.type'].new({'name': code, 'code': code, 'amount_rate': rate})
            with self.subTest(code=code):
                self.assertEqual(payslip_2024._l10n_be_is_shift_exemption_work_entry_type(work_entry_type), third_time_2024)
                self.assertEqual(payslip_2025._l10n_be_is_shift_exemption_work_entry_type(work_entry_type), third_time_2025)
                self.assertEqual(payslip_2025._l10n_be_is_shift_exemption_taxable_work_entry_type(work_entry_type), split)

    def test_withholding_tax_exemption_274_74_contteam_share_on_taxable_hours(self):
        # Since 2025, the taxable remuneration (and its withholding tax) is split between the continuous team rate (25%)
        # and the team rate (22.8%) on the hours entering the taxable remuneration, not on the hours of the third-time
        # rule (which decides the eligibility, unchanged): the public holidays count (in the continuous team hours on
        # a continuous team day), the workers' annual holidays (142, paid by the holiday fund) don't. Continuous team on
        # Mondays and Tuesdays (68.4 of the 159.6 hours of June 2025), team on Wednesdays and Thursdays (60.8 hours),
        # Whit Monday (09/06) on a continuous team day, workers' holidays on Wednesday 11, Thursday 12 (team days) and
        # Tuesday 24 (continuous team day).
        employee = self._create_researcher_employee('Continuous Team Worker', False, 0, wage=3000)
        calendar = self.resource_calendar_38_hours_per_week.copy()
        employee.resource_calendar_id = calendar
        attendances = calendar.attendance_ids.sorted(lambda a: (a.dayofweek, a.hour_from))
        attendances.write({'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id})
        attendances[0:4].category_options_ids = [Command.set([self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_CONTTEAM').id])]
        attendances[4:8].category_options_ids = [Command.set([self.env.ref('l10n_be_hr_payroll.PREMIUM_PAY_TEAM').id])]
        self.env['resource.calendar.leaves'].create([{
            'name': "Time Off",
            'calendar_id': calendar.id,
            'company_id': self.env.company.id,
            'resource_id': employee.resource_id.id,
            'date_from': date_from,
            'date_to': date_to,
            'count_as': "absence",
            'work_entry_type_id': self.env.ref(work_entry_type_xmlid).id,
        } for date_from, date_to, work_entry_type_xmlid in [
            (datetime.datetime(2025, 6, 9, 6, 0, 0), datetime.datetime(2025, 6, 9, 17, 0, 0), 'hr_work_entry.l10n_be_work_entry_type_bank_holiday'),
            (datetime.datetime(2025, 6, 11, 6, 0, 0), datetime.datetime(2025, 6, 12, 17, 0, 0), 'hr_work_entry.l10n_be_work_entry_type_worker_time_off'),
            (datetime.datetime(2025, 6, 24, 6, 0, 0), datetime.datetime(2025, 6, 24, 17, 0, 0), 'hr_work_entry.l10n_be_work_entry_type_worker_time_off'),
        ]])
        payslip, = self._create_researcher_payslips(employee, datetime.date(2025, 6, 1), datetime.date(2025, 6, 30))

        worked_days = payslip.worked_days_line_ids
        self.assertAlmostEqual(sum(worked_days.filtered(lambda line: line.code == '006.00').mapped('number_of_hours')), 7.6, places=2)
        self.assertAlmostEqual(sum(worked_days.filtered(lambda line: line.code == '142.00').mapped('number_of_hours')), 22.8, places=2)

        # The third-time rule: the workers' holidays count (on a team or continuous team day as such), not the public
        # holiday. 45.6 team and 60.8 continuous team hours reach a third of the 152 hours: eligible.
        self.assertAlmostEqual(payslip._get_l10n_be_full_pay_worked_hours(), 152.0, places=2)
        self.assertAlmostEqual(payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_TEAM'), 60.8, places=2)
        self.assertAlmostEqual(payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_CONTTEAM'), 60.8, places=2)
        self.assertTrue(self.env['l10n_be.274_xx']._is_team_exemption_eligible(payslip))

        # The split: the public holiday counts, on a continuous team day, the workers' holidays don't. 60.8 continuous
        # team hours (53.2 worked, 7.6 of public holiday) over the 136.8 taxable hours (159.6 - 22.8 of holidays),
        # 44.44% instead of the 40% (60.8 / 152) of the hours of the third-time rule.
        taxable_filter = payslip._l10n_be_is_shift_exemption_taxable_work_entry_type
        self.assertAlmostEqual(payslip._get_l10n_be_full_pay_worked_hours(taxable_filter), 136.8, places=2)
        self.assertAlmostEqual(payslip._get_l10n_be_category_option_hours('PREMIUM_PAY_CONTTEAM', taxable_filter), 60.8, places=2)
        self.assertAlmostEqual(payslip._get_l10n_be_contteam_share(), 60.8 / 136.8, places=4)

        # The theoretical exemption: 2274.63 * (44.44% * 25% + 55.56% * 22.8%) = 540.86 (538.63 with the 40% share of
        # the third-time rule), capped to the withholding tax (423.06) on the payslip.
        self._validate_rule_computed(payslip, 'WITHHOLDING_TAX_EX_274_74')
        line_values = payslip._get_line_values(['GROSS', 'PPTOTAL', 'T_WITHHOLDING_TAX_EX_274_74', 'WITHHOLDING_TAX_EX_274_74'])
        self.assertAlmostEqual(line_values['GROSS'][payslip.id]['total'], 2274.63, places=2)
        self.assertAlmostEqual(line_values['T_WITHHOLDING_TAX_EX_274_74'][payslip.id]['total'], 540.86, places=2)
        self.assertAlmostEqual(line_values['PPTOTAL'][payslip.id]['total'], 423.06, places=2)
        self.assertAlmostEqual(line_values['WITHHOLDING_TAX_EX_274_74'][payslip.id]['total'], 423.06, places=2)

    def test_keyed_withholding_tax(self):
        # The withholding tax keyed on the payslip (P.P input) is the tax of the payslip: the reductions of the scale,
        # computed on the tax of the scale (the fiscal work bonus P.P.DED here), don't apply on top of it
        for inputs in [{}, {'P.P': 150}]:
            payslip = self._generate_payslip(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31), input_values=inputs)
            self._validate_payslip(payslip)

    def test_gpa_full_time_credit_period(self):
        # Full suspension still occupies calendar time, even with zero working hours.
        # Keep the largest-period deduction and the smaller-period hourly valuation.
        for leave_start, leave_end, expected in [
            (1, 9, 3000.0),
            (24, 31, 2820.0),
            (10, 14, 3000.0),
            (1, 23, 1080.0),
        ]:
            with self.subTest(leave_start=leave_start, leave_end=leave_end):
                employee = self.env['hr.employee'].create({
                    'name': 'Full suspension employee',
                    'company_id': self.env.company.id,
                    'date_version': datetime.date(2025, 3, 1),
                    'contract_date_start': datetime.date(2025, 3, 1),
                    'wage': 3900.0,
                    'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
                    'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
                    'structure_type_id': self.version.structure_type_id.id,
                })
                version = employee.version_id
                if leave_start == 1:
                    leave_version = version
                else:
                    leave_version = version.copy({'date_version': datetime.date(2025, 3, leave_start)})
                leave_version.write({
                    'resource_calendar_id': self.resource_calendar_0_hours_per_week.id,
                    'wage': 0,
                })
                if leave_end < 31:
                    version.copy({
                        'date_version': datetime.date(2025, 3, leave_end + 1),
                        'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
                        'wage': 3900.0,
                    })
                payslip = self.env['hr.payslip'].create({
                    'employee_id': employee.id,
                    'date_from': datetime.date(2025, 3, 1),
                    'date_to': datetime.date(2025, 3, 31),
                })
                payslip.compute_sheet()
                self.assertAlmostEqual(sum(payslip.worked_days_line_ids.mapped('amount')), expected, places=2)
                self.assertAlmostEqual(payslip.line_ids.filtered(lambda line: line.code == 'BASIC').total, expected, places=2)

    def test_gpa_partial_time_credit_period(self):
        # A partial time credit from Wednesday 26 March 2025 (Wednesday off) covers 30.4 hours of the full-time month,
        # 7.6 of them unpaid: the largest period gives up those 30.4 hours, not only the 22.8 worked ones scaled to
        # the weekly average, and the month pays the wage less one day of time credit: 3,900 - 7.6 x 3,900 x 3 / (13 x
        # 38) = 3,720
        employee = self.env['hr.employee'].create({
            'name': 'Partial time credit employee',
            'company_id': self.env.company.id,
            'date_version': datetime.date(2025, 3, 1),
            'contract_date_start': datetime.date(2025, 3, 1),
            'wage': 3900.0,
            'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'structure_type_id': self.version.structure_type_id.id,
        })
        employee.version_id.copy({
            'date_version': datetime.date(2025, 3, 26),
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
        })
        payslip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'date_from': datetime.date(2025, 3, 1),
            'date_to': datetime.date(2025, 3, 31),
        })
        payslip.compute_sheet()
        self.assertAlmostEqual(payslip.line_ids.filtered(lambda line: line.code == 'BASIC').total, 3720.0, places=2)

    def test_gpa_propatisation(self):
        calendar_20h = self.env['resource.calendar'].create({
            'name': "Test Calendar: 20 Hours/Week",
            'company_id': self.env.company.id,
            'hours_per_day': 4.0,
            'full_time_required_hours': 38.0,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id
            }) for dayofweek, hour_from, hour_to in [
                ("0", 8.0, 12.0),
                ("1", 8.0, 12.0),
                ("2", 8.0, 12.0),
                ("3", 8.0, 12.0),
                ("4", 8.0, 12.0),
            ]],
        })

        calendar_30h = self.env['resource.calendar'].create({
            'name': "Test Calendar: 30 Hours/Week",
            'company_id': self.env.company.id,
            'hours_per_day': 6.0,
            'full_time_required_hours': 38.0,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id
            }) for dayofweek, hour_from, hour_to in [
                ("0", 8.0, 14.0),
                ("1", 8.0, 14.0),
                ("2", 8.0, 14.0),
                ("3", 8.0, 14.0),
                ("4", 8.0, 14.0),
            ]],
        })

        self.version.write({
            'date_version': datetime.date(2025, 3, 1),
            'contract_date_start': datetime.date(2025, 3, 1),
            'wage': 3800.0,
            'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
        })

        self.version.copy({
            'date_version': datetime.date(2025, 3, 10),
            'contract_date_start': datetime.date(2025, 3, 1),
            'wage': 2000.0,
            'resource_calendar_id': calendar_20h.id,
        })

        self.version.copy({
            'date_version': datetime.date(2025, 3, 24),
            'contract_date_start': datetime.date(2025, 3, 1),
            'wage': 3000.0,
            'resource_calendar_id': calendar_30h.id,
        })

        payslip = self._generate_payslip(datetime.date(2025, 3, 1), datetime.date(2025, 3, 31))
        # Shorter periods are valorized with their own hourly rates:
        #   version 1: 38h * (3800 * 3 / (38 * 13)) = 876.92
        #   version 3: 36h * (3000 * 3 / (30 * 13)) = 830.77
        # The longest period uses the deduction method:
        #   version 1 theoretical hours = 38 * 20 / 38 = 20
        #   version 3 theoretical hours = 36 * 20 / 30 = 24
        #   version 2 amount = wage - shoter periods theoretical hours * hourly rate = 2000 - (20 + 24) * (2000 * 3 / (20 * 13))
        self._validate_payslip(payslip)

    def test_double_holidays(self):
        self.version.write({
            'transport_mode_car': False,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        self.assertEqual(len(payslip.worked_days_line_ids), 0)

        self._validate_payslip(payslip)

    def test_double_holiday_variable_with_sunday_premiums(self):
        """ The Sunday and public holiday premiums of the reference period are part of the variable remuneration of
        the double holiday pay, as the social secretariats compute it, not of the other averages of the variable
        revenues (13th month, notice, loss on commission) """
        employee = self.employee
        monthly = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': datetime.date(2021, 3, 1),
            'date_to': datetime.date(2021, 3, 31),
        })
        monthly.compute_sheet()
        sunday_premium = self.env['hr.salary.rule'].search([('code', '=', 'PREMSUN')], limit=1)
        self.env['hr.payslip.line'].create({
            'slip_id': monthly.id,
            'salary_rule_id': sunday_premium.id,
            'name': sunday_premium.name,
            'code': 'PREMSUN',
            'amount': 120.0,
            'quantity': 1.0,
            'rate': 100.0,
            'total': 120.0,
            'employee_id': employee.id,
            'version_id': self.version.id,
        })
        monthly.action_payslip_done()

        double_holiday = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30),
        })
        reference = double_holiday.with_context(variable_revenue_date_from=double_holiday.date_from)
        # 120 EUR of premiums over the 12 months of the reference period
        self.assertAlmostEqual(reference._get_last_year_average_variable_revenues(included_codes=('PREMSUN', 'PREMHOL')), 10.0, places=2)
        self.assertEqual(reference._get_last_year_average_variable_revenues(), 0.0)
        self.assertGreater(double_holiday._get_l10n_be_double_holiday_variable_revenues(), 0.0)

    def test_double_holiday_hourly_wage(self):
        # The double holiday pay of an employee paid by the hour is computed on his monthly wage: the hourly wage
        # times the hours of a week times 13 / 3
        self.version.write({'transport_mode_car': False})
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30),
        })
        hours_per_week = self.version._l10n_be_get_hours_per_week(2021)
        self.version.write({'wage_type': 'monthly', 'wage': 20 * hours_per_week * 13 / 3})
        monthly_double_pay = payslip._l10n_be_get_paid_double_holiday()
        self.assertGreater(monthly_double_pay, 0)
        self.version.write({'wage_type': 'hourly', 'hourly_wage': 20})
        self.assertAlmostEqual(payslip._l10n_be_get_paid_double_holiday(), monthly_double_pay, places=2)

    def test_double_holiday_no_right(self):
        self.version.contract_date_start = datetime.date(2021, 1, 1)
        self.version.date_version = datetime.date(2021, 1, 1)

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        self.assertEqual(len(payslip.worked_days_line_ids), 0)

        self._validate_payslip(payslip)

    def test_double_holidays_excluded_versions(self):
        # No double holiday pay for the individual vocational trainings (PFI), the students, the former workers paid a
        # supplementary indemnity (RCC) and the workers of a foreign employer without a place of business in Belgium
        # (employer category 212): left out of the pay run, and a payslip added by hand pays nothing
        payrun = self.env['hr.payslip.run'].create({
            'name': 'Double Holiday Pay',
            'date_start': datetime.date(2021, 6, 1),
            'date_end': datetime.date(2021, 6, 30),
            'company_id': self.env.company.id,
            'structure_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
        })
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        rcc_worker_code = self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00879')
        cases = [
            ({}, True),
            ({'l10n_be_dimona_category': False, 'l10n_be_worker_code_id': False}, True),
            ({'l10n_be_dimona_category': 'ivt'}, False),
            ({'l10n_be_dimona_category': 'stu'}, False),
            ({'l10n_be_worker_code_id': rcc_worker_code.id}, False),
        ]
        regular_values = {
            'l10n_be_dimona_category': self.version.l10n_be_dimona_category,
            'l10n_be_worker_code_id': self.version.l10n_be_worker_code_id.id,
        }
        for values, has_double_holiday_pay in cases:
            with self.subTest(values=values):
                self.version.write({**regular_values, **values})
                self.assertEqual(self.employee in payrun._get_valid_versions().employee_id, has_double_holiday_pay)
                self.assertEqual(bool(payslip._l10n_be_get_paid_double_holiday()), has_double_holiday_pay)

        self.version.write(regular_values)
        payroll_config = self.version.payroll_config_id
        for employer_category, has_double_holiday_pay in [
            (self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00212'), False),
            # A payroll config without employer category keeps the double holiday pay.
            (self.env['l10n.be.employer.category'], True),
            (self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00010'), True),
        ]:
            with self.subTest(employer_category=employer_category.dmfa_code):
                payroll_config.l10n_be_employer_category_id = employer_category
                self.assertEqual(self.employee in payrun._get_valid_versions().employee_id, has_double_holiday_pay)
                self.assertEqual(bool(payslip._l10n_be_get_paid_double_holiday()), has_double_holiday_pay)

    def test_double_holidays_months_after_individual_vocational_training(self):
        # Hired on 01/07/2020 after an individual vocational training (PFI): only the months of the employment
        # contract count
        self.version.write({
            'transport_mode_car': False,
            'l10n_be_dimona_category': 'ivt',
        })
        employment_version = self.employee.create_version({
            'date_version': datetime.date(2020, 7, 1),
            'l10n_be_dimona_category': 'oth',
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': employment_version.id,
            'company_id': self.env.company.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        double_holiday_pay, explanation = payslip._l10n_be_get_paid_double_holiday(get_explanation=True)
        self.assertEqual(explanation['months'], 6)
        self.assertAlmostEqual(payslip._get_line_values(['DOUBLE'])['DOUBLE'][payslip.id]['total'], double_holiday_pay * 0.85, places=2)

    def test_double_holidays_incomplete_year_full_time(self):
        self.version.write({
            'contract_date_start': datetime.date(2020, 3, 15),
            'transport_mode_car': False,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holidays_complete_year_credit_time(self):
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week,
            'work_time_rate': 1.0,
            'wage': 2120.0,
            'transport_mode_car': False,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holidays_incomplete_year_credit_time(self):
        self.version.write({
            'contract_date_start': datetime.date(2020, 3, 15),
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week,
            'work_time_rate': 1.0,
            'wage': 2120.0,
            'transport_mode_car': False,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holidays_credit_time_unassimilated_month(self):
        # 4/5 time credit all through the reference year 2020 and the whole of February on unpaid leave (unassimilated):
        # February counts for nothing, the 11 other months in full
        self.version.write({
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week,
            'work_time_rate': 1.0,
            'wage': 2120.0,
            'transport_mode_car': False,
        })
        self.env['hr.leave'].create({
            'name': 'Unpaid leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
            'request_date_from': datetime.date(2020, 2, 1),
            'request_date_to': datetime.date(2020, 2, 29),
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        _amount, explanation = payslip._l10n_be_get_paid_double_holiday(get_explanation=True)
        self.assertAlmostEqual(explanation['months'], 11, 2)
        payslip.compute_sheet()
        self.assertTrue(payslip._get_line_values(['DOUBLE'])['DOUBLE'][payslip.id]['total'])

    def test_double_holidays_time_credit_after_reference_year(self):
        # Full time all through the reference year 2020, 4/5 time credit from January 2021: the double holiday pay of
        # June 2021 is 92% of June's gross pay (art. 38, 2° AR 30.03.1967), the time credit's, for the 12 months of 2020
        time_credit_version = self.employee.create_version({
            'date_version': datetime.date(2021, 1, 1),
            'resource_calendar_id': self.resource_calendar_4_5_wednesday_off_time_credit.id,
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'work_time_rate': 1.0,
        })
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': time_credit_version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        # June's gross pay: 2650 x 4/5 = 2120, and the benefits in kind bearing ONSS: internet 5 + mobile subscription 4
        self.assertAlmostEqual(payslip._l10n_be_get_paid_double_holiday(), 2129, 2)
        payslip.compute_sheet()
        line_values = payslip._get_line_values(['DOUBLE', 'DOUBLE_COMPLEMENTARY'])
        self.assertAlmostEqual(line_values['DOUBLE'][payslip.id]['total'], 1809.65, 2)  # 2129 x 85%
        self.assertAlmostEqual(line_values['DOUBLE_COMPLEMENTARY'][payslip.id]['total'], 149.03, 2)  # 2129 x 7%

    def test_double_holidays_complete_year_part_time(self):
        self.version.write({
            'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'wage': 2120.0,
            'transport_mode_car': False,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holidays_incomplete_year_part_time(self):
        self.version.write({
            'contract_date_start': datetime.date(2020, 3, 15),
            'resource_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'wage': 2120.0,
            'transport_mode_car': False,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holidays_children_no_reduction(self):
        self.version.write({
            'contract_date_start': datetime.date(2020, 3, 15),
            'transport_mode_car': False,
        })

        self.employee.write({
            'children': 2,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holidays_children_with_reductions(self):
        self.version.write({
            'contract_date_start': datetime.date(2020, 3, 15),
            'transport_mode_car': False,
        })

        self.employee.write({
            'children': 6,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        # This single employee's 6 children family deduction brings the theoretical tax to zero, so DH_PP is exempted.
        self._validate_payslip(payslip)

    def test_double_holidays_variable_revenues_complete_year(self):
        commission_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2020, 5, 1),
            'date_to': datetime.datetime(2020, 5, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.env.company.id,
        })
        commission_payslip._set_input_value('COMMISSION', 3000)

        commission_payslip.action_refresh_from_work_entries()
        self.employee.write({'review_state': '1_reviewed'})
        commission_payslip.action_payslip_done()

        self.version.write({
            'commission_on_target': 1000,
            'transport_mode_car': False,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holidays_variable_revenues_incomplete_year(self):
        commission_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2020, 5, 1),
            'date_to': datetime.datetime(2020, 5, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.env.company.id,
        })
        commission_payslip._set_input_value('COMMISSION', 3000)
        commission_payslip.action_refresh_from_work_entries()
        self.employee.write({'review_state': '1_reviewed'})
        commission_payslip.action_payslip_done()

        self.version.write({
            'commission_on_target': 1000,
            'contract_date_start': datetime.date(2020, 3, 15),
            'transport_mode_car': False,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holidays_variable_revenues_incomplete_year_with_attest(self):
        commission_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2020, 9, 1),
            'date_to': datetime.datetime(2020, 9, 30),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.env.company.id,
        })
        commission_payslip._set_input_value('COMMISSION', 6000)
        commission_payslip.action_refresh_from_work_entries()
        self.employee.write({'review_state': '1_reviewed'})
        commission_payslip.action_payslip_done()

        self.version.write({
            'commission_on_target': 1000,
            'contract_date_start': datetime.date(2020, 7, 1),
            'transport_mode_car': False,
        })
        self.version.employee_id.write({
            'l10n_be_fictive_hire_date': datetime.date(2020, 7, 1),
        })
        self.env["l10n.be.holiday.attest"].create([
            {
                "employee_id": self.employee.id,
                "date_from": datetime.date(2020, 1, 1),
                "date_to": datetime.date(2020, 6, 30),
                "prev_work_hours_per_week": 19,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_simple_holiday_pay_paid": 0,
                "prev_double_holiday_pay_paid": 1245.33,
            },
        ])

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holidays_holiday_attest_40_over_38(self):
        self.version.write({
            'contract_date_start': datetime.date(2020, 7, 1),
            'transport_mode_car': False,
        })

        self.env["l10n.be.holiday.attest"].create([
            {
                "employee_id": self.employee.id,
                "date_from": datetime.date(2020, 1, 1),
                "date_to": datetime.date(2020, 6, 30),
                "prev_work_hours_per_week": 40,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_simple_holiday_pay_paid": 0,
                "prev_double_holiday_pay_paid": 1245.33,
            },
        ])

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holidays_european_time_off(self):
        self.version.write({
            'contract_date_start': datetime.date(2020, 3, 15),
            'transport_mode_car': False,
        })

        self.employee.write({
            'children': 2,
        })

        self.env['hr.leave'].create({
            'name': 'European Time Off',
            'work_entry_type_id': self.european_time_off_type.id,
            'request_date_from': datetime.date(2020, 5, 4),
            'request_date_to': datetime.date(2020, 5, 4),
            'employee_id': self.employee.id,
        })

        european_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2020, 5, 1),
            'date_to': datetime.datetime(2020, 5, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.env.company.id,
        })
        european_payslip.action_refresh_from_work_entries()
        self.employee.write({'review_state': '1_reviewed'})
        european_payslip.action_payslip_done()
        self.assertEqual(european_payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '142.20').amount, 122.31)

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holidays_european_time_off_over_2_years(self):
        self.version.write({
            'contract_date_start': datetime.date(2019, 1, 1),
            'transport_mode_car': False,
        })

        self.employee.write({
            'children': 2,
        })

        # Takes all the 4 weeks of european time off in Feb 2019
        # Should recover 2650 € in 2020
        self.env['hr.leave'].create({
            'name': 'European Time Off',
            'work_entry_type_id': self.european_time_off_type.id,
            'request_date_from': datetime.date(2019, 2, 1),
            'request_date_to': datetime.date(2019, 2, 28),
            'employee_id': self.employee.id,
        })

        european_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2019, 2, 1),
            'date_to': datetime.datetime(2019, 2, 28),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.env.company.id,
        })
        european_payslip.action_refresh_from_work_entries()
        self.employee.write({'review_state': '1_reviewed'})
        european_payslip.action_payslip_done()
        self.assertEqual(european_payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '142.20').amount, 2650)

        payslip_2020 = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2020, 6, 1),
            'date_to': datetime.date(2020, 6, 30)
        })
        payslip_2020.compute_sheet()
        self.employee.write({'review_state': '1_reviewed'})
        payslip_2020.action_payslip_done()

        # We recover the maximum amount in 2020, and we should recover the remaining in 2021
        # 2650 - 2438 = 212 €
        self._validate_payslip(payslip_2020)

        payslip_2021 = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip_2021.compute_sheet()

        self._validate_payslip(payslip_2021)

    def test_double_holidays_company_car(self):
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30)
        })
        payslip.compute_sheet()

        self.assertEqual(len(payslip.worked_days_line_ids), 0)

        self._validate_payslip(payslip)

    def test_double_holidays_pay_recovery(self):
        self.version.write({
            'transport_mode_car': False,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2021, 6, 1),
            'date_to': datetime.date(2021, 6, 30),
        })
        payslip._set_input_value('DOUBLERECOVERY', 438)
        payslip.compute_sheet()

        self.assertEqual(len(payslip.worked_days_line_ids), 0)

        self._validate_payslip(payslip)

    def test_double_holiday_recovery(self):
        self.version.write({
            'contract_date_start': datetime.date(2020, 8, 3),
            'wage': 1956.69,
        })

        self.env["l10n.be.holiday.attest"].create([
            {
                "employee_id": self.employee.id,
                "date_from": datetime.date(2020, 1, 1),
                "date_to": datetime.date(2020, 6, 30),
                "prev_work_hours_per_week": 38,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
                "prev_simple_holiday_pay_paid": 0,
                "prev_double_holiday_pay_paid": 2781.82,
            }
        ])

        double_pay_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2021, 6, 1),
            'date_to': datetime.datetime(2021, 6, 30),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'company_id': self.env.company.id,
        })
        double_pay_payslip._set_input_value('MONTH', 11)
        double_pay_payslip.compute_sheet()

        self.assertAlmostEqual(double_pay_payslip._get_input_line_amount('DOUBLERECOVERY'), 900.08, 2)

        self.assertEqual(len(double_pay_payslip.worked_days_line_ids), 0)

        self._validate_payslip(double_pay_payslip)

    def test_double_holiday_recovery_half_time_multi_attest(self):
        # Note: The employee was occupied with 2 half times over the same period
        self.version.write({
            'contract_date_start': datetime.date(2020, 8, 3),
            'wage': 2322.22,
        })

        self.env["l10n.be.holiday.attest"].create([
            {
                "employee_id": self.employee.id,
                "date_from": datetime.date(2020, 6, 1),
                "date_to": datetime.date(2020, 7, 31),
                "prev_assimilated_days": 45,
                "prev_simple_holiday_pay_paid": 0,
                "prev_double_holiday_pay_paid": 520.89,
                "prev_work_hours_per_week": 19,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
            },
            {
                "employee_id": self.employee.id,
                "date_from": datetime.date(2020, 6, 1),
                "date_to": datetime.date(2020, 7, 31),
                "prev_assimilated_days": 45,
                "prev_simple_holiday_pay_paid": 0,
                "prev_double_holiday_pay_paid": 491.62,
                "prev_work_hours_per_week": 19,
                "prev_reference_work_hours_per_week": 38,
                "prev_work_days_per_week": 5,
            },
        ])
        double_pay_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2021, 6, 1),
            'date_to': datetime.datetime(2021, 6, 30),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'company_id': self.env.company.id,
        })
        double_pay_payslip._set_input_value('MONTH', 7)
        double_pay_payslip.compute_sheet()

        self.assertAlmostEqual(double_pay_payslip._get_input_line_amount('DOUBLERECOVERY'), 369.76, 2)

        self.assertEqual(len(double_pay_payslip.worked_days_line_ids), 0)

        self._validate_payslip(double_pay_payslip)

    def test_double_holiday_recovery_multi_certificates_capped(self):
        """
        - Employee enters on 25/03/2024
        - Two holiday attests in 2023 with different regimes
        - Recovery must be capped to the computed entitlement
        """

        self.version.write({
            'contract_date_start': datetime.date(2024, 3, 25),
            'wage': 3750.00,
        })

        self.env['l10n.be.holiday.attest'].create([
            {
                'employee_id': self.employee.id,
                'date_from': datetime.date(2023, 1, 1),
                'date_to': datetime.date(2023, 10, 8),
                'prev_simple_holiday_pay_paid': 0,
                'prev_double_holiday_pay_paid': 5627.34,
                'prev_work_hours_per_week': 38,
                'prev_reference_work_hours_per_week': 38,
                'prev_work_days_per_week': 5,
            },
            {
                'employee_id': self.employee.id,
                'date_from': datetime.date(2023, 10, 9),
                'date_to': datetime.date(2023, 12, 31),
                'prev_simple_holiday_pay_paid': 0,
                'prev_double_holiday_pay_paid': 2075.60,
                'prev_work_hours_per_week': 36.66,
                'prev_reference_work_hours_per_week': 38,
                'prev_work_days_per_week': 5,
            },
        ])

        # Payslip
        double_pay_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2024, 6, 1),
            'date_to': datetime.datetime(2024, 6, 30),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'company_id': self.env.company.id,
        })

        double_pay_payslip._set_input_value('MONTH', 12)
        double_pay_payslip.compute_sheet()

        # Expected recovery:
        # Total capped recovery = 3423.69
        # Remaining balance = 26.31 (taxable)
        self.assertAlmostEqual(
            double_pay_payslip._get_input_line_amount('DOUBLERECOVERY'),
            3421.93,
            2,
        )

        # No worked days expected
        self.assertEqual(len(double_pay_payslip.worked_days_line_ids), 0)

        self._validate_payslip(double_pay_payslip)

    def test_double_holiday_recovery_working_more_prorate_new_cap(self):
        """
        Employee works MORE now = limit using OLD smaller fraction

        We prorate:
        - Theoretical cap
        - New DP
        """

        # New job (2025)
        calendar_32h_40h = self._create_calendar(32)

        self.version.write({
            'resource_calendar_id': calendar_32h_40h.id,
            'contract_date_start': datetime.date(2025, 1, 1),
            'wage': 2500.00,
        })

        # Holiday attest from previous employer (2024)
        self.env['l10n.be.holiday.attest'].create([{
            'employee_id': self.employee.id,
            'date_from': datetime.date(2024, 1, 1),
            'date_to': datetime.date(2024, 12, 31),
            'prev_simple_holiday_pay_paid': 0,
            'prev_double_holiday_pay_paid': 4049.76,
            'prev_work_hours_per_week': 25,
            'prev_reference_work_hours_per_week': 38,
            'prev_work_days_per_week': 5,
        }])

        double_pay_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2025, 6, 1),
            'date_to': datetime.datetime(2025, 6, 30),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref(
                'l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday'
            ).id,
            'company_id': self.env.company.id,
        })

        double_pay_payslip._set_input_value('MONTH', 12)
        double_pay_payslip.compute_sheet()

        # Expected recovery
        self.assertAlmostEqual(
            double_pay_payslip._get_input_line_amount('DOUBLERECOVERY'),
            1891.45,
            2
        )

        self.assertEqual(len(double_pay_payslip.worked_days_line_ids), 0)

        payslip_results = {
            'DOUBLERECOVERY': -1891.45,
            'DH_BASIC': 2308.28,  # (2500 + internet 5 + mobile subscription 4) x 92%
        }

        self._validate_payslip(double_pay_payslip, payslip_results, skip_lines=True)

    def test_double_holiday_recovery_working_less_prorate_old_certificate(self):
        """
        Rule 3:
        Employee works LESS now = prorate OLD certificate

        We prorate:
        - Certificate amount (downwards)
        - Then compare with new salary cap
        """
        calendar_30h_40h = self._create_calendar(30)

        # New job (2025) → smaller schedule
        self.version.write({
            'resource_calendar_id': calendar_30h_40h.id,
            'contract_date_start': datetime.date(2025, 1, 1),
            'wage': 2500.00,
        })

        # Holiday attest from previous employer (2024)
        self.env['l10n.be.holiday.attest'].create([{
            'employee_id': self.employee.id,
            'date_from': datetime.date(2024, 1, 1),
            'date_to': datetime.date(2024, 12, 31),
            'prev_simple_holiday_pay_paid': 0,
            'prev_double_holiday_pay_paid': 4417.92 / 2,
            'prev_work_hours_per_week': 32,
            'prev_reference_work_hours_per_week': 38,
            'prev_work_days_per_week': 5,
        }])

        double_pay_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2025, 6, 1),
            'date_to': datetime.datetime(2025, 6, 30),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref(
                'l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday'
            ).id,
            'company_id': self.env.company.id,
        })

        double_pay_payslip._set_input_value('MONTH', 12)
        double_pay_payslip.compute_sheet()

        # Expected recovery
        self.assertAlmostEqual(
            double_pay_payslip._get_input_line_amount('DOUBLERECOVERY'),
            1967.36,
            2
        )

        self.assertEqual(len(double_pay_payslip.worked_days_line_ids), 0)

        payslip_results = {
            'DOUBLERECOVERY': -1967.36,
            'DH_BASIC': 2308.28,  # (2500 + internet 5 + mobile subscription 4) x 92%
        }

        self._validate_payslip(double_pay_payslip, payslip_results, skip_lines=True)

    def test_double_holidays_commission_first_incomplete_month(self):
        # If a payslip (first one or mid-month signing is incomplete and has commissions
        # take them into account
        self.version.write({
            'contract_date_start': datetime.date(2021, 12, 7),
            'commission_on_target': 1500,
        })
        self.version.employee_id.write({
            'l10n_be_fictive_hire_date': datetime.date(2021, 12, 7),
        })

        payslip = self._generate_payslip(datetime.date(2021, 12, 1), datetime.date(2021, 12, 31), input_values={'COMMISSION': 300})
        self.employee.write({'review_state': '1_reviewed'})
        payslip.action_payslip_done()

        double_payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2022, 6, 1),
            'date_to': datetime.date(2022, 6, 30)
        })
        double_payslip.compute_sheet()

        self._validate_payslip(double_payslip)

    def test_double_holidays_full_time_credit_time(self):
        # Check that a full time credit time is not taken into account
        # on the number of occupation months
        self.version.write({
            'name': "Full Time Parental Time Off",
            'reference_calendar_id': self.resource_calendar_38_hours_per_week.id,
            'work_time_rate': 0,
            'wage': 2400,
            'resource_calendar_id': self.resource_calendar_0_hours_per_week.id,
            'contract_date_start': datetime.date(2021, 1, 1),
        })
        self.version.employee_id.write({
            'l10n_be_fictive_hire_date': datetime.date(2021, 1, 1),
        })

        double_payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2022, 6, 1),
            'date_to': datetime.date(2022, 6, 30)
        })
        double_payslip.compute_sheet()

        self._validate_payslip(double_payslip)

    def test_double_holidays_european_time_off_current_year(self):
        # Check that european time off taken on the current year
        # are not recovered on the double holiday pay (and left for next year)

        self.env['hr.leave'].create({
            'name': 'European Time Off',
            'work_entry_type_id': self.european_time_off_type.id,
            'request_date_from': '2022-05-09',
            'request_date_to': '2022-05-12',
            'employee_id': self.employee.id,
        })

        european_payslip = self.env['hr.payslip'].create({
            'version_id': self.version.id,
            'date_from': datetime.datetime(2022, 5, 1),
            'date_to': datetime.datetime(2022, 5, 31),
            'employee_id': self.employee.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'company_id': self.env.company.id,
        })
        european_payslip.action_refresh_from_work_entries()
        self.employee.write({'review_state': '1_reviewed'})
        european_payslip.action_payslip_done()
        self.assertEqual(european_payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '142.20').amount, 489.23)

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2022, 6, 1),
            'date_to': datetime.date(2022, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holiday_case_01(self):
        self.version.write({
            'contract_date_start': datetime.date(2025, 1, 1),
            'date_version': datetime.date(2025, 1, 1),
            'wage': 2000,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holiday_case_02(self):
        self.version.write({
            'date_version': datetime.date(2025, 1, 1),
            'contract_date_start': datetime.date(2025, 1, 1),
            'contract_date_end': datetime.date(2025, 6, 30),
            'wage': 2000,
        })

        part_time_version = self.env['hr.version'].create([{
            'date_version': datetime.date(2025, 7, 1),
            'contract_date_start': datetime.date(2025, 7, 1),
            'employee_id': self.version.employee_id.id,
            'resource_calendar_id': self.calendar_30_4h_per_week.id,
            'wage': 1500,
        }])

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': part_time_version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holiday_case_03(self):
        self.version.write({
            'contract_date_start': datetime.date(2025, 7, 1),
            'date_version': datetime.date(2025, 7, 1),
            'wage': 2000,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holiday_case_04(self):
        self.version.write({
            'contract_date_start': datetime.date(2025, 9, 15),
            'date_version': datetime.date(2025, 9, 15),
            'wage': 2000,
        })
        # Holiday attest from previous employer (2024)
        self.env['l10n.be.holiday.attest'].create([{
            'employee_id': self.employee.id,
            'date_from': datetime.date(2025, 1, 1),
            'date_to': datetime.date(2025, 5, 25),
            'prev_simple_holiday_pay_paid': 0,
            'prev_double_holiday_pay_paid': 2781.82,
            'prev_work_hours_per_week': 38,
            'prev_reference_work_hours_per_week': 38,
            'prev_work_days_per_week': 5,
        }])

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holiday_case_05(self):
        self.version.write({
            'contract_date_start': datetime.date(2025, 9, 15),
            'date_version': datetime.date(2025, 9, 15),
            'wage': 2000,
        })

        self.env['l10n.be.holiday.attest'].create([{
            'employee_id': self.employee.id,
            'date_from': datetime.date(2025, 1, 1),
            'date_to': datetime.date(2025, 5, 25),
            'prev_simple_holiday_pay_paid': 0,
            'prev_double_holiday_pay_paid': 2781.82,
            'prev_work_hours_per_week': 38 * 0.7895,
            'prev_reference_work_hours_per_week': 38,
            'prev_work_days_per_week': 5,
        }])

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holiday_case_06(self):
        self.version.write({
            'date_version': datetime.date(2025, 1, 1),
            'contract_date_start': datetime.date(2025, 1, 1),
            'contract_date_end': False,
            'wage': 2000,
        })

        self.env['hr.leave'].create({
            'name': 'Unpaid leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
            'request_date_from': datetime.date(2025, 1, 1),
            'request_date_to': datetime.date(2025, 1, 8),
            'employee_id': self.employee.id,
        })

        self.env['hr.leave'].with_context(skip_allocation_check=True).create({
            'name': 'Unjustified leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_unjustified_reason').id,
            'request_date_from': datetime.date(2025, 2, 1),
            'request_date_to': datetime.date(2025, 2, 8),
            'employee_id': self.employee.id,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2025, 3, 1),
            'request_date_to': datetime.date(2025, 3, 8),
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        # The computation basis for the double and double complementary should be:
        #   ((23/31)/12 + (20/28)/12 + 10/12) * 2000 = 1909.37€
        #   DOUBLE = 1909.37 * 0.85 = 1622.96€
        #   DOUBLE_COMPLEMENTARY = 1909.37 * 0.07 = 133.66€
        self._validate_payslip(payslip)

    def test_double_holiday_case_07(self):
        self.version.write({
            'date_version': datetime.date(2025, 1, 1),
            'contract_date_start': datetime.date(2025, 1, 1),
            'contract_date_end': False,
            'wage': 2000,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2024, 6, 10),
            'request_date_to': datetime.date(2025, 9, 15),
            'employee_id': self.employee.id,
        })

        self.env['hr.leave'].create({
            'name': 'Unpaid leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
            'request_date_from': datetime.date(2025, 9, 30),
            'request_date_to': datetime.date(2025, 10, 8),
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        # The computation basis for the double and double complementary should be:
        #   (5/12 + (9/30)/12 + (14/30)/12 + (23/31)/12 + 2/12) * 2000 = 1418.10€
        #   DOUBLE = 1418.10 * 0.85 = 1205.39€
        #   DOUBLE_COMPLEMENTARY = 1418.10 * 0.07 = 99.27€
        self._validate_payslip(payslip)

    def test_double_holiday_case_08(self):
        self.version.write({
            'contract_date_start': datetime.date(2025, 9, 1),
            'date_version': datetime.date(2025, 9, 1),
            'wage': 4000,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holiday_case_09(self):
        self.version.write({
            'contract_date_start': datetime.date(2025, 3, 2),
            'date_version': datetime.date(2025, 3, 2),
            'wage': 3000,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        self._validate_payslip(payslip)

    def test_double_holiday_12_months_sickness(self):
        self.version.write({
            'date_version': datetime.date(2025, 1, 1),
            'contract_date_start': datetime.date(2025, 1, 1),
            'contract_date_end': False,
            'wage': 2000,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2025, 1, 1),
            'request_date_to': datetime.date(2025, 12, 31),
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        # Double holiday should be full as first 12 months of sickness are taken into account
        self._validate_payslip(payslip)

    def test_double_holiday_13_months_sickness(self):
        self.version.write({
            'date_version': datetime.date(2025, 1, 1),
            'contract_date_start': datetime.date(2025, 1, 1),
            'contract_date_end': False,
            'wage': 2000,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2024, 12, 1),
            'request_date_to': datetime.date(2025, 12, 31),
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        # Double holiday should be prorated as only the first 12 months of sickness are taken into account
        # The computation basis for the double and double complementary should be:
        #   (11/12) * 2000 = 1833.33€
        #   DOUBLE = 1909.37 * 0.85 = 1558.33€
        #   DOUBLE_COMPLEMENTARY = 1909.37 * 0.07 = 128.33€
        self._validate_payslip(payslip)

    def test_double_holiday_24_months_sickness(self):
        self.version.write({
            'date_version': datetime.date(2025, 1, 1),
            'contract_date_start': datetime.date(2025, 1, 1),
            'contract_date_end': False,
            'wage': 2000,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2024, 1, 1),
            'request_date_to': datetime.date(2025, 12, 31),
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        # Double holiday should be zero as only the first 12 months of sickness are taken into account
        self._validate_payslip(payslip)

    def test_double_holiday_sickness_relapse_chain_over_12_months(self):
        """Two sick leaves linked by the relapse flag form a single chain.

        Leave A: Jan 1 2024 - Sep 30 2024  (9 months)
        Leave B: Oct 10 2024 - Dec 31 2025  (marked as relapse, within 14-day window)

        Chain origin = Jan 1 2024, 12-month cutoff = Jan 1 2025 + 10 days from back to work
        """
        self.version.write({
            'date_version': datetime.date(2025, 1, 1),
            'contract_date_start': datetime.date(2025, 1, 1),
            'contract_date_end': False,
            'wage': 2000,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave A',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2024, 1, 1),
            'request_date_to': datetime.date(2024, 9, 30),
            'employee_id': self.employee.id,
        })

        last_sick_leave = self.env['hr.leave'].search([('employee_id', '=', self.employee.id)]).sorted('request_date_from')[-1]

        self.env['hr.leave'].create({
            'name': 'Sick leave B (relapse)',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2024, 10, 10),
            'request_date_to': datetime.date(2025, 12, 31),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': True,
            'l10n_be_sickness_relapse_origin_leave_id': last_sick_leave.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        # Basis = 9/31/12 * 2000 = 48.39€
        # DOUBLE = 48.39 * 0.85 = 41.13€
        # DOUBLE_COMPLEMENTARY = 48.39 * 0.07 = 3.39€
        self._validate_payslip(payslip)

    def test_double_holiday_sickness_no_relapse_new_chain(self):
        """Two sick leaves within the relapse window but the second is NOT marked as a relapse.

        Leave A: Jan 1 2025 - Mar 31 2025  (3 months)
        Leave B: Apr 10 2025 - Dec 31 2025  (within 14 days of A, but NOT a relapse)

        Because B is not a relapse, it starts a fresh chain.  Both chains are < 12 months
        so every sick day in 2025 is assimilated → double holiday is full.
        """
        self.version.write({
            'date_version': datetime.date(2025, 1, 1),
            'contract_date_start': datetime.date(2025, 1, 1),
            'contract_date_end': False,
            'wage': 2000,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave A',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2025, 1, 1),
            'request_date_to': datetime.date(2025, 3, 31),
            'employee_id': self.employee.id,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave B (NOT a relapse)',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2025, 4, 10),
            'request_date_to': datetime.date(2025, 12, 31),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': False,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        # Both chains < 12 months → full assimilation
        self._validate_payslip(payslip)

    def test_double_holiday_unpaid_leave_spanning_two_months(self):
        """An unpaid leave that straddles a month boundary must be split correctly.

        Leave: Jan 25 - Feb 5 2025 (unpaid)
          → Jan deduction: 7 calendar days (Jan 25-31)
          → Feb deduction: 5 calendar days (Feb 1-5)
        """
        self.version.write({
            'date_version': datetime.date(2025, 1, 1),
            'contract_date_start': datetime.date(2025, 1, 1),
            'contract_date_end': False,
            'wage': 2000,
        })

        self.env['hr.leave'].create({
            'name': 'Unpaid leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
            'request_date_from': datetime.date(2025, 1, 25),
            'request_date_to': datetime.date(2025, 2, 5),
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        # Basis = (24/31 + 23/28 + 10) / 12 * 2000 = 1932.60€
        # DOUBLE = 1932.60 * 0.85 = 1642.71€
        # DOUBLE_COMPLEMENTARY = 1932.60 * 0.07 = 135.28€
        self._validate_payslip(payslip)

    def test_double_holiday_sickness_cutoff_at_month_boundary(self):
        """Sick leave chain whose 12-month cutoff falls exactly on a month boundary.

        Leave: Feb 1 2024 - Dec 31 2025  (single leave)
        Chain origin = Feb 1 2024, 12-month cutoff = Feb 1 2025.

        In 2025:
          - Jan 2025 (before cutoff): fully assimilated → no deduction
          - Feb 1 2025 onwards: non-assimilated

        Non-assimilated days in 2025:
          Feb: 28 days, Mar-Dec: 10 full months

        Assimilated months: only January (1/12).
        """
        self.version.write({
            'date_version': datetime.date(2025, 1, 1),
            'contract_date_start': datetime.date(2025, 1, 1),
            'contract_date_end': False,
            'wage': 2000,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2024, 2, 1),
            'request_date_to': datetime.date(2025, 12, 31),
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        # The computation basis for the double and double complementary should be:
        #   BASIS = 1/12 * 2000 = 166.67€
        #   DOUBLE = 166.67 * 0.85 = 141.67€
        #   DOUBLE_COMPLEMENTARY = 166.67 * 0.07 = 11.67€
        self._validate_payslip(payslip)

    def test_double_holiday_sickness_back_to_work(self):
        """Relapse chain that crosses the 12-month boundary after a brief return to work.

        Leave A: Mar 1 2024 - Feb 1 2025  (chain origin = Mar 1 2024)
        Leave B: Feb 10 2025 - Feb 16 2025  (relapse within 14-day window)
        Leave C: Mar 1 2025 - Dec 31 2025  (relapse)
        """
        self.version.write({
            'date_version': datetime.date(2025, 1, 1),
            'contract_date_start': datetime.date(2025, 1, 1),
            'contract_date_end': False,
            'wage': 2000,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2024, 3, 1),
            'request_date_to': datetime.date(2025, 2, 1),
            'employee_id': self.employee.id,
        })

        last_sick_leave = self.env['hr.leave'].search([('employee_id', '=', self.employee.id)]).sorted('request_date_from')[-1]

        sick_leave_2 = self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2025, 2, 10),
            'request_date_to': datetime.date(2025, 2, 16),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': True,
            'l10n_be_sickness_relapse_origin_leave_id': last_sick_leave.id,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2025, 3, 1),
            'request_date_to': datetime.date(2025, 12, 31),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': True,
            'l10n_be_sickness_relapse_origin_leave_id': sick_leave_2.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        payslip.compute_sheet()

        # The computation basis for the double and double complementary should be:
        #   BASIS = 2/12 + 20/31/12 * 2000 = 440.86€
        #   DOUBLE = 440.86 * 0.85 = 374.73€
        #   DOUBLE_COMPLEMENTARY = 440.86 * 0.07 = 30.86€
        self._validate_payslip(payslip)

    def test_part_time_med_01(self):
        self.version.write({
            'date_version': datetime.date(2024, 4, 1),
            'contract_date_start': datetime.date(2024, 4, 1),
            'contract_date_end': datetime.date(2025, 5, 4),
        })

        self.employee.create_version({
            'date_version': datetime.date(2025, 5, 5),
            'contract_date_start': datetime.date(2025, 5, 5),
            'contract_date_end': datetime.date(2025, 6, 6),
            'resource_calendar_id': self.calendar_19h_per_week_med.id,
        })

        self.employee.create_version({
            'date_version': datetime.date(2025, 6, 7),
            'contract_date_start': datetime.date(2025, 6, 7),
            'contract_date_end': datetime.date(2025, 9, 24),
            'resource_calendar_id': self.calendar_26_6h_per_week_med.id,
        })

        latest_version = self.employee.create_version({
            'date_version': datetime.date(2025, 9, 25),
            'contract_date_start': datetime.date(2025, 9, 25),
            'contract_date_end': False,
            'resource_calendar_id': self.calendar_30_4h_per_week_med.id,
            'wage': 3276.77
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': latest_version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        self.assertAlmostEqual(payslip._l10n_be_get_paid_double_holiday(), 3276.77 + 9, 2)  # the wage and the benefits in kind bearing ONSS: internet 5 + mobile subscription 4

    def test_part_time_med_02(self):
        self.version.write({
            'date_version': datetime.date(2024, 8, 1),
            'contract_date_start': datetime.date(2024, 8, 1),
            'contract_date_end': datetime.date(2025, 8, 24),
        })

        self.employee.create_version({
            'date_version': datetime.date(2025, 8, 25),
            'contract_date_start': datetime.date(2025, 8, 25),
            'contract_date_end': datetime.date(2025, 12, 31),
            'resource_calendar_id': self.calendar_19h_per_week_med.id,
        })

        latest_version = self.employee.create_version({
            'date_version': datetime.date(2026, 1, 1),
            'contract_date_start': datetime.date(2026, 1, 1),
            'contract_date_end': False,
            'resource_calendar_id': self.calendar_30_4h_per_week.id,
            'wage': 1981.49,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': latest_version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        self.assertAlmostEqual(payslip._l10n_be_get_paid_double_holiday(), 1981.49 + 9, 2)  # the wage and the benefits in kind bearing ONSS: internet 5 + mobile subscription 4

    def test_part_time_med_03(self):
        self.version.write({
            'date_version': datetime.date(2024, 1, 1),
            'contract_date_start': datetime.date(2024, 1, 1),
            'contract_date_end': datetime.date(2025, 9, 21),
        })

        self.employee.create_version({
            'date_version': datetime.date(2025, 9, 22),
            'contract_date_start': datetime.date(2025, 9, 22),
            'contract_date_end': datetime.date(2025, 11, 23),
            'resource_calendar_id': self.calendar_15_12h_per_week_med.id,
            'work_time_rate': 1.0,
        })

        self.employee.create_version({
            'date_version': datetime.date(2025, 11, 24),
            'contract_date_start': datetime.date(2025, 11, 24),
            'contract_date_end': datetime.date(2026, 1, 25),
            'resource_calendar_id': self.calendar_22_8h_per_week_med.id,
            'work_time_rate': 1.0,
        })

        latest_version = self.employee.create_version({
            'date_version': datetime.date(2026, 1, 26),
            'contract_date_start': datetime.date(2026, 1, 26),
            'contract_date_end': False,
            'resource_calendar_id': self.calendar_30_4h_per_week_med.id,
            'work_time_rate': 1.0,
            'wage': 3711.22,
        })

        sick_leave1 = self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2024, 1, 3),
            'request_date_to': datetime.date(2024, 1, 12),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': True,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2024, 1, 24),
            'request_date_to': datetime.date(2024, 2, 29),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': True,
            'l10n_be_sickness_relapse_origin_leave_id': sick_leave1.id,
        })

        last_sick_leave = self.env['hr.leave'].search([('employee_id', '=', self.employee.id)]).sorted('request_date_from')[-1]

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2024, 3, 6),
            'request_date_to': datetime.date(2024, 5, 3),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': True,
            'l10n_be_sickness_relapse_origin_leave_id': last_sick_leave.id,
        })

        last_sick_leave = self.env['hr.leave'].search([('employee_id', '=', self.employee.id)]).sorted('request_date_from')[-1]

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2024, 5, 6),
            'request_date_to': datetime.date(2025, 1, 31),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': True,
            'l10n_be_sickness_relapse_origin_leave_id': last_sick_leave.id,
        })

        last_sick_leave = self.env['hr.leave'].search([('employee_id', '=', self.employee.id)]).sorted('request_date_from')[-1]

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2025, 2, 3),
            'request_date_to': datetime.date(2025, 9, 21),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': True,
            'l10n_be_sickness_relapse_origin_leave_id': last_sick_leave.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': latest_version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        self.assertAlmostEqual(payslip._l10n_be_get_paid_double_holiday(), 1245.22, 2)

    def test_part_time_med_04(self):
        self.version.write({
            'date_version': datetime.date(2024, 3, 1),
            'contract_date_start': datetime.date(2024, 3, 1),
            'contract_date_end': datetime.date(2024, 12, 31),
        })

        self.employee.create_version({
            'date_version': datetime.date(2025, 1, 1),
            'contract_date_start': datetime.date(2025, 1, 1),
            'contract_date_end': datetime.date(2025, 7, 31),
            'resource_calendar_id': self.calendar_19h_per_week_med.id,
            'work_time_rate': 1.0,
        })

        self.employee.create_version({
            'date_version': datetime.date(2025, 8, 1),
            'contract_date_start': datetime.date(2025, 8, 1),
            'contract_date_end': datetime.date(2025, 8, 19),
            'resource_calendar_id': self.employee.company_id.resource_calendar_id.id,
        })

        self.employee.create_version({
            'date_version': datetime.date(2025, 8, 20),
            'contract_date_start': datetime.date(2025, 8, 20),
            'contract_date_end': datetime.date(2026, 2, 28),
            'resource_calendar_id': self.calendar_19h_per_week_med.id,
            'work_time_rate': 1.0,
        })

        latest_version = self.employee.create_version({
            'date_version': datetime.date(2026, 3, 1),
            'contract_date_start': datetime.date(2026, 3, 1),
            'contract_date_end': False,
            'resource_calendar_id': self.calendar_30_4h_per_week.id,
            'wage': 3616.76,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2024, 10, 10),
            'request_date_to': datetime.date(2024, 12, 31),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': True,
        })

        origin_leave = self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2025, 6, 19),
            'request_date_to': datetime.date(2025, 7, 31),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': True,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2025, 8, 1),
            'request_date_to': datetime.date(2025, 8, 19),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': True,
            'l10n_be_sickness_relapse_origin_leave_id': origin_leave.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': latest_version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        self.assertAlmostEqual(payslip._l10n_be_get_paid_double_holiday(), 3616.76 + 9, 2)  # the wage and the benefits in kind bearing ONSS: internet 5 + mobile subscription 4

    def test_part_time_med_05(self):
        self.version.write({
            'date_version': datetime.date(2024, 7, 1),
            'contract_date_start': datetime.date(2024, 7, 1),
            'contract_date_end': datetime.date(2025, 4, 30),
            'resource_calendar_id': self.calendar_30_4h_per_week.id,
        })

        self.employee.create_version({
            'date_version': datetime.date(2025, 5, 1),
            'contract_date_start': datetime.date(2025, 5, 1),
            'contract_date_end': datetime.date(2025, 8, 31),
            'resource_calendar_id': self.calendar_15_12h_per_week_med.id,
            'work_time_rate': 1.0,
        })

        self.employee.create_version({
            'date_version': datetime.date(2025, 9, 1),
            'contract_date_start': datetime.date(2025, 9, 1),
            'contract_date_end': datetime.date(2025, 10, 23),
            'resource_calendar_id': self.calendar_30_4h_per_week.id,
        })

        latest_version = self.employee.create_version({
            'date_version': datetime.date(2025, 10, 24),
            'contract_date_start': datetime.date(2025, 10, 24),
            'contract_date_end': False,
            'resource_calendar_id': self.calendar_22_8h_per_week_med.id,
            'work_time_rate': 1.0,
            'wage': 2303.61,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2024, 12, 31),
            'request_date_to': datetime.date(2024, 12, 31),
            'employee_id': self.employee.id,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2025, 1, 1),
            'request_date_to': datetime.date(2025, 4, 30),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': True,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2025, 7, 14),
            'request_date_to': datetime.date(2025, 8, 31),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': True,
        })

        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2025, 9, 1),
            'request_date_to': datetime.date(2025, 10, 23),
            'employee_id': self.employee.id,
            'l10n_be_sickness_relapse': True,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': latest_version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        self.assertAlmostEqual(payslip._l10n_be_get_paid_double_holiday(), 2091.30, 2)

    def test_long_unpaid_leave(self):
        self.version.write({
            'date_version': datetime.date(2025, 1, 1),
            'contract_date_start': datetime.date(2025, 1, 1),
            'contract_date_end': False,
            'wage': 5805.46,
        })

        self.env['hr.leave'].create({
            'name': 'Unpaid leave',
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
            'request_date_from': datetime.date(2025, 3, 31),
            'request_date_to': datetime.date(2027, 3, 30),
            'employee_id': self.employee.id,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'vehicle_id': self.car.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            'date_from': datetime.date(2026, 6, 1),
            'date_to': datetime.date(2026, 6, 30)
        })
        self.assertAlmostEqual(payslip._l10n_be_get_paid_double_holiday(), 1437.98, 2)

    def _impulsion_employee_vals(self, name, plan, date_start, birthday=datetime.date(1990, 1, 1), city=None, contract=True, **values):
        """
        Returns the values of an employee with the given impulsion plan and start date.
        Set contract=True to create a contract version, or False to create an information version.
        """
        vals = {
            'name': name,
            'birthday': birthday,
            'company_id': self.env.company.id,
            'country_id': self.env.ref('base.be').id,
            'private_country_id': self.env.ref('base.be').id,
            'private_city_id': (self.city_namur if city is None else city).id,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'l10n_be_joint_committee_id': self.cp200.id,
            'date_version': date_start,
            'wage': 2500.0,
            'l10n_be_impulsion_plan': plan,
            **values,
        }
        if contract:
            vals.setdefault('contract_date_start', date_start)
        return vals

    def _create_impulsion_employees(self, vals_list):
        """
        Creates in batch the employees of the values built with _impulsion_employee_vals.
        Returns the employees in the order of vals_list.
        """
        return self.env['hr.employee'].create(vals_list)

    def _create_impulsion_employee(self, *args, **kwargs):
        return self._create_impulsion_employees([self._impulsion_employee_vals(*args, **kwargs)])

    def _add_contract(self, employee, date_start, date_end=False, **values):
        return employee.create_version({
            'date_version': date_start,
            'contract_date_start': date_start,
            'contract_date_end': date_end,
            'fixed_term': bool(date_end),
            **values,
        })

    def _add_information_version(self, employee, grant_date, **values):
        return employee.create_version({
            'date_version': grant_date,
            'contract_date_start': False,
            'contract_date_end': False,
            **values,
        })

    def _compute_payslips(self, employee_months, validate=False):
        """
        Creates and computes in batch one monthly payslip per (employee, first day of the month), on the version
        in effect at the end of the month. Returns the payslips in the order of employee_months.
        """
        payslips = self.env['hr.payslip'].create([{
            'name': f'Payslip {month_start:%m/%Y} {employee.name}',
            'employee_id': employee.id,
            'version_id': employee._get_version(month_start + relativedelta(day=31)).id,
            'date_from': month_start,
            'date_to': month_start + relativedelta(day=31),
            'company_id': self.env.company.id,
        } for employee, month_start in employee_months])
        payslips.compute_sheet()
        if validate:
            payslips.action_payslip_done()
        return payslips

    def _get_impulsion_lines(self, payslip, code):
        return payslip.line_ids.filtered(lambda line: line.code == code)

    def _assert_impulsion_line(self, payslip, code, expected_total, msg):
        """
        Checks the total of the Impulsion line ``code`` of the payslip, and that the rule of the other plan
        isn't computed. ``msg`` describes the rule being checked: it's shown, with the employee and the month,
        when the assertion fails.
        """
        context = f"{payslip.employee_id.name}, payslip {payslip.date_from:%m/%Y}"
        self.assertAlmostEqual(
            sum(self._get_impulsion_lines(payslip, code).mapped('total')), expected_total, places=2,
            msg=f"{context}: {msg}",
        )
        other_code = next(other for other in IMPULSION_CODES if other != code)
        self.assertFalse(
            self._get_impulsion_lines(payslip, other_code),
            f"{context}: the {other_code} rule should not be computed for a {code} plan",
        )

    def _assert_no_impulsion_line(self, payslip, msg):
        """ Checks that none of the Impulsion rules is computed on the payslip """
        computed_codes = [code for code in IMPULSION_CODES if self._get_impulsion_lines(payslip, code)]
        self.assertFalse(
            computed_codes,
            f"{payslip.employee_id.name}, payslip {payslip.date_from:%m/%Y}: {msg} (computed: {computed_codes})",
        )

    def _get_warning_records(self, xmlid, records):
        warning = self.env.ref(f'l10n_be_hr_payroll.{xmlid}')
        return warning._get_warning_python_records({'active_ids': records.ids})[0]

    @freeze_time("2026-04-10 10:00:00")
    def test_impulsion_deductions(self):
        employees = self._create_impulsion_employees([
            self._impulsion_employee_vals('Employee without Impulsion Plan', False, datetime.date(2025, 1, 1), birthday=datetime.date(1995, 1, 1)),
            self._impulsion_employee_vals('Employee with Impulsion 25yo', '25yo', datetime.date(2025, 1, 1), birthday=datetime.date(2002, 1, 1)),
            self._impulsion_employee_vals('Employee with Impulsion 12mo', '12mo', datetime.date(2025, 1, 1), birthday=datetime.date(1995, 1, 1)),
        ])
        # 4 days of unpaid leave in March: 18 paid days * 7.6 hours / (4 * 38 hours) = 90 %
        # The coefficient computation was updated to match the DRS
        self.env['hr.leave'].create([{
            'employee_id': employee.id,
            'request_date_from': datetime.date(2026, 3, 17),
            'request_date_to': datetime.date(2026, 3, 21),
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        } for employee in employees])

        (
            no_plan_jan, no_plan_feb, no_plan_mar,
            rw1_jan, rw1_feb, rw1_mar,
            rw2_jan, rw2_feb, rw2_mar,
        ) = self._compute_payslips([
            (employee, datetime.date(2026, month, 1)) for employee in employees for month in (1, 2, 3)
        ], validate=True)

        for payslip in (no_plan_jan, no_plan_feb, no_plan_mar):
            self._assert_no_impulsion_line(payslip, "an employee without Impulsion plan should not get any Impulsion deduction")

        for payslip in (rw1_jan, rw1_feb):
            self._assert_impulsion_line(
                payslip, 'IMPULSION25', -500.0,
                "a full-time month of the first 24 months of the <25 years plan should be fully deducted (500 €)")
        self._assert_impulsion_line(
            rw1_mar, 'IMPULSION25', -450.0,
            "4 days of unpaid leave should prorate the deduction on the paid hours: 136.8 / (4 * 38) = 90% of 500 €")

        for payslip in (rw2_jan, rw2_feb):
            self._assert_impulsion_line(
                payslip, 'IMPULSION12', -250.0,
                "the months 13 to 18 of a 12 months+ plan granted before 2026 should be deducted 250 €")
        self._assert_impulsion_line(
            rw2_mar, 'IMPULSION12', -225.0,
            "4 days of unpaid leave should prorate the deduction on the paid hours: 136.8 / (4 * 38) = 90% of 250 €")

    def test_25yo_new_hire_2025_brackets(self):
        """
        Test that for an employee hired on 01/09/2025 without an information version, the contract start is
        considered the grant date and the brackets before 2026 apply:
        < 24 months: 500 €
        24 - 30 months: 250 €
        30 - 36 months: 125 € for 6
        """
        employee = self._create_impulsion_employee('New Hire 2025', '25yo', datetime.date(2025, 9, 1), birthday=datetime.date(2002, 1, 1))
        self.assertEqual(
            employee.version_id._get_l10n_be_impulsion_start_date(), datetime.date(2025, 9, 1),
            "without information version, the contract start should be the grant date")

        month_1, month_24, month_25, month_30, month_31, month_36, month_37 = self._compute_payslips([
            (employee, month_start) for month_start in (
                datetime.date(2025, 9, 1),
                datetime.date(2027, 8, 1),
                datetime.date(2027, 9, 1),
                datetime.date(2028, 2, 1),
                datetime.date(2028, 3, 1),
                datetime.date(2028, 8, 1),
                datetime.date(2028, 9, 1),
            )
        ])
        self._assert_impulsion_line(month_1, 'IMPULSION25', -500.0, "The first month should be deducted 500 €")
        self._assert_impulsion_line(month_24, 'IMPULSION25', -500.0, "The 24th month should be deducted 500 €")
        self._assert_impulsion_line(month_25, 'IMPULSION25', -250.0, "From the 25th month, a plan granted before 2026 should be deducted 250 €")
        self._assert_impulsion_line(month_30, 'IMPULSION25', -250.0, "The 30th month should still be deducted 250 €")
        self._assert_impulsion_line(month_31, 'IMPULSION25', -125.0, "From the 31st month, a plan granted before 2026 should be deducted 125 €")
        self._assert_impulsion_line(month_36, 'IMPULSION25', -125.0, "The 36th month should still be deducted 125 €")
        self._assert_impulsion_line(month_37, 'IMPULSION25', 0.0, "No deduction should be applied after 36 months for a plan granted before 2026")

    def test_25yo_new_hire_2026_only_24_months(self):
        """
        Test that for an employee hired after 01/01/2026 new brackets with only the 24 months at 500 € apply.
        """
        employee = self._create_impulsion_employee('New Hire 2026', '25yo', datetime.date(2026, 3, 1), birthday=datetime.date(2004, 1, 1))
        month_1, month_24, month_25 = self._compute_payslips([
            (employee, datetime.date(2026, 3, 1)),
            (employee, datetime.date(2028, 2, 1)),
            (employee, datetime.date(2028, 3, 1)),
        ])
        self._assert_impulsion_line(month_1, 'IMPULSION25', -500.0, "The first month should be deducted 500 €")
        self._assert_impulsion_line(month_24, 'IMPULSION25', -500.0, "The 24th month should still be deducted 500 €")
        self._assert_impulsion_line(month_25, 'IMPULSION25', 0.0, "A plan granted from 2026 should not be deducted after 24 months (no 250 € and 125 € brackets anymore)")

    def test_25yo_age_checked_at_grant_date(self):
        """
        Test that the employee is under 25 years old at the grant date, not at the payslip date.
        """
        employee_under_25, employee_over_25 = self._create_impulsion_employees([
            self._impulsion_employee_vals('Turns 25', '25yo', datetime.date(2025, 9, 1), birthday=datetime.date(2001, 1, 1)),
            self._impulsion_employee_vals('Already 25', '25yo', datetime.date(2025, 9, 1), birthday=datetime.date(2000, 1, 1)),
        ])
        payslip_under_25, payslip_over_25 = self._compute_payslips([
            (employee_under_25, datetime.date(2026, 3, 1)),
            (employee_over_25, datetime.date(2025, 9, 1)),
        ])
        self._assert_impulsion_line(payslip_under_25, 'IMPULSION25', -500.0, "An employee under 25 years old at the grant date should keep the deduction after turning 25")
        self._assert_impulsion_line(payslip_over_25, 'IMPULSION25', 0.0, "An employee who is 25 years old or more at the grant date should not receive the deduction")

    def test_part_time_allowance_matches_drs(self):
        """
        Test that a 4/5 worker with absences gets the same allowance on the payslip and in the
        DRS WECH008: paid hours / (4 * full-time weekly hours).
        """
        employee = self._create_impulsion_employee(
            'Part Time 4/5', '25yo', datetime.date(2026, 1, 1), birthday=datetime.date(2004, 1, 1),
            resource_calendar_id=self.resource_calendar_4_5_friday_off.id,
        )
        # 2 days of unpaid leave on Tuesday and Wednesday
        self.env['hr.leave'].create({
            'employee_id': employee.id,
            'request_date_from': datetime.date(2026, 3, 17),
            'request_date_to': datetime.date(2026, 3, 18),
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        })
        payslip = self._compute_payslips([(employee, datetime.date(2026, 3, 1))], validate=True)
        # 16 paid days (Monday to Thursday) * 7.6 hours = 121.6 hours, 500 € * 121.6 / 152 = 400 €
        self._assert_impulsion_line(payslip, 'IMPULSION25', -400.0, "The deduction should be prorated on the paid hours over 4 weeks of a full-time worker: 121.6 / 152 = 80% of 500 €")

        drs = self.env['l10n.be.drs'].search([('employee_id', '=', employee.id), ('identification', '=', 'WECH008')])
        self.assertEqual(drs.risk_id, self.env.ref('l10n_be_hr_payroll.drs_risk_wech008_011'), "Validating the payslip of a -25 years plan should create a WECH008 declaration for the risk 011")
        self.assertEqual(drs.payslip_id, payslip, "The declaration should be linked to the validated payslip of the month")
        self.assertAlmostEqual(drs.paid_hours, 121.6, places=2, msg="The declaration should report the paid hours of the payslip")
        self.assertAlmostEqual(
            -sum(self._get_impulsion_lines(payslip, 'IMPULSION25').mapped('total')), drs.work_allowance, places=2,
            msg="The deduction on the payslip should match the work allowance declared in the DRS WECH008")

    def test_no_activation_after_june_2026(self):
        """
        Test that an impulsion plan granted after the last activation date (30/06/2026) gives a warning
        and is not paid.
        An impulsion plan granted before the last activation date but with a contract after the cutoff is still paid.
        """
        late_grant_employee, granted_before_employee = self._create_impulsion_employees([
            self._impulsion_employee_vals('Late Grant', '25yo', datetime.date(2026, 9, 1), birthday=datetime.date(2004, 1, 1)),
            self._impulsion_employee_vals(
                'Granted Before Cutoff', '12mo', datetime.date(2026, 6, 1), contract=False, birthday=datetime.date(1990, 1, 1)),
        ])
        self._add_contract(granted_before_employee, datetime.date(2026, 9, 1))
        late_grant_payslip, granted_before_payslip = self._compute_payslips([
            (late_grant_employee, datetime.date(2026, 9, 1)),
            (granted_before_employee, datetime.date(2026, 9, 1)),
        ])
        self._assert_impulsion_line(
            late_grant_payslip, 'IMPULSION25', 0.0,
            "A plan granted after the last activation date (30/06/2026) should not be applied in the payslip")
        self._assert_impulsion_line(
            granted_before_payslip, 'IMPULSION12', -500.0,
            "A plan granted before the last activation date should be applied, even with a contract starting after it")

        self.assertEqual(
            self._get_warning_records(
                'hr_payroll_warning_impulsion_after_activation_cutoff',
                late_grant_employee.version_ids + granted_before_employee.version_ids,
            ),
            late_grant_employee.version_id,
            "Only the version whose right starts after the last activation date should get the warning",
        )

    def test_no_payment_after_end_date(self):
        """
        Test that no payment is made after the program end date (31/12/2029). The plans granted before 30/06/2026
        end before 31/12/2029: the end is moved to 31/10/2026 with a new value of the parameter to check it applies.
        """
        rule_parameter = self.env['hr.rule.parameter']
        self.assertTrue(
            rule_parameter._get_parameter_from_code('l10n_be_impulsion_payment_permitted', date=datetime.date(2029, 12, 1)),
            "The Impulsion plans should still be payable in December 2029")
        self.assertFalse(
            rule_parameter._get_parameter_from_code('l10n_be_impulsion_payment_permitted', date=datetime.date(2030, 1, 1)),
            "The Impulsion plans should not be payable from January 2030")

        self.env['hr.rule.parameter.value'].create({
            'rule_parameter_id': self.env.ref('l10n_be_hr_payroll.rule_parameter_l10n_be_impulsion_payment_permitted').id,
            'parameter_value': 'False',
            'date_from': datetime.date(2026, 11, 1),
        })
        employee = self._create_impulsion_employee('End Date', '25yo', datetime.date(2025, 9, 1), birthday=datetime.date(2002, 1, 1))
        last_month, after_end = self._compute_payslips([
            (employee, datetime.date(2026, 10, 1)),
            (employee, datetime.date(2026, 11, 1)),
        ])
        self._assert_impulsion_line(
            last_month, 'IMPULSION25', -500.0, "The month of the end date of the plans should still apply the deduction")
        self._assert_impulsion_line(
            after_end, 'IMPULSION25', 0.0, "A payslip starting after the end date of the plans should not apply the deduction")

    def test_carried_over_right(self):
        """
        Test that a carried over grant from a previous employee is correctly applied.
        RW2 (12+ months) granted at the previous employer with 10 months remaining (14 months used), hired on
        01/03/2026.
        The information version is dated to 01/03/2026 - 14 months = 01/01/2025.
        The brackets before 2026 apply, 250 € for the months 15 to 18 and 125 € for the months 19 to 24.
        """
        employee = self._create_impulsion_employee('Carried Over', '12mo', datetime.date(2025, 1, 1), contract=False)
        contract = self._add_contract(employee, datetime.date(2026, 3, 1))
        self.assertEqual(
            contract._get_l10n_be_impulsion_start_date(), datetime.date(2025, 1, 1),
            "the grant date should be the date of the information version before the contract")

        payslips = self._compute_payslips([(employee, datetime.date(2026, 3, 1) + relativedelta(months=index)) for index in range(12)])
        for month_number, payslip in enumerate(payslips, start=15):
            if month_number <= 18:
                self._assert_impulsion_line(
                    payslip, 'IMPULSION12', -250.0,
                    f"Month {month_number} since the grant: the months 15 to 18 of a plan granted before 2026 should be applied with a deduction of 250 €")
            elif month_number <= 24:
                self._assert_impulsion_line(
                    payslip, 'IMPULSION12', -125.0,
                    f"Month {month_number} since the grant: the months 19 to 24 of a plan granted before 2026 should be applied with a deduction of 125 €")
            else:
                self._assert_impulsion_line(
                    payslip, 'IMPULSION12', 0.0,
                    f"Month {month_number} since the grant: the 10 months left of the carried over right are used up")
        self.assertFalse(
            self._get_warning_records('hr_payroll_warning_impulsion_after_activation_cutoff', employee.version_ids),
            "A right granted before the last activation date should not get the activation warning")

    def test_fixed_term_then_permanent_contract(self):
        """
        Test that a fixed-term contract followed by a permanent one without interruption continues the count from
        the information version, or from the first contract without it.
        """
        with_information, without_information = self._create_impulsion_employees([
            self._impulsion_employee_vals('With Information', '12mo', datetime.date(2025, 1, 1), contract=False),
            self._impulsion_employee_vals(
                'Without Information', '12mo', datetime.date(2025, 2, 1), contract_date_end=datetime.date(2025, 7, 31), fixed_term=True),
        ])
        self._add_contract(with_information, datetime.date(2025, 2, 1), datetime.date(2025, 7, 31))
        permanent = self._add_contract(with_information, datetime.date(2025, 8, 1))
        self.assertEqual(
            permanent._get_l10n_be_impulsion_start_date(), datetime.date(2025, 1, 1),
            "The count should go back through the fixed-term contract to the information version")

        permanent = self._add_contract(without_information, datetime.date(2025, 8, 1))
        self.assertEqual(
            permanent._get_l10n_be_impulsion_start_date(), datetime.date(2025, 2, 1),
            "Without information version, the count should start on the fixed-term contract")

        with_information_month_12, with_information_month_13, without_information_month_12, without_information_month_13 = \
            self._compute_payslips([
                (with_information, datetime.date(2025, 12, 1)),
                (with_information, datetime.date(2026, 1, 1)),
                (without_information, datetime.date(2026, 1, 1)),
                (without_information, datetime.date(2026, 2, 1)),
            ])
        self._assert_impulsion_line(
            with_information_month_12, 'IMPULSION12', -500.0, "Month 12 since the information version should be deducted 500 €")
        self._assert_impulsion_line(
            with_information_month_13, 'IMPULSION12', -250.0,
            "Month 13 since the information version should be deducted 250 €: the permanent contract continues the count")
        self._assert_impulsion_line(
            without_information_month_12, 'IMPULSION12', -500.0, "Month 12 since the fixed-term contract should be deducted 500 €")
        self._assert_impulsion_line(
            without_information_month_13, 'IMPULSION12', -250.0,
            "Month 13 since the fixed-term contract should be deducted 250 €: the permanent contract continues the count")

    def test_interruption_restarts_from_new_grant(self):
        """
        Test that after an interruption, the new information version holds the new grant and
        the count restarts from it. Without it, the count restarts from the new contract.
        """
        employee, without_information = self._create_impulsion_employees([
            self._impulsion_employee_vals('Rehired', '12mo', datetime.date(2024, 1, 1), contract=False),
            self._impulsion_employee_vals(
                'Rehired Without Information', '12mo', datetime.date(2024, 2, 1), contract_date_end=datetime.date(2024, 6, 30), fixed_term=True),
        ])
        first_contract = self._add_contract(employee, datetime.date(2024, 2, 1), datetime.date(2024, 6, 30))
        self._add_information_version(employee, datetime.date(2025, 3, 1))
        second_contract = self._add_contract(employee, datetime.date(2025, 4, 1))
        self.assertEqual(
            first_contract._get_l10n_be_impulsion_start_date(), datetime.date(2024, 1, 1),
            "The first contract should count from the first information version")
        self.assertEqual(
            second_contract._get_l10n_be_impulsion_start_date(), datetime.date(2025, 3, 1),
            "After an interruption, the count should restart from the new information version")

        month_2, month_12, month_13 = self._compute_payslips([
            (employee, datetime.date(2025, 4, 1)),
            (employee, datetime.date(2026, 2, 1)),
            (employee, datetime.date(2026, 3, 1)),
        ])
        self._assert_impulsion_line(
            month_2, 'IMPULSION12', -500.0, "Month 2 since the new grant should be deducted 500 €, as a new right")
        self._assert_impulsion_line(month_12, 'IMPULSION12', -500.0, "Month 12 since the new grant should be deducted 500 €")
        self._assert_impulsion_line(month_13, 'IMPULSION12', -250.0, "Month 13 since the new grant should be deducted 250 €")

        second_contract = self._add_contract(without_information, datetime.date(2025, 4, 1))
        self.assertEqual(
            second_contract._get_l10n_be_impulsion_start_date(), datetime.date(2025, 4, 1),
            "After an interruption without information version, the count should restart from the new contract")

    def test_eligibility_follows_residence(self):
        """
        Test that the eligibility follows the residence in French-speaking Wallonia, not the
        work location.
        An employee working in Brussels but residing in Liège should have eligibility based on residence.
        An employee working in Liège but residing in Brussels should not have eligibility based on residence.
        """
        liege_in_brussels, brussels_in_namur, eupen_in_namur = self._create_impulsion_employees([
            self._impulsion_employee_vals(
                'Liège Resident', '12mo', datetime.date(2026, 1, 1), city=self.city_liege, address_id=self.partner_brussels.id),
            self._impulsion_employee_vals(
                'Brussels Resident', '12mo', datetime.date(2026, 1, 1), city=self.city_brussels, address_id=self.partner_namur.id),
            self._impulsion_employee_vals(
                'Eupen Resident', '12mo', datetime.date(2026, 1, 1), city=self.city_eupen, address_id=self.partner_namur.id),
        ])
        self.assertRecordValues((liege_in_brussels + brussels_in_namur + eupen_in_namur).version_id, [
            {'l10n_be_working_region': 'br'},
            {'l10n_be_working_region': 'wa'},
            {'l10n_be_working_region': 'wa'},
        ])
        self.assertEqual(
            [version._get_l10n_be_employee_residence_region() for version in (liege_in_brussels + brussels_in_namur + eupen_in_namur).version_id],
            ['wa', 'br', 'cg'],
            "The residence region should come from the NIS code of the home city",
        )

        liege_payslip, brussels_payslip, eupen_payslip = self._compute_payslips([
            (liege_in_brussels, datetime.date(2026, 1, 1)),
            (brussels_in_namur, datetime.date(2026, 1, 1)),
            (eupen_in_namur, datetime.date(2026, 1, 1)),
        ])
        self._assert_impulsion_line(
            liege_payslip, 'IMPULSION12', -500.0, "A resident of Liège should be eligible for the impulsion plan, even when working in Brussels")
        self._assert_no_impulsion_line(
            brussels_payslip, "A resident of Brussels should not be eligible for the impulsion plan, even when working in Namur")
        self._assert_no_impulsion_line(
            eupen_payslip, "A resident of the German-speaking Community should not be eligible for the impulsion plan")

    def test_moving_out_of_wallonia(self):
        """
        Test that a new version with an address outside Wallonia stops the deduction from its effective date.
        """
        employee = self._create_impulsion_employee('Moving Out', '12mo', datetime.date(2026, 1, 1), city=self.city_liege)
        employee.create_version({'date_version': datetime.date(2026, 5, 1), 'private_city_id': self.city_brussels.id})
        before_move, after_move = self._compute_payslips([
            (employee, datetime.date(2026, 4, 1)),
            (employee, datetime.date(2026, 5, 1)),
        ])
        self._assert_impulsion_line(
            before_move, 'IMPULSION12', -500.0, "The deduction should be paid while residing in Wallonia")
        self._assert_no_impulsion_line(
            after_move, "Moving to Brussels should stop the deduction starting the month of the address change")

    @freeze_time('2026-03-15')
    def test_information_version_no_side_effect(self):
        """
        Test that creating an information version 2 years before hiring does not affect
        the payroll computations based on the first contract.
        """
        hire_date = datetime.date(2025, 9, 1)
        with_information, without_information = self._create_impulsion_employees([
            self._impulsion_employee_vals('With Information', '12mo', datetime.date(2023, 9, 1), contract=False, birthday=datetime.date(1968, 1, 1)),
            self._impulsion_employee_vals('Without Information', '12mo', hire_date, birthday=datetime.date(1968, 1, 1)),
        ])
        self._add_contract(with_information, hire_date)

        for employee in [with_information, without_information]:
            with self.subTest(employee=employee.name):
                contract = employee._get_version(hire_date)
                # Holiday years, seniority and occupation
                self.assertEqual(
                    employee._get_first_version_date(), hire_date,
                    "The information version should not be the first version used for payroll computations")
                self.assertEqual(
                    employee._get_first_contract_date(), hire_date, "The seniority should start on the first non-information version (version with a contract start date)")
                self.assertEqual(
                employee._get_first_versions(), contract, "The first versions should only contain contract versions")
                self.assertRecordValues(employee, [{
                    'first_contract_year_n1': '2024',
                    'first_contract_year_n2': '2023',
                    'l10n_be_company_seniority_years': 0,
                    'l10n_be_company_seniority_months': 6,
                }])
                self.assertEqual(
                    contract._get_occupation_dates()[-1][1], hire_date,
                    "The DmfA and DRS occupation should start on the contract start date, not on the information version date")
                # DmfA reduction for the 4th to 6th hires before 2024
                self.assertFalse(
                    self.env['l10n_be.dmfa']._is_eligible_for_fourth_to_sixth_hire_reduction_before_2024(employee),
                    "An information version starting in 2023 should not make the employee eligible for the 4th to 6th hire reduction before 2024 if the actual hire date is later")
                # CP 200 year-end bonus: hired after June
                thirteen_month = self.env['hr.payslip'].create({
                    'name': f'13th month {employee.name}',
                    'employee_id': employee.id,
                    'version_id': contract.id,
                    'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month').id,
                    'date_from': datetime.date(2025, 12, 1),
                    'date_to': datetime.date(2025, 12, 31),
                    'company_id': self.env.company.id,
                })
                self.assertEqual(
                    thirteen_month._get_paid_amount_13th_month(), 0.0,
                    "An employee hired after June should not get the CP 200 year-end bonus of the hiring year")
                departure = self.env['hr.employee.departure'].create({
                    'employee_id': employee.id,
                    'departure_reason_id': self.env.ref('hr.departure_fired').id,
                    'dismissal_date': datetime.date(2026, 3, 31),
                })
                self.assertEqual(
                    departure.l10n_be_first_contract_date, hire_date, "The information version should not be used to compute the departure notice seniority")

        elderly_params = [
            self.env['hr.payslip']._l10n_be_elderly_reduction_params(employee, datetime.date(2026, 3, 31), 'wa')
            for employee in [with_information, without_information]
        ]
        self.assertEqual(
            elderly_params[0], elderly_params[1],
            "The information version should not change the Walloon reduction for older workers")

    def test_information_version_no_guaranteed_salary_first_month(self):
        """
        Test that an information version does not affect sick leave computation.
        A worker sick in the first month of the contract should be unpaid, even with an
        information version 2 years before hiring.
        """
        worker = self._create_impulsion_employee(
            'Worker', '12mo', datetime.date(2024, 3, 1), contract=False,
            l10n_be_worker_code_id=self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
        )
        self._add_contract(worker, datetime.date(2026, 3, 1))
        self.env['hr.leave'].create({
            'employee_id': worker.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime.date(2026, 3, 2),
            'request_date_to': datetime.date(2026, 3, 6),
        })
        leaves = self.env['hr.leave'].search([('employee_id', '=', worker.id)])
        self.assertEqual(
            leaves.work_entry_type_id,
            self.env.ref('hr_work_entry.l10n_be_work_entry_type_common_law_illness_after_legal_period'),
            "A worker sick in the first month of the contract should not get the guaranteed salary even if there is an information version with a earlier start date",
        )

    def test_impulsion_warnings(self):
        no_city = self.env['res.city']
        namur, no_nis, brussels, eupen, france = self._create_impulsion_employees([
            self._impulsion_employee_vals('Namur Resident', '12mo', datetime.date(2026, 1, 1)),
            self._impulsion_employee_vals('No NIS Code', '12mo', datetime.date(2026, 1, 1), city=no_city),
            self._impulsion_employee_vals('Brussels Resident', '12mo', datetime.date(2026, 1, 1), city=self.city_brussels),
            self._impulsion_employee_vals('Eupen Resident', '12mo', datetime.date(2026, 1, 1), city=self.city_eupen),
            self._impulsion_employee_vals(
                'France Resident', '12mo', datetime.date(2026, 1, 1), city=no_city, private_country_id=self.env.ref('base.fr').id),
        ])
        warning = self.env.ref('l10n_be_hr_payroll.hr_payroll_warning_impulsion_residence')
        records, _, *__ = warning._get_warning_python_records(
            {'active_ids': (namur + no_nis + brussels + eupen + france).version_id.ids})
        self.assertEqual(
            records, (no_nis + brussels + eupen + france).version_id,
            "Every Impulsion plan without a residence in French-speaking Wallonia should get the residence warning")

        # Since 01/07/2023, a fixed-term contract must last at least 2 months
        employee_contract_too_short, employee_contract_two_months = self._create_impulsion_employees([
            self._impulsion_employee_vals(
                'Too Short', '12mo', datetime.date(2026, 1, 1), contract_date_end=datetime.date(2026, 2, 27), fixed_term=True),
            self._impulsion_employee_vals(
                'Two Months', '12mo', datetime.date(2026, 1, 1), contract_date_end=datetime.date(2026, 2, 28), fixed_term=True),
        ])
        self.assertEqual(
            self._get_warning_records('hr_payroll_warning_impulsion_short_fixed_term', (employee_contract_too_short + employee_contract_two_months).version_id),
            employee_contract_too_short.version_id,
            "only a fixed-term contract shorter than 2 months should get the warning",
        )

        # 0 € in payslip while the plan is still set: right exhausted after 12 months since 01/01/2026
        payslip_plan_paid, payslip_plan_exhausted = self._compute_payslips([
            (namur, datetime.date(2026, 12, 1)),
            (namur, datetime.date(2027, 1, 1)),
        ])
        self.assertEqual(
            self._get_warning_records('hr_payroll_warning_impulsion_zero_amount', payslip_plan_paid + payslip_plan_exhausted),
            payslip_plan_exhausted,
            "Only the payslip with a 0 € deduction while the plan is still set should get the warning",
        )
