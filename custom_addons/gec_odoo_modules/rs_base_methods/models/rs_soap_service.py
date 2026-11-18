# -*- coding: utf-8 -*-

import logging

from odoo import models, _
from odoo.exceptions import UserError

from odoo.addons.rs_einvoice.models.rs_soap_service import _zeep_fault_class, _zeep_fault_message, _to_rs_dt

_logger = logging.getLogger(__name__)


class RsSoapService(models.AbstractModel):
    _inherit = 'rs.soap.service'

    # Waybill-invoice links (NtosService.ntos_invoices_inv_nos); read with get_invoice_waybills() in rs_einvoice

    def save_invoice_waybill_link(self, inv_id, overhead_no, overhead_dt):
        """Attach a waybill (overhead_no, overhead_dt) to an rs.ge invoice; return rs.ge's bool result."""
        client = self._get_client()
        auth = self._auth_kwargs()
        try:
            result = client.service.save_ntos_invoices_inv_nos(invois_id=int(inv_id), overhead_no=str(overhead_no or '').strip(),
                overhead_dt=_to_rs_dt(overhead_dt), **auth)
        except _zeep_fault_class() as e:
            raise UserError(_("rs.ge rejected the waybill attachment (inv_id=%s, overhead_no=%s): %s", inv_id, overhead_no, _zeep_fault_message(e)))
        _logger.info("save_ntos_invoices_inv_nos(inv_id=%s, overhead_no=%s) result: %s", inv_id, overhead_no, result)
        return bool(result)

    def delete_invoice_waybill_link(self, remote_id, inv_id):
        """Remove a waybill attachment by its rs.ge row id; return rs.ge's bool result."""
        client = self._get_client()
        auth = self._auth_kwargs()
        try:
            result = client.service.delete_ntos_invoices_inv_nos(id=int(remote_id), inv_id=int(inv_id), **auth)
        except _zeep_fault_class() as e:
            raise UserError(_("rs.ge rejected the waybill detach (id=%s, inv_id=%s): %s", remote_id, inv_id, _zeep_fault_message(e)))
        _logger.info("delete_ntos_invoices_inv_nos(id=%s, inv_id=%s) result: %s", remote_id, inv_id, result)
        return bool(result)
