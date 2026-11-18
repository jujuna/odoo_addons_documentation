# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import timedelta, UTC
from zoneinfo import ZoneInfo

from odoo import fields, models
from odoo.fields import Domain
from odoo.tools import float_round


class HrLeaveAllocationGenerateMultiWizard(models.TransientModel):
    _inherit = 'hr.leave.allocation.generate.multi.wizard'

    public_holiday_id = fields.Many2one('resource.calendar.leaves', string='Public Holiday', readonly=True)

    def _get_public_holiday_dates(self):
        """The first and last days of the public holiday, stored in UTC, in the company's time zone."""
        tz = ZoneInfo((self.public_holiday_id.company_id or self.env.company).tz or self.env.user.tz or 'UTC')
        return (
            self.public_holiday_id.date_from.replace(tzinfo=UTC).astimezone(tz).date(),
            self.public_holiday_id.date_to.replace(tzinfo=UTC).astimezone(tz).date(),
        )

    def _get_employee_domain(self):
        domain = super()._get_employee_domain()
        if not self.public_holiday_id:
            return domain
        leave_date_from, leave_date_to = self._get_public_holiday_dates()
        versions = self.env['hr.version'].search([
            ('l10n_be_worker_code_id', '!=', False),
            ('l10n_be_joint_committee_id.egov3_code', '!=', '999'),
            ('contract_date_start', '<=', leave_date_to),
            '|',
            ('contract_date_end', '=', False),
            ('contract_date_end', '>=', leave_date_from),
        ])
        return Domain.AND([domain, [
            ('active', '=', True),
            ('id', 'in', versions.employee_id.ids),
        ]])

    def _prepare_allocation_values(self, employees):
        self.ensure_one()
        if not self.public_holiday_id:
            return super()._prepare_allocation_values(employees)

        leave = self.public_holiday_id
        company = leave.company_id or self.env.company
        leave_date_from, leave_date_to = self._get_public_holiday_dates()

        existing = self.env['hr.leave.allocation'].search([
            ('work_entry_type_id', '=', self.work_entry_type_id.id),
            ('public_holiday_id', '=', leave.id),
            ('employee_id', 'in', employees.ids),
        ])
        already_allocated_employees = existing.mapped('employee_id')
        employees = employees - already_allocated_employees

        result = []
        for employee in employees:
            days = 0
            for version in employee.version_ids.filtered('contract_date_start'):
                overlap_start = max(leave_date_from, version.date_start)
                overlap_end = min(leave_date_to, version.date_end or leave_date_to)
                if overlap_end < overlap_start:
                    continue
                current_date = overlap_start
                while current_date <= overlap_end:
                    if not company.resource_calendar_id._works_on_date(current_date):
                        days += 1
                    current_date += timedelta(days=1)

            if not days:
                continue

            self._adjust_allocation_name(days)
            result.append({
                'name': self.name,
                'work_entry_type_id': self.work_entry_type_id.id,
                'number_of_days': days,
                'employee_id': employee.id,
                'state': 'confirm',
                'date_from': self.date_from,
                'date_to': self.date_to,
                'accrual_plan_id': self.accrual_plan_id.id,
                'notes': self.notes,
                'public_holiday_id': leave.id,
            })
        return result

    def _adjust_allocation_name(self, days):
        if float_round(self.duration, precision_digits=2) != days:
            self.name = self.env._(
                '%(name)s (%(duration)s %(unit_of_measure)s(s))',
                name=self.work_entry_type_id.name,
                duration=float_round(days, precision_digits=2),
                unit_of_measure=self.unit_of_measure
            )
