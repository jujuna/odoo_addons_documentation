from json import dumps as json_dumps
from unittest.mock import patch

import requests

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'post_install_l10n')
class TestFiskalyScuState(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.write({
            'vat': 'ATU12345675',
            'street': 'Hauptstrasse 1',
            'zip': '1010',
            'city': 'Wien',
            'country_id': cls.env.ref('base.at').id,
            'l10n_at_fiskaly_api_key': 'key',
            'l10n_at_fiskaly_api_secret': 'secret',
        })
        # A new API key resets the access token and the SCU: set them afterwards
        cls.env.company.write({
            'l10n_at_fiskaly_access_token': 'token',
            'l10n_at_is_fon_authenticated': True,
            'l10n_at_pos_company_scuid': 'scu-1',
        })

    def _create_config(self, scu_state, calls, other_scus=()):
        """Fiskaly refuses to initialize a cash register while no SCU is INITIALIZED."""
        scus = {'scu-1': {'_id': 'scu-1', 'state': scu_state}}
        scus.update({s['_id']: s for s in other_scus})

        def fake_request(session, method, url, json=None, params=None, **kwargs):
            endpoint = url.split('/api/v1/')[1]
            calls.append((method, endpoint, json))
            resp = requests.Response()
            resp.status_code, body = 200, {}
            if endpoint == 'signature-creation-unit':
                body = {'data': [s for s in scus.values() if s['state'] in params['states[]']]}
            elif endpoint.startswith('signature-creation-unit/'):
                scu = scus.setdefault(endpoint.split('/')[1], {'_id': endpoint.split('/')[1], 'state': 'CREATED'})
                if method == 'PATCH' and scu['state'] != 'PENDING':
                    scu['state'] = json['state']
                body = scu
            elif method == 'PATCH' and json['state'] == 'INITIALIZED' and not any(s['state'] == 'INITIALIZED' for s in scus.values()):
                resp.status_code, body = 404, {'code': 'E_NO_INITIALIZED_SCU', 'message': 'No SCU'}
            resp._content = json_dumps(body).encode()
            return resp

        with patch('requests.Session.request', autospec=True, side_effect=fake_request), \
             patch('odoo.addons.l10n_at_pos.models.pos_config.fiskaly_iap_rpc'), \
             patch.object(self.env.cr, 'commit'):
            return self.env['pos.config'].create({'name': 'AT shop', 'company_id': self.env.company.id})

    def test_stuck_scu_is_initialized_before_cash_register(self):
        calls = []
        config = self._create_config('CREATED', calls)
        self.assertTrue(config.l10n_at_cash_regid)
        self.assertIn(('PATCH', 'signature-creation-unit/scu-1', {'state': 'INITIALIZED'}), calls)

    def test_retired_scu_is_replaced(self):
        calls = []
        config = self._create_config('DECOMMISSIONED', calls)
        new_scuid = self.env.company.l10n_at_pos_company_scuid
        self.assertNotEqual(new_scuid, 'scu-1')
        self.assertIn(('PATCH', f'signature-creation-unit/{new_scuid}', {'state': 'INITIALIZED'}), calls)
        self.assertTrue(config.l10n_at_cash_regid)

    def test_initialized_scu_preferred_over_created(self):
        calls = []
        self._create_config('CREATED', calls, other_scus=[{'_id': 'scu-2', 'state': 'INITIALIZED'}])
        self.assertEqual(self.env.company.l10n_at_pos_company_scuid, 'scu-2')
        self.assertNotIn('PATCH', [m for m, ep, _ in calls if ep.startswith('signature-creation-unit')])

    def test_pending_scu_blocks_cash_register_creation(self):
        calls = []
        with self.assertRaises(ValidationError):
            self._create_config('PENDING', calls)
        self.assertIn(('PATCH', 'signature-creation-unit/scu-1', {'state': 'INITIALIZED'}), calls)
        self.assertFalse([ep for m, ep, _ in calls if ep.startswith('cash-register')])

    def test_fiskaly_error_code_is_reported(self):
        with self.assertRaises(ValidationError) as cm:
            self._create_config('OUTAGE', [])
        self.assertIn('E_NO_INITIALIZED_SCU', str(cm.exception))
