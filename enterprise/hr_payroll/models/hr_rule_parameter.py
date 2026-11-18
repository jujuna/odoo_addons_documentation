# Part of Odoo. See LICENSE file for full copyright and licensing details.

from copy import deepcopy

from odoo import api, fields, models, SUPERUSER_ID

from odoo.exceptions import UserError
from odoo.tools.safe_eval import expr_eval

_PARAMETER_NOT_FOUND = object()


class HrRuleParameter(models.Model):
    _name = 'hr.rule.parameter'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Salary Rule Parameter'
    _clear_cache_name = 'default'
    _clear_cache_on_fields = {'code'}

    name = fields.Char(required=True, tracking=True, translate=True)
    code = fields.Char(required=True, tracking=True, copy=lambda r: f'{r.code}_copy',
        help="This code is used in salary rules to refer to this parameter.")
    active = fields.Boolean(default=True)
    description = fields.Html()
    country_id = fields.Many2one('res.country', string='Country', default=lambda self: self.env.company.country_id)
    country_code = fields.Char(related='country_id.code')
    parameter_version_ids = fields.One2many('hr.rule.parameter.value', 'rule_parameter_id', string='Versions', copy=True)
    current_value_one_line = fields.Text(string='Current Value (short)', compute='_compute_current_value')
    valid_since = fields.Date(compute='_compute_current_value')
    salary_rule_ids = fields.One2many('hr.salary.rule', compute='_compute_salary_rule', string='Salary Rules')
    salary_rule_count = fields.Integer(compute='_compute_salary_rule')
    modified_by_user = fields.Boolean(readonly=True, copy=False)
    created_by_user = fields.Boolean(readonly=True, default=lambda self: self.env.uid != SUPERUSER_ID, copy=False)

    _unique_code = models.UniqueIndex(
        '(code) WHERE (active IS TRUE)',
        "Two rule parameters cannot have the same code.",
    )

    @api.model
    def _get_parameter_from_code(self, code, date=None, raise_if_not_found=True):
        """
        Return the value of the rule parameter ``code`` at ``date``.

        The value is the ``parameter_value`` of the most recent ``hr.rule.parameter.value`` with
        ``date_from <= date``, evaluated with :func:`~odoo.tools.safe_eval.expr_eval` (literals,
        lists, tuples, dicts, arithmetic, comparisons, ``min``/``max``): typically a number, a
        list of brackets or a dict. The lookup is cached and the result is a deep copy, which can
        be modified safely. In salary rules, use ``payslip._rule_parameter(code)``, which takes
        the payslip reference date (``date_to``) by default.

        :param str code: code of the rule parameter
        :param date: reference date, today if not set
        :type date: datetime.date
        :param bool raise_if_not_found: if no value exists at that date, raise instead of
            returning ``None``
        :return: the evaluated value
        :raise UserError: if no value is found and ``raise_if_not_found`` is set
        """
        if not date:
            date = fields.Date.today()
        parameter_value = self._get_cached_parameter_from_code(code, date)
        if parameter_value is not _PARAMETER_NOT_FOUND:
            return deepcopy(parameter_value)
        if raise_if_not_found:
            raise UserError(self.env._('No rule parameter with code "%(code)s" was found for %(date)s', code=code, date=date))
        return None

    @api.model
    @api.ormcache('code', 'date', 'frozenset(self.env.companies.ids)')
    def _get_cached_parameter_from_code(self, code, date):
        """
        Cached lookup of :meth:`_get_parameter_from_code`: return the evaluated value, or the
        ``_PARAMETER_NOT_FOUND`` sentinel. The cache is invalidated when parameter values are
        created, deleted, or written on ``date_from`` or ``parameter_value``.
        """
        # a datetime or a string compares as its day, as it did in the query
        date = fields.Date.to_date(date)
        for date_from, parameter_value in self._get_cached_parameter_values(code):
            if date_from <= date:
                return expr_eval(parameter_value)
        return _PARAMETER_NOT_FOUND

    @api.model
    @api.ormcache('code', 'frozenset(self.env.companies.ids)')
    def _get_cached_parameter_values(self, code):
        """
        Return the ``(date_from, parameter_value)`` of all the values of the parameter ``code``,
        most recent first, with a single query whatever the dates they are then looked up at.
        Invalidated with :meth:`_get_cached_parameter_from_code`.

        :rtype: tuple[tuple[date, str]]
        """
        values = self.env['hr.rule.parameter.value'].search_fetch(
            [('code', '=', code)], ['date_from', 'parameter_value'], order='date_from desc')
        return tuple((value.date_from, value.parameter_value) for value in values)

    @api.depends('parameter_version_ids')
    def _compute_current_value(self):
        today = fields.Date.context_today(self)
        for rule_parameter in self:
            rule_parameter.current_value_one_line = False
            rule_parameter.valid_since = False
            if not rule_parameter.parameter_version_ids:
                continue

            # All values are already order from most recent to oldest.
            # Here we get the first value that is not in the future, i.e. the current value.
            for value_id in rule_parameter.parameter_version_ids:
                if value_id.date_from <= today:
                    parameter_value = value_id.parameter_value or ''
                    is_number = parameter_value.replace('-', '').replace('.', '').isnumeric()
                    rule_parameter.current_value_one_line = parameter_value if is_number else '(...)'
                    rule_parameter.valid_since = value_id.date_from
                    break

    def _compute_salary_rule(self):
        for rule_parameter in self:
            rule_parameter.salary_rule_ids = self.env['hr.salary.rule'].search([
                '|',
                '|',
                ('condition_python', 'like', "'" + rule_parameter.code + "'"),
                ('amount_python_compute', 'like', "'" + rule_parameter.code + "'"),
                '|',
                ('condition_python', 'like', '"' + rule_parameter.code + '"'),
                ('amount_python_compute', 'like', '"' + rule_parameter.code + '"'),
            ]) if rule_parameter.code else False
            rule_parameter.salary_rule_count = len(rule_parameter.salary_rule_ids)

    def action_open_salary_rules(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('hr_payroll.action_salary_rule_form')
        action.update({
            'domain': [
                '|',
                '|',
                ('condition_python', 'like', "'" + self.code + "'"),
                ('amount_python_compute', 'like', "'" + self.code + "'"),
                '|',
                ('condition_python', 'like', '"' + self.code + '"'),
                ('amount_python_compute', 'like', '"' + self.code + '"'),
            ],
        })
        return action

    def _set_all_external_identifiers_noupdate(self, noupdate):
        """
        Set the ``noupdate`` flag of the XML ids of these parameters and of their values.

        :param bool noupdate: ``True`` to protect them from module updates
        """
        rule_parameter_values = self.env['hr.rule.parameter.value'].search([
            ('rule_parameter_id', 'in', self.ids)
        ])
        rule_param_data = self.env['ir.model.data'].sudo().search([
            ('model', '=', "hr.rule.parameter"),
            ('res_id', 'in', self.ids)
        ]) + self.env['ir.model.data'].sudo().search([
            ('model', '=', "hr.rule.parameter.value"),
            ('res_id', 'in', rule_parameter_values.ids)
        ])
        rule_param_data.write({'noupdate': noupdate})
        self.env.flush_all()

    def write(self, vals):
        """
        Write on the parameters. When a user modifies a parameter created by the system, it is
        flagged ``modified_by_user`` and its XML ids (and those of its values) are set
        ``noupdate``.
        """
        rule_parameters_created_by_system = self.filtered(lambda r: r.create_uid.id == SUPERUSER_ID)
        if self.env.uid != SUPERUSER_ID and rule_parameters_created_by_system:
            rule_parameters_created_by_system._set_all_external_identifiers_noupdate(True)
            vals['modified_by_user'] = True
        return super().write(vals)

    def action_reset_rule_parameter(self):
        """
        Restore this parameter as defined in the module data: delete the values created by
        users, re-enable the update of the XML ids, reload the payroll data files of its country
        (``hr.payslip._update_payroll_data``), then unarchive it and clear ``modified_by_user``.

        :return: client action displaying a success notification
        """
        self.ensure_one()
        rule_parameter_values = self.env['hr.rule.parameter.value'].search([
            ('rule_parameter_id', '=', self.id)
        ])
        values_created_by_user = rule_parameter_values.filtered(lambda r: r.create_uid.id != SUPERUSER_ID)
        if values_created_by_user:
            values_created_by_user.with_user(SUPERUSER_ID).unlink()
        self._set_all_external_identifiers_noupdate(False)
        self.env['hr.payslip'].with_user(SUPERUSER_ID)._update_payroll_data(country_code=self.country_id.code)
        self._message_log(body=self.env._('Salary Rule Parameter reset'))
        self.with_user(SUPERUSER_ID).write({
            'modified_by_user': False,
            'active': True,
        })
        self.with_user(SUPERUSER_ID).parameter_version_ids.modified_by_user = False
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'sticky': False,
                'message': self.env._("Salary Rule Parameter successfully reset!"),
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    @api.ondelete(at_uninstall=False)
    def unlink_rule_parameter(self):
        if self.env.uid != SUPERUSER_ID and SUPERUSER_ID in self.create_uid.mapped('id'):
            raise UserError(self.env._('You cannot delete a rule parameter created by the system.\nArchive it instead.'))
