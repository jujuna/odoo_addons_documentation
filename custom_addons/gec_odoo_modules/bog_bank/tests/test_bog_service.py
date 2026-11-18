import json
from datetime import date
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.models import get_public_method
from odoo.tests.common import new_test_user, tagged

from .common import BogCommon


@tagged('post_install', '-at_install')
class TestBogService(BogCommon):
    """Transport layer: parsing, 429/401 handling, log redaction."""

    def test_split_account_currency_strips_suffix(self):
        """BOG rejects a statement IBAN that still carries the currency."""
        self.assertEqual(self.service.split_account_currency('GE11BG1111111111111111GEL'),
                         ('GE11BG1111111111111111', 'GEL'))

    def test_split_account_currency_plain_iban_untouched(self):
        self.assertEqual(self.service.split_account_currency('GE29BG7777777777777777'),
                         ('GE29BG7777777777777777', None))

    def test_split_account_currency_normalises_spaces(self):
        self.assertEqual(self.service.split_account_currency(' ge29 bg77 7777 7777 777777 '),
                         ('GE29BG7777777777777777', None))

    def test_parse_json_returns_native_shapes(self):
        """documents/domestic answers with an array, bulk with a bare integer."""
        self.assertEqual(self.service._parse_json('[{"UniqueKey": 1}]'), [{'UniqueKey': 1}])
        self.assertEqual(self.service._parse_json('12345'), 12345)
        self.assertEqual(self.service._parse_json('"abc-hash"'), 'abc-hash')
        self.assertIsNone(self.service._parse_json('not json'))
        self.assertIsNone(self.service._parse_json(''))

    def test_extract_result_code_from_list_and_dict(self):
        self.assertEqual(self.service._extract_result_code([{'ResultCode': 33}]), 33)
        self.assertEqual(self.service._extract_result_code({'ResultCode': 0}), 0)
        self.assertIsNone(self.service._extract_result_code(12345))
        self.assertIsNone(self.service._extract_result_code([]))

    def test_first_key_accepts_both_casings(self):
        """BOG documents camelCase for JSON and PascalCase for XML."""
        self.assertEqual(self.service._first_key({'records': [1]}, ('records', 'Records')), [1])
        self.assertEqual(self.service._first_key({'Records': [2]}, ('records', 'Records')), [2])
        self.assertEqual(self.service._first_key({}, ('records',), 'fallback'), 'fallback')

    def test_format_date_accepts_date_and_string(self):
        self.assertEqual(self.service._format_date(date(2026, 1, 31)), '2026-01-31')
        self.assertEqual(self.service._format_date('2026-01-31T10:00:00'), '2026-01-31')

    def test_authenticate_stores_token_and_activates(self):
        body = json.dumps({'access_token': 'tok-123', 'expires_in': 300})
        with patch('requests.post', return_value=self._response(200, body)):
            self.assertTrue(self.service.authenticate(self.connection))
        self.assertEqual(self.connection.state, 'active')
        self.assertEqual(self.connection.sudo().access_token, 'tok-123')
        self.assertTrue(self.connection.token_is_valid())

    def test_authenticate_defaults_to_short_lifetime(self):
        """Without expires_in, assume 300s."""
        body = json.dumps({'access_token': 'tok-123'})
        with patch('requests.post', return_value=self._response(200, body)):
            self.service.authenticate(self.connection)
        # 300s minus the 60s safety margin.
        remaining = (self.connection.sudo().token_expiry - self.env.cr.now()).total_seconds()
        self.assertLess(remaining, 600)

    def test_authenticate_failure_sets_error_state(self):
        with patch('requests.post', return_value=self._response(401, '{"error":"bad"}')):
            self.assertFalse(self.service.authenticate(self.connection))
        self.assertEqual(self.connection.state, 'error')

    def test_token_methods_cannot_be_called_over_rpc(self):
        for name in ('store_token', 'clear_token', 'token_is_valid'):
            with self.assertRaises(AccessError):
                get_public_method(self.connection, name)

    def test_test_connection_needs_write_access(self):
        reader = new_test_user(self.env, login='bog_reader', groups='base.group_user,bog_bank.group_bog_user')
        with self.assertRaises(AccessError):
            self.connection.with_user(reader).action_test_connection()

    def test_authenticate_requires_credentials(self):
        self.connection.sudo().write({'client_secret': False})
        self.assertFalse(self.service.authenticate(self.connection))
        self.assertEqual(self.connection.state, 'error')

    def _with_token(self):
        self.connection.store_token('tok-123', 3600)

    def test_call_logs_correlation_id(self):
        """The x-correlationid header is what BOG support asks for."""
        self._with_token()
        response = self._response(200, '{"ok": true}', {'x-correlationid': 'corr-42'})
        with patch('requests.request', return_value=response):
            self.service._call(self.connection, 'accounts/GE1/GEL')
        log = self.env['bog.api.log'].search([('connection_id', '=', self.connection.id)],
                                             limit=1, order='id desc')
        self.assertEqual(log.correlation_id, 'corr-42')

    def test_call_retries_once_on_429(self):
        self._with_token()
        responses = [self._response(429, '', {'Retry-After': '0'}),
                     self._response(200, '{"ok": true}')]
        with patch('requests.request', side_effect=responses) as request:
            data = self.service._call(self.connection, 'accounts/GE1/GEL')
        self.assertEqual(request.call_count, 2)
        self.assertEqual(data, {'ok': True})

    def test_call_does_not_loop_on_repeated_429(self):
        """A repeating 429 is a quota, not a burst: stop after one retry."""
        self._with_token()
        responses = [self._response(429, '', {'Retry-After': '0'}),
                     self._response(429, '', {'Retry-After': '0'})]
        with patch('requests.request', side_effect=responses) as request:
            result = self.service._call(self.connection, 'accounts/GE1/GEL', soft=True)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result['http_status'], 429)

    def test_call_reauthenticates_once_on_401(self):
        self._with_token()
        responses = [self._response(401, ''), self._response(200, '{"ok": true}')]
        token_body = json.dumps({'access_token': 'tok-new', 'expires_in': 300})
        with patch('requests.request', side_effect=responses), \
             patch('requests.post', return_value=self._response(200, token_body)):
            data = self.service._call(self.connection, 'accounts/GE1/GEL')
        self.assertEqual(data, {'ok': True})
        self.assertEqual(self.connection.sudo().access_token, 'tok-new')

    def test_call_soft_mode_returns_zero_status_on_timeout(self):
        """No response means unknown, not failed."""
        import requests
        self._with_token()
        with patch('requests.request', side_effect=requests.Timeout()):
            result = self.service._call(self.connection, 'documents/domestic',
                                        method='POST', payload=[], soft=True, money=True)
        self.assertEqual(result['http_status'], 0)
        self.assertIsNone(result['data'])

    def test_money_calls_are_flagged_in_the_log(self):
        """is_money_movement protects a row from the log vacuum."""
        self._with_token()
        with patch('requests.request', return_value=self._response(200, '[]')):
            self.service.create_domestic(self.connection, [{'UniqueId': 'x'}])
        log = self.env['bog.api.log'].search([('endpoint', '=', 'documents/domestic')],
                                             limit=1, order='id desc')
        self.assertTrue(log.is_money_movement)

    def test_secrets_are_redacted_in_logs(self):
        body = json.dumps({'access_token': 'tok-123', 'expires_in': 300})
        with patch('requests.post', return_value=self._response(200, body)):
            self.service.authenticate(self.connection)
        log = self.env['bog.api.log'].search([('endpoint', '=', 'oauth/token')],
                                             limit=1, order='id desc')
        self.assertNotIn('test-secret', log.request_payload)
        self.assertNotIn('tok-123', log.response_payload)

    def test_fetch_all_records_stops_when_count_reached(self):
        self._with_token()
        page_one = json.dumps({'id': 7, 'totalCount': 2, 'records': [{'entryId': 1}, {'entryId': 2}]})
        with patch('requests.request', return_value=self._response(200, page_one)) as request:
            records = self.service.fetch_all_records(
                self.connection, 'GE29BG7777777777777777', 'GEL',
                date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(len(records), 2)
        self.assertEqual(request.call_count, 1)

    def test_fetch_all_records_pages_sequentially_from_two(self):
        """BOG requires pages in order and the first response is page 1."""
        self._with_token()
        page_one = json.dumps({'id': 7, 'totalCount': 3, 'records': [{'entryId': 1}]})
        page_two = json.dumps([{'entryId': 2}])
        page_three = json.dumps([{'entryId': 3}])
        responses = [self._response(200, page_one),
                     self._response(200, page_two),
                     self._response(200, page_three)]
        with patch('requests.request', side_effect=responses) as request:
            records = self.service.fetch_all_records(
                self.connection, 'GE29BG7777777777777777', 'GEL',
                date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual([r['entryId'] for r in records], [1, 2, 3])
        self.assertIn('/7/2', request.call_args_list[1].args[1])
        self.assertIn('/7/3', request.call_args_list[2].args[1])

    def _fetch(self, *bodies):
        responses = [self._response(200, body) for body in bodies]
        with patch('requests.request', side_effect=responses):
            return self.service.fetch_all_records(
                self.connection, 'GE29BG7777777777777777', 'GEL',
                date(2026, 1, 1), date(2026, 1, 31))

    def test_statement_without_an_id_to_read_the_rest_is_refused(self):
        """The first page alone would look like the whole period."""
        self._with_token()
        with self.assertRaisesRegex(UserError, 'no statement id'):
            self._fetch(json.dumps({'totalCount': 3, 'records': [{'entryId': 1}]}))

    def test_statement_that_stops_before_its_total_is_refused(self):
        self._with_token()
        with self.assertRaisesRegex(UserError, '2 of the 3 entries'):
            self._fetch(json.dumps({'id': 7, 'totalCount': 3, 'records': [{'entryId': 1}]}),
                        json.dumps([{'entryId': 2}]),
                        json.dumps([]))

    def test_upload_file_rejects_unsupported_extension(self):
        self._with_token()
        with self.assertRaises(UserError):
            self.service.upload_file(self.connection, 'payload.exe', b'x')

    def test_upload_file_returns_bare_hash(self):
        self._with_token()
        with patch('requests.request', return_value=self._response(200, '"hash-abc"')):
            file_hash = self.service.upload_file(self.connection, 'invoice.pdf', b'%PDF')
        self.assertEqual(file_hash, 'hash-abc')

    def test_upload_file_reads_the_hash_from_a_reply_object(self):
        self._with_token()
        with patch('requests.request', return_value=self._response(200, json.dumps({'externalFileHash': ' hash-abc '}))):
            file_hash = self.service.upload_file(self.connection, 'invoice.pdf', b'%PDF')
        self.assertEqual(file_hash, 'hash-abc')

    def test_upload_file_without_a_hash_raises(self):
        self._with_token()
        for body in (json.dumps({'fileName': 'invoice.pdf'}), json.dumps({'externalFileHash': ''}), '""'):
            with patch('requests.request', return_value=self._response(200, body)), \
                    self.assertRaisesRegex(UserError, 'no file hash'):
                self.service.upload_file(self.connection, 'invoice.pdf', b'%PDF')

    def test_upload_file_content_is_not_logged(self):
        self._with_token()
        with patch('requests.request', return_value=self._response(200, '"hash-abc"')):
            self.service.upload_file(self.connection, 'invoice.pdf', b'SECRET-CONTRACT-BODY')
        log = self.env['bog.api.log'].search([('endpoint', '=', 'files/upload')],
                                             limit=1, order='id desc')
        self.assertNotIn('SECRET-CONTRACT-BODY', log.request_payload)
