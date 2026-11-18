from odoo import _
from odoo.http import request

from odoo.addons.mail.controllers.thread import ThreadController

NOTE_SUBTYPE = 'mail.mt_note'


class ThreadAccess(ThreadController):

    def _prepare_message_data(self, post_data, *, thread, from_create=True, **kwargs):
        res = super()._prepare_message_data(post_data, thread=thread, from_create=from_create, **kwargs)
        # a note that names partners notifies them: it is a message too
        if from_create and request.env.uid and (
                res.get('subtype_xmlid') not in (None, False, NOTE_SUBTYPE)
                or res.get('partner_ids') or res.get('partner_cc_ids')):
            rules = request.env['gec.access.profile']._current_rules()
            if rules.enabled and rules.model_flag(thread._name, 'hide_send_message'):
                raise request.env['gec.access.profile']._gec_refusal(
                    _("Your access profile does not allow sending messages here. Log a note instead."),
                    model=thread._name, method='message_post', record_ids=thread.ids)
        return res
