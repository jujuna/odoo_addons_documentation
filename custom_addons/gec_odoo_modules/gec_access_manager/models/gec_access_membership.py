import logging
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class GecAccessProfile(models.Model):
    _inherit = 'gec.access.profile'

    group_ids = fields.Many2many(
        'res.groups', 'gec_access_profile_res_groups_rel', 'profile_id', 'group_id',
        string='Odoo Groups', tracking=True, copy=False,
        help="Every member of these groups gets this profile. This includes members of groups that contain these "
             "groups. Users who join a group get the profile. Users who leave it lose the profile.")
    assignment_ids = fields.One2many(
        'gec.access.profile.assignment', 'profile_id', string='Temporary Users',
        context={'active_test': False})

    @api.constrains('group_ids')
    def _check_group_ids(self):
        technical = self.sudo().search([]).group_id
        for profile in self:
            if profile.group_ids & technical:
                raise ValidationError(_(
                    "A profile's own group cannot be used to give another profile. Pick that profile's users instead."))

    def _gec_in_company(self, users):
        """ ``users`` the profile applies to by company, as the resolver judges: all of them when it has none. """
        self.ensure_one()
        if not self.company_id:
            return users
        return users.filtered(lambda user: self.company_id.id in user.sudo().company_ids._ids)

    def _gec_direct_users(self):
        """ The users of the profile and the users it is assigned to today, in its company. """
        self.ensure_one()
        running = self.assignment_ids.filtered(lambda line: line.active and line.state == 'active')
        return self._gec_in_company(self.user_ids | running.user_id)

    def _gec_members(self):
        self.ensure_one()
        return self._gec_direct_users() | self._gec_in_company(self.group_ids.all_user_ids)

    @api.model
    def _gec_profiles_of(self, user):
        """ The profiles ``user`` carries: their own, the ones assigned to them today and the ones of their groups. """
        Assignment = self.env['gec.access.profile.assignment'].sudo()
        assigned = Assignment.search([('user_id', '=', user.id), ('state', '=', 'active')]).profile_id
        by_group = self.sudo().search([('group_ids', 'in', user.all_group_ids.ids)])
        return user.access_profile_ids.sudo() | assigned | by_group


class GecAccessProfileAssignment(models.Model):
    _name = 'gec.access.profile.assignment'
    _description = 'Temporary Access Profile Assignment'
    _order = 'date_from desc, id desc'
    _clear_cache_name = 'default'
    # the reason is a note for the people
    _clear_cache_on_fields = ('profile_id', 'user_id', 'date_from', 'date_to', 'state', 'active')

    profile_id = fields.Many2one('gec.access.profile', string='Access Profile', required=True,
                                 ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='User', required=True, ondelete='cascade', index=True,
                              domain=[('share', '=', False)])
    date_from = fields.Date(string='From', required=True, default=fields.Date.context_today)
    date_to = fields.Date(string='Until', help="The user still has the profile on this day. Leave empty to keep it with"
                                               " no end date.")
    note = fields.Char(string='Reason')
    state = fields.Selection([('planned', 'Planned'), ('active', 'Running'), ('ended', 'Ended')],
                             default='planned', required=True, readonly=True)
    active = fields.Boolean(default=True)

    _check_dates = models.Constraint(
        'CHECK(date_to IS NULL OR date_to >= date_from)',
        "The end date cannot be before the start date.")

    @api.depends('profile_id', 'user_id')
    def _compute_display_name(self):
        for line in self:
            line.display_name = f"{line.profile_id.name or ''}: {line.user_id.name or ''}"

    def _gec_state_today(self):
        self.ensure_one()
        # the day as the user lives it
        today = fields.Date.context_today(self.with_context(tz=self.user_id.tz or 'UTC'))
        if today < self.date_from:
            return 'planned'
        if self.date_to and today > self.date_to:
            return 'ended'
        return 'active'

    def _gec_refresh(self):
        """ Bring the state of the assignments to today; archive the ended ones. """
        changed = self.browse()
        for line in self:
            state = line._gec_state_today()
            if state != line.state or (state == 'ended' and line.active):
                values = {'state': state}
                if state == 'ended':
                    values['active'] = False
                super(GecAccessProfileAssignment, line).write(values)
                changed |= line
        if changed:
            profiles = changed.profile_id
            profiles._sync_group()
            profiles._check_last_administrator()
        return changed

    def _gec_trigger_refresh(self):
        """ Run the refresh cron a minute after local midnight of the first and of the day after the last day. """
        times = []
        for line in self:
            zone = ZoneInfo(line.user_id.tz or 'UTC')
            for day in (line.date_from, line.date_to and line.date_to + timedelta(days=1)):
                if day:
                    times.append(datetime.combine(day, time(0, 1), tzinfo=zone).astimezone(UTC).replace(tzinfo=None))
        times = [at for at in times if at > fields.Datetime.now()]
        if times:
            self.env.ref('gec_access_manager.ir_cron_refresh_assignments')._trigger(at=times)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.profile_id._gec_check_editor()
        lines._gec_refresh()
        lines._gec_trigger_refresh()
        return lines

    def write(self, vals):
        """ When the dates, user, profile, archiving or state change, refresh the states (a state written by hand
        follows the dates again) and the groups of the profiles involved. """
        profiles = self.profile_id
        profiles._gec_check_editor()
        result = super().write(vals)
        if 'profile_id' in vals:
            self.profile_id._gec_check_editor()
        if {'date_from', 'date_to', 'user_id', 'profile_id', 'active', 'state'} & set(vals):
            self.filtered('active')._gec_refresh()
            (profiles | self.profile_id)._sync_group()
            (profiles | self.profile_id)._check_last_administrator()
        if {'date_from', 'date_to', 'user_id', 'active'} & set(vals):
            self._gec_trigger_refresh()
        return result

    def unlink(self):
        profiles = self.profile_id
        profiles._gec_check_editor()
        result = super().unlink()
        profiles.exists()._sync_group()
        return result

    @api.model
    def _cron_refresh(self):
        """ Refresh all assignments together, so a handover between two managers moves both. A refused one (it would
        lock out the last access manager) is retried alone on a savepoint: it stays as it was and is noted on its
        profile once a day, the others still move. """
        lines = self.search([('state', '!=', 'ended')])
        try:
            with self.env.cr.savepoint():
                lines._gec_refresh()
            return
        except ValidationError:
            pass
        for line in lines:
            try:
                with self.env.cr.savepoint():
                    line._gec_refresh()
            except ValidationError as error:
                profile = line.profile_id
                _logger.warning("Assignment %s of profile %s not refreshed: %s", line.id, profile.id, error.args[0])
                body = _("The temporary access of %(user)s (from %(date_from)s) could not be applied: %(reason)s",
                         user=line.user_id.name, date_from=line.date_from, reason=error.args[0])
                posted = self.env['mail.message'].search([
                    ('model', '=', profile._name), ('res_id', '=', profile.id),
                    ('subtype_id', '=', self.env['ir.model.data']._xmlid_to_res_id('mail.mt_note')),
                    ('create_date', '>=', fields.Datetime.today())])
                if not any(html2plaintext(message.body) == html2plaintext(escape(body)) for message in posted):
                    profile.message_post(body=body, subtype_xmlid='mail.mt_note')


class ResGroups(models.Model):
    _inherit = 'res.groups'

    def _get_light_group_xmlids(self):
        """ A profile's technical group is light: a profile that restricts, grants nothing or is archived leaves its
        members' role as it was; what it grants still counts through the granted groups it implies. """
        return (*super()._get_light_group_xmlids(), *self._gec_profile_group_xmlids())

    @api.model
    @api.ormcache(cache='groups')
    def _gec_profile_group_xmlids(self):
        """ The XML ids of all profiles' technical groups, given by _sync_group and _gec_ensure_group_xml_ids.
        Cached with core's group definitions: creating or deleting a group or its XML id clears it. """
        profiles = self.env['gec.access.profile'].sudo().with_context(active_test=False).search_fetch(
            [], ['group_id'], order='id')
        return tuple(xmlid for xmlid in profiles.group_id.get_external_id().values() if xmlid)

    def write(self, vals):
        """ Refresh the cached rules, only when a profile exists, when the members of a group change from the group's
        side: the profiles of their groups, and the Settings users a profile spares, are resolved from them. """
        result = super().write(vals)
        if ({'user_ids', 'implied_ids', 'implied_by_ids'} & set(vals)
                and self.env['gec.access.profile'].sudo().search_count([], limit=1)):
            self.env.transaction.invalidate_ormcache('default')
        return result
