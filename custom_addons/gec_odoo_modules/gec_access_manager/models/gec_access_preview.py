import time

from psycopg2.errors import ReadOnlySqlTransaction

from odoo import _, api, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.base.models.res_users import check_identity

PREVIEW_KEY = 'gec_access_preview'
PREVIEW_SECONDS = 3600
MANAGER_GROUP = 'gec_access_manager.group_access_manager'
# what the previewed user talks about or writes privately: out of reach of the administrator who previews
PREVIEW_HIDDEN_MODELS = frozenset({'discuss.channel', 'discuss.channel.member', 'knowledge.article'})


def preview_of_request():
    """ The preview the current request is served in, or None. """
    data = getattr(request, 'gec_preview', None) if request else None
    return data if isinstance(data, dict) else None


def preview_ended():
    """ Whether the preview of the current request has ended: still read only, no longer as the user. """
    data = preview_of_request()
    return bool(data and data.get('ended'))


def preview_refused():
    if preview_ended():
        return UserError(_("The preview has ended. Click 'Exit preview'."))
    return UserError(_("This is a preview: nothing is saved."))


def preview_allowed():
    """ A button the previewed user may use: said, not run. """
    if preview_ended():
        return preview_refused()
    name = request.env.user.sudo().name
    return UserError(_("%s can use this. In a preview, it does not run.", name))


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _gec_preview_refusal(self, viewer):
        """ Why ``viewer`` may not preview this user, or None. """
        self.ensure_one()
        if not viewer._has_group(MANAGER_GROUP):
            return _("Only access managers can preview a user.")
        if not viewer._is_system():
            return _("Only Settings administrators can preview a user.")
        if self == viewer:
            return _("You cannot preview yourself.")
        if not self.active or self.share:
            return _("Only active internal users can be previewed.")
        if self.id in self.env['gec.access.profile']._exempt_user_ids():
            return _("The administrator is never limited, so there is nothing to preview.")
        return None

    @check_identity
    def action_gec_preview(self, back_url=None):
        """ Start previewing this user; needs a password confirmed in the last ten minutes, as for core API keys. """
        self.ensure_one()
        target = self.sudo()
        viewer = self.env.user.sudo()
        reason = target._gec_preview_refusal(viewer)
        if reason:
            raise AccessError(reason)
        request.session[PREVIEW_KEY] = {
            'uid': target.id,
            'by': viewer.id,
            'until': time.time() + PREVIEW_SECONDS,
            'back': back_url or f'/odoo/action-base.action_res_users/{target.id}',
            'cids': request.httprequest.cookies.get('cids'),
            'context': dict(request.session.context),
        }
        self.env['gec.user.audit.log']._gec_log('other', separate=True, detail=_("Preview as %s started", target.name))
        # the screens of the user are cached per user: start from a clean page
        return {'type': 'ir.actions.act_url', 'url': '/odoo', 'target': 'self'}

    @api.model
    def _gec_preview_stop(self):
        data = request.session.pop(PREVIEW_KEY, None) if request else None
        if data:
            # the web client's session info gave the session the user's language
            request.session.context = data.get('context') or request.session.context
            # attributed to the administrator by the audit override below
            self.env['gec.user.audit.log']._gec_log('other', separate=True, detail=_("Preview ended"))
        return data


def valid_preview(env):
    """ The session's preview, checked on every request: None, and dropped, when another user signed in. Once expired or
    no longer allowed it is marked ended and stays: read only, as the administrator, until Exit. """
    data = request.session.get(PREVIEW_KEY)
    if not data:
        return None
    if data.get('by') != request.session.uid:
        request.session.pop(PREVIEW_KEY, None)
        return None
    if data.get('ended'):
        return data
    viewer = env['res.users'].sudo().browse(request.session.uid)
    target = env['res.users'].sudo().browse(data.get('uid')).exists()
    if data.get('until', 0) > time.time() and target and not target._gec_preview_refusal(viewer):
        return data
    data = dict(data, ended=True)
    request.session[PREVIEW_KEY] = data
    return data


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _authenticate_explicit(cls, routing):
        """ Serve the request as the previewed user while the preview runs, as the administrator once it has ended;
        read only in both cases. Asset bundles are left out: they are the same for every user, and a read-only
        transaction could not build a missing one. """
        super()._authenticate_explicit(routing)
        if not request.env.uid or request.env.uid != request.session.uid:
            return
        if request.httprequest.path.startswith('/web/assets/'):
            return
        data = valid_preview(request.env)
        if not data:
            return
        request.gec_preview = data
        if not data.get('ended'):
            target = request.env['res.users'].sudo().browse(data['uid'])
            request.update_env(user=target.id)
            request.update_context(**{key: value for key, value in target.context_get().items()
                                      if key in ('lang', 'tz')})
        # whatever the request does from here, the database refuses to write it
        request.env.cr.execute('SET TRANSACTION READ ONLY')

    @classmethod
    def _dispatch(cls, endpoint):
        if not preview_of_request():
            return super()._dispatch(endpoint)
        try:
            result = super()._dispatch(endpoint)
            request.env.flush_all()
        except ReadOnlySqlTransaction:
            raise preview_refused() from None
        finally:
            # nothing was written: end the read-only transaction here
            request.env.cr.rollback()
        return result

    def session_info(self):
        """ Session info of the previewed user while the preview runs; once it has ended, the administrator's own,
        flagged ended so the banner shows it. """
        data = preview_of_request()
        if not data and request and self.env.uid and self.env.uid == request.session.uid:
            # /odoo is served without a user: the preview is read from the session
            data = valid_preview(self.env)
        elif not data and request and self.env.context.get('gec_preview'):
            data = request.session.get(PREVIEW_KEY)
        if data and self.env.uid == data['by']:
            if not data.get('ended'):
                return self.with_user(data['uid']).with_context(gec_preview=True).session_info()
            result = super().session_info()
            result['gec_preview'] = {
                'name': self.env['res.users'].sudo().browse(data['uid']).exists().name or '',
                'viewer': self.env.user.name,
                'profiles': [],
                'until': data['until'],
                'ended': True,
            }
            result['gec_access_classes'] = [*result.get('gec_access_classes', []), 'o_gec_preview']
            return result
        result = super().session_info()
        if data and self.env.uid == data['uid']:
            result['uid'] = data['uid']
            viewer = self.env['res.users'].sudo().browse(data['by'])
            rules = self.env['gec.access.profile']._resolve(data['uid'])
            result['gec_preview'] = {
                'name': self.env.user.sudo().name,
                'viewer': viewer.name,
                'profiles': [rule.name for rule in rules.additive + rules.override],
                'until': data['until'],
            }
            result['gec_access_classes'] = [*result.get('gec_access_classes', []), 'o_gec_preview']
        return result


class Base(models.AbstractModel):
    _inherit = 'base'

    @api.model
    def _access_domain(self, operation):
        """ In an active preview, leave out the chats and knowledge articles of the previewed user, which the
        administrator may not read. Not cached: the cached domain of base_model.py has no preview in its key. A
        domain matching nothing, not Domain.FALSE, which makes searches raise and the web client fail to start. """
        domain = super()._access_domain(operation)
        if domain.is_false() or not preview_of_request() or preview_ended():
            return domain
        if self._name in PREVIEW_HIDDEN_MODELS:
            return domain & Domain('id', '=', 0)
        if self._name == 'mail.message':
            return domain & Domain('model', '!=', 'discuss.channel')
        return domain

    def _gec_audit(self, operation):
        """ Log preview reads for the viewer regardless of log_reads and client context. Explicit rules or model
        exclusions still decide coverage (abstract and transient models stay out); not cached, it depends on the
        preview. """
        if (operation == 'read' and preview_of_request() and not preview_ended() and not self.env.su
                and self.env.registry.ready and not self._transient and not self._abstract):
            Rule = self.env['gec.user.audit.rule']
            return super()._gec_audit(operation) or not Rule._gec_excluded(self._name, Rule._gec_policy())
        return super()._gec_audit(operation)

    # refused before the database does it, which would log the query as an error

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and preview_of_request():
            raise preview_refused()
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and preview_of_request():
            raise preview_refused()
        return super().write(vals)

    def unlink(self):
        if not self.env.su and preview_of_request():
            raise preview_refused()
        return super().unlink()


class GecUserAuditLog(models.Model):
    _inherit = 'gec.user.audit.log'

    def _gec_values(self, event, **values):
        # what is read during a preview is read by the person previewing
        values = super()._gec_values(event, **values)
        data = preview_of_request()
        if data and not data.get('ended'):
            name = self.env['res.users'].sudo().browse(data['uid']).name
            values['user_id'] = data['by']
            values['detail'] = ' — '.join(filter(None, [_("Preview as %s", name), values.get('detail')]))
        return values

    @api.model
    def _gec_buffer(self, vals_list):
        # the transaction of a preview is read only: write the lines after it
        if preview_of_request():
            return self._gec_after_transaction(vals_list)
        return super()._gec_buffer(vals_list)
