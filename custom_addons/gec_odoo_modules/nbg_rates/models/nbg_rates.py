import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

NBG_API_URL = 'https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/ka/json/'
CURRENCIES = ['EUR', 'USD']
BACKFILL_DAYS = 365
REQUEST_TIMEOUT = 10


def _fetch_rate(currency, date_str):
    """Fetch one currency rate from the NBG API; runs in a thread."""
    try:
        resp = requests.get(
            NBG_API_URL,
            params={'currencies': currency, 'date': date_str},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data and data[0].get('currencies'):
            cur = data[0]['currencies'][0]
            return {
                'currency': cur['code'],
                'rate': cur['rate'],
                'date': date_str,
            }
    except Exception:
        _logger.warning('NBG: failed to fetch %s for %s', currency, date_str)
    return None


class ResCurrency(models.Model):
    _inherit = 'res.currency'

    @api.model
    def _cron_fetch_nbg_rates(self):
        today = fields.Date.context_today(self)
        rate_model = self.env['res.currency.rate']

        currencies = self.search([('name', 'in', CURRENCIES), ('active', '=', True)])
        if not currencies:
            currencies = self.search([('name', 'in', CURRENCIES)])
            if currencies:
                currencies.write({'active': True})
            else:
                _logger.error('NBG: EUR/USD currencies not found in the system.')
                return

        currency_map = {c.name: c for c in currencies}

        tasks = []  # (currency_code, date_str)
        for cur_code, cur_record in currency_map.items():
            latest_rate = rate_model.search(
                [('currency_id', '=', cur_record.id)],
                order='name desc',
                limit=1,
            )
            if latest_rate:
                start_date = latest_rate.name + timedelta(days=1)
            else:
                start_date = today - timedelta(days=BACKFILL_DAYS)

            d = start_date
            while d <= today:
                tasks.append((cur_code, str(d)))
                d += timedelta(days=1)

        if not tasks:
            _logger.info('NBG: all rates are up to date.')
            return

        max_workers = min(len(tasks), 20)
        _logger.info('NBG: fetching %d rates with %d workers...', len(tasks), max_workers)

        # Threads are safe: _fetch_rate does not touch the ORM.
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_fetch_rate, cur_code, date_str): (cur_code, date_str)
                for cur_code, date_str in tasks
            }
            for future in as_completed(futures):
                result = future.result()
                if result:
                    results.append(result)

        if not results:
            _logger.warning('NBG: no rates returned from API.')
            return

        # NBG gives GEL per foreign unit; res.currency.rate stores the inverse.
        vals_list = []
        for r in results:
            cur_record = currency_map.get(r['currency'])
            if cur_record and r['rate']:
                vals_list.append({
                    'currency_id': cur_record.id,
                    'name': r['date'],
                    'rate': 1.0 / r['rate'],
                })

        vals_list.sort(key=lambda v: v['name'])

        existing = rate_model.search([
            ('currency_id', 'in', currencies.ids),
            ('name', 'in', [v['name'] for v in vals_list]),
        ])
        existing_keys = {(r.currency_id.id, str(r.name)) for r in existing}
        vals_list = [
            v for v in vals_list
            if (v['currency_id'], v['name']) not in existing_keys
        ]

        if vals_list:
            rate_model.create(vals_list)
            _logger.info('NBG: created %d currency rate records.', len(vals_list))
        else:
            _logger.info('NBG: no new rates to create (all already exist).')
