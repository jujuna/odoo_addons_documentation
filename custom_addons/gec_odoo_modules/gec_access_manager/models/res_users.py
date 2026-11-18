from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.tools import LazyTranslate

from odoo.addons.gec_user_audit.models.client_call import client_address

from .login_tools import utc_now

EXPORT_GROUP = 'base.group_allow_export'
_lt = LazyTranslate(__name__)
LOGIN_REFUSALS = {
    'hours': _lt("Your access profile only allows signing in during your working hours."),
    'network': _lt("Your access profile does not allow signing in from this network."),
}
# session key holding the sign-in moment (One Session per User)
LOGIN_STAMP_KEY = 'gec_access_login_stamp'
USER_FIELDS_IN_FILTERS = ('company_ids', 'property_warehouse_id')


class ResUsers(models.Model):
    _inherit = 'res.users'

    access_allowed_ids = fields.One2many(
        'gec.access.allowed', 'user_id', string='Allowed Records', groups='gec_access_manager.group_access_manager',
        help="Used by profiles whose allowed records are 'Each User's Own'. For example, this user's point of sale or "
             "warehouse.")
    access_assignment_ids = fields.One2many(
        'gec.access.profile.assignment', 'user_id', string='Temporary Profiles',
        groups='gec_access_manager.group_access_manager')
    gec_access_login_stamp = fields.Float(
        copy=False, groups='gec_access_manager.group_access_manager',
        help="When the user last signed in. Used by 'One Session per User'.")
    access_effective = fields.Html(
        string='Effective Access', compute='_compute_access_effective', sanitize=False,
        groups='gec_access_manager.group_access_manager',
        help="What this user can actually do, with all their profiles combined.")
    access_profile_ids = fields.Many2many(
        'gec.access.profile', 'gec_access_profile_users_rel', 'uid', 'profile_id',
        string='Access Profiles', groups='gec_access_manager.group_access_manager',
        help="A user can have several profiles. Additive profiles add up: an action is allowed if one of them allows "
             "it. Override profiles always limit.")

    def _after_session_login(self):
        """ Stamp the sign-in under One Session per User once the session is open: with 2FA the password alone is not
        a sign-in, and an API call opens no session. An older session ends on its next request (ir_http.py). """
        super()._after_session_login()
        if request:
            rules = self.env['gec.access.profile']._resolve(self.id)
            if rules.enabled and rules.has_flag('single_session'):
                stamp = utc_now().timestamp()
                request.session[LOGIN_STAMP_KEY] = stamp
                self.sudo().gec_access_login_stamp = stamp

    @api.depends('access_profile_ids', 'access_allowed_ids')
    def _compute_access_effective(self):
        Report = self.env['gec.access.test.user']
        for user in self:
            user.access_effective = Report.new({'user_id': user.id}).report if user.id else False

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users.sudo().access_profile_ids._gec_check_editor()
        users.sudo().access_profile_ids._sync_group()
        internal = users.filtered(lambda user: not user.share)
        if internal:
            profiles = self.env['gec.access.profile'].sudo().search([('for_new_users', '=', True)])
            if profiles:
                # the profiles every new user gets are not chosen by the creator
                internal.with_user(SUPERUSER_ID).write(
                    {'access_profile_ids': [(4, profile.id) for profile in profiles]})
        return users

    def write(self, vals):
        """ Check editors only for profiles a user gains or loses (one a Settings user gave stays); keep the groups of
        the profiles involved in step, company-restricted ones too when the user's companies change; refuse a
        change that locks every access manager out. """
        users = self.sudo()
        before = {user.id: user.access_profile_ids for user in users} if 'access_profile_ids' in vals else None
        result = super().write(vals)
        if 'access_profile_ids' in vals:
            changed = self.env['gec.access.profile'].sudo()
            for user in users:
                after = user.access_profile_ids
                changed |= (before[user.id] - after) | (after - before[user.id])
            changed._gec_check_editor()
            (changed | users.access_profile_ids)._sync_group()
            # the guard against locking every administrator out applies here too
            self.sudo().access_profile_ids._check_last_administrator()
            self.env.transaction.invalidate_ormcache('default')
        elif vals.get('active') is False or 'group_ids' in vals:
            # archiving, or taking out of Access Management, the last manager able to undo the profiles
            self.env['gec.access.profile'].sudo().search([])._check_last_administrator()
        elif not set(vals).isdisjoint(USER_FIELDS_IN_FILTERS) or not set(vals).isdisjoint(
                self.env['gec.access.profile']._gec_user_fields_in_filters()):
            # _resolve() depends on the user's companies, and record filters read the default warehouse
            self.env.transaction.invalidate_ormcache('default')
        if 'company_ids' in vals:
            running = self.env['gec.access.profile.assignment'].sudo().search(
                [('user_id', 'in', users.ids), ('state', '=', 'active')]).profile_id
            (users.access_profile_ids | running).filtered('company_id')._sync_group()
            # also when the same write changes group_ids, which takes the branch above
            self.env.transaction.invalidate_ormcache('default')
        return result

    def has_group(self, group_ext_id):
        result = super().has_group(group_ext_id)
        if not result or group_ext_id != EXPORT_GROUP:
            return result
        if self.id != self.env.uid:
            return result
        # the Export menu, export_data() and the export controller all check this group; env.user is sudo
        rules = self.env['gec.access.profile']._resolve(self.id)
        if rules.enabled and rules.has_flag('block_export'):
            return False
        return result

    def _gec_check_sign_in_rules(self, interactive):
        """ Refuse a sign-in the profiles forbid: a blocked login, hours or networks, and for the external API
        (``interactive`` False) its block. Run when a credential is checked and on every XML-RPC/JSON-RPC call
        (_check_uid_passwd), whose password check is cached. """
        for user in self:
            rules = self.env['gec.access.profile']._resolve(user.id)
            if not rules.enabled:
                continue
            if rules.has_flag('block_login'):
                raise AccessDenied(_("Your access profile does not allow you to sign in."))
            reason = rules.login_refusal(utc_now(), client_address())
            if reason:
                raise AccessDenied(self.env._(LOGIN_REFUSALS[reason]))
            if not interactive and rules.has_flag('block_rpc'):
                raise AccessDenied(_("Your access profile does not allow signing in through the external API."))

    def _check_credentials(self, credential, env):
        result = super()._check_credentials(credential, env)
        # after super(), so it covers every kind of credential once accepted; 'interactive' is False for XML/JSON-RPC
        self._gec_check_sign_in_rules(env.get('interactive', True))
        return result

    @api.model
    def _check_uid_passwd(self, uid, passwd):
        """ Every XML-RPC/JSON-RPC object call checks the password here, cached by Odoo: the profile rules are checked
        again each time, so hours and blocks apply to a session already open. """
        super()._check_uid_passwd(uid, passwd)
        self.browse(uid)._gec_check_sign_in_rules(interactive=False)

    def _session_token_get_values(self):
        # the session token is checked on every request: changing it while the login is blocked ends open sessions
        values = super()._session_token_get_values()
        if values:
            rules = self.env['gec.access.profile']._resolve(self.id)
            if rules.enabled and rules.has_flag('block_login'):
                values += (('gec_access_block_login', True),)
        return values

    @api.model
    def _get_access_profile_action(self):
        return self.env.ref('gec_access_manager.gec_access_profile_action').sudo().read()[0]
