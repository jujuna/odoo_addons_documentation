from odoo import _, api, models


class IrActionsActions(models.Model):
    _inherit = 'ir.actions.actions'

    @api.model
    def get_bindings(self, model_name):
        result = super().get_bindings(model_name)
        rules = self.env['gec.access.profile']._current_rules()
        if not rules.enabled:
            return result
        kept = {}
        for action_type, actions in result.items():
            if action_type == 'report' and rules.model_flag(model_name, 'hide_print'):
                continue
            if action_type == 'action' and rules.model_flag(model_name, 'hide_action_menu'):
                continue
            visible = [
                action for action in actions
                if not (rules.hides_report(action['id']) or rules.hides_action(action['id']))
            ]
            if visible:
                kept[action_type] = visible
        return kept


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _gec_check_report_access(self, report_ref):
        """ Refuse a hidden report or a Hide Print model. Only the report routes call it: Odoo's own rendering
        (Send & Print, mail templates) is not the user printing and must pass. """
        rules = self.env['gec.access.profile']._current_rules()
        if not rules.enabled:
            return
        report = self._get_report(report_ref)
        if rules.hides_report(report.id) or rules.model_flag(report.model, 'hide_print'):
            raise self.env['gec.access.profile']._gec_refusal(_(
                "Your access profile does not allow printing '%s'.",
                report.name), model=report.model, method=report.report_name)


class IrActionsServer(models.Model):
    _inherit = 'ir.actions.server'

    def run(self):
        """ Refuse a hidden server action run by a client call (call_kw, XML-RPC), as /web/action/run does;
        Odoo's own runs (automations, buttons, crons) are not checked. """
        if self._gec_rpc_entry('run'):
            for action in self:
                self.env['gec.access.profile']._check_action(action.id)
        return super().run()
