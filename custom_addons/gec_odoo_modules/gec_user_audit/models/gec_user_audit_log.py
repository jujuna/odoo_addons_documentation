import logging
from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.modules import module

from .client_call import RPC_ADDRESS

_logger = logging.getLogger(__name__)

EVENTS = [
    ('login', 'Sign-in'),
    ('login_failed', 'Failed Sign-in'),
    ('logout', 'Sign-out'),
    ('session_end', 'Session Ended'),
    ('read', 'Read'),
    ('create', 'Create'),
    ('write', 'Edit'),
    ('unlink', 'Delete'),
    ('export', 'Export'),
    ('import', 'Import'),
    ('print', 'Print'),
    ('refused', 'Refused'),
    ('other', 'Other'),
]
SIGN_IN_EVENTS = ('login', 'login_failed', 'logout', 'session_end')
BUFFER_KEY = 'gec_user_audit_lines'
RECORD_IDS_KEPT = 20


def request_context():
    """ The address and the browser of the current request. """
    if not request:
        address = RPC_ADDRESS.get()
        return {'ip': address} if address else {}
    httprequest = request.httprequest
    address = httprequest.remote_addr
    values = {'ip': address if isinstance(address, str) and address else False}
    agent = httprequest.user_agent
    if agent and isinstance(agent.string, str) and agent.string:
        values['user_agent'] = agent.string[:500]
    return values


class GecUserAuditLog(models.Model):
    _name = 'gec.user.audit.log'
    _description = 'User Audit Log'
    _order = 'id desc'
    _log_access = False
    _rec_name = 'event'

    date = fields.Datetime(required=True, default=fields.Datetime.now, index=True, readonly=True)
    user_id = fields.Many2one('res.users', string='User', index=True, readonly=True, ondelete='set null')
    login = fields.Char(readonly=True, help="The login typed, for a failed sign-in.")
    event = fields.Selection(EVENTS, required=True, index=True, readonly=True)
    model = fields.Char(string='Model', index=True, readonly=True)
    model_name = fields.Char(string='Data', compute='_compute_model_name')
    res_id = fields.Many2oneReference(string='Record', model_field='model', readonly=True)
    res_name = fields.Char(string='Stored Record Name', readonly=True, groups=fields.NO_ACCESS)
    res_name_shown = fields.Char(string='Record Name', compute='_compute_changes_shown', compute_sudo=False)
    method = fields.Char(readonly=True)
    record_count = fields.Integer(string='Records', readonly=True)
    record_ids = fields.Char(string='Record Ids', readonly=True, help="The first ids of the records read, printed or exported.")
    detail = fields.Text(readonly=True)
    changes = fields.Text(readonly=True, groups='base.group_no_one',
        help="What changed, as stored. The screens show Changes, which hides it from a reader who cannot read the record.")
    changes_shown = fields.Text(string='Changes', compute='_compute_changes_shown', compute_sudo=False)
    ip = fields.Char(string='Address', readonly=True)
    user_agent = fields.Char(string='Browser', readonly=True)

    @api.depends('model')
    def _compute_model_name(self):
        IrModel = self.env['ir.model'].sudo()
        names = {}
        for line in self:
            if line.model not in names:
                names[line.model] = IrModel._get(line.model).name if line.model in self.env else line.model
            line.model_name = names[line.model] or False

    def _gec_readable_record_names(self):
        """ Resolve record names with the caller's access to records and fields; only the log lines are sudo. """
        names = {}
        for model, lines in self.sudo().filtered('res_id').grouped('model').items():
            if model in self.env:
                records = self.env[model].browse(lines.mapped('res_id')).exists()._filtered_access('read')
                for record in records:
                    try:
                        names[(model, record.id)] = record.display_name
                    except AccessError:
                        names[(model, record.id)] = False
        return names

    @api.depends('changes', 'res_name', 'model', 'res_id')
    @api.depends_context('uid', 'allowed_company_ids', 'lang')
    def _compute_changes_shown(self):
        """ Show values and names only for records the caller can read; the others get a neutral text.
        For a Settings reader, deleted records keep their stored name and changes. """
        names = self._gec_readable_record_names()
        deleted = set()
        if self.env.is_system():
            unresolved = self.sudo().filtered(lambda line: line.res_id and (line.model, line.res_id) not in names)
            for model, lines in unresolved.grouped('model').items():
                if model in self.env:
                    res_ids = set(lines.mapped('res_id'))
                    existing = set(self.env[model].browse(res_ids).exists().ids)
                    deleted.update((model, res_id) for res_id in res_ids - existing)
        notice = self.env._("changed (not readable by you)")
        hidden_name = self.env._("Record (not readable by you)")
        for line in self:
            stored = line.sudo()
            key = (stored.model, stored.res_id)
            changes = stored.changes
            if key in deleted:
                line.changes_shown = changes or False
                line.res_name_shown = stored.res_name or False
                continue
            line.changes_shown = (changes if key in names else notice) if changes else False
            line.res_name_shown = (names.get(key) or hidden_name) if stored.res_name else False

    @api.depends('event', 'res_name_shown', 'model')
    @api.depends_context('uid', 'allowed_company_ids', 'lang')
    def _compute_display_name(self):
        """Build the log label from the name permitted for the current reader."""
        labels = dict(self._fields['event']._description_selection(self.env))
        for line in self:
            line.display_name = ' '.join(filter(None, (labels.get(line.event), line.res_name_shown or line.model)))

    @api.model
    def _gec_values(self, event, **values):
        values = dict(values, event=event)
        values.setdefault('user_id', self.env.uid)
        values.setdefault('date', fields.Datetime.now())
        for key, value in request_context().items():
            values.setdefault(key, value)
        if 'record_ids' in values and not isinstance(values['record_ids'], str):
            ids = list(values['record_ids'] or ())
            values.setdefault('record_count', len(ids))
            values['record_ids'] = ','.join(map(str, ids[:RECORD_IDS_KEPT])) + (',...' if len(ids) > RECORD_IDS_KEPT else '')
        return values

    @api.model
    def _gec_log(self, event, separate=False, **values):
        """ Log an event of another module: ``refused``, ``other``... With ``separate``, the line is written on a cursor
        of its own once the transaction ends, and survives its rollback. """
        values = self._gec_values(event, **values)
        if separate:
            self._gec_after_transaction([values])
        else:
            self._gec_buffer([values])

    @api.model
    def _gec_buffer(self, vals_list):
        """ Insert with the business transaction, so raw savepoints also undo events.
        Read-only requests keep the separate-cursor path for read evidence. """
        if not vals_list:
            return
        cr = self.env.cr
        if cr.readonly:
            self._gec_after_transaction(vals_list)
            return
        self.sudo().create(vals_list)

    @api.model
    def _gec_after_transaction(self, vals_list):
        cr = self.env.cr
        if cr.readonly and module.current_test:
            # tests cannot open a write cursor from a read-only one in use: roll back, write now (as res.device.log)
            cr.rollback()
            self._gec_write_separately(self.env.registry, vals_list)
            return
        lines = cr.postcommit.data.get(BUFFER_KEY)
        if lines is None:
            # the hooks hold the list itself: a rollback clears the postcommit data before the postrollback hooks run
            lines = cr.postcommit.data[BUFFER_KEY] = []
            registry = self.env.registry

            def flush():
                pending = lines[:]
                lines.clear()
                if pending:
                    self._gec_write_separately(registry, pending)
            cr.postcommit.add(flush)
            cr.postrollback.add(flush)
        lines.extend(vals_list)

    @api.model
    def _gec_write_separately(self, registry, vals_list):
        try:
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env[self._name].create(vals_list)
        except Exception:
            _logger.warning("Could not write %s audit lines", len(vals_list), exc_info=True)

    @api.model
    def _cron_clean(self):
        params = self.env['ir.config_parameter'].sudo()
        days = params.get_int('gec_user_audit.keep_days', 90)
        sign_in_days = params.get_int('gec_user_audit.keep_sign_in_days') or days
        if days > 0 and not self._gec_delete_before(fields.Datetime.now() - timedelta(days=days), [('event', 'not in', SIGN_IN_EVENTS)]):
            return
        if sign_in_days > 0:
            self._gec_delete_before(fields.Datetime.now() - timedelta(days=sign_in_days), [('event', 'in', SIGN_IN_EVENTS)])

    def _gec_delete_before(self, limit_date, domain, batch=10000):
        """ Delete the lines older than ``limit_date`` matching ``domain``, in batches, then drop the cache of what the
        raw DELETE removed. Returns False when the cron ran out of time: the next run goes on. """
        while True:
            lines = self.sudo().search(domain + [('date', '<', limit_date)], limit=batch, order='id')
            if not lines:
                return True
            self.env.cr.execute("DELETE FROM gec_user_audit_log WHERE id IN %s", [tuple(lines.ids)])
            self.invalidate_model()
            if self.env.context.get('ir_cron_progress_id') and not self.env['ir.cron']._commit_progress(len(lines)):
                return False
            if len(lines) < batch:
                return True

    def action_open_record(self):
        self.ensure_one()
        if not (self.model and self.res_id and self.model in self.env):
            return False
        return {'type': 'ir.actions.act_window', 'res_model': self.model, 'res_id': self.res_id, 'view_mode': 'form', 'target': 'current'}

    @api.model
    def _gec_lines_per_day(self):
        self.env.cr.execute("SELECT count(*) FROM gec_user_audit_log WHERE date > now() at time zone 'UTC' - interval '1 day'")
        return self.env.cr.fetchone()[0]
