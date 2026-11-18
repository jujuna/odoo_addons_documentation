from datetime import timedelta
from unittest.mock import patch

import requests
from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import AccessError, LockError, UserError
from odoo.tests import tagged
from odoo.tests.common import new_test_user
from odoo.tools import mute_logger

from odoo.addons.signify.tools.signify_api import SignifyAPI, SignifyError, SignifyTransportError

from .common import SignifyCommon

STATUS = 'get-documents-status'
CONNECT_AGAIN = "must connect it again in Signify > Configuration > Signify Accounts"


@tagged('post_install', '-at_install')
class TestSignifyConnection(SignifyCommon):

    def _expire(self, connection=None):
        (connection or self.connection).expiry = fields.Datetime.now() - timedelta(minutes=5)

    def _stored(self):
        """What the database holds: the cache is dropped first because the refresh is written from another cursor."""
        self.env.invalidate_all()
        return self.connection.access_token, self.connection.refresh_token

    def test_a_valid_token_is_returned_without_any_call(self):
        with self._signify() as post:
            token = self.connection._get_access_token()
        self.assertEqual(token, 'tok-1')
        post.assert_not_called()

    def test_a_token_that_expires_within_a_minute_is_refreshed(self):
        self.connection.expiry = fields.Datetime.now() + timedelta(seconds=30)
        with self._signify({'oauth/token': self._token_response('tok-2')}) as post:
            token = self.connection._get_access_token()
        self.assertEqual(token, 'tok-2')
        self.assertEqual(self._operations(post), ['oauth/token'])

    def test_an_expired_token_is_refreshed_before_the_call(self):
        self._expire()
        handlers = {'oauth/token': self._token_response('tok-2', refresh_token='ref-2'), STATUS: self._ok(documentsStatus=[])}
        with self._signify(handlers) as post:
            SignifyAPI(self.connection).call(STATUS, {'documentIds': [1]})
        self.assertEqual(self._operations(post), ['oauth/token', STATUS])
        refresh = self._calls(post, 'oauth/token')[0]
        self.assertEqual(refresh['data'], {'grant_type': 'refresh_token', 'refresh_token': 'ref-signify_user'})
        self.assertEqual(refresh['auth'], ('client-id', 'client-secret'))
        self.assertEqual(self._calls(post, STATUS)[0]['headers']['Authorization'], 'Bearer tok-2')
        self.assertEqual(self._stored(), ('tok-2', 'ref-2'))
        self.assertGreater(self.connection.expiry, fields.Datetime.now() + timedelta(minutes=25))

    def test_the_old_refresh_token_is_kept_when_the_answer_has_none(self):
        self._expire()
        with self._signify({'oauth/token': self._token_response('tok-2')}):
            self.connection._get_access_token()
        self.assertEqual(self._stored(), ('tok-2', 'ref-signify_user'))

    def test_a_refresh_answer_without_expires_in_gets_the_default_lifetime(self):
        self._expire()
        with self._signify({'oauth/token': self._response({'access_token': 'tok-2'})}):
            self.assertEqual(self.connection._get_access_token(), 'tok-2')
        self.assertGreater(self.connection.expiry, fields.Datetime.now() + timedelta(minutes=25))

    def test_a_token_changed_by_another_worker_is_used_without_a_refresh(self):
        with self._signify() as post:
            token = self.connection._get_access_token(stale='tok-0')
        self.assertEqual(token, 'tok-1')
        post.assert_not_called()

    def test_invalid_grant_clears_the_tokens_and_asks_to_connect_again(self):
        """The clearing is committed before the error; assertRaises would roll it back, so the error is caught by hand."""
        self._expire()
        error = None
        with self._signify({'oauth/token': self._oauth_error('invalid_grant', "Token revoked")}):
            try:
                self.connection._get_access_token()
            except UserError as exc:
                error = exc
        self.assertIn(CONNECT_AGAIN, str(error))
        self.assertIn(f"The Signify account {self.connection.email} of {self.user.name} has expired", str(error))
        self.assertEqual(self._stored(), (False, False))
        self.assertFalse(self.connection.connected)
        self.assertTrue(self.connection.active)

    def test_without_a_refresh_token_it_asks_to_connect_again_and_sends_nothing(self):
        self.connection.write({'access_token': False, 'refresh_token': False, 'expiry': False})
        with self._signify() as post, self.assertRaises(UserError) as cm:
            self.connection._get_access_token()
        self.assertIn(CONNECT_AGAIN, str(cm.exception))
        post.assert_not_called()

    def test_another_oauth_error_keeps_the_refresh_token_and_shows_the_message(self):
        self._expire()
        with self._signify({'oauth/token': self._oauth_error('server_error', "Try later", status=500)}), self.assertRaises(SignifyError) as cm:
            self.connection._get_access_token()
        self.assertEqual((str(cm.exception), cm.exception.status_code), ("Try later", 'server_error'))
        self.assertEqual(self._stored()[1], 'ref-signify_user')

    def test_an_oauth_error_without_a_body_names_the_http_code(self):
        self._expire()
        with self._signify({'oauth/token': self._response('<html>Bad gateway</html>', 502)}), self.assertRaises(UserError) as cm:
            self.connection._get_access_token()
        self.assertIn('502', str(cm.exception))

    def test_a_transport_error_during_the_refresh_is_a_plain_user_error(self):
        """action_send treats a SignifyTransportError as an unknown share outcome; a refresh failure is not."""
        self._expire()
        with self._signify({'oauth/token': requests.Timeout()}), self.assertRaises(UserError) as cm:
            self.connection._get_access_token()
        self.assertNotIsInstance(cm.exception, SignifyTransportError)
        self.assertIn("did not answer in time", str(cm.exception))
        self.assertEqual(self._stored()[1], 'ref-signify_user')

    def test_a_refresh_that_cannot_get_the_lock_gives_up(self):
        self._expire()
        with (
            self._signify() as post,
            patch.object(type(self.connection), 'lock_for_update', side_effect=LockError("locked")) as lock,
            patch('odoo.addons.signify.models.signify_connection.time.sleep'),
            self.assertRaises(UserError) as cm,
        ):
            self.connection._get_access_token()
        self.assertEqual(lock.call_count, 40)
        self.assertIn("busy", str(cm.exception))
        post.assert_not_called()

    def test_missing_client_credentials_say_signify_is_not_set_up_and_send_nothing(self):
        self._expire()
        for key in ('signify.client_id', 'signify.client_secret'):
            with self.subTest(key=key):
                self.env['ir.config_parameter'].set_str('signify.client_id', 'client-id')
                self.env['ir.config_parameter'].set_str('signify.client_secret', 'client-secret')
                self.env['ir.config_parameter'].set_str(key, '')
                with self._signify() as post, self.assertRaises(UserError) as cm:
                    self.connection._get_access_token()
                self.assertIn("Signify is not set up", str(cm.exception))
                post.assert_not_called()

    def _disconnect(self, connection=None, user=None, handlers=None):
        with self._signify({'oauth/revoke': self._response('', 200), **(handlers or {})}) as post:
            (connection or self.connection).with_user(user or self.user).action_disconnect()
        return post

    def test_disconnect_revokes_the_refresh_token_and_archives_the_connection(self):
        post = self._disconnect()
        revoke = self._calls(post, 'oauth/revoke')[0]
        self.assertEqual(revoke['data'], {'token': 'ref-signify_user', 'token_type_hint': 'refresh_token'})
        self.assertEqual(revoke['auth'], ('client-id', 'client-secret'))
        self.assertEqual(self._stored(), (False, False))
        self.assertFalse(self.connection.active)
        self.assertFalse(self.connection.expiry)

    def test_disconnect_still_happens_when_the_revoke_fails(self):
        for failure in (self._oauth_error('server_error', status=500), requests.Timeout()):
            with self.subTest(failure=type(failure).__name__):
                connection = self._connect(self.user_2, signify_sub=f'sub-{type(failure).__name__}')
                with self.assertLogs('odoo.addons.signify.models.signify_connection', 'WARNING'):
                    self._disconnect(connection, self.user_2, {'oauth/revoke': failure})
                self.assertFalse(connection.active)
                self.assertFalse(connection.refresh_token)

    def test_disconnect_without_a_refresh_token_sends_no_revoke(self):
        self.connection.write({'access_token': False, 'refresh_token': False, 'expiry': False})
        post = self._disconnect()
        self.assertEqual(self._operations(post), [])
        self.assertFalse(self.connection.active)

    def test_disconnect_is_refused_while_a_document_is_with_signify(self):
        self._shared()
        with self._signify() as post, self.assertRaises(UserError) as cm:
            self.connection.with_user(self.user).action_disconnect()
        self.assertIn("still in progress", str(cm.exception))
        post.assert_not_called()
        self.assertTrue(self.connection.active)
        self.assertEqual(self._stored(), ('tok-1', 'ref-signify_user'))

    def test_disconnect_is_refused_while_the_evidence_report_is_missing(self):
        self._shared().sudo().state = 'finished'
        with self._signify() as post, self.assertRaises(UserError):
            self.connection.with_user(self.user).action_disconnect()
        post.assert_not_called()

    def test_disconnect_is_allowed_once_every_document_is_final(self):
        finished, canceled = self._shared(), self._shared()
        finished.sudo().write({'state': 'finished', 'evidence_attachment_id': self._attachment().id})
        canceled.sudo().state = 'canceled'
        post = self._disconnect()
        self.assertEqual(self._operations(post), ['oauth/revoke'])
        self.assertFalse(self.connection.active)

    def test_a_document_of_another_user_with_this_account_also_blocks_the_disconnect(self):
        """The check sees every document, not only the ones the user can read."""
        document = self._shared(user=self.user_2)
        document.sudo().connection_id = self.connection
        with self._signify() as post, self.assertRaises(UserError):
            self.connection.with_user(self.user).action_disconnect()
        post.assert_not_called()

    def test_another_user_cannot_disconnect_my_account(self):
        with self._signify() as post, self.assertRaises(AccessError):
            self.connection.with_user(self.user_2).action_disconnect()
        post.assert_not_called()
        self.assertTrue(self.connection.active)

    def test_a_settings_administrator_can_disconnect_any_account(self):
        admin = new_test_user(self.env, login='signify_settings', groups='base.group_user,base.group_system',
            company_id=self.company.id)
        post = self._disconnect(user=admin)
        self.assertEqual(self._operations(post), ['oauth/revoke'])
        self.assertFalse(self.connection.active)

    def test_one_active_account_per_user_and_company(self):
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError), self.cr.savepoint():
            self._connect(self.user, signify_sub='sub-second')

    def test_the_same_account_is_connected_once_per_user_and_company(self):
        self.connection.action_archive()
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError), self.cr.savepoint():
            self._connect(self.user)

    def test_the_connection_is_company_scoped_and_not_copied_with_its_tokens(self):
        self.assertEqual(self.connection.company_id, self.company)
        copy = self.connection.copy({'signify_sub': 'sub-copy', 'active': False})
        self.assertFalse(copy.access_token or copy.refresh_token or copy.expiry)

    def test_a_connection_with_a_refresh_token_is_connected(self):
        self.assertTrue(self.connection.connected)
        self.connection.refresh_token = False
        self.assertFalse(self.connection.connected)
