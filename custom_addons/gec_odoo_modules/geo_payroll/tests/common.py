from datetime import date
from itertools import count

from odoo import Command, fields
from odoo.tests import TransactionCase


class GeoPayrollCase(TransactionCase):
    contract_start = date(2025, 1, 1)
    contract_end = date(2027, 12, 31)
    period_start = date(2026, 1, 1)
    period_end = date(2026, 1, 31)
    # January 2026 on the default Mon-Fri 8h calendar; core prorates a monthly wage against these hours.
    period_hours = 176.0
    period_days = 22.0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._sequence = count(1)
        cls.company = cls.env.company
        cls.company.country_id = cls.env.ref('base.ge')
        cls.company.tz = 'Asia/Tbilisi'
        cls.env.user.tz = 'Asia/Tbilisi'
        cls.env.user.group_ids |= cls.env.ref('hr_payroll.group_hr_payroll_manager')

        cls.structure_types = {
            'monthly': cls.env.ref('geo_payroll.structure_type_geo_monthly'),
            'hourly': cls.env.ref('geo_payroll.structure_type_geo_hourly'),
            'daily': cls.env.ref('geo_payroll.structure_type_geo_daily'),
            'unit': cls.env.ref('geo_payroll.structure_type_geo_unit'),
        }
        cls.structures = {
            'monthly': cls.env.ref('geo_payroll.structure_geo_monthly'),
            'hourly': cls.env.ref('geo_payroll.structure_geo_hourly'),
            'daily': cls.env.ref('geo_payroll.structure_geo_daily'),
            'unit': cls.env.ref('geo_payroll.structure_geo_unit'),
        }
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.uom_sqm = cls.env['uom.uom'].create({'name': 'GEO Square Meter', 'relative_factor': 1.0})
        cls.attendance_type = cls.env.ref('hr_work_entry.generic_work_entry_type_attendance')
        cls.project = cls.env['project.project'].create({
            'name': 'GEO Payroll Allowed Project',
            'company_id': cls.company.id,
            'allow_timesheets': True,
        })
        cls.other_project = cls.env['project.project'].create({
            'name': 'GEO Payroll Excluded Project',
            'company_id': cls.company.id,
            'allow_timesheets': True,
        })

    @classmethod
    def _next_name(cls, prefix):
        return f'{prefix} {next(cls._sequence)}'

    @classmethod
    def _scheme_wage_type(cls, scheme):
        return {
            'fixed': 'monthly',
            'hourly': 'hourly',
            'daily': 'daily',
            'fixed_daily': 'monthly',
            'fixed_hourly': 'monthly',
            'daily_hourly': 'daily',
            'unit': 'unit',
            'daily_unit': 'daily',
        }[scheme]

    @classmethod
    def _make_unit_rate(cls, name=None, price=10.0, uom=None, **values):
        create_values = {
            'name': name or cls._next_name('GEO Unit Rate'),
            'uom_id': (uom or cls.uom_sqm).id,
            'price_per_unit': price,
            'currency_id': cls.company.currency_id.id,
        }
        create_values.update(values)
        return cls.env['hr.payroll.unit.rate'].create(create_values)

    @classmethod
    def _make_user(cls, name='GEO User', groups=(), company=None):
        company = company or cls.company
        group_ids = {cls.env.ref('base.group_user').id}
        group_ids.update(group.id for group in groups)
        login = f'geo_payroll_{next(cls._sequence)}@example.com'
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': name,
            'login': login,
            'email': login,
            'company_id': company.id,
            'company_ids': [Command.set([company.id])],
            'group_ids': [Command.set(group_ids)],
        })

    @classmethod
    def _make_employee(
        cls,
        scheme='fixed',
        name=None,
        user=None,
        parent=None,
        company=None,
        structure_type=None,
        project_ids=None,
        **version_values,
    ):
        company = company or cls.company
        wage_type = cls._scheme_wage_type(scheme)
        structure_type = structure_type or cls.structure_types[wage_type]
        values = {
            'name': name or cls._next_name('GEO Employee'),
            'company_id': company.id,
            'date_version': cls.contract_start,
            'contract_date_start': cls.contract_start,
            'contract_date_end': cls.contract_end,
            'resource_calendar_id': company.resource_calendar_id.id,
            'structure_type_id': structure_type.id,
            'pay_scheme': scheme,
            'wage': 1600.0,
            'hourly_wage': 10.0,
            'daily_wage': 80.0,
            'timesheet_pay_project_ids': [Command.set(
                (project_ids or cls.project).ids
            )],
        }
        if scheme in ('fixed_hourly', 'daily_hourly'):
            values['timesheet_pay_start_date'] = cls.contract_start
        if user:
            values['user_id'] = user.id
        if parent:
            values['parent_id'] = parent.id
        values.update(version_values)
        return cls.env['hr.employee'].create(values)

    @classmethod
    def _make_template(cls, scheme='fixed', **values):
        wage_type = cls._scheme_wage_type(scheme)
        create_values = {
            'name': cls._next_name('GEO Contract Template'),
            'company_id': cls.company.id,
            'date_version': cls.contract_start,
            'resource_calendar_id': cls.company.resource_calendar_id.id,
            'structure_type_id': cls.structure_types[wage_type].id,
            'pay_scheme': scheme,
            'wage': 1600.0,
            'hourly_wage': 10.0,
            'daily_wage': 80.0,
        }
        if scheme in ('fixed_hourly', 'daily_hourly'):
            create_values['timesheet_pay_start_date'] = cls.contract_start
        create_values.update(values)
        return cls.env['hr.version'].create(create_values)

    @classmethod
    def _make_work_log(
        cls,
        employee,
        log_type='overtime',
        work_date=None,
        hours=None,
        units=None,
        percentage='100',
        work_unit=None,
        unit_qty=None,
        **values,
    ):
        create_values = {
            'name': cls._next_name('GEO Work Log'),
            'employee_id': employee.id,
            'date': work_date or cls.period_start,
            'type': log_type,
            'hours': hours if hours is not None else (2.0 if log_type == 'overtime' else 0.0),
            'units': units if units is not None else (1.0 if log_type == 'daily' else 0.0),
            'unit_qty': unit_qty if unit_qty is not None else (1.0 if log_type == 'unit' else 0.0),
            'work_unit_id': work_unit.id if work_unit else False,
            'percentage': percentage,
        }
        create_values.update(values)
        return cls.env['hr.employee.work.log'].create(create_values)

    @classmethod
    def _approve_log(cls, employee, **values):
        log = cls._make_work_log(employee, **values)
        log.action_approve()
        return log

    @classmethod
    def _make_timesheet(cls, employee, work_date=None, hours=2.0, project=None, validated=True, **values):
        create_values = {
            'name': cls._next_name('GEO Timesheet'),
            'employee_id': employee.id,
            'project_id': (project or cls.project).id,
            'date': work_date or cls.period_start,
            'unit_amount': hours,
            'validated': validated,
            'company_id': cls.company.id,
        }
        create_values.update(values)
        return cls.env['account.analytic.line'].create(create_values)

    @classmethod
    def _make_payslip(
        cls,
        employee,
        date_from=None,
        date_to=None,
        structure=None,
        version=None,
        worked_hours=None,
        worked_days=20.0,
        **values,
    ):
        date_from = date_from or cls.period_start
        date_to = date_to or cls.period_end
        version = version or employee._get_version(date_from)
        structure = structure or version.structure_type_id.default_struct_id
        create_values = {
            'name': cls._next_name('GEO Payslip'),
            'employee_id': employee.id,
            'version_id': version.id,
            'date_from': date_from,
            'date_to': date_to,
            'struct_id': structure.id,
        }
        create_values.update(values)
        payslip = cls.env['hr.payslip'].create(create_values)
        if worked_hours is not None:
            payslip.worked_days_line_ids.unlink()
            cls.env['hr.payslip.worked_days'].create({
                'payslip_id': payslip.id,
                'version_id': payslip.version_id.id,
                'work_entry_type_id': cls.attendance_type.id,
                'number_of_days': worked_days,
                'number_of_hours': worked_hours,
            })
        return payslip

    @classmethod
    def _make_correction_pair(cls, original):
        if original.state == 'draft':
            original.compute_sheet()
            original.action_payslip_done()
        refund = original._action_refund_payslips()
        correction = original._action_correct_payslips()
        return refund, correction

    @classmethod
    def _make_settlement(
        cls,
        payslip,
        component_code,
        amount,
        work_log=None,
        timesheet=None,
        quantity=1.0,
        rate=None,
        active_claim=True,
        **values,
    ):
        create_values = {
            'work_log_id': work_log.id if work_log else False,
            'timesheet_line_id': timesheet.id if timesheet else False,
            'payslip_id': payslip.id if payslip else False,
            'payslip_ref': payslip.name if payslip else '',
            'employee_id': payslip.employee_id.id,
            'company_id': payslip.company_id.id,
            'currency_id': payslip.company_id.currency_id.id,
            'component_code': component_code,
            'source_version_id': payslip.employee_id._get_version(
                (work_log or timesheet).date).id,
            'date': (work_log or timesheet).date,
            'quantity': quantity,
            'rate': rate if rate is not None else amount / quantity,
            'amount': amount,
            'active_claim': active_claim,
        }
        create_values.update(values)
        return cls.env['hr.payroll.component.settlement'].sudo().create(create_values)

    @staticmethod
    def _line_total(payslip, code):
        return sum(payslip.line_ids.filtered(lambda line: line.code == code).mapped('total'))

    @classmethod
    def _seed_legacy_sources(cls, version, hourly_source='timesheet'):
        version.flush_recordset(['hourly_source'])
        cls.env.cr.execute(
            """
                UPDATE hr_version
                   SET hourly_source = %s
                 WHERE id = %s
             RETURNING id
            """,
            (hourly_source, version.id),
        )
        changed = version.browse([row[0] for row in cls.env.cr.fetchall()])
        changed.invalidate_recordset(['hourly_source'], flush=False)
        changed.modified(['hourly_source'])
        return changed

    @classmethod
    def _seed_attendance_based(cls, version):
        """Flag a version as attendance-tracked without work-entry side effects."""
        version.flush_recordset(['attendance_based'])
        cls.env.cr.execute(
            """
                UPDATE hr_version
                   SET attendance_based = TRUE
                 WHERE id = %s
             RETURNING id
            """,
            (version.id,),
        )
        changed = version.browse([row[0] for row in cls.env.cr.fetchall()])
        changed.invalidate_recordset(['attendance_based'], flush=False)
        changed.modified(['attendance_based'])
        return changed

    @classmethod
    def _today(cls):
        return fields.Date.context_today(cls.env['hr.employee.work.log'])
