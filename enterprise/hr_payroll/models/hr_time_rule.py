# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models
from odoo.fields import Command


class HrTimeRule(models.Model):
    _inherit = 'hr.time.rule'

    premium_pay_category_ids = fields.Many2many(
        'hr.salary.rule.category',
        string='Premium Pay Categories',
        domain="[('optional_on_work_entry_type_ids', 'in', country_work_entry_type_ids)]",
        groups='hr_payroll.group_hr_payroll_user',
    )

    def _get_pp_frozenset(self):
        """
        Return the ids of the premium pay categories of this rule, attached as category options
        to the intervals it classifies.

        :rtype: frozenset
        """
        self.ensure_one()
        return frozenset(self.premium_pay_category_ids.ids)

    def _get_output_leave_merge_key(self, accumulated_pp=frozenset()):
        """
        Extend the merge key with the premium pay categories: consecutive slices with different
        premium pays are not merged into one time off.
        """
        base = super()._get_output_leave_merge_key(accumulated_pp=accumulated_pp)
        return (base, accumulated_pp)

    def _get_source_annotation_vals(self, accumulated_pp=frozenset()):
        """
        Set the accumulated premium pay categories as ``category_options_ids`` of the source
        record repurposed in place.
        """
        if not accumulated_pp:
            return {}
        return {'category_options_ids': [Command.set(list(accumulated_pp))]}

    def _get_output_leave_vals(self, employee, rule, date_from, date_to, source_leave, accumulated_pp=frozenset()):
        """
        Set the accumulated premium pay categories as ``category_options_ids`` of the generated
        time off.
        """
        vals = super()._get_output_leave_vals(
            employee, rule, date_from, date_to, source_leave,
            accumulated_pp=accumulated_pp,
        )
        if accumulated_pp:
            vals['category_options_ids'] = [Command.set(list(accumulated_pp))]
        return vals
