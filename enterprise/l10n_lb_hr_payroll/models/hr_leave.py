# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import models

# Sick leave of the Labour Code (art. 40, Decree-law No. 7607 of 1974), by years of service: (up to years of
# service, days on full pay, days on half pay), half a month counting 15 days. Below 3 months of service the sick
# leave is not paid. The law renews the entitlement within the year (art. 41) without defining the year: the
# calendar year is used, like the income tax.
L10N_LB_SICK_LEAVE_SENIORITY_MONTHS = 3
L10N_LB_SICK_LEAVE_SCALE = [(2, 15, 15), (4, 30, 30), (6, 45, 45), (10, 60, 60), (None, 75, 75)]


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    def _issues_dependencies(self):
        return super()._issues_dependencies() + ['work_entry_type_id', 'date_from', 'date_to', 'employee_id']

    def _l10n_lb_get_sick_leave_types(self):
        """Sick leave on full pay (the type of the requests), on half pay and unpaid."""
        return (
            self.env.ref('hr_work_entry.lb_work_entry_type_sick_leave'),
            self.env.ref('hr_work_entry.l10n_lb_work_entry_type_sick_leave_half'),
            self.env.ref('hr_work_entry.l10n_lb_work_entry_type_sick_leave_unpaid'),
        )

    def _l10n_lb_is_sick_leave_to_split(self):
        self.ensure_one()
        return (
            self.company_id.country_code == 'LB'
            and self.employee_id
            and self.request_date_from
            and self.request_date_to
            and self.work_entry_type_id == self.env.ref('hr_work_entry.lb_work_entry_type_sick_leave')
        )

    def _l10n_lb_get_sick_leave_entitlement(self, day, service_start):
        """Days on full pay and on half pay of the year for the years of service reached on ``day``."""
        for years, full_pay_days, half_pay_days in L10N_LB_SICK_LEAVE_SCALE:
            if years is None or day <= service_start + relativedelta(years=years):
                return full_pay_days, half_pay_days
        return 0, 0

    def _l10n_lb_get_used_sick_days(self, year):
        """Days of sick leave on full pay and on half pay already taken in the calendar year, by the validated
        requests starting before this one."""
        self.ensure_one()
        full_pay_type, half_pay_type, _unpaid_type = self._l10n_lb_get_sick_leave_types()
        year_start, year_end = date(year, 1, 1), date(year, 12, 31)
        leaves = self.env['hr.leave'].search([
            ('id', 'not in', self._origin.ids),
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'validate'),
            ('work_entry_type_id', 'in', (full_pay_type | half_pay_type).ids),
            ('request_date_from', '<', self.request_date_from),
            ('request_date_from', '<=', year_end),
            ('request_date_to', '>=', year_start),
        ])
        used = {full_pay_type: 0, half_pay_type: 0}
        for leave in leaves:
            used[leave.work_entry_type_id] += (min(leave.request_date_to, year_end) - max(leave.request_date_from, year_start)).days + 1
        return used[full_pay_type], used[half_pay_type]

    def _get_l10n_lb_sick_leave_split(self):
        """Split of a sick leave on full pay of the Labour Code (art. 40 and 41), in calendar days:

        - below 3 months of service: unpaid
        - then, every calendar year, depending on the years of service: from 3 months to 2 years, half a month on
          full pay then half a month on half pay; up to 4 years, 1 month and 1 month; up to 6 years, 1.5 and 1.5
          months; up to 10 years, 2 and 2 months; beyond 10 years, 2.5 and 2.5 months
        - unpaid beyond

        The days already taken on full pay and on half pay in the calendar year are deducted. The years of service
        are those reached on the first paid day of the leave in each calendar year. A leave over two calendar years
        is split at the 1st of January, the entitlement being renewed.

        :return: ordered list of tuples (work entry type, number of days)
        """
        self.ensure_one()
        full_pay_type, half_pay_type, unpaid_type = self._l10n_lb_get_sick_leave_types()
        service_start = self.employee_id.sudo()._get_first_version_date()
        paid_from = service_start + relativedelta(months=L10N_LB_SICK_LEAVE_SENIORITY_MONTHS) if service_start else False
        result = []

        def add(work_entry_type, days):
            if days <= 0:
                return
            if result and result[-1][0] == work_entry_type:
                result[-1] = (work_entry_type, result[-1][1] + days)
            else:
                result.append((work_entry_type, days))

        day = self.request_date_from
        while day <= self.request_date_to:
            segment_end = min(self.request_date_to, date(day.year, 12, 31))
            days = (segment_end - day).days + 1
            if not paid_from or paid_from > segment_end:
                add(unpaid_type, days)
                day = segment_end + timedelta(days=1)
                continue
            if day < paid_from:
                unpaid_days = (paid_from - day).days
                add(unpaid_type, unpaid_days)
                days -= unpaid_days
                day = paid_from
            full_pay_days, half_pay_days = self._l10n_lb_get_sick_leave_entitlement(day, service_start)
            used_full_pay_days, used_half_pay_days = self._l10n_lb_get_used_sick_days(day.year)
            paid_full = min(days, max(full_pay_days - used_full_pay_days, 0))
            paid_half = min(days - paid_full, max(half_pay_days - used_half_pay_days, 0))
            add(full_pay_type, paid_full)
            add(half_pay_type, paid_half)
            add(unpaid_type, days - paid_full - paid_half)
            day = segment_end + timedelta(days=1)
        return result

    def _action_validate(self, check_state=True):
        l10n_lb_sick_leaves = self.filtered(lambda leave: leave._l10n_lb_is_sick_leave_to_split()).sorted('request_date_from')
        res = True
        for l10n_lb_employee_sick_leaves in l10n_lb_sick_leaves.grouped('employee_id').values():
            # Validated one by one: the days taken by a request reduce the entitlement left for the next ones
            for sick_leave in l10n_lb_employee_sick_leaves:
                new_leaves = sick_leave._create_leaves_from_split(sick_leave._get_l10n_lb_sick_leave_split())
                res &= super(HrLeave, new_leaves)._action_validate(check_state=check_state)
        res &= super(HrLeave, self - l10n_lb_sick_leaves)._action_validate(check_state=check_state)
        return res
