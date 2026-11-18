from contextlib import contextmanager
from unittest.mock import patch

from zeep import Client

from odoo import Command

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.rs_einvoice.models import rs_soap_service
from odoo.addons.rs_einvoice.tests.soap_transport_stub import SoapTransportStub


class RsEinvoiceCommon(AccountTestInvoicingCommon):
    """A Georgian company with a stored rs.ge login and taxpayer id, a customer with a TIN and
    an 18% sale tax; rs.ge itself is answered by a SoapTransportStub through _patch_rsge()."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data['company']
        gel = cls.env.ref('base.GEL')
        gel.active = True
        cls.company.write({'vat': '206322102', 'currency_id': gel.id})
        cls.env.user.with_company(cls.company).sudo().write({
            'rs_username': 'alpha_srv', 'rs_password': 'secret',
            'rs_user_id': '783', 'rs_un_id': 731937,
        })
        cls.customer = cls.env['res.partner'].create({'name': 'GE Customer', 'vat': '12345678910'})
        cls.tax_18 = cls.env['account.tax'].create({
            'name': 'VAT 18%', 'amount': 18, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': cls.company.id,
            'ubl_cii_tax_category_code': 'S',
        })

    def _invoice(self, **vals):
        """A posted-ready customer invoice of one line: 2 x 50 GEL + 18% VAT = 118 GEL."""
        vals = {
            'move_type': 'out_invoice',
            'partner_id': self.customer.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'name': 'Service', 'quantity': 2, 'price_unit': 50,
                'tax_ids': [Command.set(self.tax_18.ids)],
            })],
            **vals,
        }
        return self.env['account.move'].with_company(self.company).create(vals)

    def _rsge_failing(self, operation, error):
        return patch.object(type(self.env['rs.soap.service']), operation, side_effect=error)

    @contextmanager
    def _patch_rsge(self, **responses):
        """Route every rs.ge SOAP call to a stub answering ``responses`` (keyed by operation) via the service's client
        cache. Commits right after an rs.ge write become flushes (order kept), as a test transaction forbids commit.
        Each stubbed rs.ge starts logged out, so its chek is answered too."""
        for key in [key for key in self.env.cr.cache if isinstance(key, tuple) and key[0] == 'rs_einvoice_auth_ok']:
            del self.env.cr.cache[key]
        transport = SoapTransportStub(**responses)
        client = Client(rs_soap_service.WSDL_URL, transport=transport)
        cache = rs_soap_service._RS_CLIENT_CACHE
        previous = cache.get(rs_soap_service.WSDL_URL)
        cache[rs_soap_service.WSDL_URL] = client
        try:
            with patch.object(self.env.cr, 'commit', self.env.cr.flush):
                yield transport
        finally:
            if previous is None:
                cache.pop(rs_soap_service.WSDL_URL, None)
            else:
                cache[rs_soap_service.WSDL_URL] = previous
