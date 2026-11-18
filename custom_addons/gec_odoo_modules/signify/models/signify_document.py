import base64
import logging
import os

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, RedirectWarning, UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import split_every

from ..tools.signify_api import FILE_TIMEOUT, STATUS_BATCH_SIZE, SignifyAPI, SignifyError, SignifyTransportError

_logger = logging.getLogger(__name__)

SYNC_FIELDS = frozenset({'state', 'signify_ref', 'signed_attachment_ids', 'evidence_attachment_id', 'connection_id'})


class SignifyDocument(models.Model):
    _name = 'signify.document'
    _inherit = ['mail.thread']
    _description = 'Signify Document'
    _order = 'id desc'
    _check_company_auto = True
    _mail_post_access = 'read'

    @api.model
    def _selection_target_model(self):
        return [(model.model, model.name) for model in self.env['ir.model'].sudo().search([
            ('model', 'not in', ('signify.document', 'discuss.channel')),
            ('is_mail_thread', '=', True),
            ('abstract', '=', False),
        ])]

    name = fields.Char(required=True, compute='_compute_name', store=True, readonly=False, precompute=True)
    company_id = fields.Many2one('res.company', required=True, index=True, default=lambda self: self.env.company)
    reference_doc = fields.Reference(string="Linked To", selection='_selection_target_model', index='btree_not_null')
    file = fields.Binary(required=True)
    file_name = fields.Char()
    workflow_type = fields.Selection([('serial', "In Order"), ('parallel', "All at Once")], string="Signing Order", required=True, default='serial')
    message = fields.Text(string="Message for Recipients")
    recipient_ids = fields.One2many('signify.recipient', 'document_id', string="Recipients", copy=True)
    state = fields.Selection([
        ('draft', "Draft"),
        ('shared', "Sent"),
        ('finished', "Signed"),
        ('rejected', "Rejected"),
        ('canceled', "Recalled"),
        ('deleted', "Deleted"),
    ], required=True, default='draft', readonly=True, tracking=True, copy=False)
    signify_ref = fields.Char(string="Signify ID", readonly=True, copy=False, index='btree_not_null')
    signed_attachment_ids = fields.Many2many('ir.attachment', 'signify_document_signed_attachment_rel', 'document_id', 'attachment_id',
        string="Signed Files", readonly=True, copy=False)
    evidence_attachment_id = fields.Many2one('ir.attachment', string="Evidence Report", readonly=True, copy=False, ondelete='set null')
    connection_id = fields.Many2one('signify.connection', string="Sent With", readonly=True, copy=False, ondelete='restrict', index='btree_not_null',
        check_company=True)

    @api.depends('file_name')
    def _compute_name(self):
        for document in self:
            document.name = document.name or os.path.splitext(document.file_name or '')[0]

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            if any(SYNC_FIELDS.intersection(vals) for vals in vals_list):
                raise AccessError(self.env._("Only Signify can change the status and the signed files of a document."))
            # explicit values keep a context default_* or an ir.default row from filling the sync fields
            vals_list = [dict.fromkeys(SYNC_FIELDS, False) | {'state': 'draft'} | vals for vals in vals_list]
        documents = super().create(vals_list)
        documents._check_reference_doc()
        return documents

    def write(self, vals):
        if not self.env.su and SYNC_FIELDS.intersection(vals):
            raise AccessError(self.env._("Only Signify can change the status and the signed files of a document."))
        res = super().write(vals)
        if 'reference_doc' in vals:
            self._check_reference_doc()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_shared_or_finished(self):
        if any(document.state == 'shared' for document in self):
            raise UserError(self.env._("Recall a sent document before deleting it."))
        if any(document.state == 'finished' for document in self):
            raise UserError(self.env._("A signed document cannot be deleted: it keeps the signed files and the evidence report."))

    def _check_reference_doc(self):
        """Runs on the saved value, so a link set by a context default or an ir.default is checked too."""
        for document in self.filtered('reference_doc'):
            linked = document.reference_doc
            if not linked.exists() or not linked.has_access('read'):
                raise ValidationError(self.env._("You don't have access to the linked document."))

    def _linked_thread(self):
        record = self.reference_doc
        if record and record.exists() and self.env['ir.model']._get(record._name).is_mail_thread:
            return record
        return None

    def _signify_details_payload(self, document_id):
        self.ensure_one()
        company = self.company_id
        details = {'remindersFrequencyType': company.signify_reminder_frequency.upper()}
        if company.signify_reminder_frequency != 'never':
            details['remindersMaxCount'] = company.signify_reminder_max_count
        if self.message:
            details['messageForRecipients'] = self.message
        return {
            'documentId': document_id,
            'workflowType': self.workflow_type.upper(),
            'shareAutomatically': False,
            'recipients': [recipient._signify_payload(order) for order, recipient in enumerate(self.recipient_ids.sorted('sequence'), start=1)],
            'additionalDetails': details,
        }

    def action_send(self):
        """A retried request must not share twice: Odoo writes are flushed first, share-document is the last call."""
        self.ensure_one()
        self.check_access('write')
        if not self.try_lock_for_update(allow_referencing=True):
            raise UserError(self.env._("This document is being sent already."))
        if self.state != 'draft':
            raise UserError(self.env._("Only a draft document can be sent."))
        missing_keyword = self.recipient_ids.filtered(lambda line: line.role == 'signer' and not (line.placement_keyword or '').strip())[:1]
        if missing_keyword:
            raise UserError(self.env._("Enter a Signature Keyword for %(signer)s using text that appears in the uploaded file.",
                signer=missing_keyword.partner_id.display_name))
        unproven = self.recipient_ids.filtered(lambda line: line.role in ('signer', 'approver')
            and line.contact_type == 'link' and line.auth_type == 'basic')[:1]
        if unproven:
            raise UserError(self.env._(
                "Choose SMS Code or another Signing Method for %(recipient)s: with Link and Basic, Signify cannot prove who signed.",
                recipient=unproven.partner_id.display_name))
        no_phone = self.recipient_ids.filtered(lambda line: not line.partner_id.phone and (line.contact_type == 'mobile'
            or line.role in ('signer', 'approver') and line.auth_type == 'sms_otp'))[:1]
        if no_phone:
            raise UserError(self.env._("Add a mobile number to the Phone of %(recipient)s: SMS invitations and SMS codes need it.",
                recipient=no_phone.partner_id.display_name))
        connection = self.env['signify.connection'].search([('user_id', '=', self.env.uid), ('company_id', '=', self.company_id.id)], limit=1)
        if not connection:
            raise RedirectWarning(self.env._("Connect your Signify account before sending this document."),
                self.env.ref('signify.action_signify_connection').id, self.env._("Open Signify Accounts"))
        client = SignifyAPI(connection.sudo())
        data = client.call('create-document',
            {'documentName': self.name, 'extension': os.path.splitext(self.file_name or '')[1][1:].lower(), 'fileBase64': self.file.to_base64()},
            timeout=FILE_TIMEOUT)
        document_id = data['documentId']
        try:
            details = client.call('set-document-details', self._signify_details_payload(document_id))
            items = {str(item.get('recipientCode')): item for item in details.get('recipients') or []}
            if any(str(recipient.id) not in items for recipient in self.recipient_ids):
                raise UserError(self.env._("Signify did not confirm every recipient. The document was not sent."))
            document = self.sudo()
            commands = []
            for recipient in document.recipient_ids:
                item = items[str(recipient.id)]
                commands.append(Command.update(recipient.id, {'signify_ref': str(item['id']), **recipient._signify_sync_vals(item)}))
            document.write({
                'signify_ref': str(document_id),
                'state': 'shared',
                'connection_id': connection.id,
                'recipient_ids': commands,
            })
            linked = document._linked_thread()
            if linked:
                linked.message_post(body=self.env._("Sent for signature with Signify: %(name)s", name=self.name), subtype_xmlid='mail.mt_note')
            self.env.cr.flush()
        except Exception:
            self._signify_discard_draft(client, document_id)
            raise
        try:
            client.call('share-document', {'documentId': document_id}, timeout=FILE_TIMEOUT)
        except SignifyTransportError as exc:
            raise UserError(self.env._("Signify did not confirm the share of %s (%s): check the Signify portal before sending it again.", self.name,
                exc.args[0])) from exc
        except Exception:
            self._signify_discard_draft(client, document_id)
            raise
        return True

    def _signify_discard_draft(self, client, document_id):
        try:
            client.call('delete-document', {'documentId': document_id, 'omitTrash': True})
        except Exception:
            _logger.exception("Signify: could not delete the draft %s after a failed send", document_id)

    def action_refresh(self):
        self.check_access('read')
        for connection, documents in self.sudo().filtered('signify_ref').grouped('connection_id').items():
            documents.with_company(documents.company_id[:1])._signify_sync(SignifyAPI(connection))
        return True

    def action_recall(self):
        self.ensure_one()
        self.check_access('read')
        if self.state != 'shared':
            raise UserError(self.env._("Only a sent document can be recalled."))
        SignifyAPI(self.sudo().connection_id).call('recall-document', {'documentId': int(self.signify_ref)})
        self.sudo().state = 'canceled'
        return True

    @api.model
    def action_new_from_attachment(self, attachment_id):
        """The file is read as the user, so the attachment's own access rule applies."""
        attachment = self.env['ir.attachment'].browse(attachment_id)
        attachment.check_access('read')
        vals, record = {'file': attachment.raw, 'file_name': attachment.name}, None
        if attachment.res_id and attachment.res_model in dict(self._selection_target_model()):
            record = self.env[attachment.res_model].browse(attachment.res_id).exists()
        if record:
            vals['reference_doc'] = f"{record._name},{record.id}"
            vals['company_id'] = record._mail_get_companies()[record.id].id or self.env.company.id
        document = self.create(vals)
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': document.id, 'views': [(False, 'form')], 'target': 'current'}

    @api.model
    def _signify_in_progress_domain(self):
        """Signify still works on the document: Sent, or Signed while its evidence report has not arrived."""
        return Domain('state', '=', 'shared') | (Domain('state', '=', 'finished') & Domain('evidence_attachment_id', '=', False))

    @api.model
    def _cron_signify_sync(self):
        documents = self.search(Domain('signify_ref', '!=', False) & self._signify_in_progress_domain())
        for connection, connection_documents in documents.grouped('connection_id').items():
            try:
                if not connection_documents.with_company(connection.company_id)._signify_sync(SignifyAPI(connection), cron=True):
                    break
            except UserError as exc:
                _logger.warning("Signify: sync with account %s stopped: %s", connection.id, exc)

    def _signify_sync(self, client, cron=False):
        """In cron mode a failing document is logged and skipped, and progress is committed per document; False means the cron has no time left."""
        statuses = {}
        batches = list(split_every(STATUS_BATCH_SIZE, self.mapped('signify_ref')))
        while batches:
            batch = batches.pop(0)
            try:
                data = client.call('get-documents-status', {'documentIds': [int(ref) for ref in batch]})
            except SignifyError as exc:
                if len(batch) > 1:
                    batches.extend((ref,) for ref in batch)
                elif exc.status_code == 'DOCUMENT_NOT_FOUND':
                    statuses[batch[0]] = {'documentStatus': 'DELETED'}
                elif cron:
                    _logger.warning("Signify: the status of document %s was not read: %s", batch[0], exc)
                else:
                    raise
                continue
            statuses.update({str(item['documentId']): item for item in data.get('documentsStatus') or []})
        for document in self:
            status = statuses.get(document.signify_ref)
            if status is None:
                continue
            document._signify_step(cron, document._signify_apply_status, client, status)
            if document.state == 'finished' and not document.evidence_attachment_id:
                document._signify_step(cron, document._signify_fetch_evidence, client)
            if cron and not self.env['ir.cron']._commit_progress(1):
                return False
        return True

    def _signify_step(self, cron, method, *args):
        """In the cron each step has its own savepoint, so a failed evidence download keeps the signed files."""
        if not cron:
            return method(*args)
        try:
            with self.env.cr.savepoint():
                method(*args)
        except Exception:
            _logger.exception("Signify: %s of document %s failed", method.__name__, self.id)

    def _signify_apply_status(self, client, status):
        """A DRAFT answer is ignored: it would reopen Send on a document Signify still holds."""
        self.ensure_one()
        state = (status.get('documentStatus') or '').lower()
        if state == 'draft' or state not in dict(self._fields['state'].selection):
            _logger.warning("Signify: unknown status %s on document %s, skipped", status.get('documentStatus'), self.id)
            return
        items = {str(item['id']): item for item in status.get('recipientsStatus') or []}
        commands = []
        for recipient in self.recipient_ids:
            item = items.get(recipient.signify_ref)
            if item:
                vals = {k: v for k, v in recipient._signify_sync_vals(item).items() if recipient[k] != v}
                if vals:
                    commands.append(Command.update(recipient.id, vals))
        vals = {'state': state} if state != self.state else {}
        if commands:
            vals['recipient_ids'] = commands
        newly_rejected = state == 'rejected' and self.state != 'rejected'
        newly_finished = state == 'finished' and self.state != 'finished'
        if vals:
            self.write(vals)
        if newly_rejected:
            rejecting = [item for item in items.values() if item.get('status') == 'REJECTED']
            body = self.env._("Rejected in Signify by %(names)s. %(reasons)s", names=", ".join(item.get('name') or "" for item in rejecting),
                reasons=" ".join(item['message'] for item in rejecting if item.get('message'))).strip()
            for thread in (self, self._linked_thread()):
                if thread:
                    thread.message_post(body=body, subtype_xmlid='mail.mt_note')
        if newly_finished:
            self._signify_fetch_signed_files(client)

    def _signify_fetch_signed_files(self, client):
        data = client.call('download-document', {'documentId': int(self.signify_ref)}, timeout=FILE_TIMEOUT)
        files = [(item, base64.b64decode(item['base64'])) for item in data['documents']]
        attachments = self.env['ir.attachment'].create([{
            'name': item['fileName'],
            'raw': raw,
            'res_model': self._name,
            'res_id': self.id,
        } for item, raw in files])
        self.signed_attachment_ids = attachments
        self.message_post(body=self.env._("Signed files received from Signify"), attachment_ids=attachments.ids, subtype_xmlid='mail.mt_note')
        linked = self._linked_thread()
        if linked:
            copies = [{
                'name': item['fileName'],
                'raw': raw,
                'res_model': linked._name,
                'res_id': linked.id,
            } for item, raw in files if item.get('fileType') == 'DOCUMENT']
            if copies:
                self.env['ir.attachment'].with_context(no_document=True).create(copies)
                linked.message_post(body=self.env._("Signed with Signify: %(files)s", files=", ".join(copy['name'] for copy in copies)),
                    subtype_xmlid='mail.mt_note')

    def _signify_fetch_evidence(self, client):
        """A report not generated yet is no error: the next sync asks for it again."""
        try:
            data = client.call('download-evidence-report', {'documentId': int(self.signify_ref)}, timeout=FILE_TIMEOUT)
        except SignifyError as exc:
            if exc.status_code == 'EVIDENCE_REPORT_NOT_YET_GENERATED':
                return
            raise
        attachment = self.env['ir.attachment'].create({
            'name': data['fileName'],
            'raw': base64.b64decode(data['base64']),
            'res_model': self._name,
            'res_id': self.id,
        })
        self.evidence_attachment_id = attachment
        self.message_post(body=self.env._("Evidence report received from Signify"), attachment_ids=attachment.ids, subtype_xmlid='mail.mt_note')
