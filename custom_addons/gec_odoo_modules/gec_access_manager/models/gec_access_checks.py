from odoo import Command, _, api, models
from odoo.exceptions import AccessError, UserError

from .field_guard import ARCHIVE_FIELDS
from .gec_access_rules import BLOCK_MODES


class GecAccessProfile(models.Model):
    _inherit = 'gec.access.profile'

    @api.model
    def _gec_refusal(self, message, **values):
        """ The error refusing an operation, logged in the audit log first: the line survives the rollback. """
        self.env['gec.user.audit.log']._gec_log('refused', separate=True, detail=message, **values)
        return AccessError(message)

    def _check_button(self, model_name, button_type, name, ids=None):
        """ Refuse a blocked button; one blocked under a condition only on the records ``ids`` matching it. """
        rules = self._current_rules()
        if not rules.enabled:
            return
        condition = rules.button_condition(BLOCK_MODES, model_name, button_type, name)
        if condition is None:
            return
        if condition is not True:
            # only records the user may read are judged: Odoo refuses the rest, and judging them would reveal a match
            readable = (self.env[model_name].browse([int(record_id) for record_id in ids])._filtered_access('read')
                        if ids and model_name in self.env else None)
            if not (readable and readable._gec_matching(condition, readable.ids)):
                return
        raise self._gec_refusal(_(
            "You cannot use this button.\n\nYour access profile blocks '%(button)s' on '%(model)s'.",
            button=name, model=model_name), model=model_name, method=name, record_ids=ids or [])

    @api.model
    def _check_archive(self, model_name):
        rules = self._current_rules()
        if rules.enabled and rules.model_flag(model_name, 'hide_archive'):
            raise UserError(_(
                "Your access profile does not allow archiving '%s'.",
                self.env['ir.model']._get(model_name).name or model_name))

    @api.model
    def _check_archive_call(self, model_name, method, args, kwargs):
        """ Refuse a client write, web_save or web_save_multi setting ``active`` when a profile hides Archive; a create,
        or a web_save without ids, has only its x2many commands checked. Run at the controllers on what the client sent:
        in the ORM, Odoo's own archiving (recurrences...) cannot be told apart. ``args`` start with the ids. """
        if method not in ('create', 'write', 'web_save', 'web_save_multi'):
            return
        if method == 'create':
            creating = True
            values = (args[0] if args else None) or kwargs.get('vals_list', kwargs.get('vals'))
        else:
            creating = method != 'write' and not (args and args[0])
            values = args[1] if len(args) > 1 else kwargs.get('vals', kwargs.get('vals_list'))
        check = self._check_archive_commands if creating else self._check_archive_values
        for vals in values if isinstance(values, (list, tuple)) else [values]:
            check(model_name, vals)

    @api.model
    def _check_archive_values(self, model_name, vals, creating=False):
        """ Refuse ``vals`` setting ``active`` on ``model_name`` or, at any depth, on the records its x2many commands
        create or update, when a profile hides Archive for them; with ``creating``, only archiving values count. """
        if not isinstance(vals, dict):
            return
        if any(not creating or not vals[name] for name in ARCHIVE_FIELDS.intersection(vals)):
            self._check_archive(model_name)
        self._check_archive_commands(model_name, vals)

    @api.model
    def _check_archive_commands(self, model_name, vals):
        """ The x2many part of ``_check_archive_values``: the commands of ``vals`` that create or update records. """
        if not isinstance(vals, dict) or model_name not in self.env:
            return
        model_fields = self.env[model_name]._fields
        for name, commands in vals.items():
            field = model_fields.get(name)
            if field is None or field.type not in ('one2many', 'many2many') or not isinstance(commands, (list, tuple)):
                continue
            for command in commands:
                if isinstance(command, (list, tuple)) and len(command) > 2 and command[0] in (
                        Command.CREATE, Command.UPDATE):
                    self._check_archive_values(field.comodel_name, command[2], creating=command[0] == Command.CREATE)

    @api.model
    def _check_action(self, action_id):
        rules = self._current_rules()
        if not rules.enabled or not action_id:
            return
        if (rules.hides_report(action_id)
                or rules.hides_action(action_id)
                or rules.blocks_action(action_id)
                or self._hides_menu_of(rules, action_id)):
            action = self.env['ir.actions.actions'].sudo().browse(action_id).exists()
            raise self._gec_refusal(_(
                "You cannot run this action.\n\nYour access profile hides it."), method=action.name or str(action_id))

    @api.model
    def _check_hidden_menu_action(self, action_id):
        """ Refuse an action all of whose menus a profile hides, since its URL would still work. """
        rules = self._current_rules()
        if not rules.enabled or not action_id:
            return
        hidden = rules.menu_blacklist()
        action = self.env['ir.actions.actions'].sudo().browse(action_id).exists()
        if not hidden or not action:
            return
        menus = self.env['ir.ui.menu'].sudo().with_context(active_test=False).search(
            [('action', '=', f'{action.type},{action.id}')])
        if menus and all(menu.id in hidden for menu in menus):
            raise self._gec_refusal(_(
                "You cannot run this action.\n\nYour access profile hides it."), method=action.name or str(action_id))

    @api.model
    def _hides_menu_of(self, rules, action_id):
        """ Whether the action is in a Print or Action menu a profile hides (a model's report or Action entry). """
        if not rules.model_flags_set():
            return False
        self.env.cr.execute(
            "SELECT a.type, a.binding_type, m.model FROM ir_actions a "
            "LEFT JOIN ir_model m ON m.id = a.binding_model_id WHERE a.id = %s", [action_id])
        row = self.env.cr.fetchone()
        if not row:
            return False
        action_type, binding_type, binding_model = row
        if action_type == 'ir.actions.report':
            report_model = self.env['ir.actions.report'].sudo().browse(action_id).model
            return rules.model_flag(report_model, 'hide_print')
        return bool(binding_model and binding_type == 'action' and rules.model_flag(binding_model, 'hide_action_menu'))

    @api.model
    def _filter_action_views(self, action):
        """ Drop the view types a profile hides; when it hides all of them, the action stays as it is. """
        if not isinstance(action, dict) or action.get('type') != 'ir.actions.act_window':
            return action
        model_name = action.get('res_model')
        if not model_name:
            return action
        rules = self._current_rules()
        if not rules.enabled:
            return action
        hidden = rules.hidden_view_types(model_name)
        if not hidden:
            return action

        views = [view for view in action.get('views') or [] if view[1] not in hidden]
        if not views:
            return action
        action['views'] = views
        action['view_mode'] = ','.join(view[1] for view in views)
        if action.get('view_type') in hidden:
            action['view_type'] = views[0][1]
        return action
