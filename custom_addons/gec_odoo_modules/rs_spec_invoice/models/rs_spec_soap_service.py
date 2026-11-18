from datetime import datetime
from types import SimpleNamespace

from odoo import models
from odoo.exceptions import UserError
from odoo.addons.rs_einvoice.models.account_move import rs_to_int
from odoo.addons.rs_einvoice.models.rs_soap_service import _zeep_fault_class, _zeep_fault_message

SPEC_WSDL_URL = "https://webserv.rs.ge/specinvoices/SpecInvoicesService.asmx?WSDL"
SPEC_INT_COLUMNS = ('k_id', 'k_type', 'seller_un_id', 'buyer_un_id', 'was_ref')
SPEC_EMPTY_COLUMNS = ('f_series', 'f_number', 'tr_st_date', 'no_text', 'oil_st_n', 'oil_st_address', 'oil_fn_n', 'oil_fn_address')


class RsSpecSoapService(models.AbstractModel):
    _name = 'rs.spec.soap.service'
    _description = 'RS Petroleum Invoice SOAP Client'

    def _rs_base(self):
        return self.env['rs.soap.service']

    def _client(self):
        return self._rs_base()._get_client(SPEC_WSDL_URL)

    def _auth(self):
        return self._rs_base()._auth_kwargs()

    def _login(self):
        """One chek_in per transaction: its sui is the p_S_USER_ID of a save; the ordinary chek returns none."""
        key = ('rs_spec_sui', self.env.uid, self.env.company.id)
        if key not in self.env.cr.cache:
            result = self._rs_write('chek_in', log_text='odoo')
            if not result.chek_inResult:
                raise UserError(self.env._("rs.ge rejected your credentials."))
            self.env.cr.cache[key] = result.sui
        return self.env.cr.cache[key]

    def _rs_table(self, operation, **kwargs):
        return self._rs_base()._call_datatable(operation, wsdl_url=SPEC_WSDL_URL, **kwargs, **self._auth())

    def _rs_write(self, operation, **kwargs):
        """Writes are never retried: a repeated save or status change on rs.ge is not safe."""
        try:
            return getattr(self._client().service, operation)(**kwargs, **self._auth())
        except _zeep_fault_class() as e:
            raise UserError(self.env._("rs.ge rejected the request: %s", _zeep_fault_message(e)))

    def _check_auth(self):
        self._login()

    def _rs_company_un_id(self):
        return self._rs_base()._rs_company_un_id()

    def _rs_partner_un_id(self, partner):
        return self._rs_base()._rs_partner_un_id(partner)

    def get_invoice(self, inv_id):
        """rs.ge leaves empty columns out of a row: the ones the buyer path reads are filled with None."""
        rows = self._rs_table('get_invoice_n', invois_id=inv_id)
        if not rows:
            raise UserError(self.env._("rs.ge has no petroleum invoice with ID %s.", inv_id))
        row = {**dict.fromkeys(SPEC_EMPTY_COLUMNS), **rows[0]}
        operation_dt = datetime.fromisoformat(row['operation_dt']) if row.get('operation_dt') else None
        ints = {'status': int(row['status']), **{name: rs_to_int(row.get(name)) for name in SPEC_INT_COLUMNS}}
        return SimpleNamespace(**{**row, **ints, 'operation_dt': operation_dt})

    def get_invoice_desc(self, inv_id):
        rows = self._rs_table('get_invoice_desc_n', invois_id=inv_id)
        return [dict(row, full_amount=row.get('unit_price'), drg_amount=row.get('dgg_price')) for row in rows]

    def get_invoice_waybills(self, inv_id):
        """A ნსაფ replaces the waybill: rs_base_methods asks on every pull."""
        return []

    def get_buyer_invoices(self, un_id, s_dt, e_dt, op_s_dt=None, op_e_dt=None, invoice_no='', sa_ident_no='', desc='', doc_mos_nom=''):
        rows = self._rs_table('get_buyer_invoices_n', un_id=int(un_id or 0), s_dt=s_dt, e_dt=e_dt, op_s_dt=op_s_dt or s_dt, op_e_dt=op_e_dt or e_dt,
            invoice_no=invoice_no, sa_ident_no=sa_ident_no, desc=desc, doc_mos_nom=doc_mos_nom)
        return [dict(row, sa_ident_no=row.get('seller_sn'), org_name=row.get('seller_name'), tanxa=row.get('full_amount'),
            reg_dt=row.get('reg_date')) for row in rows]

    def buyer_accept_invoice(self, inv_id, target_status):
        return self._rs_write('acsept_invoice_status_n', inv_id=inv_id, status=target_status)

    def buyer_reject_invoice(self, inv_id, reason):
        return self._rs_write('ref_invoice_status_n', inv_id=inv_id, ref_text=reason or '')
