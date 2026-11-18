from odoo import _, api, models
from odoo.fields import Domain

NOTE_SUBTYPE = 'mail.mt_note'


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    def _gec_check_send_message(self, method, kwargs, sends=False):
        """ Refuse a client message when a profile hides Send Message for the model it lands on (message_notify on
        mail.thread itself names it in ``model``); a note naming no partner is allowed, unless ``sends``. """
        if not self._gec_rpc_entry(method):
            return
        sends = sends or (kwargs.get('subtype_xmlid') not in (None, False, NOTE_SUBTYPE)
                          or kwargs.get('subtype_id') or kwargs.get('partner_ids'))
        model_name = self._name if self else (kwargs.get('model') or self._name)
        rules = self.env['gec.access.profile']._current_rules()
        if sends and rules.enabled and rules.model_flag(model_name, 'hide_send_message'):
            raise self.env['gec.access.profile']._gec_refusal(
                _("Your access profile does not allow sending messages here. Log a note instead."),
                model=model_name, method=method, record_ids=self.ids)

    def message_post(self, **kwargs):
        self._gec_check_send_message('message_post', kwargs)
        return super().message_post(**kwargs)

    def message_notify(self, **kwargs):
        self._gec_check_send_message('message_notify', kwargs)
        return super().message_notify(**kwargs)

    def message_post_with_source(self, source_ref, **kwargs):
        self._gec_check_send_message('message_post_with_source', kwargs)
        return super().message_post_with_source(source_ref, **kwargs)

    def message_mail_with_source(self, source_ref, **kwargs):
        self._gec_check_send_message('message_mail_with_source', kwargs, sends=True)
        return super().message_mail_with_source(source_ref, **kwargs)

    def _notify_get_recipients(self, message, **kwargs):
        """ Drop from a tracking message's notifications the users it shows a hidden field to: mail, Inbox and push
        carry the body. """
        recipients = super()._notify_get_recipients(message, **kwargs)
        if message.message_type != 'tracking' or not recipients:
            return recipients
        body = (message.sudo().body or '').lower()
        Profile, Message = self.env['gec.access.profile'], self.env['mail.message']

        def shows_hidden(uid):
            rules = Profile._resolve(uid)
            return rules.enabled and any(
                marker.lower() in body for marker in Message._gec_hidden_tracking_markers(rules))
        return [recipient for recipient in recipients if not (recipient.get('uid') and shows_hidden(recipient['uid']))]


class MailMessage(models.Model):
    _inherit = 'mail.message'

    def _search(self, domain, offset=0, limit=None, order=None, *, bypass_access=False, **kwargs):
        """ A search past the access rules (messages filtered through message_ids) still leaves out tracking messages
        that show a hidden field: their body tells the value. """
        if bypass_access and not self.env.su:
            rules = self.env['gec.access.profile']._current_rules()
            hidden = rules.enabled and self._gec_hidden_tracking_domain(rules)
            if hidden:
                domain = Domain(domain) & hidden
        return super()._search(domain, offset, limit, order, bypass_access=bypass_access, **kwargs)


class MailScheduledMessage(models.Model):
    _inherit = 'mail.scheduled.message'

    def _gec_check_send_message(self):
        """ Refuse scheduled messages that would be sent (not partner-less notes) when Send Message is hidden for their
        model: the cron posts them as their creator, outside any client call. """
        rules = self.env['gec.access.profile']._current_rules()
        for scheduled in self:
            if (rules.enabled and (not scheduled.is_note or scheduled.partner_ids)
                    and rules.model_flag(scheduled.model, 'hide_send_message')):
                raise self.env['gec.access.profile']._gec_refusal(
                    _("Your access profile does not allow sending messages here. Log a note instead."),
                    model=scheduled.model, method='message_post')

    def _gec_client_saves(self):
        return self._gec_client_reads_model() and not self.env.su

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if self._gec_client_saves():
            records._gec_check_send_message()
        return records

    def write(self, vals):
        result = super().write(vals)
        if self._gec_client_saves():
            self._gec_check_send_message()
        return result

    def post_message(self):
        """ Refuse the posting a client asks for of a scheduled message, as for the composer that scheduled it. """
        if self._gec_rpc_entry('post_message'):
            self._gec_check_send_message()
        return super().post_message()


class MailTemplate(models.Model):
    _inherit = 'mail.template'

    def _gec_check_send_mail(self, method):
        if not self._gec_rpc_entry(method):
            return
        rules = self.env['gec.access.profile']._current_rules()
        for template in self:
            if rules.enabled and template.model and rules.model_flag(template.model, 'hide_send_message'):
                raise self.env['gec.access.profile']._gec_refusal(
                    _("Your access profile does not allow sending messages here. Log a note instead."),
                    model=template.model, method=method)

    def send_mail(self, res_id, *args, **kwargs):
        self._gec_check_send_mail('send_mail')
        return super().send_mail(res_id, *args, **kwargs)

    def send_mail_batch(self, res_ids, *args, **kwargs):
        self._gec_check_send_mail('send_mail_batch')
        return super().send_mail_batch(res_ids, *args, **kwargs)


class MailComposeMessage(models.TransientModel):
    _inherit = 'mail.compose.message'

    def _gec_check_send_message(self, method):
        """ Refuse a composer send or schedule when Send Message is hidden for its model: its message_post is a call of
        the wizard, not of the model (mail_thread.py). A log note with no partner stays allowed, as in the chatter. """
        if not self._gec_rpc_entry(method):
            return
        rules = self.env['gec.access.profile']._current_rules()
        for wizard in self:
            if (rules.enabled and wizard.model
                    and (wizard.composition_mode != 'comment' or not wizard.subtype_is_log or wizard.partner_ids)
                    and rules.model_flag(wizard.model, 'hide_send_message')):
                raise self.env['gec.access.profile']._gec_refusal(
                    _("Your access profile does not allow sending messages here. Log a note instead."),
                    model=wizard.model, method='message_post')

    def _action_send_mail(self, auto_commit=False):
        self._gec_check_send_message('action_send_mail')
        return super()._action_send_mail(auto_commit=auto_commit)

    def _action_schedule_message(self):
        self._gec_check_send_message('action_schedule_message')
        return super()._action_schedule_message()
