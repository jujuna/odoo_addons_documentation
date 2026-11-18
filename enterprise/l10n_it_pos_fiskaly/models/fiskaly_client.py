import logging
import requests
import time
import uuid
from contextlib import contextmanager

from odoo.exceptions import UserError, ValidationError

from odoo.addons.pos_enterprise.models.data_validator import list_of, object_of

_logger = logging.getLogger(__name__)

TIMEOUT = 10
TRANSIENT_RETRIES = 3
TRANSIENT_BACKOFF = 2
FISKALY_API_VERSION = '2026-06-01'
FISKALY_TOKEN_TYPE = 'API_KEY'
FISKALY_URL_LIVE = 'https://api.fiskaly.com'
FISKALY_URL_TEST = 'https://test.api.fiskaly.com'

address_schema = object_of({
    'line': object_of({
        'type': True,
        'street': True,
        'number': True,
    }),
    'code': True,
    'city': True,
    'country': True,
})
taxpayer_schema = object_of({
    'type': True,
    'name': object_of({
        'legal': True,
    }),
    'address': address_schema,
    'fiscalization': object_of({
        'type': True,
        'tax_id_number': True,
        'vat_id_number': True,
        'credentials': object_of({
            'type': True,
            'pin': True,
            'password': True,
            'tax_id_number': True,
        }),
    }),
})
location_schema = object_of({
    'type': True,
    'taxpayer': object_of({
        'id': True,
    }),
    'name': True,
    'address': address_schema,
})
system_schema = object_of({
    'type': True,
    'location': object_of({
        'id': True,
    }),
    'producer': object_of({
        'type': True,
        'number': True,
        'details': object_of({
            'name': True,
        }),
    }),
    'software': object_of({
        'name': True,
        'version': True,
    }),
})
receipt_schema = object_of({
    'document': object_of({
        'number': True,
    }),
    'breakdown': list_of(object_of({
        'type': True,
        'code': True,
    })),
    'totals': object_of({
        'vat': object_of({
            'amount': True,
            'exclusive': True,
            'inclusive': True,
        }),
    }),
    'entries': list_of(object_of({
        'type': True,
        'details': object_of({
            'concept': True,
        }),
        'data': object_of({
            'type': True,
            'text': True,
            'unit': object_of({
                'quantity': True,
                'price': object_of({
                    'inclusive': True,
                    'exclusive': True,
                }),
            }),
            'value': object_of({
                'base': True,
                'discount': True,
            }),
            'vat': object_of({
                'type': True,
                'code': True,
            }),
        }),
    })),
    'payments': list_of(object_of({
        'type': True,
        'details': object_of({
            'amount': True,
        }),
    })),
})


def validate_schema(schema, data, env):
    _is_valid, error = schema(data)
    if error:
        raise ValidationError(env._("Fiskaly schema validation error, %s", error))


@contextmanager
def fiskaly_client(company, subject=False):
    client = FiskalySignItClient(company, subject)
    with client.session:
        yield client


class FiskalySignItClient:

    def __init__(self, company, subject=False):
        root = company.root_id.sudo()
        if subject:
            self.api_key = root.l10n_it_fiskaly_subject_api_key
            self.api_secret = root.l10n_it_fiskaly_subject_api_secret
            if not self.api_key or not self.api_secret:
                raise UserError(root.env._("Please create the fiskaly subject of %s first.", root.display_name))
        else:
            self.api_key = root.l10n_it_fiskaly_api_key
            self.api_secret = root.l10n_it_fiskaly_api_secret
            if not self.api_key or not self.api_secret:
                raise UserError(root.env._("Please set the fiskaly API key and secret of %s first.", root.display_name))
        self.company = root
        self.subject = subject
        self.base_url = FISKALY_URL_TEST if root.l10n_it_fiskaly_test_mode else FISKALY_URL_LIVE
        self.attempts = 0
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'X-Api-Version': FISKALY_API_VERSION,
        })

    def _bearer_field(self):
        return 'l10n_it_fiskaly_subject_access_token' if self.subject else 'l10n_it_fiskaly_access_token'

    def _bearer(self):
        return self.company[self._bearer_field()] or self.refresh_bearer()

    def refresh_bearer(self):
        response = self.create_token()
        bearer = response.get('authentication', {}).get('bearer')
        if not bearer:
            raise self._authentication_error()
        self.company[self._bearer_field()] = bearer
        return bearer

    def _authentication_error(self):
        company = self.company.display_name
        if self.subject:
            return UserError(self.company.env._(
                "Fiskaly refused the subject credentials of %s. Make sure the subject still exists in "
                "the fiskaly dashboard, then try again. If it was deleted, contact the fiskaly support.",
                company,
            ))
        return UserError(self.company.env._(
            'Fiskaly refused the API key and secret of %s. Check them in the Fiskaly tab of the '
            'company, then click "Authenticate Keys".',
            company,
        ))

    def _request(self, method, endpoint, data=None, idempotency_key=None, scope_identifier=None, retry=True):
        headers = {}
        if endpoint != 'tokens':
            headers['Authorization'] = f"Bearer {self._bearer()}"
        if scope_identifier:
            headers['X-Scope-Identifier'] = scope_identifier
        if method != 'GET':
            idempotency_key = idempotency_key or str(uuid.uuid4())
            headers['X-Idempotency-Key'] = idempotency_key
        # A request that may have been processed is replayed with the same idempotency key, so
        # fiskaly returns the original outcome instead of recording the same document twice.
        for attempt in range(TRANSIENT_RETRIES):
            self.attempts = attempt + 1
            try:
                response = self.session.request(method, f"{self.base_url}/{endpoint}", json=data, headers=headers, timeout=TIMEOUT)
                response.raise_for_status()
                break
            except requests.exceptions.HTTPError as error:
                if endpoint == 'tokens' and error.response.status_code == 401:
                    raise self._authentication_error() from error
                if retry and error.response.status_code == 401:
                    # The request was rejected before being processed: a new idempotency key is
                    # needed, otherwise fiskaly replays the rejection instead of the fixed request.
                    _logger.info("fiskaly SIGN IT rejected the bearer, re-authenticating.")
                    self.refresh_bearer()
                    return self._request(method, endpoint, data=data, scope_identifier=scope_identifier, retry=False)
                if error.response.status_code >= 500:
                    if self.attempts < TRANSIENT_RETRIES:
                        _logger.info("fiskaly SIGN IT is unavailable, retrying the %s on %s.", method, endpoint)
                        time.sleep(TRANSIENT_BACKOFF ** self.attempts)
                        continue
                    _logger.warning("fiskaly SIGN IT is unavailable: %s", error.response.text)
                    raise UserError(self.company.env._("The fiskaly server is not available, please try again later."))
                _logger.warning("fiskaly SIGN IT rejected a %s on %s: %s", method, endpoint, error.response.text)
                raise UserError(self.company.env._("Fiskaly returned an error: %s", error.response.text))
            except requests.exceptions.RequestException as error:
                if self.attempts < TRANSIENT_RETRIES:
                    _logger.info("fiskaly SIGN IT is unreachable, retrying the %s on %s.", method, endpoint)
                    time.sleep(TRANSIENT_BACKOFF ** self.attempts)
                    continue
                _logger.warning("fiskaly SIGN IT is unreachable: %s", error)
                raise UserError(self.company.env._("The fiskaly server is not available, please try again later."))
        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError as error:
            _logger.warning("fiskaly SIGN IT returned an invalid response to a %s on %s: %s", method, endpoint, response.text)
            raise UserError(self.company.env._("Fiskaly returned an invalid response, please try again later.")) from error
        return payload.get('content', payload)

    def create_token(self):
        return self._request('POST', 'tokens', data={
            'content': {
                'type': FISKALY_TOKEN_TYPE,
                'key': self.api_key,
                'secret': self.api_secret,
            },
        })

    def create_organization(self, name, idempotency_key=None):
        return self._request('POST', 'organizations', idempotency_key=idempotency_key, data={
            'content': {
                'type': 'UNIT',
                'name': name,
            },
        })

    def create_taxpayer(self, content, idempotency_key=None):
        validate_schema(taxpayer_schema, content, self.company.env)
        return self._request('POST', 'taxpayers', idempotency_key=idempotency_key, data={
            'content': content,
        })

    def create_system(self, content, idempotency_key=None):
        validate_schema(system_schema, content, self.company.env)
        return self._request('POST', 'systems', idempotency_key=idempotency_key, data={
            'content': content,
        })

    def create_location(self, content, idempotency_key=None):
        validate_schema(location_schema, content, self.company.env)
        return self._request('POST', 'locations', idempotency_key=idempotency_key, data={
            'content': content,
        })

    def get_taxpayer(self, taxpayer_id):
        return self._request('GET', f"taxpayers/{taxpayer_id}")

    def update_taxpayer(self, taxpayer_id, content, idempotency_key=None):
        return self._request('PATCH', f"taxpayers/{taxpayer_id}", idempotency_key=idempotency_key, data={
            'content': content,
        })

    def update_taxpayer_while_suspended(self, taxpayer_id, content):
        taxpayer = self.get_taxpayer(taxpayer_id)
        if taxpayer.get('state') != 'COMMISSIONED':
            return self.update_taxpayer(taxpayer_id, content)
        if taxpayer.get('mode') != 'SUSPENDED':
            self.update_taxpayer(taxpayer_id, {'mode': 'SUSPENDED'})
        try:
            return self.update_taxpayer(taxpayer_id, content)
        finally:
            self.update_taxpayer(taxpayer_id, {'mode': 'OPERATIVE'})

    def get_location(self, location_id):
        return self._request('GET', f"locations/{location_id}")

    def update_location(self, location_id, content, idempotency_key=None):
        return self._request('PATCH', f"locations/{location_id}", idempotency_key=idempotency_key, data={
            'content': content,
        })

    def update_location_while_suspended(self, location_id, content):
        location = self.get_location(location_id)
        if location.get('state') != 'COMMISSIONED':
            return self.update_location(location_id, content)
        if location.get('mode') != 'SUSPENDED':
            self.update_location(location_id, {'mode': 'SUSPENDED'})
        try:
            return self.update_location(location_id, content)
        finally:
            self.update_location(location_id, {'mode': 'OPERATIVE'})

    def update_system(self, system_id, content, idempotency_key=None):
        return self._request('PATCH', f"systems/{system_id}", idempotency_key=idempotency_key, data={
            'content': content,
        })

    def create_subject(self, name, scope_identifier, idempotency_key=None):
        return self._request('POST', 'subjects', idempotency_key=idempotency_key,
            scope_identifier=scope_identifier, data={
                'content': {
                    'type': FISKALY_TOKEN_TYPE,
                    'name': name,
                },
            })

    def get_record(self, record_id):
        return self._request('GET', f"records/{record_id}")

    def create_record(self, content, idempotency_key=None, scope_identifier=None):
        operation = content.get('operation', {})
        if content['type'] == 'TRANSACTION' and operation.get('type') in ('RECEIPT', 'CORRECTION'):
            validate_schema(receipt_schema, operation.get('data', operation), self.company.env)
        return self._request('POST', 'records', idempotency_key=idempotency_key,
            scope_identifier=scope_identifier, data={
                'content': content,
            })
