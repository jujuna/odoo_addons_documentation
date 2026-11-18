from odoo import models, fields, api, Command


class PosSession(models.Model):
    _inherit = "pos.session"

    l10n_be_employees_clocked_ids = fields.Many2many(
        "hr.employee",
        "employees_session_clocking_info",
        string="Employees clocked-in",
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        return super()._load_pos_data_fields(config_id) + ['l10n_be_employees_clocked_ids']

    @api.model
    def _load_pos_data_read(self, records, config):
        data = super()._load_pos_data_read(records, config)
        # POS users without Employees rights would read, and notify, an empty list
        clocked = {s.id: s.l10n_be_employees_clocked_ids.ids for s in records.sudo()}
        for vals in data:
            vals['l10n_be_employees_clocked_ids'] = clocked.get(vals['id'], [])
        return data

    def set_work_in_out_cashier(self, cashier_id, action="in"):
        self.ensure_one()
        if self.config_id.module_pos_hr:
            # POS users without Employees rights can neither read nor link hr.employee records
            session_sudo = self.sudo()
            cashier = session_sudo.env["hr.employee"].browse(cashier_id)
            clocked_ids = session_sudo.l10n_be_employees_clocked_ids

            if action == 'in' and cashier not in clocked_ids:
                session_sudo.l10n_be_employees_clocked_ids |= cashier
                self._create_clock_events(cashier, 'in')
                if self.config_id.module_pos_hr:
                    self.employee_id = cashier
            elif action == 'out' and cashier in clocked_ids:
                session_sudo.l10n_be_employees_clocked_ids -= cashier
                self._create_clock_events(cashier, 'out')
            self._notify_clocking()
        else:
            super().set_work_in_out_cashier(cashier_id, action=action)

    def work_out_all_cashiers(self):
        self.ensure_one()
        if self.config_id.module_pos_hr:
            session_sudo = self.sudo()
            clocked_ids = session_sudo.l10n_be_employees_clocked_ids
            self._create_clock_events(clocked_ids, 'out')
            session_sudo.l10n_be_employees_clocked_ids = [Command.clear()]
            self._notify_clocking()
            return clocked_ids.mapped('l10n_be_insz_or_bis_number')
        else:
            return super().work_out_all_cashiers()

    def _notify_clocking(self):
        if self.config_id.module_pos_hr:
            self.config_id._notify("CLOCKING", {
                'session_id': self.id,
                'data': {
                    'pos.session': self._load_pos_data_read(self, self.config_id),
                }
            })
