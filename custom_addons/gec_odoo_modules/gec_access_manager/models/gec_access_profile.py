import logging

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .gec_access_rules import GLOBAL_FLAGS, GROUP_FIELDS, UNGRANTABLE_GROUPS

_logger = logging.getLogger(__name__)


class GecAccessProfile(models.Model):
    _name = 'gec.access.profile'
    _inherit = ['mail.thread']
    _description = 'Access Profile'
    _order = 'sequence, name, id'

    # a write clears the ormcaches only if it changes what _resolve() or _build_rules() read; create/unlink always
    _clear_cache_name = 'default'
    _clear_cache_on_fields = (
        *GLOBAL_FLAGS, 'hide_costs', 'hide_sale_prices', 'name', 'active', 'sequence', 'company_id', 'strictness',
        'group_id', 'user_ids', 'apply_to_admin', 'home_action_id', 'granted_group_ids', 'group_ids',
        'hidden_menu_ids', 'hidden_report_ids', 'hidden_action_ids', 'hidden_window_action_ids',
        'login_tz', 'allowed_ips', 'login_slot_ids', 'assignment_ids', 'model_ids', 'menu_rule_ids',
        'allowed_ids', 'field_ids', 'button_ids', 'element_ids', 'page_element_ids', 'filter_element_ids',
        'view_element_ids',
    )

    name = fields.Char(required=True, translate=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    sequence = fields.Integer(default=10)
    note = fields.Html(string='Notes')
    company_id = fields.Many2one(
        'res.company', string='Restrict to Company', ondelete='set null',
        help="Leave empty to use the profile for all its users. If you set a company, only users who belong to it are "
             "affected. What counts is the companies a user belongs to, not the company they are working in now.", tracking=True)

    strictness = fields.Selection(
        [('additive', 'Additive'), ('override', 'Override')],
        default='additive', required=True,
        help="Additive: works together with the user's other additive profiles. An action is allowed if one of them "
             "allows it. Override: always used, and no other profile can undo it. Use it for a general limit, such as "
             "'Read Only', on top of another profile.", tracking=True)

    group_id = fields.Many2one(
        'res.groups', string='Technical Group', ondelete='restrict', copy=False,
        help="Created and updated automatically. Odoo needs it to show the users of each profile the right menus.")
    user_ids = fields.Many2many(
        'res.users', 'gec_access_profile_users_rel', 'profile_id', 'uid',
        string='Users', tracking=True)
    apply_to_admin = fields.Boolean(
        string='Apply to Settings Users',
        help="By default this profile never limits members of the Settings group. The Odoo superuser and the "
             "Administrator user are never limited, whatever you choose here.", tracking=True)

    global_readonly = fields.Boolean(
        string='Read Only Everywhere',
        help="Users cannot create, edit or delete anything, not even their own profile (language, timezone, "
             "signature). Only what the browser saves by itself still changes: interface settings, saved searches "
             "and messages marked as read in Discuss. Odoo's normal rules still cover those.", tracking=True)
    hide_chatter_all = fields.Boolean(string='Hide the Chatter Everywhere', tracking=True)
    block_export = fields.Boolean(string='Block Export', tracking=True)
    block_import = fields.Boolean(string='Block Import', tracking=True)
    block_archive = fields.Boolean(string='Block Archiving', tracking=True)
    block_duplicate = fields.Boolean(string='Block Duplication', tracking=True)
    hide_activities = fields.Boolean(string='Hide Activities', tracking=True)
    hide_settings_menu = fields.Boolean(string='Hide the Settings App', tracking=True)
    lock_statusbar = fields.Boolean(string='Lock the Status Bars', tracking=True)
    block_rpc = fields.Boolean(
        string='Block the External API',
        help="These users cannot use XML-RPC and JSON-RPC calls (/xmlrpc, /jsonrpc) or JSON-2 API keys. They can still "
             "use Odoo in a browser. A script that signs in like a browser, through /web/session/authenticate, and "
             "keeps its session cookie is not stopped. Odoo counts that as a browser sign-in.", tracking=True)
    for_new_users = fields.Boolean(
        string='Give to New Users',
        help="Every internal user created from now on gets this profile. Portal "
             "and public users never do.", tracking=True)
    hide_print_all = fields.Boolean(
        string='Hide the Print Menu',
        help="Users cannot print any report, from the Print menu or from a button.", tracking=True)
    hide_action_menu_all = fields.Boolean(
        string='Hide the Action Menu Entries',
        help="Hides the entries of the Action menu (Send by Email, server actions...). Odoo also refuses them. Export, "
             "Duplicate, Archive and Delete have their own switches.", tracking=True)
    hide_send_message_all = fields.Boolean(
        string='Hide Send Message',
        help="In the chatter, users can only use 'Log note'. They cannot send messages to followers or customers.", tracking=True)
    hide_followers_all = fields.Boolean(string='Hide the Followers', tracking=True)
    hide_attachments_all = fields.Boolean(string='Hide the Attachments', tracking=True)
    home_action_id = fields.Many2one(
        'ir.actions.act_window', string='Home Page', ondelete='set null',
        help="The page users of this profile see first after signing in. It replaces the home screen and their own home"
             " page.", tracking=True)
    hide_costs = fields.Boolean(
        string='Hide Costs and Margins',
        help="Hides product costs, sales and point of sale margins, and stock valuation. They are hidden on the screens"
             " and in the API, in every app, now and later. PDF and analysis reports still show these values, and so do"
             " other fields with the same values. Hide those reports too.", tracking=True)
    hide_sale_prices = fields.Boolean(
        string='Hide Sales Prices',
        help="Hides the sales price of products, and the prices, discounts and amounts of quotations and sales orders. "
             "They are hidden on the screens and in the API. PDF and analysis reports still show these values, and so "
             "do other fields with the same values. Hide those reports too. For staff who handle the goods, not the "
             "sales.", tracking=True)
    block_login = fields.Boolean(
        string='Block Login',
        help="These users cannot sign in, in the browser or through the external API. Their open sessions end. Their "
             "records stay as they are. To let them back in, remove them from the profile, e.g. after a leave.", tracking=True)
    block_developer_mode = fields.Boolean(
        string='Block Developer Mode',
        help="These users cannot turn on developer mode, from the menu or from the web address. Odoo turns it off on "
             "every action.", tracking=True)
    block_custom_filter = fields.Boolean(
        string='No Custom Filters',
        help="Hides 'Custom Filter...' and 'Custom Date...' in the search bar. Users can only use the ready-made "
             "filters of the screens.", tracking=True)
    block_custom_group = fields.Boolean(
        string='No Custom Group By',
        help="Hides 'Add Custom Group' in the search bar.", tracking=True)
    block_favorites = fields.Boolean(
        string='No Saved Searches',
        help="Hides 'Save current search'. Users cannot save a favorite.", tracking=True)
    block_properties = fields.Boolean(
        string='No New Properties',
        help="Hides 'Add Property'. Users cannot change the properties of any form.",
        tracking=True)
    block_apps = fields.Boolean(
        string='Block Installing Apps',
        help="Users cannot install, upgrade or uninstall modules. This matters for Settings users: for them, also tick "
             "'Apply to Settings Users'.", tracking=True)

    granted_group_ids = fields.Many2many(
        'res.groups', 'gec_access_profile_granted_group_rel', 'profile_id', 'group_id',
        string='Granted Access',
        help="Odoo groups that this profile's users get on top of their own. Use them to open an app (Purchase / User) "
             "for users who do not have it on their user form. Users lose these groups when the profile is removed.", tracking=True)
    hidden_menu_ids = fields.Many2many(
        'ir.ui.menu', 'gec_access_profile_menu_rel', 'profile_id', 'menu_id',
        string='Hidden Menus',
        help="When you hide a menu, its sub-menus are hidden too. Hiding does not block the records. To block them, use"
             " Block on the Menus & Apps tab.", tracking=True)
    hidden_report_ids = fields.Many2many(
        'ir.actions.report', 'gec_access_profile_report_rel', 'profile_id', 'report_id',
        string='Hidden Reports', tracking=True)
    # Action menu entries are server or window actions: two tables, two fields; the checks match the shared action id.
    hidden_action_ids = fields.Many2many(
        'ir.actions.server', 'gec_access_profile_server_action_rel', 'profile_id', 'action_id',
        string='Hidden Server Actions', tracking=True)
    hidden_window_action_ids = fields.Many2many(
        'ir.actions.act_window', 'gec_access_profile_window_action_rel', 'profile_id', 'action_id',
        string='Hidden Window Actions', domain=[('binding_model_id', '!=', False)], tracking=True)

    model_ids = fields.One2many('gec.access.profile.model', 'profile_id', string='Models')
    menu_rule_ids = fields.One2many(
        'gec.access.profile.menu', 'profile_id', string='Menu Rules',
        help="Settings made on a menu. They also cover all its sub-menus.")
    allowed_ids = fields.One2many('gec.access.allowed', 'profile_id', string='Allowed Records')
    field_ids = fields.One2many('gec.access.profile.field', 'profile_id', string='Fields')
    button_ids = fields.One2many('gec.access.profile.button', 'profile_id', string='Buttons')
    element_ids = fields.One2many('gec.access.profile.element', 'profile_id', string='View Elements')
    # the same lines, one tab each
    page_element_ids = fields.One2many(
        'gec.access.profile.element', 'profile_id', string='Pages',
        domain=[('element_type', '=', 'page')])
    filter_element_ids = fields.One2many(
        'gec.access.profile.element', 'profile_id', string='Filters',
        domain=[('element_type', 'in', ('filter', 'searchpanel'))])
    view_element_ids = fields.One2many(
        'gec.access.profile.element', 'profile_id', string='Views',
        domain=[('element_type', '=', 'view')])

    user_count = fields.Integer(compute='_compute_user_count', string='# Users')

    @api.depends('user_ids', 'group_ids', 'company_id', 'assignment_ids.state', 'assignment_ids.active')
    def _compute_user_count(self):
        for profile in self:
            profile.user_count = len(profile._gec_members())

    def _group_values(self):
        self.ensure_one()
        return {
            'name': _('Access Profile: %s', self.name),
            'user_ids': [(6, 0, self._gec_direct_users().ids)],
            # grants come with the group; an archived group still implies its groups, so an archived profile grants none
            'implied_ids': [(6, 0, self.granted_group_ids.ids if self.active else [])],
            'comment': _("Managed by the access profile with the same name. Do not give this group by hand."),
        }

    def _sync_group(self):
        """ One hidden res.groups per profile with its users: the group set is the cache key of _visible_menu_ids().
        A new group gets its XML id here, which makes core count it as light; core classified it before that,
        and the XML id writes nothing to res.groups, so the classification is re-run after the loop. """
        created = False
        for profile in self:
            if profile.group_id:
                profile.group_id.sudo().write(profile._group_values())
            else:
                group = self.env['res.groups'].sudo().create(profile._group_values())
                profile.sudo().with_context(gec_access_skip_sync=True).group_id = group
                group._ensure_xml_id()
                created = True
        if created:
            self.env['res.groups'].sudo()._apply_group_regular()

    @api.model
    def _gec_ensure_group_xml_ids(self):
        """ Give each profile's group an XML id so core counts it as light; data calls it before core reclassifies. """
        self.sudo().with_context(active_test=False).search([]).group_id._ensure_xml_id()

    def _gec_check_group_id(self, vals_list):
        """ Refuse a technical group set by a user: _sync_group rewrites the group it points at and unlink deletes it,
        so a user pointing it at base.group_system would take over Settings. Any value is refused, False included
        (the old group would keep its users while the next sync makes another). Only the module (env.su) may set it. """
        if not self.env.su and any('group_id' in vals for vals in vals_list):
            raise AccessError(_("Access Manager manages the technical group of each profile. You cannot set it."))

    @api.model
    def default_get(self, fields):
        """ No group_id default: core fills defaults after the create check; _sync_group would rewrite the group. """
        defaults = super().default_get(fields)
        defaults.pop('group_id', None)
        return defaults

    @api.model_create_multi
    def create(self, vals_list):
        self._gec_check_group_id(vals_list)
        profiles = super().create(vals_list)
        profiles._gec_check_editor()
        profiles._sync_group()
        return profiles

    def write(self, vals):
        """ Check the editor before and after: the change may take a profile into or out of their reach. """
        self._gec_check_group_id([vals])
        self._gec_check_editor()
        result = super().write(vals)
        self._gec_check_editor()
        # rewriting the group clears every worker's access caches: sync only when what it carries changes
        if not self.env.context.get('gec_access_skip_sync') and GROUP_FIELDS.intersection(vals):
            self._sync_group()
        return result

    def unlink(self):
        self._gec_check_editor()
        groups = self.group_id.sudo()
        result = super().unlink()
        groups.unlink()
        # removing a permissive additive profile can make another's login block effective: check before committing
        if not self.env.registry.uninstalling_modules:
            self.sudo().search([])._check_last_administrator()
        return result

    def copy_data(self, default=None):
        default = dict(default or {})
        default.setdefault('user_ids', [])
        vals_list = super().copy_data(default=default)
        for profile, vals in zip(self, vals_list):
            vals.setdefault('name', _('%s (copy)', profile.name))
        return vals_list

    @api.constrains('granted_group_ids')
    def _check_granted_groups(self):
        """ Refuse admin groups and the group of any profile: its grants would pass that profile's own limits. """
        forbidden = self.env['res.groups']
        for xmlid in UNGRANTABLE_GROUPS:
            forbidden |= self.env.ref(xmlid, raise_if_not_found=False) or self.env['res.groups']
        technical = self._gec_grants_technical_groups()
        for profile in self:
            for group in profile.sudo().granted_group_ids:
                if (group | group.all_implied_ids) & forbidden:
                    raise ValidationError(_(
                        "A profile cannot give %s. It would make its users administrators or access managers. Give this"
                        " group on the user form instead.", group.full_name))
                if group.id in profile.sudo().group_id.ids:
                    raise ValidationError(_("A profile cannot give its own group."))
                if (group | group.all_implied_ids) & technical:
                    raise ValidationError(_(
                        "A profile cannot give %s. It is or carries the group of another profile. Give that profile to"
                        " the users instead.", group.full_name))

    @api.model
    def _gec_editor_is_trusted(self):
        """ Whether the real user, not env.su, needs no check: the superuser, a Settings user or no user at all. """
        user = self.env.user
        return self.env.uid == SUPERUSER_ID or not user or user._is_system()

    @api.model
    def _gec_readable_records(self, model_name, res_ids):
        """ The records among ``res_ids`` the real user may read in all their companies, as sudo records, archived kept.
        A model missing from the registry gives an empty profile recordset. The wizards run with sudo: the check is on
        the real user. """
        if model_name not in self.env:
            return self.browse()
        records = self.env[model_name].sudo().with_context(active_test=False).browse(res_ids).exists()
        if not records or self._gec_editor_is_trusted():
            return records
        reader = self.env(su=False, context=dict(
            self.env.context, active_test=False, allowed_company_ids=list(self.env.user._get_company_ids())))
        return records.browse(records.with_env(reader)._filtered_access('read').ids)

    def _gec_check_editor(self):
        """ Refuse a non-Settings editor the profiles that apply to Settings users or grant a group they lack.
        It decides on the real user, not env.su: the wizards write with sudo. The superuser (install, crons), Settings
        users and a call with no real user (a sign-in creating a user) pass. """
        if self._gec_editor_is_trusted():
            return
        held = self.env.user.all_group_ids
        for profile in self.sudo():
            if profile.apply_to_admin:
                raise AccessError(_(
                    "Only a Settings administrator can change the profile '%s'. It also limits Settings users.",
                    profile.name))
            for group in profile.granted_group_ids:
                if not (group | group.all_implied_ids) <= held:
                    raise AccessError(_(
                        "Only a Settings administrator can change the profile '%(profile)s'. It gives '%(group)s', "
                        "which you do not have.", profile=profile.name, group=group.full_name))

    @api.constrains('hide_settings_menu', 'block_login', 'login_slot_ids', 'allowed_ips',
                    'user_ids', 'group_ids', 'apply_to_admin', 'active', 'hidden_menu_ids',
                    'global_readonly', 'strictness', 'company_id')
    def _check_last_administrator(self):
        """ Refuse a change leaving no access manager able to undo it: locked out of login, the app or the profiles. """
        managers_group = self.env.ref('gec_access_manager.group_access_manager', raise_if_not_found=False)
        if not managers_group or not self:
            return
        # the rules as they are now, not as cached before this change
        self.env.transaction.invalidate_ormcache('default')
        managers = managers_group.sudo().all_user_ids.filtered('active')
        # no active access manager left at all is the worst lock out
        reasons = [self._gec_lockout(manager) for manager in managers] or ['login']
        if all(reasons):
            names = ', '.join(self.mapped('name')[:3]) + (', ...' if len(self) > 3 else '')
            if reasons[0] == 'login':
                raise ValidationError(_(
                    "Profile %s could stop everyone who can undo it from signing in. Keep at least one access manager "
                    "(Access Management group) out of it.", names))
            if reasons[0] == 'app':
                raise ValidationError(_(
                    "Profile %s would hide the Access Manager app from everyone who can show it again. Keep at least "
                    "one access manager (Access Management group) out of it.", names))
            raise ValidationError(_(
                "Profile %s would stop everyone who can undo it from editing access profiles. Keep at least one access "
                "manager (Access Management group) out of it.", names))

    @api.model
    def _gec_lockout(self, user):
        """ Why ``user`` could not undo a profile, all combined: 'login', 'app', 'profiles', or False. """
        if user.id in self._exempt_user_ids():
            return False
        rules = self._resolve(user.id)
        if not rules.enabled:
            return False
        if rules.has_flag('block_login'):
            return 'login'
        # working hours and networks: refused at some moment or from some place
        limits = [bool(profile.login_slots or profile.networks) for profile in rules.override]
        if any(limits) or (rules.additive and all(
                profile.login_slots or profile.networks for profile in rules.additive)):
            return 'login'
        app = self.env.ref('gec_access_manager.gec_access_root_menu', raise_if_not_found=False)
        if app and app.id in rules.menu_blacklist():
            return 'app'
        if not (rules.allows(self._name, 'read') and rules.allows(self._name, 'write')):
            return 'profiles'
        return False

    def action_open_users(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Users'),
            'res_model': 'res.users',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self._gec_members().ids)],
        }

    def _open_wizard(self, res_model, name):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': res_model,
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_model': self._name, 'active_id': self.id,
                        'default_profile_id': self.id},
        }

    def action_load_models(self):
        return self._open_wizard('gec.access.load.models', _('Load Models'))

    def action_restrict_app(self):
        return self._open_wizard('gec.access.app.wizard', _('Restrict an App'))

    def action_scan_buttons(self):
        return self._open_wizard('gec.access.scan.buttons', _('Scan Buttons'))

    def _gec_preview_users(self):
        self.ensure_one()
        viewer = self.env.user.sudo()
        return self._gec_members().filtered(lambda user: not user._gec_preview_refusal(viewer))

    def action_test_user(self):
        self.ensure_one()
        if not self.env.user._is_system():
            raise UserError(_("Only Settings administrators can preview a user."))
        users = self._gec_preview_users()
        if not users:
            raise UserError(_(
                "No user has this profile yet.\n\nAdd users in the 'Users' field, save, then preview the profile as one"
                " of them."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Preview as User'),
            'res_model': 'gec.access.test.user',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_profile_id': self.id,
                'default_user_id': users[:1].id,
                'gec_preview_back': f'/odoo/action-gec_access_manager.gec_access_profile_action/{self.id}',
            },
        }

    def action_copy_restrictions(self):
        return self._open_wizard('gec.access.copy.restrictions', _('Copy Restrictions'))
