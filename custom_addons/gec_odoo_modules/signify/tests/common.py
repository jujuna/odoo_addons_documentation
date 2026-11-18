import base64
import itertools
import json
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import Command, fields
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools import BinaryBytes

from odoo.addons.signify.tools.signify_api import BASE_URL, OAUTH_URL

PDF = b'%PDF-1.4 test'
REQUEST = 'odoo.addons.signify.tools.signify_api.requests.request'
DOCUMENT_LOGGER = 'odoo.addons.signify.models.signify_document'
RECIPIENT_LOGGER = 'odoo.addons.signify.models.signify_recipient'

_refs = itertools.count(1000)


class SignifyCommon(TransactionCase):
    """Shared fixture; the HTTP layer is always mocked."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not cls._registry_patched:
            cls.enterClassContext(cls.registry_test_mode())  # the token refresh runs in a cursor of its own
        cls.env = cls.env(context=dict(
            cls.env.context, mail_create_nolog=True, mail_notrack=True, no_reset_password=True))
        cls.company = cls.env.company
        cls.env['ir.config_parameter'].set_str('signify.client_id', 'client-id')
        cls.env['ir.config_parameter'].set_str('signify.client_secret', 'client-secret')
        cls.company_b = cls.env['res.company'].create({'name': "Signify Company B"})

        user_groups = 'base.group_user,signify.group_signify_user'
        manager_groups = 'base.group_user,signify.group_signify_manager'
        cls.user = new_test_user(cls.env, login='signify_user', groups=user_groups, company_id=cls.company.id)
        cls.user_2 = new_test_user(cls.env, login='signify_user_2', groups=user_groups, company_id=cls.company.id)
        cls.manager = new_test_user(cls.env, login='signify_manager', groups=manager_groups, company_id=cls.company.id)
        cls.employee = new_test_user(cls.env, login='signify_employee', groups='base.group_user',
                                     company_id=cls.company.id)
        company_b_vals = {'company_id': cls.company_b.id, 'company_ids': [Command.set(cls.company_b.ids)]}
        cls.user_b = new_test_user(cls.env, login='signify_user_b', groups=user_groups, **company_b_vals)
        cls.manager_b = new_test_user(cls.env, login='signify_manager_b', groups=manager_groups, **company_b_vals)
        cls.connection = cls._connect(cls.user)
        cls.connection_manager = cls._connect(cls.manager)
        cls.connection_b = cls._connect(cls.user_b)
        cls.connection_root = cls._connect(cls.env.user, cls.company)

        Partner = cls.env['res.partner'].with_context(no_vat_validation=True)
        cls.person = Partner.create({
            'name': "Test Person",
            'email': 'person@example.com',
            'phone': '+995 599 12 34 56',
            'country_id': cls.env.ref('base.ge').id,
            'vat': '01010112312',
        })
        cls.company_partner = Partner.create({'name': "Test Company LLC", 'vat': '204567890'})
        cls.contact = Partner.create({
            'name': "Test Contact",
            'email': 'contact@example.com',
            'parent_id': cls.company_partner.id,
        })
        cls.linked = cls.env['res.partner'].create({'name': "Linked Record"})

    @classmethod
    def _connect(cls, user, company=None, **vals):
        """A connected Signify account with a valid access token; ``cls.env.user`` is the user of a test that sends as superuser."""
        cls.env.flush_all()
        return cls.env['signify.connection'].sudo().create({
            'user_id': user.id,
            'company_id': (company or user.company_id).id,
            'signify_sub': f'sub-{user.login}',
            'email': f'{user.login}@signify.example',
            'access_token': 'tok-1',
            'refresh_token': f'ref-{user.login}',
            'expiry': fields.Datetime.now() + timedelta(hours=1),
            **vals,
        })

    @staticmethod
    def _response(body, status=200):
        response = MagicMock()
        response.status_code = status
        if isinstance(body, dict):
            response.json.return_value = body
            response.text = json.dumps(body)
        else:
            response.json.side_effect = ValueError("not JSON")
            response.text = body or ''
        return response

    def _ok(self, **body):
        return self._response({'status': 'SUCCESS', **body})

    def _failure(self, message, code=None, status=400):
        body = {'status': 'VALIDATION_WARNING', 'statusMessage': message}
        if code:
            body['statusCode'] = code
        return self._response(body, status)

    @staticmethod
    def _operation(url):
        """The document API operation, or ``oauth/<endpoint>`` for an OAuth URL."""
        return 'oauth/' + url.removeprefix(OAUTH_URL) if url.startswith(OAUTH_URL) else url.removeprefix(BASE_URL)

    def _token_response(self, access_token='tok-new', expires_in=1799, **body):
        return self._response({'access_token': access_token, 'token_type': 'Bearer', 'expires_in': expires_in, **body})

    def _oauth_error(self, error, description=None, status=400):
        return self._response({'error': error, 'error_description': description} if description else {'error': error}, status)

    @contextmanager
    def _signify(self, handlers=None):
        """Patch requests.request with a router on the operation name (``oauth/token`` for the OAuth endpoints); yields the mock.
        A handler is a response, a callable(payload), an exception or a list of those consumed in order."""
        handlers = dict(handlers or {})
        queues = {operation: list(handler) for operation, handler in handlers.items() if isinstance(handler, list)}
        unhandled = []

        def router(method, url, **kwargs):
            operation = self._operation(url)
            handler = handlers.get(operation)
            if isinstance(handler, list):
                handler = queues[operation].pop(0) if queues[operation] else None
            if handler is None:
                unhandled.append(operation)
                raise AssertionError(f"Unexpected Signify call: {operation}")
            if isinstance(handler, BaseException):
                raise handler
            if isinstance(handler, MagicMock):
                return handler
            return handler(kwargs.get('json') or kwargs.get('data'))

        with patch(REQUEST, side_effect=router) as post:
            yield post
        self.assertEqual(unhandled, [])

    def _operations(self, post):
        return [self._operation(call.args[1]) for call in post.call_args_list]

    def _calls(self, post, operation):
        """The keyword arguments (json or data, headers, auth, timeout) of every call of one operation."""
        return [call.kwargs for call in post.call_args_list if self._operation(call.args[1]) == operation]

    def _sent(self, post, operation):
        return [kwargs.get('json') or kwargs.get('data') for kwargs in self._calls(post, operation)]

    def _details_response(self, payload):
        """The set-document-details answer: recipients in reverse order."""
        recipients = [{
            'recipientCode': item['recipientCode'],
            'id': int(item['recipientCode']) + 5000,
            'status': 'PENDING_ON_USER' if item.get('orderNumber', 1) == 1 else 'PENDING',
        } for item in payload['recipients']]
        return self._ok(recipients=recipients[::-1])

    def _send_handlers(self, overrides=None):
        return {
            'create-document': self._ok(documentId=777),
            'set-document-details': self._details_response,
            'share-document': self._ok(),
            **(overrides or {}),
        }

    def _signed_files_response(self):
        pdf = base64.b64encode(PDF).decode()
        return self._ok(documents=[
            {'fileName': 'contract-signed.pdf', 'base64': pdf, 'fileType': 'DOCUMENT'},
            {'fileName': 'attachment.pdf', 'base64': pdf, 'fileType': 'ATTACHMENT'},
        ])

    def _evidence_response(self):
        return self._ok(fileName='evidence.pdf', base64=base64.b64encode(PDF).decode())

    def _status(self, document, status, recipients=None):
        """One entry of get-documents-status."""
        items = [{
            'id': int(recipient.sudo().signify_ref),
            'name': recipient.sudo().partner_id.name,
            **(value if isinstance(value, dict) else {'status': value}),
        } for recipient, value in (recipients or {}).items()]
        return {'documentId': int(document.sudo().signify_ref), 'documentStatus': status, 'recipientsStatus': items}

    def _status_body(self, *entries):
        return self._ok(documentsStatus=list(entries))

    def _sync_handlers(self, *entries, overrides=None):
        return {
            'get-documents-status': self._status_body(*entries),
            'download-document': self._signed_files_response(),
            'download-evidence-report': self._evidence_response(),
            **(overrides or {}),
        }

    def _run_cron(self):
        """The progress commit is patched out because a TransactionCase cannot commit."""
        with patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=float('inf')) as commit:
            self.env['signify.document']._cron_signify_sync()
        return commit

    def _line(self, **vals):
        """Values of one recipient line; keyword args override the defaults."""
        return {
            'partner_id': self.person.id,
            'role': 'signer',
            'contact_type': 'email',
            'auth_type': 'basic',
            'placement_keyword': 'Director',
            **vals,
        }

    def _document_vals(self, recipients=None, **vals):
        lines = [self._line()] if recipients is None else recipients
        return {
            'file': BinaryBytes(PDF),
            'file_name': 'contract.pdf',
            'reference_doc': f'res.partner,{self.linked.id}',
            'recipient_ids': [Command.create(line) for line in lines],
            **vals,
        }

    def _document(self, user=None, recipients=None, **vals):
        """A draft document created by ``user`` (default: Signify User of company A)."""
        return self.env['signify.document'].with_user(user or self.user).create(self._document_vals(recipients, **vals))

    def _shared(self, user=None, recipients=None, **vals):
        """A sent document: state, Signify ids and the account of its creator set directly, no API call."""
        document = self._document(user, recipients, **vals)
        ref = next(_refs)
        connection = self.env['signify.connection'].search([('user_id', '=', (user or self.user).id), ('company_id', '=', document.company_id.id)])
        document.sudo().write({'state': 'shared', 'signify_ref': str(ref), 'connection_id': connection.id})
        for index, recipient in enumerate(document.sudo().recipient_ids, start=1):
            recipient.signify_ref = str(ref * 100 + index)
        return document

    def _attachment(self):
        return self.env['ir.attachment'].create({'name': 'file.pdf', 'raw': PDF})

    @staticmethod
    def _notes(record, text):
        return record.sudo().message_ids.filtered(lambda message: text in str(message.body))
