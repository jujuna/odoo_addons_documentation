"""A filed petroleum invoice (ნსაფ) is corrected through the petroleum service: k_invoice_n, then its goods line;
the original is cancelled once the buyer confirms the correction, and an ordinary fuel invoice stays ordinary."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.rs_einvoice.tests.common import RsEinvoiceCommon

ORIGINAL, CORRECTION = 900001, 900002


class FakeSpecRsge:
    """The petroleum rs.ge service holding documents by id; any call a test does not expect fails it."""

    def __init__(self):
        self.docs = {ORIGINAL: {'status': '2', 'line_id': 800001}}
        self.calls = []

    @property
    def operations(self):
        return [operation for operation, _kwargs in self.calls]

    def called(self, operation):
        """The keyword arguments of every call to ``operation``."""
        return [kwargs for name, kwargs in self.calls if name == operation]

    def _auth(self):
        return {'user_id': 783, 'su': 'alpha_srv', 'sp': 'secret'}

    def _login(self):
        return 1

    def _rs_base(self):
        return self

    def _rs_company_un_id(self):
        return 731937

    def _rs_partner_un_id(self, partner):
        return 1149251

    def _rs_table(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        doc = self.docs.get(kwargs.get('invois_id'))
        if operation == 'get_invoice_n':
            return [{
                'status': doc['status'], 'f_series': 'ეს', 'f_number': str(kwargs['invois_id']),
                'no_text': doc.get('no_text'),
            }] if doc else []
        if operation == 'get_invoice_desc_n':
            return [{'id': str(doc['line_id'])}] if doc else []
        raise AssertionError("unexpected rs.ge call %s" % operation)

    def _rs_write(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        if operation == 'k_invoice_n':
            self.docs[kwargs['inv_id']]['status'] = '3'
            self.docs[CORRECTION] = {'status': '4', 'line_id': 800002}
            return SimpleNamespace(k_invoice_nResult=True, k_id=CORRECTION)
        if operation == 'save_invoice_desc_n':
            return SimpleNamespace(save_invoice_desc_nResult=True, id=kwargs['id'])
        if operation == 'change_invoice_status_n':
            self.docs[kwargs['inv_id']]['status'] = str(kwargs['status'])
            return True
        raise AssertionError("unexpected rs.ge call %s" % operation)


@tagged('post_install', '-at_install')
class TestSpecCorrection(RsEinvoiceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer.rs_un_id = 1149251
        litre = cls.env.ref('uom.product_uom_litre')
        cls.fuel = cls.env['product.product'].create({'name': 'Diesel', 'uom_id': litre.id, 'rs_spec_rs_id': 55})
        Site = cls.env['rs.spec.site']
        cls.start = Site.create({'rs_un_id': 731937, 'code': '0100001', 'address': 'Tbilisi depot'})
        cls.end = Site.create({'rs_un_id': 1149251, 'code': '0200002', 'address': 'Rustavi station'})

    def setUp(self):
        super().setUp()
        self.rsge = FakeSpecRsge()
        Service = type(self.env['rs.spec.soap.service'])
        for name in ('_auth', '_login', '_rs_base', '_rs_company_un_id', '_rs_partner_un_id', '_rs_table', '_rs_write'):
            self.enterContext(patch.object(Service, name, lambda s, *a, _m=getattr(self.rsge, name), **kw: _m(*a, **kw)))
        self.enterContext(patch.object(self.env.cr, 'commit', self.env.cr.flush))

    def _fuel_line(self):
        """1000 litres of diesel at 2.00 with 18% VAT."""
        return Command.create({
            'product_id': self.fuel.id, 'quantity': 1000, 'price_unit': 2.0,
            'tax_ids': [Command.set(self.tax_18.ids)],
        })

    def _filed_spec_invoice(self):
        """A posted petroleum invoice, 830 kg typed by hand, filed on rs.ge and accepted (status 2)."""
        invoice = self._invoice(
            invoice_line_ids=[self._fuel_line()],
            rs_spec_start_site_id=self.start.id, rs_spec_end_site_id=self.end.id, rs_spec_car_number='AA-001-AA',
        )
        invoice.action_post()
        self.assertTrue(invoice.rs_einv_is_spec)
        invoice.write({'rs_spec_quantity_kg': 830, 'rs_einv_id': str(ORIGINAL), 'rs_einv_status': '2'})
        return invoice

    def _wizard(self, invoice, **vals):
        """The credit-note wizard opened on ``invoice``, its RS treatment left to the default."""
        return self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=invoice.ids,
        ).create({'journal_id': invoice.journal_id.id, **vals})

    def _correct(self, invoice, k_type):
        """The draft correction the wizard opens; the rs.ge calls made while copying are forgotten."""
        action = self._wizard(invoice, rs_spec_k_type=k_type).modify_moves()
        self.rsge.calls.clear()
        return self.env['account.move'].browse(action['res_id'])

    def _saved_correction(self, k_type='13'):
        """A filed invoice and its correction, saved on rs.ge while still a draft; return (invoice, correction)."""
        invoice = self._filed_spec_invoice()
        correction = self._correct(invoice, k_type)
        correction.action_rs_spec_save()
        return invoice, correction

    def _logs(self, move, text, level):
        return self.env['rs.einvoice.log'].search([
            ('move_id', '=', move.id), ('level', '=', level), ('name', 'ilike', text)])

    def test_wizard_copies_the_petroleum_invoice(self):
        invoice = self._filed_spec_invoice()
        wizard = self._wizard(invoice, rs_spec_k_type='13')
        self.assertEqual((wizard.rs_einv_flow, wizard.rs_spec_is_filed), ('correct_reissue', True))
        copy = self.env['account.move'].browse(wizard.modify_moves()['res_id'])
        self.assertEqual(
            (copy.state, copy.rs_einv_is_spec, copy.rs_einv_replacement_mode, copy.rs_einv_replaces_id),
            ('draft', True, 'correction', invoice))
        self.assertEqual((copy.rs_spec_k_type, copy.rs_einv_k_type), ('13', False))
        self.assertEqual(
            (copy.rs_spec_start_site_id, copy.rs_spec_end_site_id, copy.rs_spec_car_number, copy.rs_spec_quantity_kg),
            (self.start, self.end, 'AA-001-AA', 830))
        self.assertEqual(invoice.rs_einv_replaced_by_id, copy)

    def test_save_files_the_correction_then_edits_its_line(self):
        _invoice, correction = self._saved_correction()
        self.assertEqual(
            self.rsge.operations, ['get_invoice_n', 'k_invoice_n', 'get_invoice_desc_n', 'save_invoice_desc_n'])
        self.assertEqual(self.rsge.called('k_invoice_n'), [{'inv_id': ORIGINAL, 'k_type': 13}])
        self.assertEqual(self.rsge.called('get_invoice_desc_n'), [{'invois_id': CORRECTION}])
        line = self.rsge.called('save_invoice_desc_n')[0]
        self.assertEqual((line['id'], line['p_inv_id'], line['p_g_number_alt']), (800002, CORRECTION, Decimal('830')))
        self.assertEqual((correction.rs_einv_id, correction.rs_einv_status), (str(CORRECTION), '4'))
        self.assertEqual(correction._rs_spec_line().rs_line_id, '800002')

    def test_buyer_confirmation_cancels_the_original(self):
        invoice, correction = self._saved_correction()
        correction.action_rs_spec_send()
        self.assertEqual(correction.rs_einv_status, '5')
        self.assertEqual(self.rsge.called('change_invoice_status_n'), [{'inv_id': CORRECTION, 'status': 5}])
        self.rsge.docs[CORRECTION]['status'] = '8'
        invoice.action_rs_refresh_status()
        self.assertEqual((invoice.state, invoice.rs_einv_status), ('cancel', '3'))
        self.assertEqual((correction.state, correction.rs_einv_status, correction.date), ('posted', '8', fields.Date.context_today(correction)))

    def test_type_11_zeroes_the_copy_and_sends_no_line(self):
        copy = self._correct(self._filed_spec_invoice(), '11')
        self.assertEqual((copy._rs_spec_line().quantity, copy.amount_total), (0, 0))
        copy.action_rs_spec_save()
        self.assertEqual(self.rsge.operations, ['get_invoice_n', 'k_invoice_n'])
        self.assertEqual(self.rsge.called('k_invoice_n')[0]['k_type'], 11)

    def test_rejected_correction_returns_to_draft(self):
        _invoice, correction = self._saved_correction()
        correction.action_rs_spec_send()
        self.rsge.docs[CORRECTION].update(status='4', no_text='Wrong price')
        correction.action_rs_refresh_status()
        self.assertEqual((correction.state, correction.rs_einv_status), ('draft', '4'))
        self.assertTrue(self._logs(correction, 'Wrong price', 'info'))

    def test_ordinary_fuel_invoice_copy_stays_ordinary(self):
        invoice = self._invoice(invoice_line_ids=[self._fuel_line()], rs_einv_id='700100', rs_einv_status='2')
        invoice.action_post()
        self.assertFalse(invoice.rs_einv_is_spec)
        vals = invoice._rs_correction_copy_vals('3')
        self.assertEqual(vals['rs_einv_k_type'], '3')
        self.assertFalse({'rs_spec_k_type', 'rs_einv_is_spec'} & set(vals))
        self.assertEqual(invoice._rs_correction_k_types(), ['1', '2', '3', '4'])
        copy = invoice.with_context(include_business_fields=True).copy(vals)
        self.assertFalse(copy.rs_einv_is_spec)
        self.assertEqual(self.rsge.calls, [])

    def test_original_refresh_survives_a_missing_correction(self):
        invoice, _correction = self._saved_correction()
        del self.rsge.docs[CORRECTION]
        invoice.action_rs_refresh_status()
        self.assertEqual(invoice.rs_einv_status, '3')
        self.assertTrue(self._logs(invoice, 'Could not refresh correction', 'warning'))

    def test_correction_type_is_not_required_on_the_form(self):
        arch = etree.fromstring(self.env['account.move'].get_view(view_type='form')['arch'])
        nodes = arch.xpath("//field[@name='rs_spec_k_type']")
        self.assertEqual(len(nodes), 1)
        self.assertEqual((nodes[0].get('required'), nodes[0].get('readonly')), (None, '1'))

    def test_cancel_and_reissue_stays_refused(self):
        invoice = self._filed_spec_invoice()
        wizard = self._wizard(invoice, rs_einv_flow='replace')
        with self.assertRaises(UserError) as error:
            wizard.modify_moves()
        self.assertIn("Replace RS invoice with a corrected invoice", str(error.exception))
        self.assertFalse(invoice.rs_einv_replaced_by_id)
