from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)

# Georgian unit name (as in akciz TITLE/MEASUREMENT) -> rs_unit_id. data/uom_data.xml already tags the
# Odoo UoMs with rs_unit_id, so only this direction is needed.
GEORGIAN_TO_RS_UNIT_ID = {
    'ცალი':       1,
    'კგ':         2,
    'გრამი':      3,
    'ლიტრი':      4,
    'ტონა':       5,
    'სანტიმეტრი': 7,
    'მეტრი':      8,
    'კილომეტრი':  9,
    'კვ.სმ':      10,
    'კვ.მ':       11,
    'მ³':         12,
    'მილილიტრი':  13,
    'შეკვრა':     14,
    'სხვა':       99,
    'ტ':          5,
    'მ3':         12,
    'მლ':         13,
    'სმ3':        13,
    'ღერი':       1,
    'წუთი':       1,
}

# rs_unit_id -> RS.GE's own unit name, sent as UNIT_TXT. 99 (Other) has none: its UNIT_TXT is the Odoo unit's name.
RS_UNIT_NAMES = {
    1: 'ცალი', 2: 'კგ', 3: 'გრამი', 4: 'ლიტრი', 5: 'ტონა', 7: 'სანტიმეტრი', 8: 'მეტრი',
    9: 'კილომეტრი', 10: 'კვ.სმ', 11: 'კვ.მ', 12: 'მ³', 13: 'მილილიტრი', 14: 'შეკვრა',
}


class ProductTemplate(models.Model):
    _inherit = 'product.template'


    # Per company: a shared product registered in company A's RS.GE account is not in company B's.
    is_rs_product = fields.Boolean(string='Is RS Product', company_dependent=True,
                                   help="This product's barcode is registered in the current company's RS.GE account.")
    is_excise = fields.Boolean(string='Excise Product', help='Subject to Georgian excise tax (alcohol, tobacco, fuel, etc.).')
    rs_excise_id = fields.Many2one('rs.excise.code', string='Excise Code', domain="[('is_currently_active', '=', True)]",
                                   help='Required when this product is excise.')
    external_ref_ids = fields.One2many('rs.product.external.ref', 'product_id', string='External References',
                                       help='How different sellers refer to this product(their barcode + name).')
    external_ref_count = fields.Integer(compute='_compute_external_ref_count', string='# Refs')


    @api.constrains('is_excise', 'rs_excise_id')
    def _check_excise_code_required(self):
        for tmpl in self:
            if tmpl.is_excise and not tmpl.rs_excise_id:
                raise ValidationError(_("'%s' is marked as Excise Product — pick an Excise Code.") % tmpl.display_name)


    @api.depends('external_ref_ids')
    def _compute_external_ref_count(self):
        for tmpl in self:
            tmpl.external_ref_count = len(tmpl.external_ref_ids)


    def action_send_single_barcode(self):
        """ Pushes this product's barcode to RS.GE """
        self.ensure_one()
        if not self.barcode:
            raise UserError(_("Product '%s' has no barcode.") % self.display_name)
        if self.is_rs_product:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('RS.GE Sync'),
                    'message': _("'%s' is already registered on RS.GE.") % self.display_name,
                    'type': 'info',
                    'sticky': False,
                },
            }

        # Excise products: RS.GE expects the excise code TITLE as goods_name (the portal field is bound to
        # the akciz catalog, not free text); other products send our own name.
        goods_name = self.rs_excise_id.name if (self.is_excise and self.rs_excise_id) else self.name

        service = self.env['rs.waybill.soap.service']
        service.save_bar_code(bar_code=self.barcode, goods_name=goods_name, unit_id=self.uom_id._rs_code(),
                              unit_txt=self.uom_id._rs_text(), a_id=int(self.rs_excise_id.rs_id or 0),)
        self.is_rs_product = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('RS.GE Sync'),
                'message': _("'%s' sent to RS.GE successfully.") % self.display_name,
                'type': 'success',
                'sticky': False,
            }
        }


    def action_send_bulk_to_rs(self):
        """ Pushes selected products' barcodes to RS.GE (best-effort) """
        service = self.env['rs.waybill.soap.service']
        sent = 0
        skipped = []
        failed = []
        already = []
        for product in self:
            if not product.barcode:
                skipped.append(product.display_name)
                continue
            if product.is_rs_product:
                already.append(product.display_name)
                continue
            try:
                # See note in action_send_single_barcode about excise TITLE.
                goods_name = (product.rs_excise_id.name if (product.is_excise and product.rs_excise_id) else product.name)
                service.save_bar_code(
                    bar_code=product.barcode,
                    goods_name=goods_name,
                    unit_id=product.uom_id._rs_code(),
                    unit_txt=product.uom_id._rs_text(),
                    a_id=int(product.rs_excise_id.rs_id or 0),
                )
                product.is_rs_product = True
                sent += 1
            except UserError as e:
                failed.append("%s (%s)" % (product.display_name, e))

        msg = _('%s product(s) sent to RS.GE') % sent
        if already:
            msg += _('\nAlready sent: %s') % ', '.join(already)
        if skipped:
            msg += _('\nSkipped (no barcode): %s') % ', '.join(skipped)
        if failed:
            msg += _('\nFailed: %s') % ', '.join(failed)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('RS.GE Bulk Sync'),
                'message': msg,
                'type': 'success' if sent else 'warning',
                'sticky': bool(failed) or bool(already),
            }
        }


def _as_date(value):
    """RS.GE date string ('YYYY-MM-DD') -> date; False when RS sent nothing. An unparseable value is
    passed through so the ORM raises about the real format."""
    value = (value or '').strip()
    if not value:
        return False
    try:
        return fields.Date.to_date(value)
    except (ValueError, TypeError):
        return value


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def action_send_single_barcode(self):
        """ Variant-form wrapper: the RS-send logic lives on product.template (_inherits delegates fields,
            not methods). """
        self.ensure_one()
        return self.product_tmpl_id.action_send_single_barcode()

    def action_update_rs_products(self):

        service = self.env['rs.waybill.soap.service']
        UoM = self.env['uom.uom']
        ExciseCode = self.env['rs.excise.code']

        # Excise catalog first: A_ID barcodes need it.
        # RS row: {ID, TITLE, MEASUREMENT, SAKON_KODI, AKCIS_GANAKV, START_DATE (YYYY-MM-DD), END_DATE (optional)}.
        akciz_new = 0
        akciz_updated = 0
        try:
            akciz_rows = service.get_akciz_codes() or []
        except Exception as e:
            _logger.warning("Failed to fetch akciz codes from RS.GE: %s", e)
            akciz_rows = []
        _logger.info("Akciz codes fetched from RS.GE: %d rows", len(akciz_rows))
        codes_by_rs_id = {c.rs_id: c for c in ExciseCode.search([])}
        code_vals_to_create = []
        for row in akciz_rows:
            try:
                rs_id = int(row.get('ID') or row.get('A_ID') or row.get('CODE') or 0)
            except (ValueError, TypeError):
                rs_id = 0
            if not rs_id:
                continue
            # Description: RS.GE uses TITLE (full description with code + unit + rate).
            name = (row.get('TITLE') or row.get('NAME') or row.get('DESC')
                    or f'Akciz {rs_id}')
            # Parse validity dates to real dates: a date never equals its string, so the change check always wrote.
            start_date = _as_date(row.get('START_DATE'))
            end_date = _as_date(row.get('END_DATE'))
            vals = {'name': name}
            if end_date:
                vals['active_until'] = end_date
            existing = codes_by_rs_id.get(rs_id)
            if existing:
                # active_from is written only when RS sent a START_DATE (a default would move the window every run).
                if start_date:
                    vals['active_from'] = start_date
                changed = {k: v for k, v in vals.items() if existing[k] != v}
                if changed:
                    existing.write(changed)
                    akciz_updated += 1
            else:
                vals['rs_id'] = rs_id
                # active_from is required: a new code with no START_DATE starts today (create path only).
                vals['active_from'] = start_date or fields.Date.context_today(self)
                code_vals_to_create.append(vals)
        if code_vals_to_create:
            for code in ExciseCode.create(code_vals_to_create):
                codes_by_rs_id[code.rs_id] = code
            akciz_new = len(code_vals_to_create)
        _logger.info("Akciz sync: %d new, %d updated", akciz_new, akciz_updated)

        # RS.GE treats each excise code as a product: every active code becomes an Odoo product (is_excise).
        default_uom = self.env.ref('uom.product_uom_unit', raise_if_not_found=False) or UoM.search([], limit=1)
        uom_by_rs_unit_id = UoM._rs_uom_by_code()
        uom_by_name = {u.name: u for u in UoM.search([])}
        # product_id per excise code; also guards step 3, so a barcode whose NAME matches an excise TITLE
        # never creates a second product for it.
        product_by_excise_id = {p.rs_excise_id.id: p for p in self.search([('rs_excise_id', '!=', False)])}
        excise_product_vals = []
        pending_excise_ids = []
        for code in ExciseCode.search([('is_currently_active', '=', True)]):
            if code.id in product_by_excise_id:
                continue

            # Parse MEASUREMENT from the TITLE: "<name> (<code>) _ <unit> _ (<rate>)". Georgian units map via
            # GEORGIAN_TO_RS_UNIT_ID to an rs_unit_id, then to the Odoo UoM.
            parts = (code.name or '').split('_')
            uom_name = parts[1].strip() if len(parts) >= 2 else ''
            rs_unit_id = GEORGIAN_TO_RS_UNIT_ID.get(uom_name)
            uom = uom_by_rs_unit_id.get(rs_unit_id) if rs_unit_id else None
            if not uom:
                uom = default_uom
                if uom_name:
                    _logger.warning("Excise code %s: MEASUREMENT '%s' not in GEORGIAN_TO_RS_UNIT_ID — "
                                    "defaulting to %s.", code.rs_id, uom_name, default_uom.name)

            excise_product_vals.append({
                'name': code.name,
                'is_excise': True,
                'rs_excise_id': code.id,
                'uom_id': uom.id,
                'is_storable': True,
                'is_rs_product': True,
            })
            pending_excise_ids.append(code.id)
        if excise_product_vals:
            for code_id, product in zip(pending_excise_ids, self.create(excise_product_vals)):
                product_by_excise_id[code_id] = product
        excise_products_new = len(excise_product_vals)
        _logger.info("Excise products created from codes: %d", excise_products_new)

        products = service.get_bar_codes()
        created_count = 0
        updated_count = 0
        product_by_barcode = {p.barcode: p for p in self.search([('barcode', '!=', False)])}
        # setdefault: two codes can share a TITLE; the first seen wins (as search(limit=1) did).
        excise_by_name = {}
        for excise_code in codes_by_rs_id.values():
            excise_by_name.setdefault(excise_code.name, excise_code)
        new_product_vals = []
        queued_barcodes = set()
        queued_excise_ids = set()
        for product in products:
            code = product.get('CODE', '')
            if not code:
                continue

            # Excise match once for NEW and EXISTING paths: get_bar_codes has no A_ID, so match the returned NAME
            # against rs.excise.code TITLEs (excise products are pushed with goods_name = TITLE).
            name = product.get('NAME', code)
            excise_match = excise_by_name.get(name)

            a_id_str = (product.get('A_ID') or '').strip()
            try:
                a_id = int(a_id_str) if a_id_str else 0
            except (ValueError, TypeError):
                a_id = 0
            if a_id and not excise_match:
                excise_match = codes_by_rs_id.get(a_id)
                if not excise_match:
                    _logger.warning("Product import: barcode %s has A_ID=%s but no matching "
                                    "rs.excise.code locally — leaving non-excise.", code, a_id)

            existing = product_by_barcode.get(code)
            if existing:
                # UPDATE path: set is_excise / rs_excise_id only on a match not tagged yet; never untag (may be manual).
                update_vals = {}
                if excise_match and existing.rs_excise_id.id != excise_match.id:
                    update_vals.update({'is_excise': True, 'rs_excise_id': excise_match.id})
                # RS says this barcode is registered: flag the product so it stops offering 'Send to RS'.
                if not existing.is_rs_product:
                    update_vals['is_rs_product'] = True
                if update_vals:
                    existing.write(update_vals)
                    updated_count += 1
                continue
            if code in queued_barcodes:
                continue

            vals = {
                'name': name,
                'barcode': code,
                'is_rs_product': True,
                'is_storable': True,
            }

            # Match the unit by the rs_unit_id bridge (RS sends UNIT_ID as a string: cast), else by UNIT_TXT;
            # if nothing matches keep the default and log it.
            unit_id = (product.get('UNIT_ID') or '').strip()
            unit_txt = (product.get('UNIT_TXT') or '').strip()
            uom = None
            if unit_id:
                try:
                    uom = uom_by_rs_unit_id.get(int(unit_id))
                except (ValueError, TypeError):
                    uom = None
            if not uom and unit_txt:
                uom = uom_by_name.get(unit_txt)
            if uom:
                vals['uom_id'] = uom.id
            elif unit_id or unit_txt:
                _logger.warning("Product import: barcode %s has RS unit id=%s txt=%s with no "
                                "matching Odoo UoM (rs_unit_id) — defaulting to Units.",
                                code, unit_id or '-', unit_txt or '-')

            if excise_match:
                # Step 2 may already have created a product for this excise code: tag it, do not create a second one.
                twin = product_by_excise_id.get(excise_match.id)
                if twin:
                    if not twin.barcode:
                        twin.barcode = code
                        product_by_barcode[code] = twin
                        updated_count += 1
                    else:
                        _logger.info("Product import: excise code %s already has product %s "
                                     "(barcode %s); skipping duplicate for barcode %s.",
                                     excise_match.rs_id, twin.display_name, twin.barcode, code)
                    continue
                if excise_match.id in queued_excise_ids:
                    _logger.info("Product import: excise code %s already queued this run; "
                                 "skipping duplicate for barcode %s.", excise_match.rs_id, code)
                    continue
                vals['is_excise'] = True
                vals['rs_excise_id'] = excise_match.id
                queued_excise_ids.add(excise_match.id)

            new_product_vals.append(vals)
            queued_barcodes.add(code)

        if new_product_vals:
            self.create(new_product_vals)
            created_count = len(new_product_vals)

        _logger.info("Product sync: %d created, %d existing flagged as excise",
                     created_count, updated_count)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Complete'),
                'message': _('%s new barcoded products imported, %s existing products flagged as excise. '
                             'Excise codes: %s new, %s updated. '
                             '%s new excise products created from codes.')
                             % (created_count, updated_count, akciz_new, akciz_updated, excise_products_new),
                'type': 'success',
                'sticky': False,
            }
        }


class RsExciseProduct(models.Model):
    _name = 'rs.excise.code'
    _description = 'RS.GE Excise (Akciz) Code'
    _order = 'rs_id'

    rs_id = fields.Integer(string='RS Code ID', required=True, index=True,
                           help='Numeric A_ID from RS.GE — used in waybill goods and save_bar_code.')
    name = fields.Char(string='Product Description', required=True)
    active_from = fields.Date(string='Active From', required=True)
    active_until = fields.Date(string='Active Until', help='Leave empty if the code has no end date.')
    is_currently_active = fields.Boolean(string='Currently Active', compute='_compute_is_currently_active',
                                         search='_search_is_currently_active')

    _rs_id_unique = models.Constraint(
        'UNIQUE(rs_id)',
        'Akciz code with this RS ID already exists.',
    )


    @api.depends('rs_id')
    def _compute_display_name(self):
        # RS.GE convention: excise codes show as "ა207" (ა = akciz + numeric ID); the TITLE is a separate column.
        for rec in self:
            rec.display_name = f"ა{rec.rs_id}" if rec.rs_id else ''


    @api.depends('active_from', 'active_until')
    def _compute_is_currently_active(self):
        today = fields.Date.context_today(self)
        for rec in self:
            ok_from = rec.active_from and rec.active_from <= today
            ok_until = not rec.active_until or rec.active_until >= today
            rec.is_currently_active = bool(ok_from and ok_until)


    def _search_is_currently_active(self, operator, value):
        """Same rule as the compute, as a domain: active_from has arrived AND active_until hasn't passed
        (empty active_until = no expiry)."""
        if operator not in ('=', '!='):
            raise UserError(_("Unsupported operator '%s' for Currently Active.") % operator)
        today = fields.Date.context_today(self)
        live = ['&', ('active_from', '<=', today), '|', ('active_until', '=', False), ('active_until', '>=', today)]
        return live if (operator == '=') == bool(value) else ['!'] + live


class UomUom(models.Model):
    _inherit = 'uom.uom'

    # Not unique: RS.GE declares the kind of unit, not its size, so Pack of 6 and Pack of 24 both carry 14 (შეკვრა).
    rs_unit_id = fields.Integer(string='RS Unit ID', index=True,
                                help="RS.GE unit code sent with this unit (14 = შეკვრა for any package, 99 = Other). "
                                     "Several units may share a code. Empty: sent as 99 with the unit's name.")


    def _rs_code(self):
        """ The RS.GE UNIT_ID this unit is sent as: its code, else 99 (Other). """
        self.ensure_one()
        return self.rs_unit_id or 99


    def _rs_text(self):
        """ The RS.GE UNIT_TXT: RS.GE's own name for the code; for 99 the unit's name. """
        self.ensure_one()
        return RS_UNIT_NAMES.get(self._rs_code()) or self.name


    @api.model
    def _rs_uom_by_code(self):
        """ {rs_unit_id: uom} picking one unit per shared code: the oldest, i.e. the one this module or Odoo shipped
            (Units for 1, Bundle for 14) before any user-made package. """
        by_code = {}
        for uom in self.search([('rs_unit_id', '!=', False)], order='id'):
            by_code.setdefault(uom.rs_unit_id, uom)
        return by_code
