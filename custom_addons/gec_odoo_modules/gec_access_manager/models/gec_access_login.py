from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.base.models.res_partner import _tz_get

from .login_tools import parse_networks

DAYS = [
    ('0', 'Monday'), ('1', 'Tuesday'), ('2', 'Wednesday'), ('3', 'Thursday'),
    ('4', 'Friday'), ('5', 'Saturday'), ('6', 'Sunday'),
]


class GecAccessLoginSlot(models.Model):
    _name = 'gec.access.login.slot'
    _inherit = ['gec.access.history.mixin']
    _description = 'Working Hours of an Access Profile'
    _order = 'dayofweek, hour_from'

    _clear_cache_name = 'default'

    profile_id = fields.Many2one('gec.access.profile', required=True, ondelete='cascade', index=True)
    dayofweek = fields.Selection(DAYS, string='Day', required=True, default='0')
    hour_from = fields.Float(string='Work from', required=True, default=8.0)
    hour_to = fields.Float(string='Work to', required=True, default=17.0)

    def _gec_history_kind(self):
        return _("working hours")

    def _gec_history_label(self):
        day = dict(self._fields['dayofweek']._description_selection(self.env)).get(self.dayofweek)
        return '%s %02d:%02d - %02d:%02d' % (
            day, int(self.hour_from), round(self.hour_from % 1 * 60),
            int(self.hour_to), round(self.hour_to % 1 * 60))

    @api.constrains('hour_from', 'hour_to')
    def _check_hours(self):
        for slot in self:
            if not 0 <= slot.hour_from < slot.hour_to <= 24:
                raise ValidationError(_("Working hours must be between 00:00 and 24:00. The end must be after the "
                                        "start."))


class GecAccessProfile(models.Model):
    _inherit = 'gec.access.profile'

    login_slot_ids = fields.One2many(
        'gec.access.login.slot', 'profile_id', string='Working Hours',
        help="Leave empty to let users sign in at any time. Otherwise they can sign in only during these hours. Outside"
             " them, sign-in is refused and open sessions end.")
    login_tz = fields.Selection(
        _tz_get, string='Timezone of the Hours', default=lambda self: self.env.user.tz or 'UTC',
        tracking=True)
    allowed_ips = fields.Text(
        string='Allowed Networks', tracking=True,
        help="One address or network per line (192.168.1.10, 10.0.0.0/8). Leave empty to allow any address. Otherwise, "
             "sign-in from other addresses is refused. An open session also ends if it is used from another address. If"
             " Odoo runs behind a reverse proxy, start it with --proxy-mode so that it sees the real addresses.")
    single_session = fields.Boolean(
        string='One Session per User', tracking=True,
        help="When a user signs in, their other sessions end. Only the newest session stays open.")

    @api.constrains('allowed_ips')
    def _check_allowed_ips(self):
        for profile in self:
            try:
                parse_networks(profile.allowed_ips)
            except ValueError as error:
                raise ValidationError(_("Allowed Networks: %s", error)) from error
