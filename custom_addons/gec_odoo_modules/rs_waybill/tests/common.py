"""Shared fixtures for the rs_waybill tests. No test touches RS.GE: network calls are mocked."""

from contextlib import contextmanager
from unittest.mock import patch

from odoo.tests.common import TransactionCase


class RsWaybillCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env['rs.waybill.soap.service']
        cls.buyer = cls.env['res.partner'].create({
            'name': 'Test Buyer LLC',
            'vat': '400000001',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Test Widget',
            'type': 'consu',
        })

    @classmethod
    def clear_rs_responsible(cls, company):
        """Untick the company's RS Responsible User (one per company); tests appoint their own."""
        Settings = cls.env['res.users.settings'].sudo().with_company(company)
        Settings.search([('rs_is_responsible', '=', True)]).rs_is_responsible = False

    def make_waybill(self, **overrides):
        """A minimal seller waybill; rs_skip_resolve skips the RS driver lookup on create()."""
        vals = {
            'waybill_direction': 'seller',
            'waybill_type': '2',
            'transport_type': '1',
            'start_address': 'Tbilisi, Kostava 1',
            'end_address': 'Batumi, Rustaveli 5',
            'buyer_id': self.buyer.id,
            'buyer_tin': self.buyer.vat,
            'buyer_name': self.buyer.name,
            'driver_tin': '01001000001',
            'driver_name': 'Test Driver',
            'car_number': 'AA-001-AA',
        }
        vals.update(overrides)
        return self.env['rs.waybill'].with_context(rs_skip_resolve=True).create(vals)

    def add_line(self, waybill, quantity=10.0, unit_price=5.0, **overrides):
        vals = {
            'rs_waybill_id': waybill.id,
            'product_id': self.product.id,
            'name': self.product.name,
            'quantity': quantity,
            'unit_price': unit_price,
        }
        vals.update(overrides)
        return self.env['rs.waybill.line'].create(vals)

    def force_create_date(self, record, value):
        """Write create_date directly (the ORM blocks it), then drop the cache."""
        self.env.cr.execute(
            "UPDATE rs_waybill SET create_date = %s WHERE id = %s", (value, record.id))
        record.invalidate_recordset(['create_date'])

    @contextmanager
    def mocked_client(self, service_double):
        """Patch _get_client with a fake zeep client; service_double stands in for client.service.

        _rs_company_un_id is stubbed to skip the Test RS Credentials run."""
        fake_client = type('FakeClient', (), {'service': service_double})()
        with patch.object(type(self.service), '_get_client',
                          return_value=(fake_client, 'su', 'sp', None)), \
             patch.object(type(self.service), '_rs_company_un_id', return_value='12345'):
            yield fake_client
