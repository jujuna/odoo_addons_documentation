import base64
import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

from odoo import fields
from odoo.http.session import session_store
from odoo.tests import HttpCase, tagged

from odoo.addons.signify.tools.signify_api import CALLBACK_ROUTE, OAUTH_SCOPE, OAUTH_URL, START_ROUTE, oauth_redirect_uri

from .common import SignifyCommon

CONNECTIONS_ACTION = '/odoo/action-signify.action_signify_connection'
NOT_FOUND = "This Signify connection attempt was not found. Start again from Signify Accounts"


@tagged('post_install', '-at_install')
class TestSignifyOauthRoutes(SignifyCommon, HttpCase):

    def _start(self, user, company=None):
        self.authenticate(user.login, user.login)
        return self.url_open(f'{START_ROUTE}?company_id={(company or user.company_id).id}', allow_redirects=False)

    def _query(self, response):
        return {key: values[0] for key, values in parse_qs(urlsplit(response.headers['Location']).query).items()}

    def _callback(self, state, **params):
        return self.url_open(f'{CALLBACK_ROUTE}?{urlencode({"state": state, **params})}', allow_redirects=False)

    def _connect_handlers(self, sub='sub-new', email='new@signify.example'):
        return {
            'oauth/token': self._token_response('acc-new', refresh_token='ref-new'),
            'oauth/userinfo': self._response({'sub': sub, 'email': email}),
        }

    def _connect_through_the_routes(self, user, handlers=None):
        """The whole round trip; returns the callback response and the mock."""
        state = self._query(self._start(user))['state']
        with self._signify(handlers or self._connect_handlers()) as post:
            response = self._callback(state, code='the-code')
        return response, post

    def _pending(self):
        return session_store().get(self.session.sid)['signify_oauth']

    def _accounts(self, user):
        self.env.invalidate_all()
        return self.env['signify.connection'].with_context(active_test=False).search([('user_id', '=', user.id)], order='id')

    def test_start_redirects_to_signify_with_a_pkce_challenge(self):
        response = self._start(self.user)
        self.assertEqual(response.status_code, 303)
        location = urlsplit(response.headers['Location'])
        self.assertEqual(f'{location.scheme}://{location.netloc}{location.path}', OAUTH_URL + 'authorize')
        query = self._query(response)
        self.assertEqual(query['client_id'], 'client-id')
        self.assertEqual(query['redirect_uri'], oauth_redirect_uri(self.env))
        self.assertEqual((query['response_type'], query['scope']), ('code', OAUTH_SCOPE))
        self.assertEqual(query['code_challenge_method'], 'S256')
        pending = self._pending()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(pending['verifier'].encode()).digest()).rstrip(b'=').decode()
        self.assertEqual(query['code_challenge'], challenge)
        self.assertEqual((pending['state'], pending['company_id'], pending['redirect_uri']), (query['state'], self.company.id, query['redirect_uri']))
        self.assertNotIn('=', challenge)

    def test_every_start_has_its_own_state_and_verifier_and_replaces_the_pending_attempt(self):
        first, second = self._query(self._start(self.user)), self._query(self._start(self.user))
        self.assertNotEqual(first['state'], second['state'])
        self.assertNotEqual(first['code_challenge'], second['code_challenge'])
        self.assertEqual(self._pending()['state'], second['state'])

    def test_start_refuses_an_unknown_company_and_a_company_of_the_user_does_not_belong_to(self):
        for company_id in ('999999', 'abc', str(self.company_b.id), ''):
            with self.subTest(company_id=company_id):
                self.authenticate(self.user.login, self.user.login)
                self.assertEqual(self.url_open(f'{START_ROUTE}?company_id={company_id}', allow_redirects=False).status_code, 404)
        self.assertEqual(self.url_open(START_ROUTE, allow_redirects=False).status_code, 404)

    def test_start_is_for_signify_users_only(self):
        self.assertEqual(self._start(self.employee).status_code, 404)

    def test_start_without_a_client_id_says_signify_is_not_set_up(self):
        self.env['ir.config_parameter'].set_str('signify.client_id', '')
        response = self._start(self.user)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Signify is not set up", response.text)
        self.assertIn(CONNECTIONS_ACTION, response.text)

    def test_start_without_a_client_secret_stays_in_odoo(self):
        self.env['ir.config_parameter'].set_str('signify.client_secret', '')
        response = self._start(self.user)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Signify is not set up", response.text)

    def test_the_callback_without_a_matching_attempt_says_to_start_again(self):
        self.authenticate(self.user.login, self.user.login)
        for state in ('wrong-state', ''):
            with self.subTest(state=state):
                with self._signify() as post:
                    response = self._callback(state, code='the-code')
                self.assertEqual(response.status_code, 400)
                self.assertIn(NOT_FOUND, response.text)
                self.assertEqual(response.headers['Content-Type'].split(';')[0], 'text/html')
                self.assertIn(CONNECTIONS_ACTION, response.text)
                post.assert_not_called()
        self.assertEqual(self.url_open(f'{CALLBACK_ROUTE}?code=the-code', allow_redirects=False).status_code, 400)

    def test_a_wrong_state_connects_nothing_and_drops_the_pending_attempt(self):
        state = self._query(self._start(self.user_2))['state']
        with self._signify() as post:
            self.assertEqual(self._callback('wrong-state', code='the-code').status_code, 400)
            self.assertEqual(self._callback(state, code='the-code').status_code, 400)
        post.assert_not_called()
        self.assertFalse(self._accounts(self.user_2))

    def test_the_callback_connects_the_account_of_the_user(self):
        state = self._query(self._start(self.user_2))['state']
        verifier = self._pending()['verifier']
        with self._signify(self._connect_handlers()) as post:
            response = self._callback(state, code='the-code')
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['Location'].endswith(CONNECTIONS_ACTION))
        self.assertEqual(self._sent(post, 'oauth/token'), [{
            'grant_type': 'authorization_code',
            'code': 'the-code',
            'redirect_uri': oauth_redirect_uri(self.env),
            'code_verifier': verifier,
        }])
        self.assertEqual(self._calls(post, 'oauth/token')[0]['auth'], ('client-id', 'client-secret'))
        self.assertEqual(self._calls(post, 'oauth/userinfo')[0]['headers'], {'Authorization': 'Bearer acc-new'})
        connection = self._accounts(self.user_2)
        self.assertEqual((connection.company_id, connection.signify_sub, connection.email), (self.company, 'sub-new', 'new@signify.example'))
        self.assertEqual((connection.access_token, connection.refresh_token, connection.active), ('acc-new', 'ref-new', True))
        self.assertGreater(connection.expiry, fields.Datetime.now() + timedelta(minutes=25))

    def test_a_state_works_once(self):
        state = self._query(self._start(self.user_2))['state']
        with self._signify(self._connect_handlers()):
            self.assertEqual(self._callback(state, code='the-code').status_code, 303)
            self.assertEqual(self._callback(state, code='the-code').status_code, 400)
        self.assertEqual(len(self._accounts(self.user_2)), 1)

    def test_the_callback_reuses_the_redirect_uri_of_the_start_when_the_base_url_changes(self):
        state = self._query(self._start(self.user_2))['state']
        stored = self._pending()['redirect_uri']
        self.env['ir.config_parameter'].set_str('web.base.url', 'https://changed.example.com')
        self.assertNotEqual(oauth_redirect_uri(self.env), stored)
        with self._signify(self._connect_handlers()) as post:
            self.assertEqual(self._callback(state, code='the-code').status_code, 303)
        self.assertEqual(self._sent(post, 'oauth/token')[0]['redirect_uri'], stored)

    def test_a_token_answer_without_expires_in_connects_with_the_default_lifetime(self):
        handlers = {**self._connect_handlers(), 'oauth/token': self._response({'access_token': 'acc-new', 'refresh_token': 'ref-new'})}
        response, _post = self._connect_through_the_routes(self.user_2, handlers)
        self.assertEqual(response.status_code, 303)
        self.assertGreater(self._accounts(self.user_2).expiry, fields.Datetime.now() + timedelta(minutes=25))

    def test_connecting_another_account_archives_the_old_one_and_keeps_its_tokens(self):
        response, _post = self._connect_through_the_routes(self.user, self._connect_handlers(sub='sub-other'))
        self.assertEqual(response.status_code, 303)
        old, new = self._accounts(self.user)
        self.assertEqual((old.id, old.active, old.access_token, old.refresh_token), (self.connection.id, False, 'tok-1', 'ref-signify_user'))
        self.assertEqual((new.signify_sub, new.active, new.refresh_token), ('sub-other', True, 'ref-new'))

    def test_reconnecting_the_first_account_reactivates_it_with_new_tokens(self):
        self._connect_through_the_routes(self.user, self._connect_handlers(sub='sub-other'))
        self._connect_through_the_routes(self.user, self._connect_handlers(sub=self.connection.signify_sub))
        old, other = self._accounts(self.user)
        self.assertEqual((old.id, old.active, old.access_token, old.refresh_token), (self.connection.id, True, 'acc-new', 'ref-new'))
        self.assertEqual((other.signify_sub, other.active), ('sub-other', False))

    def test_the_callback_with_an_error_connects_nothing(self):
        state = self._query(self._start(self.user_2))['state']
        with self._signify() as post:
            response = self._callback(state, error='access_denied', error_description="The user denied access")
        self.assertEqual(response.status_code, 400)
        self.assertIn("The user denied access", response.text)
        self.assertEqual(response.headers['Content-Type'].split(';')[0], 'text/html')
        self.assertIn(CONNECTIONS_ACTION, response.text)
        post.assert_not_called()
        self.assertFalse(self._accounts(self.user_2))

    def test_the_callback_names_the_error_code_when_there_is_no_description(self):
        state = self._query(self._start(self.user_2))['state']
        response = self._callback(state, error='access_denied')
        self.assertEqual(response.status_code, 400)
        self.assertIn("access_denied", response.text)

    def test_a_refused_code_connects_nothing_and_shows_the_message(self):
        handlers = {'oauth/token': self._oauth_error('invalid_grant', "The code expired")}
        state = self._query(self._start(self.user_2))['state']
        with self._signify(handlers), self.assertLogs('odoo.addons.signify.controllers.main', 'WARNING'):
            response = self._callback(state, code='the-code')
        self.assertEqual(response.status_code, 400)
        self.assertIn("The code expired", response.text)
        self.assertFalse(self._accounts(self.user_2))

    def test_the_callback_refuses_a_user_without_the_signify_group(self):
        """A state stored in the session of an employee is no ticket."""
        self.authenticate(self.employee.login, self.employee.login)
        session = session_store().get(self.session.sid)
        session['signify_oauth'] = {'state': 'forged', 'verifier': 'v', 'company_id': self.company.id, 'redirect_uri': 'https://odoo.example.com'}
        session_store().save(session)
        with self._signify() as post:
            self.assertEqual(self._callback('forged', code='the-code').status_code, 404)
        post.assert_not_called()

    def test_the_callback_refuses_a_company_the_user_does_not_belong_to(self):
        self.authenticate(self.user_2.login, self.user_2.login)
        session = session_store().get(self.session.sid)
        session['signify_oauth'] = {'state': 'forged', 'verifier': 'v', 'company_id': self.company_b.id, 'redirect_uri': 'https://odoo.example.com'}
        session_store().save(session)
        with self._signify() as post:
            self.assertEqual(self._callback('forged', code='the-code').status_code, 404)
        post.assert_not_called()
