from fnmatch import fnmatchcase

from odoo import SUPERUSER_ID, api, fields, models
from odoo.tools import frozendict

OPERATIONS = ('read', 'create', 'write', 'unlink', 'export', 'import', 'print')
# models that would only log the logger, Odoo's own bookkeeping or the web client's noise
DEFAULT_EXCLUDED = ('ir.*', 'bus.*', 'base.*', 'base_import.*', 'web_tour.*', 'res.users.log', 'res.users.settings*', 'res.device*', 'res.session*',
    'mail.tracking.value', 'mail.notification', 'mail.followers', 'mail.mail', 'mail.message.schedule', 'mail.link.preview', 'mail.presence',
    'discuss.channel.member', 'gec.user.audit.log', 'res.config*', 'digest.*', 'auth_totp.device', 'iap.*', 'spreadsheet.*revision*')
DEFAULT_KEPT = ('ir.attachment', 'account.analytic.line', 'account.bank.statement.line')


def excluded_from_text(text):
    """ The patterns of the "Never Logged" setting, split by commas or lines; the default list when empty. """
    return tuple(filter(None, (part.strip() for part in text.replace('\n', ',').split(',')))) or DEFAULT_EXCLUDED


class GecUserAuditRule(models.Model):
    _name = 'gec.user.audit.rule'
    _description = 'User Audit Rule'
    _order = 'sequence, id'
    # the parameters are cached there too: a parameter changed by hand reaches the rules
    _clear_cache_name = 'stable'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    model_ids = fields.Many2many('ir.model', 'gec_user_audit_rule_model_rel', 'rule_id', 'model_id', string='Data',
        domain=[('transient', '=', False)], help="Left empty, the rule covers every kind of data but the technical ones.")
    user_ids = fields.Many2many('res.users', 'gec_user_audit_rule_user_rel', 'rule_id', 'user_id', string='Users')
    group_ids = fields.Many2many('res.groups', 'gec_user_audit_rule_group_rel', 'rule_id', 'group_id', string='Groups',
        help="With neither users nor groups, the rule covers everyone.")
    log_read = fields.Boolean(string='Read')
    log_create = fields.Boolean(string='Create', default=True)
    log_write = fields.Boolean(string='Edit', default=True)
    log_unlink = fields.Boolean(string='Delete', default=True)
    log_export = fields.Boolean(string='Export', default=True)
    log_import = fields.Boolean(string='Import', default=True)
    log_print = fields.Boolean(string='Print', default=True)

    @api.model
    @api.ormcache(cache='stable')
    def _gec_policy(self):
        """ The rules and settings, frozen. """
        params = self.env['ir.config_parameter'].sudo()
        excluded = excluded_from_text(params.get_str('gec_user_audit.excluded_models'))
        rules = tuple(frozendict(models=frozenset(rule.model_ids.mapped('model')) or None,
            operations=frozenset(op for op in OPERATIONS if rule[f'log_{op}']), users=frozenset(rule.user_ids.ids),
            groups=frozenset(rule.group_ids.ids)) for rule in self.sudo().search([]))
        return frozendict(rules=rules, excluded=excluded, log_reads=params.get_bool('gec_user_audit.log_reads', False))

    @api.model
    def _gec_excluded(self, model_name, policy):
        if model_name in DEFAULT_KEPT:
            return False
        return any(fnmatchcase(model_name, pattern) for pattern in policy['excluded'])

    @api.model
    @api.ormcache('model_name', 'operation', 'uid', cache='default')
    def _gec_should_log(self, model_name, operation, uid):
        """ Whether ``uid`` is logged for ``operation`` on the model. Cached in 'default', which a
        change of the user's groups clears; the rules and settings clear 'stable', which includes it.
        The log_reads setting only decides reads when no rule exists: a rule ticking Read logs them. """
        if not uid or uid == SUPERUSER_ID:
            return False
        policy = self._gec_policy()
        model = self.env.get(model_name)
        if model is None or model._transient or model._abstract:
            return False
        if not policy['rules']:
            if operation == 'read' and not policy['log_reads']:
                return False
            return not self._gec_excluded(model_name, policy)
        user_groups = None
        for rule in policy['rules']:
            if operation not in rule['operations']:
                continue
            if rule['models'] is None:
                if self._gec_excluded(model_name, policy):
                    continue
            elif model_name not in rule['models']:
                continue
            if rule['users'] or rule['groups']:
                if uid not in rule['users']:
                    if user_groups is None:
                        user_groups = set(self.env['res.users'].sudo().browse(uid).all_group_ids.ids)
                    if not rule['groups'] & user_groups:
                        continue
            return True
        return False
