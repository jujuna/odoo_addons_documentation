import time

from odoo import SUPERUSER_ID, api, models
from odoo.http import request
from odoo.http.session import logout

SEEN_KEY = 'gec_user_audit_seen'
# the session is saved at most this often to note the last request
SEEN_PRECISION = 60


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _authenticate_explicit(cls, routing):
        """ Remember whose session this is: ``logout`` clears it before ``_post_logout``; then end an idle one. """
        uid = request and request.session.uid
        if uid:
            request.gec_session_uid = uid
            cls._gec_check_idle(uid)
        return super()._authenticate_explicit(routing)

    @classmethod
    def _gec_check_idle(cls, uid):
        env = api.Environment(request.env.cr, SUPERUSER_ID, {})
        minutes = env['ir.config_parameter'].get_int('gec_user_audit.idle_minutes')
        if minutes <= 0:
            request.session.pop(SEEN_KEY, None)
            return
        now = time.time()
        seen = request.session.get(SEEN_KEY)
        if seen and now - seen > minutes * 60:
            env['gec.user.audit.log']._gec_log('session_end', separate=True, user_id=uid, detail='idle')
            request.gec_session_uid = None
            logout(request.session, keep_db=True)
            request.env = api.Environment(request.env.cr, None, request.env.context)
            return
        if not seen or now - seen > SEEN_PRECISION:
            request.session[SEEN_KEY] = now

    @classmethod
    def _post_logout(cls):
        """ Log the sign-out of the user the request carried, whatever ended it; an idle end logs its own line. """
        super()._post_logout()
        uid = getattr(request, 'gec_session_uid', None)
        if uid:
            request.gec_session_uid = None
            env = api.Environment(request.env.cr, SUPERUSER_ID, {})
            env['gec.user.audit.log']._gec_log('logout', separate=True, user_id=uid)
