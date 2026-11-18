from datetime import UTC, datetime
from decimal import Decimal

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.addons.rs_einvoice.models.account_move import _rs_clean_number, rs_to_float
from odoo.addons.rs_einvoice.models.rs_soap_service import _to_rs_dt

INVOICE_TYPES = [('1', 'Retail'), ('2', 'Wholesale')]
ROAD = 'საავტომობილო'
TRANSPORT_TYPES = [
    (ROAD, 'Road'),
    ('სარკინიგზო', 'Railway'),
    ('მილსადენი', 'Pipeline'),
    ('გადაწერა', 'Re-registration (no transport)'),
    ('ტალონებით', 'Coupons'),
    ('პლასტიკური ბარათით', 'Plastic card'),
    ('სხვა', 'Other'),
]
LITRE = 'ლ'
KG = 'კგ'
UNITS = [(LITRE, 'Litre'), (KG, 'Kilogram')]
PURCHASE_DOC_ALT_TYPES = [
    ('მოპოვება', 'Extraction'),
    ('წარმოება', 'Production'),
    ('შეძენა ნსაფ-ის გარეშე', 'Purchase without a petroleum invoice'),
    ('შეძენა აუქციონზე', 'Purchase at auction'),
    ('შეძენა სასამართლო გადაწყვეტილებით', 'Purchase by court decision'),
    ('სხვა', 'Other'),
]
SPEC_DRG_TYPES = {'taxable': 1, 'zero': 0, 'untaxed': -1}
SPEC_K_TYPES = [
    ('11', 'Taxable operation cancelled (11)'),
    ('12', 'Taxable operation type changed (12)'),
    ('13', 'Agreed price changed (13)'),
    ('14', 'Goods returned (14)'),
    ('21', 'Taxable operation type changed (21)'),
    ('22', 'Agreed price changed (22)'),
]
SPEC_K_TYPE_HELP = ("rs.ge correction type of the petroleum invoice. Types 11-14 apply before transport starts, types 21 and 22 presumably after "
    "(the rs.ge description does not say so directly). After type 11 the invoice cannot be corrected again.")
SPEC_COPY_FIELDS = ('rs_spec_invoice_type', 'rs_spec_start_site_id', 'rs_spec_end_site_id', 'rs_spec_transport_type', 'rs_spec_vehicle_id',
    'rs_spec_car_brand', 'rs_spec_car_number', 'rs_spec_driver_partner_id', 'rs_spec_driver_tin', 'rs_spec_driver_name',
    'rs_spec_driver_is_foreigner', 'rs_spec_carrier_name', 'rs_spec_carrier_tin', 'rs_spec_ssaf_number', 'rs_spec_ssaf_date', 'rs_spec_ssaf_alt_type',
    'rs_spec_ssaf_alt_number', 'rs_spec_ssd_number', 'rs_spec_ssd_date')


class AccountMove(models.Model):
    _inherit = 'account.move'

    rs_spec_invoice_type = fields.Selection(INVOICE_TYPES, string='Petroleum Invoice Type', default='2', copy=False)
    rs_spec_unit = fields.Selection(UNITS, string='Petroleum Unit', compute='_compute_rs_spec_quantities', store=True, readonly=False, copy=False)
    rs_spec_quantity_l = fields.Float('Quantity (litres)', digits=(16, 3), compute='_compute_rs_spec_quantities', store=True, readonly=False,
        copy=False)
    rs_spec_quantity_kg = fields.Float('Quantity (kg)', digits=(16, 3), compute='_compute_rs_spec_quantities', store=True, readonly=False, copy=False)
    rs_spec_seller_un_id = fields.Integer('Seller RS ID', compute='_compute_rs_spec_seller_un_id')
    rs_spec_buyer_un_id = fields.Integer('Buyer RS ID', compute='_compute_rs_spec_buyer_un_id')
    rs_spec_start_site_id = fields.Many2one('rs.spec.site', string='Start Site', ondelete='restrict', copy=False)
    rs_spec_end_site_id = fields.Many2one('rs.spec.site', string='End Site', ondelete='restrict', copy=False)
    rs_spec_transport_type = fields.Selection(TRANSPORT_TYPES, string='Transport Type', default=ROAD, copy=False)
    rs_spec_vehicle_id = fields.Many2one('fleet.vehicle', string='Car Plate', ondelete='set null', check_company=True, copy=False,
        context={'rs_plate_only': True})
    rs_spec_car_brand = fields.Char('Car Brand', copy=False)
    rs_spec_car_number = fields.Char('Car Number', copy=False)
    rs_spec_driver_partner_id = fields.Many2one('res.partner', string='Driver (Partner)', ondelete='set null', domain=[('rs_is_driver', '=', True)],
        check_company=True, context={'show_partner_tin': True}, copy=False)
    rs_spec_driver_tin = fields.Char('Driver TIN', copy=False)
    rs_spec_driver_name = fields.Char('Driver Name', copy=False)
    rs_spec_driver_is_foreigner = fields.Boolean('Driver is Foreigner', copy=False)
    rs_spec_carrier_name = fields.Char('Carrier Name', copy=False)
    rs_spec_carrier_tin = fields.Char('Carrier TIN', copy=False)
    rs_spec_ssaf_number = fields.Char('Purchase Invoice Number', copy=False)
    rs_spec_ssaf_date = fields.Date('Purchase Invoice Date', copy=False)
    rs_spec_ssaf_alt_type = fields.Selection(PURCHASE_DOC_ALT_TYPES, string='Other Purchase Document', copy=False)
    rs_spec_ssaf_alt_number = fields.Char('Other Purchase Document Number', copy=False)
    rs_spec_ssd_number = fields.Char('Customs Document Number', copy=False)
    rs_spec_ssd_date = fields.Date('Customs Document Date', copy=False)
    rs_spec_transport_started_at = fields.Datetime('Transport Started', readonly=True, copy=False)
    rs_spec_k_type = fields.Selection(SPEC_K_TYPES, string='Petroleum Correction Type', copy=False, tracking=True, help=SPEC_K_TYPE_HELP)

    @api.depends('invoice_line_ids.quantity', 'invoice_line_ids.product_uom_id', 'invoice_line_ids.product_id',
        'invoice_line_ids.product_id.rs_spec_rs_id', 'invoice_line_ids.display_type')
    def _compute_rs_spec_quantities(self):
        litre = self.env.ref('uom.product_uom_litre')
        kg = self.env.ref('uom.product_uom_kgm')
        for move in self:
            line = move._rs_spec_line()
            uom = line.product_uom_id if len(line) == 1 else self.env['uom.uom']
            has_l = bool(uom) and uom._has_common_reference(litre)
            has_kg = bool(uom) and uom._has_common_reference(kg)
            move.rs_spec_quantity_l = uom._compute_quantity(line.quantity, litre, round=False) if has_l else 0
            move.rs_spec_quantity_kg = uom._compute_quantity(line.quantity, kg, round=False) if has_kg else 0
            move.rs_spec_unit = KG if has_kg and not has_l else LITRE

    @api.depends('company_id')
    @api.depends_context('uid')
    def _compute_rs_spec_seller_un_id(self):
        for move in self:
            move.rs_spec_seller_un_id = move.env.user.with_company(move.company_id).rs_un_id

    @api.depends('commercial_partner_id.rs_un_id')
    def _compute_rs_spec_buyer_un_id(self):
        for move in self:
            move.rs_spec_buyer_un_id = move.commercial_partner_id.rs_un_id

    @api.onchange('rs_spec_vehicle_id')
    def _onchange_rs_spec_vehicle_id(self):
        vehicle = self.rs_spec_vehicle_id
        if vehicle:
            self.rs_spec_car_number = (vehicle.license_plate or '').upper()
            self.rs_spec_car_brand = vehicle.model_id.brand_id.name
            if vehicle.driver_id and not self.rs_spec_driver_tin:
                self.rs_spec_driver_partner_id = vehicle.driver_id
                self._onchange_rs_spec_driver_partner_id()

    @api.onchange('rs_spec_driver_partner_id')
    def _onchange_rs_spec_driver_partner_id(self):
        driver = self.rs_spec_driver_partner_id
        self.rs_spec_driver_tin = driver.vat
        self.rs_spec_driver_name = driver.name
        self.rs_spec_driver_is_foreigner = driver.rs_is_foreigner

    def _rs_spec_line(self):
        return self._rs_product_lines().filtered('product_id.rs_spec_rs_id')

    def _rs_spec_service(self):
        return self.env['rs.spec.soap.service'].with_company(self.company_id)

    def _rs_correction_k_types(self):
        if self.rs_einv_is_spec:
            return [code for code, _label in SPEC_K_TYPES]
        return super()._rs_correction_k_types()

    def _rs_correction_copy_vals(self, k_type):
        vals = super()._rs_correction_copy_vals(k_type)
        if not self.rs_einv_is_spec:
            return vals
        vals.pop('rs_einv_k_type')
        vals.update({'rs_einv_is_spec': True, 'rs_spec_k_type': k_type})
        vals.update({name: self._fields[name].convert_to_write(self[name], self) for name in SPEC_COPY_FIELDS})
        return vals

    def _rs_do_correct_reissue(self, k_type=None):
        action = super()._rs_do_correct_reissue(k_type=k_type)
        if self.rs_einv_is_spec:
            copy = self.rs_einv_replaced_by_id
            if k_type == '11':
                copy._rs_spec_line().quantity = 0
            else:
                copy.write({
                    'rs_spec_unit': self.rs_spec_unit,
                    'rs_spec_quantity_l': self.rs_spec_quantity_l,
                    'rs_spec_quantity_kg': self.rs_spec_quantity_kg,
                })
        return action

    def _rs_spec_mark_before_post(self):
        mark = unmark = self.browse()
        for move in self.filtered(lambda m: m.state == 'draft' and m.move_type == 'out_invoice'):
            if move.rs_einv_skip or (not move.rs_einv_is_spec and (move.rs_einv_replaces_id or move.rs_einv_id)):
                continue
            lines = move._rs_product_lines().filtered(lambda line: not line.is_downpayment)
            fuel = lines.filtered('product_id.rs_spec_rs_id')
            if fuel and fuel != lines:
                raise UserError(self.env._("Invoice petroleum products on their own invoice: %s also has other products.", move.display_name))
            if len(fuel) > 1:
                raise UserError(self.env._("One petroleum product per invoice: %s has %s fuel lines (one ნსაფ holds one product and one vehicle).",
                    move.display_name, len(fuel)))
            if (move.rs_einv_id or move.rs_einv_replaces_id) and not fuel:
                raise UserError(self.env._("%s is filed on rs.ge as a petroleum invoice: keep its petroleum product line.", move.display_name))
            if fuel and not move.rs_einv_is_spec:
                mark |= move
            elif not fuel and move.rs_einv_is_spec:
                unmark |= move
        mark.write({'rs_einv_is_spec': True})
        unmark.write({'rs_einv_is_spec': False})

    def action_post(self):
        self._rs_spec_mark_before_post()
        return super().action_post()

    def action_validate_moves_with_confirmation(self):
        self._rs_spec_mark_before_post()
        return super().action_validate_moves_with_confirmation()

    def action_rs_refresh_status(self):
        self.ensure_one()
        if not self.rs_einv_is_spec:
            return super().action_rs_refresh_status()
        if not self.rs_einv_id:
            return
        service = self._rs_get_service()
        result = service.get_invoice(self._rs_inv_id_int)
        status = str(result.status)
        vals = {'rs_einv_series': result.f_series, 'rs_einv_number': _rs_clean_number(result.f_number)}
        if result.tr_st_date:
            started = datetime.fromisoformat(result.tr_st_date)
            vals['rs_spec_transport_started_at'] = started.astimezone(UTC).replace(tzinfo=None)
        self.write(vals)
        previous = self.rs_einv_status
        self._rs_refresh_apply_status(status, previous)
        if self.rs_einv_is_buyer_side:
            self._rs_refresh_rejection(result, status, previous)
        if previous == '5' and self.rs_einv_status == '4' and self.rs_einv_replacement_mode == 'correction':
            if result.no_text:
                self._rs_log("Buyer rejected the correction on rs.ge: %s" % result.no_text)
            self._rs_reset_correction_to_draft_after_rejection()
        child = self.rs_einv_replaced_by_id
        if child.rs_einv_replacement_mode == 'correction':
            try:
                with self.env.cr.savepoint():
                    child._rs_safe_refresh_status()
            except (UserError, ValidationError) as e:
                self._rs_log("Could not refresh correction %s: %s" % (child.display_name, e), 'warning')
        if self.rs_einv_is_buyer_side:
            self._rs_refresh_pulled_lines(service)

    def _rs_raise_if_locked(self, action_label, allow_pending=False):
        seller_spec = self.rs_einv_is_spec and not self.rs_einv_is_buyer_side
        return super()._rs_raise_if_locked(action_label, allow_pending=allow_pending and not seller_spec)

    def _rs_get_service(self, check_auth=False):
        if not self.rs_einv_is_spec:
            return super()._rs_get_service(check_auth=check_auth)
        service = self._rs_spec_service()
        if check_auth:
            service._check_auth()
        return service

    def _rs_line_snapshot_vals(self, row):
        vals = super()._rs_line_snapshot_vals(row)
        vals.update(rs_good_id=int(row.get('good_id') or 0), rs_g_number_alt=rs_to_float(row.get('goods_number_alt')))
        return vals

    def _rs_find_product_for_pulled(self, snap):
        if not (self.rs_einv_is_spec and snap.rs_good_id):
            return super()._rs_find_product_for_pulled(snap)
        Product = self.env['product.product']
        by_rs_id = ('product_tmpl_id.rs_spec_rs_id', '=', snap.rs_good_id)
        return Product.search([by_rs_id, *Product._check_company_domain(self.company_id)], limit=1)

    def _rs_pulled_line_vals(self, snap, purchase_vat_18, existing_line=None):
        vals = super()._rs_pulled_line_vals(snap, purchase_vat_18, existing_line=existing_line)
        kg_qty = snap.rs_g_number_alt
        if not (self.rs_einv_is_spec and kg_qty):
            return vals
        line = existing_line or self.env['account.move.line']
        uom = (line.product_id or self.env['product.product'].browse(vals.get('product_id'))).uom_id
        litre, kg = self.env.ref('uom.product_uom_litre'), self.env.ref('uom.product_uom_kgm')
        if uom and uom._has_common_reference(kg) and not uom._has_common_reference(litre):
            vals.update(quantity=kg_qty, price_unit=vals['price_unit'] * vals['quantity'] / kg_qty)
        return vals

    def _rs_pull_apply_header(self, result, status):
        super()._rs_pull_apply_header(result, status)
        if self.rs_einv_is_spec:
            self._rs_spec_write_sites(result)

    def _rs_reissue_create_draft(self, service, verify, correction_id_int, verify_status, v_k_type, correction_rs_id):
        draft = super()._rs_reissue_create_draft(service, verify, correction_id_int, verify_status, v_k_type, correction_rs_id)
        if self.rs_einv_is_spec:
            draft._rs_spec_write_sites(verify)
        return draft

    def _rs_spec_write_sites(self, result):
        Site = self.env['rs.spec.site']
        sites = []
        for un_id, code, address in (
            (result.seller_un_id, result.oil_st_n, result.oil_st_address),
            (result.buyer_un_id, result.oil_fn_n, result.oil_fn_address),
        ):
            site = Site
            if code and code != '-':
                site = Site.search([('rs_un_id', '=', un_id), ('code', '=', code)], limit=1)
                site = site or Site.create({
                    'rs_un_id': un_id,
                    'code': code,
                    'address': address,
                })
            sites.append(site.id)
        self.write({'rs_spec_start_site_id': sites[0], 'rs_spec_end_site_id': sites[1]})

    def action_rs_spec_save(self):
        self._rs_acquire_row_lock(self.env._("Save on rs.ge"))
        self._rs_spec_push()

    def _rs_spec_push(self):
        self.ensure_one()
        if self.rs_einv_pending_action and not self.rs_einv_id:
            raise UserError(self.env._("rs.ge did not answer the last save of %s, so it may already be on rs.ge: link it with Resolve Orphan, "
                "or click Dismiss Pending if rs.ge does not show it.", self.display_name))
        correction = self.rs_einv_replacement_mode == 'correction'
        if correction and not self.rs_einv_id:
            self._rs_spec_create_correction()
        if correction and self.rs_spec_k_type == '11':
            self._rs_stamp_sync_hash()
            return
        line = self._rs_spec_line()
        payload = self._rs_line_to_payload(line)
        drg_type = SPEC_DRG_TYPES[self._rs_line_vat_class(line)[0]]
        service = self._rs_spec_service()
        line_id = int(line.rs_line_id or 0)
        if self.rs_einv_id and not line_id:
            rows = service._rs_table('get_invoice_desc_n', invois_id=self._rs_inv_id_int)
            line_id = int(rows[0]['id']) if rows else 0
        auth = service._auth()
        if not correction:
            sui = service._login()
            base = service._rs_base()
            seller_un_id, buyer_un_id = base._rs_company_un_id(), base._rs_partner_un_id(self.commercial_partner_id)
            car_number = self.rs_spec_car_number or ''
            mark = f"{self.rs_spec_car_brand or ''}|{car_number}" if self.rs_spec_transport_type == ROAD else car_number
            if not self.rs_einv_id:
                self._rs_mark_pending('create')
            header = service._rs_write('save_invoice_b_n', invois_id=self._rs_inv_id_int, p_OPERATION_DT=_to_rs_dt(self.invoice_date),
                p_SELLER_UN_ID=seller_un_id, p_BUYER_UN_ID=buyer_un_id,
                p_SSD_N=self.rs_spec_ssd_number or '', p_SSAF_N=self.rs_spec_ssaf_number or '', p_CALC_DATE=None, p_K_SSAF_N='', p_TR_ST_DATE=None,
                p_OIL_ST_ADDRESS=self.rs_spec_start_site_id.address or '', p_OIL_ST_N=self.rs_spec_start_site_id.code or '',
                p_OIL_FN_ADDRESS=self.rs_spec_end_site_id.address or '', p_OIL_FN_N=self.rs_spec_end_site_id.code or '-',
                p_TRANSPORT_TYPE=self.rs_spec_transport_type, p_TRANSPORT_MARK=mark, p_DRIVER_INFO=self.rs_spec_driver_tin or '',
                p_CARRIER_INFO=self.rs_spec_carrier_name or '', p_CARRIE_S_NO=self.rs_spec_carrier_tin or '', p_USER_ID=auth['user_id'],
                p_S_USER_ID=sui, p_B_S_USER_ID=0, p_SSD_DATE=_to_rs_dt(self.rs_spec_ssd_date or None),
                p_SSAF_DATE=_to_rs_dt(self.rs_spec_ssaf_date or None), p_PAY_TYPE=0, p_SELLER_PHONE='', p_BUYER_PHONE='',
                p_driver_no=self.rs_spec_driver_name or '', p_SSAF_ALT_NUMBER=self.rs_spec_ssaf_alt_number or '',
                p_SSAF_ALT_TYPE=self.rs_spec_ssaf_alt_type or '', p_SSD_ALT_NUMBER='', p_SSD_ALT_TYPE='',
                p_SSAF_ALT_STATUS=1 if self.rs_spec_ssaf_alt_type else 0, p_SSD_ALT_STATUS=0,
                p_driver_is_geo=0 if self.rs_spec_driver_is_foreigner else 1, invoiceType=int(self.rs_spec_invoice_type))
            if not header.save_invoice_b_nResult:
                if not self.rs_einv_id:
                    # rs.ge answered "not saved", so there is nothing to recover and a corrected Save may run at once
                    self._rs_clear_pending()
                    self.env.cr.commit()
                raise UserError(self.env._("rs.ge refused the petroleum invoice; check sites, transport and document numbers."))
            if not self.rs_einv_id:
                self.write({'rs_einv_id': str(header.invois_id), 'rs_einv_status': '0'})
                self._rs_clear_pending()
                self._rs_log("Created on rs.ge with ID: %s" % header.invois_id)
                # rs.ge now holds the document: a retry must edit it, not create a second one
                self.env.cr.commit()
                if not self._rs_relock_after_commit():
                    raise UserError(self.env._("The invoice is busy: click Save on rs.ge again to add its goods line."))
        result = service._rs_write('save_invoice_desc_n', id=line_id, p_inv_id=self._rs_inv_id_int, p_goods='', p_g_unit=self.rs_spec_unit,
            p_g_number=Decimal(str(self.rs_spec_quantity_l)), p_un_price=Decimal(str(payload['full_amount'])),
            p_drg_amount=Decimal(str(max(payload['vat_amount'], 0))), p_aqcizi_amount=Decimal('0'), p_user_id=auth['user_id'], p_aqcizi_id='',
            p_aqcizi_rate=Decimal('0'), p_dgg_rate=Decimal('0'), p_g_number_alt=Decimal(str(self.rs_spec_quantity_kg)),
            p_good_id=line.product_id.rs_spec_rs_id, p_drg_type=drg_type)
        if not result.save_invoice_desc_nResult:
            raise UserError(self.env._("rs.ge refused the goods line of the petroleum invoice."))
        line.rs_line_id = str(result.id)
        self._rs_stamp_sync_hash()

    def _rs_spec_create_correction(self):
        original = self._rs_assert_correction_can_be_sent()
        service = self._rs_spec_service()
        self._rs_mark_pending('correction')
        result = service._rs_write('k_invoice_n', inv_id=original._rs_inv_id_int, k_type=int(self.rs_spec_k_type))
        if not result.k_invoice_nResult or not result.k_id:
            # rs.ge answered "not created", so there is nothing to recover and a new Save may run at once
            self._rs_clear_pending()
            self.env.cr.commit()
            raise UserError(self.env._("rs.ge did not create the correction of petroleum invoice %s. If rs.ge already shows a correction for it, "
                "finish or delete that one on rs.ge first.", original.display_name))
        self.write({'rs_einv_id': str(result.k_id), 'rs_einv_status': '4'})
        self._rs_clear_pending()
        self._rs_log("Correction created on rs.ge with ID %s (corrects %s, type %s)" % (result.k_id, original.rs_einv_id, self.rs_spec_k_type))
        # rs.ge now holds the correction: a retry must edit it, not create a second one
        self.env.cr.commit()
        if not self._rs_relock_after_commit():
            raise UserError(self.env._("The invoice is busy: click Save on rs.ge again to add its goods line."))

    def action_rs_spec_send(self):
        self._rs_acquire_row_lock(self.env._("Send to buyer"))
        self._rs_spec_push()
        target = 5 if self.rs_einv_status == '4' else 1
        if not self._rs_spec_service()._rs_write('change_invoice_status_n', inv_id=self._rs_inv_id_int, status=target):
            raise UserError(self.env._("rs.ge did not accept the status change."))
        self.write({'rs_einv_status': str(target), 'rs_einv_sent_at': fields.Datetime.now()})
        # rs.ge accepted the send: a failing status read must not undo it
        self.env.cr.commit()
        if self._rs_relock_after_commit():
            self.action_rs_refresh_status()

    def action_rs_spec_delete(self):
        self._rs_acquire_row_lock(self.env._("Delete on rs.ge"))
        if not self._rs_spec_service()._rs_write('change_invoice_status_n', inv_id=self._rs_inv_id_int, status=-1):
            raise UserError(self.env._("rs.ge did not delete the petroleum invoice."))
        self._rs_log("Deleted on rs.ge (ID %s)" % self.rs_einv_id)
        self.invoice_line_ids.rs_line_id = False
        self.with_context(rs_allow_id_overwrite=True).write({
            'rs_einv_id': False,
            'rs_einv_status': False,
            'rs_einv_series': False,
            'rs_einv_number': False,
            'rs_einv_last_sync_hash': False,
        })

    def action_rs_spec_load_sites(self):
        service = self._rs_spec_service()
        base = service._rs_base()
        Site = self.env['rs.spec.site']
        Site._rs_sync(service, base._rs_company_un_id())
        Site._rs_sync(service, base._rs_partner_un_id(self.commercial_partner_id))
