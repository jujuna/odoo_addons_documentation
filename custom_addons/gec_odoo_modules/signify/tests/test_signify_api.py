from datetime import timedelta

import requests

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.signify.tools.signify_api import FILE_TIMEOUT, TIMEOUT, SignifyAPI, SignifyError, SignifyTransportError

from .common import SignifyCommon

STATUS = 'get-documents-status'


@tagged('post_install', '-at_install')
class TestSignifyApi(SignifyCommon):

    def test_the_token_of_the_connection_is_used_without_any_oauth_call(self):
        self.connection_b.access_token = 'tok-b'
        with self._signify({STATUS: self._ok(documentsStatus=[])}) as post:
            SignifyAPI(self.connection_b).call(STATUS, {'documentIds': [1]})
        self.assertEqual(self._operations(post), [STATUS])
        self.assertEqual(self._calls(post, STATUS)[0]['headers']['Authorization'], 'Bearer tok-b')

    def test_calls_carry_the_bearer_token(self):
        with self._signify({STATUS: self._ok(documentsStatus=[])}) as post:
            SignifyAPI(self.connection).call(STATUS, {'documentIds': [1]})
        headers = self._calls(post, STATUS)[0]['headers']
        self.assertEqual(headers['Authorization'], 'Bearer tok-1')
        self.assertEqual(headers['Content-Type'], 'application/json')

    def test_call_returns_the_success_body(self):
        with self._signify({STATUS: self._ok(documentsStatus=[{'documentId': 5}])}):
            data = SignifyAPI(self.connection).call(STATUS, {'documentIds': [5]})
        self.assertEqual(data['documentsStatus'], [{'documentId': 5}])

    def test_the_token_is_reused(self):
        with self._signify({STATUS: self._ok(documentsStatus=[])}) as post:
            api = SignifyAPI(self.connection)
            api.call(STATUS, {'documentIds': [1]})
            api.call(STATUS, {'documentIds': [2]})
        self.assertEqual(self._operations(post), [STATUS, STATUS])

    def test_http_401_forces_one_refresh_and_repeats_the_call(self):
        """A token Signify no longer accepts is renewed even when its expiry is still in the future."""
        handlers = {'oauth/token': self._token_response('tok-2'), STATUS: [self._response('', 401), self._ok(documentsStatus=[])]}
        with self._signify(handlers) as post:
            SignifyAPI(self.connection).call(STATUS, {'documentIds': [1]})
        self.assertEqual(self._operations(post), [STATUS, 'oauth/token', STATUS])
        tokens = [kwargs['headers']['Authorization'] for kwargs in self._calls(post, STATUS)]
        self.assertEqual(tokens, ['Bearer tok-1', 'Bearer tok-2'])
        self.assertEqual(self.connection.access_token, 'tok-2')

    def test_a_second_http_401_is_an_error_and_does_not_loop(self):
        handlers = {'oauth/token': self._token_response('tok-2'), STATUS: [self._response('', 401), self._response('', 401)]}
        with self._signify(handlers) as post, self.assertRaises(UserError) as cm:
            SignifyAPI(self.connection).call(STATUS, {'documentIds': [1]})
        self.assertIn('401', str(cm.exception))
        self.assertEqual(self._operations(post), [STATUS, 'oauth/token', STATUS])

    def test_a_json_error_body_is_read_before_the_http_code(self):
        failure = self._failure("The name is too long", status=400)
        with self._signify({STATUS: failure}), self.assertRaises(UserError) as cm:
            SignifyAPI(self.connection).call(STATUS, {'documentIds': [1]})
        self.assertIn("The name is too long", str(cm.exception))
        self.assertNotIn('400', str(cm.exception))

    def test_a_non_success_status_is_an_error_even_with_http_200(self):
        with self._signify({STATUS: self._failure("Refused", status=200)}), self.assertRaises(UserError) as cm:
            SignifyAPI(self.connection).call(STATUS, {'documentIds': [1]})
        self.assertIn("Refused", str(cm.exception))

    def test_the_status_code_is_kept_on_the_error(self):
        """The caller can tell errors apart by the statusCode Signify sent."""
        failure = self._failure("Not ready", code='EVIDENCE_REPORT_NOT_YET_GENERATED')
        with self._signify({STATUS: failure}), self.assertRaises(SignifyError) as cm:
            SignifyAPI(self.connection).call(STATUS, {'documentIds': [1]})
        self.assertEqual(cm.exception.status_code, 'EVIDENCE_REPORT_NOT_YET_GENERATED')
        self.assertIsInstance(cm.exception, UserError)

    def test_the_status_code_is_empty_when_signify_sends_none(self):
        with self._signify({STATUS: self._failure("Plain error")}), self.assertRaises(SignifyError) as cm:
            SignifyAPI(self.connection).call(STATUS, {'documentIds': [1]})
        self.assertIsNone(cm.exception.status_code)

    def test_a_body_that_is_not_json_names_the_http_code(self):
        with (
            self._signify({STATUS: self._response('<html>Bad gateway</html>', 502)}),
            self.assertRaises(UserError) as cm,
        ):
            SignifyAPI(self.connection).call(STATUS, {'documentIds': [1]})
        self.assertIn('502', str(cm.exception))

    def test_network_errors_become_user_errors(self):
        cases = [
            (requests.Timeout(), "did not answer in time"),
            (requests.ConnectionError(), "unreachable"),
            (requests.RequestException(), "request to Signify failed"),
        ]
        for exception, text in cases:
            with self.subTest(exception=type(exception).__name__):
                with self._signify({STATUS: exception}), self.assertRaises(SignifyTransportError) as cm:
                    SignifyAPI(self.connection).call(STATUS, {'documentIds': [1]})
                self.assertIn(text, str(cm.exception))

    def test_no_connection_asks_to_connect_and_sends_nothing(self):
        with self._signify() as post, self.assertRaises(UserError) as cm:
            SignifyAPI(self.env['signify.connection'])
        self.assertIn("Connect your Signify account", str(cm.exception))
        post.assert_not_called()

    def test_the_language_header_is_ka_for_georgian(self):
        self.env['res.lang']._activate_lang('ka_GE')
        with self._signify({STATUS: self._ok(documentsStatus=[])}) as post:
            SignifyAPI(self.connection.with_context(lang='ka_GE')).call(STATUS, {'documentIds': [1]})
        for call in post.call_args_list:
            self.assertEqual(call.kwargs['headers']['X-Language'], 'ka')

    def test_the_language_header_is_en_otherwise(self):
        with self._signify({STATUS: self._ok(documentsStatus=[])}) as post:
            SignifyAPI(self.connection.with_context(lang='en_US')).call(STATUS, {'documentIds': [1]})
        for call in post.call_args_list:
            self.assertEqual(call.kwargs['headers']['X-Language'], 'en')

    def test_send_uses_the_file_timeout_for_the_upload_and_the_share(self):
        """Upload and share get the long timeout: a share timeout is an unknown outcome."""
        document = self._document()
        with self._signify(self._send_handlers()) as post:
            document.action_send()
        timeouts = {operation: kwargs['timeout']
                    for operation in self._operations(post) for kwargs in self._calls(post, operation)}
        self.assertEqual(timeouts, {
            'create-document': FILE_TIMEOUT,
            'set-document-details': TIMEOUT,
            'share-document': FILE_TIMEOUT,
        })

    def test_sync_uses_the_file_timeout_for_the_downloads_only(self):
        document = self._shared()
        with self._signify(self._sync_handlers(self._status(document, 'FINISHED'))) as post:
            document.action_refresh()
        timeouts = {operation: kwargs['timeout']
                    for operation in self._operations(post) for kwargs in self._calls(post, operation)}
        self.assertEqual(timeouts, {
            STATUS: TIMEOUT,
            'download-document': FILE_TIMEOUT,
            'download-evidence-report': FILE_TIMEOUT,
        })

    def test_the_secret_and_the_tokens_are_never_logged(self):
        self.connection.expiry = fields.Datetime.now() - timedelta(minutes=5)
        handlers = {'oauth/token': self._token_response('tok-fresh'), STATUS: self._ok(documentsStatus=[])}
        with self._signify(handlers), self.assertLogs('odoo.addons.signify', 'INFO') as logs:
            SignifyAPI(self.connection).call(STATUS, {'documentIds': [1]})
        output = '\n'.join(logs.output)
        for secret in ('client-secret', 'tok-1', 'tok-fresh', 'ref-signify_user'):
            self.assertNotIn(secret, output)
