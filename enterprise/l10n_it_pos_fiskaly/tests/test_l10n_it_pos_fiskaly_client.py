import requests

from odoo.addons.l10n_it_pos_fiskaly.models.fiskaly_client import FiskalySignItClient
from odoo.exceptions import UserError
from odoo.tools import mute_logger
from odoo.tests import TransactionCase, tagged


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nItPosFiskalyClient(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.sudo().write({
            'l10n_it_fiskaly_subject_api_key': 'key',
            'l10n_it_fiskaly_subject_api_secret': 'secret',
        })

    def _l10n_it_update_while_suspended(self, record, fail=False):
        modes = []

        def request(client, method, endpoint, data=None, idempotency_key=None, scope_identifier=None, retry=True):
            if method == 'GET':
                return record
            content = data['content']
            if 'mode' in content:
                modes.append(content['mode'])
            elif fail:
                raise UserError("Fiskaly returned an error")
            return {'state': record['state']}

        self.patch(FiskalySignItClient, '_request', request)
        client = FiskalySignItClient(self.env.company, subject=True)
        if fail:
            with self.assertRaises(UserError):
                client.update_taxpayer_while_suspended('taxpayer', {'name': {'legal': 'New'}})
        else:
            client.update_taxpayer_while_suspended('taxpayer', {'name': {'legal': 'New'}})
        return modes

    def test_commissioned_taxpayer_is_suspended_then_resumed(self):
        modes = self._l10n_it_update_while_suspended({'state': 'COMMISSIONED', 'mode': 'OPERATIVE'})
        self.assertEqual(modes, ['SUSPENDED', 'OPERATIVE'])

    def test_failed_update_resumes_the_taxpayer(self):
        modes = self._l10n_it_update_while_suspended({'state': 'COMMISSIONED', 'mode': 'OPERATIVE'}, fail=True)
        self.assertEqual(modes, ['SUSPENDED', 'OPERATIVE'])

    def test_suspended_taxpayer_is_resumed(self):
        modes = self._l10n_it_update_while_suspended({'state': 'COMMISSIONED', 'mode': 'SUSPENDED'})
        self.assertEqual(modes, ['OPERATIVE'])

    def test_taxpayer_not_commissioned_is_not_suspended(self):
        modes = self._l10n_it_update_while_suspended({'state': 'ACQUIRED'})
        self.assertEqual(modes, [])

    def _l10n_it_client(self, responses, subject=False):
        tokens = []

        def create_token(client):
            tokens.append(f'bearer-{len(tokens) + 1}')
            return {'authentication': {'bearer': tokens[-1], 'expires_at': '2999-01-01T00:00:00+00:00'}}

        self.patch(FiskalySignItClient, 'create_token', create_token)
        if not subject:
            self.env.company.sudo().write({
                'l10n_it_fiskaly_api_key': 'key',
                'l10n_it_fiskaly_api_secret': 'secret',
            })
        client = FiskalySignItClient(self.env.company, subject=subject)
        sent = []

        def request(method, url, json=None, headers=None, timeout=None):
            sent.append(headers)
            status, content = responses.pop(0)
            response = requests.Response()
            response.status_code = status
            response.url = url
            response._content = content
            return response

        client.session.request = request
        return client, sent

    def test_organization_bearer_is_renewed_on_401(self):
        client, sent = self._l10n_it_client([(401, b'{}'), (200, b'{"content": {"id": "organization"}}')])
        self.assertEqual(client.create_organization('Company'), {'id': 'organization'})
        self.assertEqual([headers['Authorization'] for headers in sent], ['Bearer bearer-1', 'Bearer bearer-2'])
        # fiskaly replays the rejection of an idempotency key, the retry must use a new one.
        self.assertNotEqual(sent[0]['X-Idempotency-Key'], sent[1]['X-Idempotency-Key'])

    @mute_logger('odoo.addons.l10n_it_pos_fiskaly.models.fiskaly_client')
    def test_invalid_response_is_a_user_error(self):
        client, _sent = self._l10n_it_client([(200, b'<html>Maintenance</html>')], subject=True)
        with self.assertRaisesRegex(UserError, 'invalid response'):
            client.get_taxpayer('taxpayer')
