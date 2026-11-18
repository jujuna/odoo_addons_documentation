# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging

from odoo import api, fields, models, Command, SUPERUSER_ID, _
from odoo.exceptions import UserError
from odoo.tools import convert_file

_logger = logging.getLogger(__name__)


class HrWorkEntryType(models.Model):
    _inherit = 'hr.work.entry.type'
    _description = 'Time Type'

    display_hours = fields.Boolean(
        string="Display Hours",
        help="If checked, the worked hours will be displayed in the payslip worked days lines.")
    round_days_type = fields.Selection(
        [('HALF-UP', 'Closest'),
         ('UP', 'Up'),
         ('DOWN', 'Down')
        ], string="Rounding Method", required=True, default='DOWN',
        help="According to the Duration Rounding, the duration will be rounded to closest, top, or bottom value")
    category_ids = fields.Many2many('hr.salary.rule.category', string="Salary Rule Categories", groups='hr_payroll.group_hr_payroll_user',
        domain="['|', ('country_id', '=', False), ('country_id', '=', country_id)]")
    optional_category_ids = fields.Many2many('hr.salary.rule.category',
        relation='hr_salary_rule_category_options_hr_work_entry_type_rel',
        string="Optional Categories",
        groups='hr_payroll.group_hr_payroll_user',
        domain="[('country_id', '=', country_id)]",
        help="Categories that can be added optionally on time off created by HR user")
    is_extra_hours = fields.Boolean(compute="_compute_is_extra_hours", store=True,
        help="Indicates if the hours are considered as extra time and added as a bonus to the basic salary.")

    modified_by_user = fields.Boolean(readonly=True, copy=False)

    @api.depends('category_ids')
    def _compute_is_extra_hours(self):
        extra_hours_category = self.env.ref('hr_payroll.EXTRA_HOURS', raise_if_not_found=False)
        for work_entry_type in self:
            work_entry_type.is_extra_hours = extra_hours_category in work_entry_type.category_ids if extra_hours_category else False

    @api.depends('code', 'name')
    @api.depends_context('is_work_time_report')
    def _compute_display_name(self):
        if self.env.context.get('is_work_time_report'):
            for work_entry_type in self:
                work_entry_type.display_name = f"{work_entry_type.name} [{work_entry_type.code}]"
        else:
            super()._compute_display_name()

    def _set_all_external_identifiers_noupdate(self, noupdate):
        self.env['ir.model.data'].sudo().search([
            ('model', '=', "hr.work.entry.type"), ('res_id', 'in', self.ids)
        ]).write({'noupdate': noupdate})
        self.env.flush_all()

    def action_reset_rule(self):
        """
        Restore this time type as defined in the module data
        (:meth:`_update_payroll_related_fields`), then unarchive it and clear
        ``modified_by_user``.

        :return: client action displaying a success notification
        """
        self.ensure_one()
        self.with_user(SUPERUSER_ID)._update_payroll_related_fields()
        self.with_user(SUPERUSER_ID).write({
            'modified_by_user': False,
            'active': True,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'sticky': False,
                'message': self.env._("Time type successfully reset!"),
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def _get_data_files_to_update(self):
        """
        Hook: data files reloaded to reset the payroll fields of time types, as
        ``[(module name, [file paths])]``, in loading order. Localizations append their
        ``data/hr_work_entry_type_data.xml``.

        :rtype: list
        """
        # Note: file order should be maintained
        return [(
            'hr_payroll', [
                'data/hr_work_entry_type_data.xml',
            ])]

    def _update_payroll_related_fields(self, country_code=False):
        """
        Reload the payroll fields of time types from the module data files.

        On records, reset these time types. On an empty recordset (payroll data update), first
        create the missing time types of ``hr_work_entry`` and ``hr_holidays``, then reset all
        the time types not modified by users (of ``country_code`` or without country). The
        update of their XML ids is re-enabled, then the files of
        :meth:`_get_data_files_to_update` are reloaded (only those of ``l10n_<country_code>``
        modules if ``country_code`` is set).

        :param str country_code: restrict the update to that country
        """
        domain = []
        if not self:
            # That file is flagged `noupdate`: loading it only creates the time types missing from
            # the database, so that the payroll data files below can safely reference the new ones.
            _logger.info("Loading new time types from hr_work_entry/data/hr_work_entry_type_data.xml")
            convert_file(self.env, 'hr_work_entry', 'data/hr_work_entry_type_data.xml', {})
            _logger.info("Loading new time types' Time off data from hr_holidays/data/hr_work_entry_type_data.xml")
            convert_file(self.env, 'hr_holidays', 'data/hr_work_entry_type_data.xml', {})
            domain = [('modified_by_user', '=', False)]
            if country_code:
                domain.append(('country_id.code', 'in', [country_code, False]))

        time_types_to_update = self if self else self.env['hr.work.entry.type'].search(domain)
        time_types_to_update._set_all_external_identifiers_noupdate(False)
        data_to_update = self._get_data_files_to_update()
        for module_name, files_to_update in data_to_update:
            if country_code and not module_name.startswith(f"l10n_{country_code.lower()}"):
                continue
            for file_to_update in files_to_update:
                _logger.info("Updating %s/%s", module_name, file_to_update)
                convert_file(self.env, module_name, file_to_update, {})

    @api.ondelete(at_uninstall=False)
    def _unlink_except_work_entry_type(self):
        if self and self.env.uid != SUPERUSER_ID:
            raise UserError(_("You cannot delete time type(s). Instead archive it."))

    @api.model
    def _get_critical_fields(self):
        """
        Return the payroll fields of time types. When a user changes one of them on a time type
        created by the system, it is flagged ``modified_by_user`` and its XML ids are set
        ``noupdate``, so module updates no longer overwrite it (until :meth:`action_reset_rule`).

        :rtype: list
        """
        return ['amount_rate', 'display_hours', 'round_days_type', 'category_ids', 'optional_category_ids', 'is_extra_hours']

    def write(self, vals):
        types_created_by_system = self.filtered(
            lambda r: r.sudo().create_uid.id == SUPERUSER_ID
        )
        if (
            self.env.uid != SUPERUSER_ID
            and types_created_by_system
            and any(f in vals for f in self._get_critical_fields())
        ):
            types_created_by_system._set_all_external_identifiers_noupdate(True)
            vals["modified_by_user"] = True

        return super().write(vals)

    def _load_records_write(self, values):
        self.ensure_one()
        # This optimization reads current values. A caller allowed to `write`
        # but not `read` them should fallback on the standard `write`.
        if (
            not {'amount_rate', 'category_ids'}.intersection(values)
            or not self.has_access('read')
        ):
            return super()._load_records_write(values)

        # PERF: Payroll reloads replay XML values, often writing the same value
        # that's already set in database. That can trigger expensive computes
        # (e.g. `hr.payslip.worked_days.amount`) traversing years of history data,
        # which can be slow and is redundant.

        # The normal write cannot check permissions on fields omitted below.
        for name in ('amount_rate', 'category_ids'):
            if name in values:
                self.check_field_access(self._fields[name], 'write')

        if 'amount_rate' in values:
            rate = self._fields['amount_rate'].convert_to_cache(values['amount_rate'], self)
            if self.amount_rate == rate:
                values.pop('amount_rate')

        if isinstance(commands := values.get('category_ids'), list):
            category_ids = set(self.category_ids.ids)
            all_category_ids = set(self.with_context(active_test=False).category_ids.ids)
            inactive_category_ids = all_category_ids - category_ids
            for command in commands:
                match command:
                    case (Command.LINK, category_id) | (Command.LINK, category_id, _):
                        unchanged = category_id in all_category_ids
                    case (Command.UNLINK, category_id) | (Command.UNLINK, category_id, _):
                        unchanged = category_id not in category_ids
                    case (Command.SET, _, target_ids):
                        unchanged = (set(target_ids) | inactive_category_ids) == all_category_ids
                    case (Command.CLEAR, _, _):
                        unchanged = not category_ids
                    case _:
                        unchanged = False
                if not unchanged:
                    break
            else:
                values.pop('category_ids')

        return super()._load_records_write(values)
