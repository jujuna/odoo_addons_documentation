import logging
import time as time_mod
import requests as http_requests
from datetime import datetime
from decimal import Decimal
from lxml import etree
from zeep.exceptions import TransportError

from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

WSDL_URL = "https://www.revenue.mof.ge/ntosservice/ntosservice.asmx?WSDL"

# Fresh parser per call (lxml parsers are not thread-safe); the flags harden it against XXE.
def _new_safe_parser():
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, dtd_validation=False, load_dtd=False)

# Per-call SOAP timeout in seconds: a hung request must not lock a worker for minutes.
SOAP_TIMEOUT = 30

# WRITES are never retried: a duplicate side effect on rs.ge is unsafe.
SOAP_READ_RETRIES = 3
SOAP_RETRY_BASE_DELAY = 0.2

# Cache the zeep Client: WSDL parsing is slow; credentials travel per call, so sharing it is safe.
_RS_CLIENT_CACHE = {}


def _to_rs_dt(value):
    """rs.ge reads it as that Tbilisi day; noon, to avoid midnight tz cliffs."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime(value.year, value.month, value.day, 12, 0)


_TRANSIENT_EXCEPTIONS = (http_requests.exceptions.ConnectionError, http_requests.exceptions.Timeout, http_requests.exceptions.ChunkedEncodingError,
    http_requests.exceptions.ReadTimeout, http_requests.exceptions.HTTPError, TransportError)


def _retry_read(call, *args, **kwargs):
    """For idempotent SOAP reads only; writes are never retried."""
    last_exc = None
    for attempt in range(SOAP_READ_RETRIES):
        try:
            return call(*args, **kwargs)
        except _TRANSIENT_EXCEPTIONS as e:
            last_exc = e
            if attempt == SOAP_READ_RETRIES - 1:
                _logger.warning("rs.ge SOAP retry budget exhausted (%d attempts): %s", SOAP_READ_RETRIES, e)
                raise
            wait = SOAP_RETRY_BASE_DELAY * (2 ** attempt)
            _logger.info("rs.ge SOAP transient failure (%s); retrying in %.1fs", e, wait)
            time_mod.sleep(wait)
    raise last_exc  # pragma: no cover


def _zeep_fault_class():
    """Returns () without zeep: an except clause on it catches nothing."""
    try:
        from zeep.exceptions import Fault
        return Fault
    except ImportError:
        return ()


def _zeep_fault_message(exc):
    return getattr(exc, 'message', None) or str(exc)


def _rs_row_lookup(row, *keys):
    """rs.ge and zeep spell the same column differently (ID / id), so case variants also match."""
    if not row:
        return None
    lowered = ({str(k).lower(): v for k, v in row.items()} if isinstance(row, dict) else None)
    for key in keys:
        if lowered is not None:
            value = lowered.get(str(key).lower())
        else:
            value = next((getattr(row, variant) for variant in (key, str(key).upper(), str(key).lower()) if hasattr(row, variant)), None)
        if value is not None:
            return value
    return None


class RsSoapService(models.AbstractModel):
    _name = 'rs.soap.service'
    _description = 'Revenue Service SOAP Client'

    def _get_credentials(self):
        # rs_base_methods cannot be a manifest dependency (cycle), so check here for a clear message.
        getter = getattr(self.env.user, '_get_rs_credentials', None)
        if not callable(getter):
            raise UserError(_("rs.ge credentials provider is missing on res.users (_get_rs_credentials is not defined). The 'rs_base_methods' module "
                "must be installed and loaded before rs_einvoice. Install/upgrade it under Apps, then restart the worker."))
        creds = getter()
        if not creds or not creds.get('user_id'):
            raise UserError(_("Your rs.ge User ID for %(company)s is not set yet (user: %(user)s). Switch to that company, open your User "
                "Preferences, fill in the rs.ge Username and Password fields, then click 'Test RS Credentials' so Odoo can fetch and save your User "
                "ID.", company=self.env.company.display_name, user=self.env.user.display_name))
        return creds

    def _get_client(self, wsdl_url=WSDL_URL):
        client = _RS_CLIENT_CACHE.get(wsdl_url)
        if client is not None:
            return client
        try:
            from zeep import Client
            from zeep.transports import Transport
        except ImportError:
            raise UserError(_("The Python package 'zeep' is required for rs.ge. Ask the system administrator to install it: pip install zeep"))
        session = http_requests.Session()
        transport = Transport(session=session, timeout=SOAP_TIMEOUT, operation_timeout=SOAP_TIMEOUT)
        client = Client(wsdl_url, transport=transport)
        _RS_CLIENT_CACHE[wsdl_url] = client
        return client

    def _auth_kwargs(self):
        creds = self._get_credentials()
        return {'user_id': creds['user_id'], 'su': creds['su'], 'sp': creds['sp']}

    @staticmethod
    def _parse_datatable_rows(xml_bytes):
        rows = []
        root = etree.fromstring(xml_bytes, parser=_new_safe_parser())
        for doc_el in root.iter('DocumentElement'):
            for item in doc_el:
                row = {}
                for child in item:
                    tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    row[tag.lower()] = child.text
                rows.append(row)
        return rows

    def _call_datatable(self, operation, wsdl_url=WSDL_URL, **kwargs):
        """zeep cannot read DataTable replies, so they are parsed raw; rs.ge takes whole seconds only."""
        client = self._get_client(wsdl_url)
        params = {name: value.replace(microsecond=0) if isinstance(value, datetime) else value for name, value in kwargs.items()}
        envelope = client.create_message(client.service, operation, **params)
        resp = _retry_read(client.transport.post_xml, client.service._binding_options['address'], envelope,
            {'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': 'http://tempuri.org/%s' % operation})
        resp.raise_for_status()
        return self._parse_datatable_rows(resp.content)

    def _check_auth(self):
        """One chek per transaction and user/company, not one per document."""
        key = ('rs_einvoice_auth_ok', self.env.uid, self.env.company.id)
        if key in self.env.cr.cache:
            return
        client = self._get_client()
        auth = self._auth_kwargs()
        result = client.service.chek(**auth)
        ok = getattr(result, 'chekResult', result)
        if not ok:
            raise UserError(_("rs.ge rejected your credentials. Open your User Preferences, double-check the rs.ge Username and Password, and click "
                "'Test RS Credentials' to revalidate."))
        self.env.cr.cache[key] = True

    def get_un_id_from_tin(self, tin):
        client = self._get_client()
        auth = self._auth_kwargs()
        result = _retry_read(client.service.get_un_id_from_tin, tin=tin, **auth)
        if hasattr(result, 'get_un_id_from_tinResult'):
            un_id = result.get_un_id_from_tinResult
        elif isinstance(result, int):
            un_id = result
        else:
            un_id = 0
        if not un_id or un_id < 0:
            raise UserError(_("rs.ge could not find a registrant with TIN '%s'. Verify the TIN with the partner and try again.", tin))
        return un_id

    def get_seller_un_id(self):
        client = self._get_client()
        auth = self._auth_kwargs()
        result = _retry_read(client.service.get_un_id_from_user_id, **auth)
        un_id = getattr(result, 'get_un_id_from_user_idResult', result)
        if isinstance(un_id, int):
            return un_id
        return int(un_id) if un_id else 0

    def _rs_company_un_id(self):
        """Every taxpayer call uses this id, so a document files for its company even on a representative login."""
        un_id = int(getattr(self.env.user, 'rs_un_id', 0) or 0)
        if not un_id:
            raise UserError(_("The rs.ge taxpayer id of %s is not stored yet. Switch to that company, open your User Preferences and click 'Test RS "
                "Credentials'.", self.env.company.display_name))
        return un_id

    def _rs_partner_un_id(self, partner):
        """Written as superuser: the accountant may not edit partners."""
        partner.ensure_one()
        if not partner.rs_un_id:
            partner.sudo().rs_un_id = self.get_un_id_from_tin((partner.vat or '').strip())
        return partner.rs_un_id

    def get_party_from_un_id(self, un_id):
        client = self._get_client()
        auth = self._auth_kwargs()
        result = _retry_read(client.service.get_tin_from_un_id, un_id=int(un_id or 0), **auth)
        tin = getattr(result, 'get_tin_from_un_idResult', result)
        name = getattr(result, 'name', '') or ''
        return {'tin': str(tin) if tin not in (None, '') else '', 'name': str(name) if name else ''}

    def save_invoice(self, inv_id, operation_date, seller_un_id, buyer_un_id, variant='regular', note=''):
        """The date goes to rs.ge as Tbilisi noon, to avoid VAT-period shifts."""
        client = self._get_client()
        auth = self._auth_kwargs()
        op_dt = _to_rs_dt(operation_date) or datetime.now()
        kwargs = dict(invois_id=inv_id or 0, operation_date=op_dt, seller_un_id=seller_un_id, buyer_un_id=buyer_un_id, overhead_no="",
            overhead_dt=op_dt, b_s_user_id=0, **auth)
        try:
            if variant == 'advance':
                result = client.service.save_invoice_a(**kwargs)
                _logger.info("save_invoice_a result: %s", result)
            elif variant == 'note':
                result = client.service.save_invoice_n(note=note or '', **kwargs)
                _logger.info("save_invoice_n result: %s", result)
            else:
                result = client.service.save_invoice(**kwargs)
                _logger.info("save_invoice result: %s", result)
        except _zeep_fault_class() as e:
            raise UserError(_("rs.ge rejected the invoice (SOAP fault): %s", _zeep_fault_message(e)))
        return result

    def save_invoice_desc(self, inv_id, goods, g_unit, quantity, full_amount, vat_amount, desc_id=0):
        client = self._get_client()
        auth = self._auth_kwargs()
        try:
            result = client.service.save_invoice_desc(id=desc_id or 0, invois_id=inv_id, goods=goods, g_unit=g_unit or 'ერთეული',
                g_number=Decimal(str(quantity)), full_amount=Decimal(str(full_amount)), drg_amount=Decimal(str(vat_amount)),
                aqcizi_amount=Decimal('0'), akciz_id=0, **auth)
        except _zeep_fault_class() as e:
            raise UserError(_("rs.ge rejected the line (inv_id=%s, goods='%s'): %s", inv_id, goods, _zeep_fault_message(e)))
        _logger.info("save_invoice_desc result: %s", result)
        return result

    def delete_invoice_desc(self, desc_id, inv_id):
        client = self._get_client()
        auth = self._auth_kwargs()
        return client.service.delete_invoice_desc(id=desc_id, inv_id=inv_id, **auth)

    def change_invoice_status(self, inv_id, status):
        client = self._get_client()
        auth = self._auth_kwargs()
        try:
            result = client.service.change_invoice_status(inv_id=inv_id, status=status, **auth)
        except _zeep_fault_class() as e:
            raise UserError(_("rs.ge rejected the status change (inv_id=%s, status=%s): %s", inv_id, status, _zeep_fault_message(e)))
        _logger.info("change_invoice_status(inv_id=%s, status=%s) result: %s", inv_id, status, result)
        return result

    def delete_invoice(self, inv_id):
        return self.change_invoice_status(inv_id, -1)

    def send_invoice(self, inv_id):
        """rs.ge status 0 -> 1."""
        return self.change_invoice_status(inv_id, 1)

    def send_correction(self, k_id):
        """Corrections go from status 4 to 5, not 1: target 1 silently fails on rs.ge."""
        return self.change_invoice_status(k_id, 5)

    def cancel_invoice(self, inv_id):
        """rs.ge status 2 -> 6."""
        return self.change_invoice_status(inv_id, 6)

    def buyer_accept_invoice(self, inv_id, target_status):
        """target_status is the destination: 1 -> 2 (original), 5 -> 8 (correction), 6 -> 7 (cancellation)."""
        client = self._get_client()
        auth = self._auth_kwargs()
        result = client.service.acsept_invoice_status(inv_id=inv_id, status=target_status, **auth)
        _logger.info("acsept_invoice_status(inv_id=%s, target_status=%s) result: %s", inv_id, target_status, result)
        return result

    def buyer_reject_invoice(self, inv_id, reason):
        """The reason text is shown to the supplier on rs.ge."""
        client = self._get_client()
        auth = self._auth_kwargs()
        result = client.service.ref_invoice_status(inv_id=inv_id, ref_text=reason or '', **auth)
        _logger.info("ref_invoice_status(inv_id=%s) result: %s", inv_id, result)
        return result

    def get_invoice(self, inv_id):
        client = self._get_client()
        auth = self._auth_kwargs()
        try:
            return _retry_read(client.service.get_invoice, invois_id=inv_id, **auth)
        except _zeep_fault_class() as e:
            raise UserError(_("rs.ge rejected the invoice read (inv_id=%s): %s", inv_id, _zeep_fault_message(e)))

    def get_invoice_desc(self, inv_id):
        return self._call_datatable('get_invoice_desc', invois_id=inv_id, **self._auth_kwargs())

    def get_invoice_waybills(self, inv_id):
        return self._call_datatable('get_ntos_invoices_inv_nos', invois_id=int(inv_id or 0), **self._auth_kwargs())

    def get_attachable_advance_invoices(self, seller_un_id, buyer_tin, operation_date):
        return self._call_datatable('get_attachable_advance_invoices', seller_un_id=int(seller_un_id or 0), buyer_tin=buyer_tin,
            operation_date=_to_rs_dt(operation_date) or datetime.now(), **self._auth_kwargs())

    def get_attached_advance_invoices(self, invoice_id):
        return self._call_datatable('get_attached_advance_invoices', invoice_id=int(invoice_id or 0), **self._auth_kwargs())

    def attach_advance_invoice(self, invoice_id, advance_invoice_id, advance_invoice_drg_amount, seller_un_id, buyer_tin):
        client = self._get_client()
        auth = self._auth_kwargs()
        try:
            result = client.service.attach_advance_invoice(invoice_id=int(invoice_id or 0), advance_invoice_id=int(advance_invoice_id or 0),
                advance_invoice_drg_amount=Decimal(str(advance_invoice_drg_amount)), seller_un_id=int(seller_un_id or 0), buyer_tin=buyer_tin or '',
                **auth)
        except _zeep_fault_class() as e:
            raise UserError(_("rs.ge rejected the advance attachment (invoice=%s, advance=%s): %s", invoice_id, advance_invoice_id,
                _zeep_fault_message(e)))
        _logger.info("attach_advance_invoice result: %s", result)
        return result

    def update_advance_invoice(self, invoice_id, advance_invoice_id, advance_invoice_drg_amount):
        client = self._get_client()
        auth = self._auth_kwargs()
        try:
            result = client.service.update_advance_invoice(invoice_id=int(invoice_id or 0), advance_invoice_id=int(advance_invoice_id or 0),
                advance_invoice_drg_amount=Decimal(str(advance_invoice_drg_amount)), **auth)
        except _zeep_fault_class() as e:
            raise UserError(_("rs.ge rejected the advance attachment update (invoice=%s, advance=%s): %s", invoice_id, advance_invoice_id,
                _zeep_fault_message(e)))
        _logger.info("update_advance_invoice result: %s", result)
        return result

    def create_correction(self, original_inv_id, k_type=1):
        client = self._get_client()
        auth = self._auth_kwargs()
        result = client.service.k_invoice(inv_id=original_inv_id, k_type=k_type, **auth)
        _logger.info("k_invoice result: %s", result)
        return result

    def get_makoreqtirebeli(self, inv_id):
        """Active correction k_id (0 or -1 if none). get_invoice's k_id is unreliable, so this is the only source."""
        client = self._get_client()
        auth = self._auth_kwargs()
        result = _retry_read(client.service.get_makoreqtirebeli, inv_id=inv_id, **auth)
        k_id = getattr(result, 'k_id', None)
        if k_id is None:
            return 0
        try:
            return int(k_id)
        except (TypeError, ValueError):
            return 0


    def get_buyer_invoices(self, un_id, s_dt, e_dt, op_s_dt=None, op_e_dt=None, invoice_no='', sa_ident_no='', desc='', doc_mos_nom=''):
        """rs.ge invoices where un_id is the buyer, one dict per invoice with lowercased column names."""
        return self._call_datatable('get_buyer_invoices', un_id=int(un_id or 0), s_dt=s_dt, e_dt=e_dt, op_s_dt=op_s_dt or s_dt,
            op_e_dt=op_e_dt or e_dt, invoice_no=invoice_no, sa_ident_no=sa_ident_no, desc=desc, doc_mos_nom=doc_mos_nom, **self._auth_kwargs())

    def get_user_invoices(self, un_id, last_update_s, last_update_e):
        """rs.ge caps the last-update window at 3 days."""
        return self._call_datatable('get_user_invoices', last_update_date_s=last_update_s, last_update_date_e=last_update_e, un_id=int(un_id or 0),
            **self._auth_kwargs())
