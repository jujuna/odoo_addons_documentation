from odoo import models, fields, api, _
from odoo.exceptions import UserError
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)

RS_VAT_TYPE_BY_TAX_CATEGORY = {'S': '0', 'Z': '1', 'G': '1', 'K': '1', 'E': '2', 'O': '2'}


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    rs_create_waybill = fields.Boolean(
        string='Create RS Waybill',
        default=False,
        help='When enabled, pickings of this type auto-create an RS waybill '
             'on action_assign (reservation).',
    )
    rs_waybill_type = fields.Selection(
        [('1', 'Internal Transport'),
         ('2', 'With Transport'),
         ('3', 'Without Transport'),
         ('4', 'Distribution'),
         ('5', 'Return'),
         ('6', 'Sub Waybill')],
        string='RS Waybill Type',
        default='2',
    )


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    waybill_id = fields.Many2one('rs.waybill', string='Waybill', copy=False, index='btree_not_null')
    # Every transfer that moves a distribution's goods onto or off its truck (the
    # warehouse's Distribution location) names that distribution, so what is still on
    # the truck is always known (rs.waybill._rs_on_truck). Copied, so a backorder or a
    # return of a sub's delivery still counts for its truck.
    rs_distribution_id = fields.Many2one('rs.waybill', string='Distribution Waybill',
                                         readonly=True, index='btree_not_null')
    waybill_count = fields.Integer(
        string='Waybill Count',
        compute='_compute_waybill_count',
    )
    rs_waybill_state = fields.Selection(related='waybill_id.state', string='Waybill State')
    rs_waybill_locked = fields.Boolean(
        string='RS Waybill Locked',
        compute='_compute_rs_waybill_locked',
        help='True when the linked waybill is on RS.GE (rs_internal_id set). Products, '
             'quantities and partner are then read-only here — edit via the waybill.',
    )
    rs_progress = fields.Selection([
        ('draft', 'Draft'),
        ('waiting', 'Waiting'),
        ('reserved', 'Reserved'),
        ('pending', 'Pending'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ], string='RS Progress', compute='_compute_rs_progress', store=True,
        help='Parallel RS waybill progress, derived from the delivery state and '
             'the linked waybill state. Does not affect the native picking status.')
    # Form banner: seller deliveries point to "Edit Waybill"; for buyer receipts the vendor owns the waybill
    # and changes arrive via RS sync (Receive/Reject).
    rs_waybill_direction = fields.Selection(
        related='waybill_id.waybill_direction', string='RS Waybill Direction')

    @api.depends('waybill_id')
    def _compute_waybill_count(self):
        for picking in self:
            picking.waybill_count = 1 if picking.waybill_id else 0

    @api.depends('waybill_id', 'waybill_id.rs_internal_id')
    def _compute_rs_waybill_locked(self):
        for picking in self:
            picking.rs_waybill_locked = bool(picking.waybill_id and picking.waybill_id.rs_internal_id)

    @api.depends('state', 'waybill_id', 'waybill_id.state')
    def _compute_rs_progress(self):
        """ Read-only mirror of delivery + waybill progress; never writes the picking state. """
        for picking in self:
            wb = picking.waybill_id
            if picking.state == 'cancel':
                picking.rs_progress = 'cancelled'
            elif (wb and wb.state == 'completed') or picking.state == 'done':
                picking.rs_progress = 'delivered'
            elif wb and wb.state == 'active':
                picking.rs_progress = 'pending'
            elif picking.state == 'assigned':
                picking.rs_progress = 'reserved'
            elif picking.state in ('waiting', 'confirmed'):
                picking.rs_progress = 'waiting'
            else:
                picking.rs_progress = 'draft'

    def action_view_waybill(self):
        self.ensure_one()
        if not self.waybill_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Waybill'),
            'res_model': 'rs.waybill',
            'view_mode': 'form',
            'res_id': self.waybill_id.id,
            'target': 'current',
        }

    def action_assign(self):
        """ Manual 'Check Availability' button — also catches automatic reservation. """
        result = super().action_assign()
        for picking in self:
            picking._rs_try_create_waybill()
        return result


    def action_cancel(self):
        """ Cancel the linked seller waybill before super(): RS draft deleted, local draft unlinked, active cancelled
            on RS, cancelled skipped; completed not handled. Batch: a picking failing on RS is excluded from super()
            (RS cancels commit); one record is all-or-nothing. """
        vendor_waybill_pickings = self.filtered(
            lambda p: p.waybill_id and p.waybill_id.waybill_direction == 'buyer'
            and p.waybill_id.state != 'cancelled')
        targets = self.filtered('waybill_id') - vendor_waybill_pickings
        # SO cancel is all or nothing: an RS.GE error on one delivery stops it; Cancel again retries only the rest.
        isolate = len(targets) > 1 and not self.env.context.get('rs_order_cancel')
        blocked = self.browse()
        # A draft waybill disappears with the cancel and has no follow-up of its own,
        # so its order is reduced here; an active one is reduced by its waybill cancel.
        draft_owed = {picking: picking._rs_open_sale_qty() for picking in targets
                      if picking.waybill_id.state == 'draft'}
        for picking in targets:
            waybill = picking.waybill_id
            if waybill.state == 'cancelled':
                continue
            try:
                if waybill.state == 'draft':
                    if waybill.rs_internal_id:
                        waybill.action_delete_waybill()
                    else:
                        waybill.unlink()
                elif waybill.state == 'active':
                    waybill.action_refuse_waybill()
            except Exception as e:
                if not isolate:
                    raise
                _logger.warning("Cancel cascade failed for picking %s (waybill %s): %s",
                                picking.name, waybill.display_name, e)
                blocked |= picking
                picking.message_post(body=Markup(_(
                    "This transfer was NOT cancelled: its waybill <b>%(waybill)s</b> could not be "
                    "cancelled on RS.GE (%(error)s). The other transfers in this batch were "
                    "processed. Fix the cause and cancel this one again."
                )) % {'waybill': waybill.display_name, 'error': e})
                if waybill.exists():
                    waybill.rs_post_commit_error = _("Cancel failed on RS.GE: %s. Fix the cause and click "
                                                    "Cancel on the waybill again.") % e
        result = super(StockPicking, self - blocked).action_cancel()
        for picking in vendor_waybill_pickings.filtered(lambda p: p.state == 'cancel'):
            picking.waybill_id.message_post(body=_(
                "Receipt %s was cancelled in Odoo. The vendor's waybill is still active on "
                "RS.GE: use Reject if you refuse the goods.") % picking.name)
        if not self.env.context.get('rs_order_cancel'):
            for picking, owed in draft_owed.items():
                order = picking.sale_id
                if (owed and picking not in blocked and picking.state == 'cancel'
                        and order.state == 'sale'):
                    picking._rs_reduce_sale_order(order, owed, _("its draft waybill was deleted"))
        return result


    def _rs_open_sale_qty(self, minus_picked=False):
        """ SO quantity each open move of this delivery still owes, per SO line; returns are left out.
            minus_picked: only the unpicked part, i.e. what validation without backorder leaves undelivered. """
        self.ensure_one()
        owed = {}
        if self.picking_type_code != 'outgoing':
            return owed
        for move in self.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')
                                           and m.sale_line_id and not m.origin_returned_move_id):
            sol = move.sale_line_id
            qty = move.product_uom_qty - (move.quantity if minus_picked and move.picked else 0.0)
            if move.uom_id.compare(qty, 0.0) <= 0:
                continue
            owed[sol] = owed.get(sol, 0.0) + move.uom_id._compute_quantity(qty, sol.product_uom_id)
        return owed


    def _rs_reduce_sale_order(self, order, cancelled_qty, reason, closed_short=False):
        """ SO follows this cancelled delivery: cancelled when nothing else was delivered or invoiced, else each
            line lowered by what the delivery owed (never below delivered); a locked order or over-invoiced line gets
            an activity. closed_short (no backorder): lowered, never cancelled. """
        self.ensure_one()
        user = order.user_id or self.env.user
        if order.locked:
            if closed_short:
                summary = _("Adjust the order: delivery validated without backorder")
                note = _("Delivery %(picking)s was validated without a backorder. The order "
                         "is locked, so it was not changed: unlock it and lower the "
                         "quantities that will not be delivered.") % {'picking': self.name}
            else:
                summary = _("Adjust the order: delivery cancelled")
                note = _("Delivery %(picking)s was cancelled (%(reason)s). The order is locked, "
                         "so it was not changed: unlock it and reduce or cancel it.") % {
                             'picking': self.name, 'reason': reason}
            order.activity_schedule('mail.mail_activity_data_todo', summary=summary, note=note,
                                    user_id=user.id)
            return
        other_pickings = (order.picking_ids - self).filtered(lambda p: p.state != 'cancel')
        invoices = order.invoice_ids.filtered(lambda i: i.state != 'cancel')
        delivered = any(line.qty_delivered for line in order.order_line)
        if not closed_short and not other_pickings and not invoices and not delivered:
            order.action_cancel()
            order.message_post(body=_("Cancelled because delivery %(picking)s was cancelled "
                                      "(%(reason)s).") % {'picking': self.name, 'reason': reason})
            return
        changes = []
        for sol, qty in cancelled_qty.items():
            new_qty = max(sol.product_uom_qty - qty, sol.qty_delivered)
            if sol.product_uom_id.compare(new_qty, sol.product_uom_qty):
                changes.append("%s: %s → %s" % (sol.product_id.display_name,
                                                sol.product_uom_qty, new_qty))
                sol.with_context(skip_procurement=True).product_uom_qty = new_qty
        if changes and closed_short:
            order.message_post(body=Markup(_(
                "Ordered quantities reduced because delivery %(picking)s was validated "
                "without a backorder:<br/>%(changes)s")) % {
                    'picking': self.name, 'changes': Markup('<br/>').join(changes)})
        elif changes:
            order.message_post(body=Markup(_(
                "Ordered quantities reduced because delivery %(picking)s was cancelled "
                "(%(reason)s):<br/>%(changes)s")) % {
                    'picking': self.name, 'reason': reason, 'changes': Markup('<br/>').join(changes)})
        over_invoiced = order.order_line.filtered(
            lambda l: l.product_uom_id.compare(l.qty_invoiced, l.product_uom_qty) > 0)
        if over_invoiced:
            products = ', '.join(over_invoiced.mapped('product_id.display_name'))
            if closed_short:
                summary = _("Credit note needed: delivery validated without backorder")
                note = _("Delivery %(picking)s was validated without a backorder and the order "
                         "reduced. Invoiced more than ordered on: %(products)s. Issue a credit "
                         "note.") % {'picking': self.name, 'products': products}
            else:
                summary = _("Credit note needed: delivery cancelled")
                note = _("Delivery %(picking)s was cancelled (%(reason)s) and the order reduced. "
                         "Invoiced more than ordered on: %(products)s. Issue a credit note.") % {
                             'picking': self.name, 'reason': reason, 'products': products}
            order.activity_schedule('mail.mail_activity_data_todo', summary=summary, note=note,
                                    user_id=user.id)


    def _rs_try_create_waybill(self):
        """ Create a waybill from this picking's reserved moves if eligible. """
        self.ensure_one()

        if not self.picking_type_id.rs_create_waybill:
            return
        if self.env.context.get('skip_rs_auto_create'):
            return
        if self.waybill_id:
            # Keep the draft waybill's goods mirrored so one made at partial reservation catches up; no-op once on RS.
            self._rs_sync_waybill_lines()
            return

        if self.picking_type_id.code == 'internal':
            return self._rs_create_internal_waybill()

        if self.picking_type_id.code == 'incoming':
            return self._rs_create_return_waybill()

        if not self.partner_id:
            return

        line_vals = self._rs_build_waybill_lines()
        if not line_vals:
            return

        partner = self.partner_id
        src_wh = self.location_id.warehouse_id
        waybill_vals = {
            'waybill_direction': 'seller',
            'waybill_type': self.picking_type_id.rs_waybill_type or '2',
            'picking_id': self.id,
            'sales_order_id': self.sale_id.id if self.sale_id else False,
            'buyer_id': partner.id,
            'buyer_name': partner.name or '',
            'buyer_tin': partner.vat or '',
            'source_warehouse_id': src_wh.id if src_wh else False,
            'start_address': self._rs_warehouse_address(src_wh) if src_wh else (self.company_id.street or ''),
            'end_address': partner.street or '',
            'line_ids': line_vals,
        }

        # In the delivery's company, not the switcher's: it supplies company, seller TIN/name and address defaults.
        waybill = self.env['rs.waybill'].with_company(self.company_id).with_context(
            skip_rs_auto_create=True
        ).create(waybill_vals)
        self.waybill_id = waybill.id
        return waybill

    def _rs_unit_price(self, move, unit=None):
        """ The RS.GE unit price: what the customer pays per unit (default: the move's), after the
            discount and with the VAT in it, in GEL at today's rate (the waybill's date).
            Without an order line: the product's sales price with its VAT. """
        unit = unit or move.uom_id
        sol = move.sale_line_id
        if sol:
            price = sol.product_uom_id._compute_price(sol.price_reduce_taxinc, unit)
            currency = sol.currency_id
        else:
            product = move.product_id
            taxes = product.taxes_id.filtered(lambda t: t.company_id == self.company_id)
            price = (taxes.compute_all(product.lst_price, product=product)['total_included']
                     if taxes else product.lst_price)
            price = product.uom_id._compute_price(price, unit)
            currency = self.company_id.currency_id
        return currency._convert(price, self.env.ref('base.GEL'), self.company_id,
                                 fields.Date.context_today(self))

    def _rs_waybill_unit(self, move, qty):
        """ (unit, quantity) the waybill declares qty of the move in. Odoo delivers in the product's unit (24 Units)
            even when the order sold packs: a whole number of the order line's unit is declared in it (2 x Pack of 12
            = 2 შეკვრა at the pack price), anything else (18 Units, 1.5 packs) stays in the move's unit. """
        sol = move.sale_line_id
        unit = sol.product_uom_id if sol else move.uom_id
        if unit and unit != move.uom_id:
            in_unit = move.uom_id._compute_quantity(qty, unit, round=False)
            if in_unit > 0 and unit.is_zero(in_unit - round(in_unit)):
                return unit, round(in_unit)
        return move.uom_id, qty

    def _rs_line_vals_from_move(self, move, qty, sequence):
        """ Build the rs.waybill.line value dict for a single stock move. """
        product = move.product_id
        unit, qty = self._rs_waybill_unit(move, qty)
        return {
            'sequence': sequence,
            'product_id': product.id,
            'name': move.description_picking or product.name,
            'bar_code': product.default_code or product.barcode or '',
            'uom_id': unit.id,
            'unit_name': unit._rs_text(),
            'quantity': qty,
            'unit_price': self._rs_unit_price(move, unit),
            'vat_type': self._rs_vat_type_for_move(move),
            'stock_move_id': move.id,
        }

    def _rs_vat_type_for_move(self, move):
        """ VAT_TYPE from the order line taxes' Tax Category Code (S 0, Z/G/K 1, E/O 2); a tax without a code is not VAT;
            nothing found gives '0'; mixed codes give the first of 0, 1, 2 with a warning. """
        self.ensure_one()
        line = move.sale_line_id if 'sale_line_id' in move._fields else False
        if not line and 'purchase_line_id' in move._fields:
            line = move.purchase_line_id
        taxes = line.tax_ids.flatten_taxes_hierarchy() if line else self.env['account.tax']
        types = {RS_VAT_TYPE_BY_TAX_CATEGORY[t.ubl_cii_tax_category_code]
                 for t in taxes if t.ubl_cii_tax_category_code in RS_VAT_TYPE_BY_TAX_CATEGORY}
        if len(types) > 1:
            _logger.warning(
                "Move %s carries taxes with conflicting RS VAT types %s; declaring the first. Fix the taxes on %s.",
                move.id, sorted(types), line.display_name)
        return min(types, default='0')

    def _rs_waybill_qty(self, move):
        """ Quantity of this move the waybill may declare: the reserved quantity. A backorder with nothing reserved
            uses its demand (draft only): _validate_before_save lets only 'assigned'/'done' reach RS.GE. """
        if move.quantity:
            return move.quantity
        return move.product_uom_qty if self.backorder_id else 0

    def _rs_check_waybill_qty(self):
        """ Refuse to ship a quantity the waybill does not declare: per product, waybill lines vs what this picking
            ships (picked moves, or all if none picked); stock arriving after the waybill went to RS.GE is reserved
            silently. """
        self.ensure_one()
        moves = self.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
        if any(moves.mapped('picked')):
            moves = moves.filtered('picked')
        # Per product in its own unit: one product may ship in packs on one line and in units on another.
        declared, shipping = {}, {}
        for line in self.waybill_id.line_ids.filtered('product_id'):
            declared[line.product_id] = declared.get(line.product_id, 0.0) + line._rs_base_qty()
        for move in moves:
            shipping[move.product_id] = shipping.get(move.product_id, 0.0) + move.uom_id._compute_quantity(
                move.quantity, move.product_id.uom_id, round=False)
        diffs = [
            _("%(product)s: delivery ships %(shipping)s, waybill declares %(declared)s") % {
                'product': product.display_name,
                'shipping': shipping.get(product, 0.0),
                'declared': declared.get(product, 0.0)}
            for product in declared.keys() | shipping.keys()
            if product.uom_id.compare(declared.get(product, 0.0), shipping.get(product, 0.0))
        ]
        if diffs:
            raise UserError(_("Delivery '%(name)s' does not match waybill %(waybill)s:\n%(diffs)s\n"
                              "Use Adjustment on the waybill to declare what actually ships.") % {
                'name': self.name, 'waybill': self.waybill_id.display_name, 'diffs': '\n'.join(diffs)})


    def _rs_build_waybill_lines(self):
        """ Build line vals from moves with reserved quantity > 0. """
        self.ensure_one()
        line_vals = []
        seq = 10
        for move in self.move_ids:
            qty = self._rs_waybill_qty(move)
            if not qty or qty <= 0:
                continue
            line_vals.append((0, 0, self._rs_line_vals_from_move(move, qty, seq)))
            seq += 10
        return line_vals

    def _rs_sync_waybill_lines(self):
        """ Re-mirror a local-draft waybill's goods from this picking's moves: update linked lines, add new, drop gone
            ones; manual lines (no stock_move_id) stay. No-op once the waybill has rs_internal_id or is not draft. """
        self.ensure_one()
        waybill = self.waybill_id
        if not waybill or waybill.rs_internal_id or (waybill.state and waybill.state != 'draft'):
            return
        self._rs_mirror_buyer_to_waybill()
        existing_by_move = {l.stock_move_id.id: l for l in waybill.line_ids if l.stock_move_id}
        seq = max(waybill.line_ids.mapped('sequence') or [0])
        commands = []
        handled = set()
        for move in self.move_ids:
            handled.add(move.id)
            # Same rule as _rs_build_waybill_lines; walks a backorder's draft down from its demand as stock reserves.
            qty = self._rs_waybill_qty(move)
            line = existing_by_move.get(move.id)
            if not qty or qty <= 0:
                if line:
                    commands.append((2, line.id))
                continue
            if line:
                unit, unit_qty = self._rs_waybill_unit(move, qty)
                if line.uom_id != unit:
                    # 18 -> 24 Units reserved: now 2 whole packs, declared (and priced) per pack.
                    commands.append((1, line.id, {'quantity': unit_qty, 'uom_id': unit.id,
                                                  'unit_name': unit._rs_text(),
                                                  'unit_price': self._rs_unit_price(move, unit)}))
                elif line.quantity != unit_qty:
                    commands.append((1, line.id, {'quantity': unit_qty}))
            else:
                seq += 10
                commands.append((0, 0, self._rs_line_vals_from_move(move, qty, seq)))
        for move_id, line in existing_by_move.items():
            if move_id not in handled:
                commands.append((2, line.id))
        if commands:
            waybill.line_ids = commands


    def _rs_create_internal_waybill(self):
        """ Internal transport waybill (RS type 1) from an internal transfer; warehouses come from the move locations.
            Skips: sale-driven pickings, same warehouse on both sides, a side without a warehouse (transit). """
        self.ensure_one()
        if self.sale_id:
            return

        src_wh = self.location_id.warehouse_id
        dst_wh = self.location_dest_id.warehouse_id
        if not src_wh or not dst_wh:
            return
        if src_wh == dst_wh:
            return

        line_vals = self._rs_build_waybill_lines()
        if not line_vals:
            return

        company = self.company_id
        waybill_vals = {
            'waybill_direction': 'seller',
            'waybill_type': '1',
            'picking_id': self.id,
            'source_warehouse_id': src_wh.id,
            'dest_warehouse_id': dst_wh.id,
            'start_address': self._rs_warehouse_address(src_wh),
            'end_address': self._rs_warehouse_address(dst_wh),
            # Internal: company is buyer too; set name/TIN, not buyer_id (validation forbids the company's own partner).
            'buyer_name': company.name,
            'buyer_tin': company.vat or '',
            'line_ids': line_vals,
        }

        # In the delivery's company, not the switcher's: it supplies company, seller TIN/name and address defaults.
        waybill = self.env['rs.waybill'].with_company(self.company_id).with_context(
            skip_rs_auto_create=True
        ).create(waybill_vals)
        self.waybill_id = waybill.id
        return waybill


    def _rs_warehouse_address(self, warehouse):
        """ Warehouse address: street + city, falling back to the warehouse company's if the partner has neither. """
        partner = warehouse.partner_id
        parts = [partner.street, partner.city] if partner else []
        address = ', '.join(p for p in parts if p)
        if not address:
            company = warehouse.company_id or self.env.company
            address = ', '.join(p for p in [company.street, company.city] if p)
        return address


    def _rs_mirror_buyer_to_waybill(self):
        """ While the linked waybill is a local draft (no rs_internal_id), mirror the picking's partner onto its
            buyer. No-op once on RS, for internal transfers (no partner) and when already matching. """
        self.ensure_one()
        waybill = self.waybill_id
        if not waybill or waybill.rs_internal_id or (waybill.state and waybill.state != 'draft'):
            return
        partner = self.partner_id
        if not partner or waybill.buyer_id == partner:
            return
        waybill.write({
            'buyer_id': partner.id,
            'buyer_name': partner.name or '',
            'buyer_tin': partner.vat or '',
            'end_address': partner.street or '',
        })

    def write(self, vals):
        """ picking_type_id change re-derives the linked waybill: draft or unsaved is synced locally (pushed to RS
            if it has an rs_internal_id); active/completed/cancelled/sent-to-transporter is left alone. Raises when the
            new type is an internal RS-waybill type and the picking came from a sale. """
        if 'picking_type_id' in vals and not self.env.context.get('rs_from_waybill'):
            fixed = self.filtered(lambda p: p.waybill_id.state in ('active', 'completed'))
            if fixed:
                # RS.GE does not change the type of an active waybill, so neither does its delivery.
                raise UserError(_(
                    "The waybill of %s is already active on RS.GE, so the Operation Type "
                    "cannot change any more. Cancel the waybill first if it must.")
                    % ', '.join(fixed.mapped('name')))
        if 'picking_type_id' in vals:
            new_type = self.env['stock.picking.type'].browse(vals['picking_type_id'])
            if new_type.rs_create_waybill and new_type.code == 'internal':
                for picking in self:
                    if picking.sale_id:
                        raise UserError(_(
                            "Internal transport waybills cannot be linked to a Sales Order.\n"
                            "Cancel the sales order and create the internal transfer "
                            "manually from Inventory → Transfers."
                        ))
        result = super().write(vals)
        if 'picking_type_id' in vals and not self.env.context.get('rs_from_waybill'):
            for picking in self:
                picking._rs_resync_waybill_from_picking_type()
        if 'partner_id' in vals:
            for picking in self:
                picking._rs_mirror_buyer_to_waybill()
        if 'move_ids' in vals or 'move_line_ids' in vals:
            for picking in self.filtered('waybill_id'):
                picking._rs_sync_waybill_lines()
        return result


    def _rs_create_return_waybill(self):
        """ Return waybill (RS type 5) from a customer-return receipt: only for a return of OUR delivery (return_id);
            any other receipt is the vendor's to document (a type 5 would name the vendor as buyer). """
        self.ensure_one()
        if not self.return_id or self.return_id.picking_type_code != 'outgoing':
            return
        if not self.partner_id:
            return
        self._rs_check_return_quantities()

        line_vals = self._rs_build_waybill_lines()
        if not line_vals:
            return
        partner = self.partner_id
        destination_wh = self.location_dest_id.warehouse_id
        waybill_vals = {
            'waybill_direction': 'seller',
            'waybill_type': '5',
            'picking_id': self.id,
            'buyer_id': partner.id,
            'buyer_name': partner.name,
            'buyer_tin': partner.vat or '',
            'start_address': partner.street or '',
            'end_address': self._rs_warehouse_address(destination_wh) if destination_wh else (self.company_id.street or ''),
            'line_ids': line_vals,
        }
        waybill = self.env['rs.waybill'].with_company(self.company_id).with_context(
            skip_rs_auto_create=True).create(waybill_vals)
        self.waybill_id = waybill.id
        return waybill


    def _rs_resync_waybill_from_picking_type(self):
        """ Re-derive the linked waybill when picking_type_id changes; only while it is draft and not transporter-bound.
            Never calls RS.GE: a draft already on RS gets rs_needs_resave and goes there on the waybill's Save. """
        self.ensure_one()
        waybill = self.waybill_id
        if not waybill:
            return
        if (waybill.state and waybill.state != 'draft') or waybill.waybill_status == '8':
            return

        if self.picking_type_id.code == 'internal':
            src_wh = self.location_id.warehouse_id
            dst_wh = self.location_dest_id.warehouse_id
            if not src_wh or not dst_wh or src_wh == dst_wh:
                _logger.warning(
                    "Cannot resync waybill %s to internal: missing or identical warehouses",
                    waybill.id,
                )
                return
            company = self.company_id
            waybill.with_context(rs_from_picking=True).write({
                'waybill_type': '1',
                'source_warehouse_id': src_wh.id,
                'dest_warehouse_id': dst_wh.id,
                'start_address': self._rs_warehouse_address(src_wh),
                'end_address': self._rs_warehouse_address(dst_wh),
                'buyer_id': False,
                'buyer_name': company.name,
                'buyer_tin': company.vat or '',
                'sales_order_id': False,
            })
        else:
            if not self.partner_id:
                _logger.warning(
                    "Cannot resync waybill %s to external: picking has no partner",
                    waybill.id,
                )
                return
            new_type = self.picking_type_id.rs_waybill_type or '2'
            partner = self.partner_id
            vals = {}
            if waybill.waybill_type == '1':
                # From internal transport the addresses meant two warehouses: set again (start = shipping warehouse).
                src_wh = self.location_id.warehouse_id
                vals.update({
                    'start_address': (self._rs_warehouse_address(src_wh) if src_wh
                                      else self.company_id.street or ''),
                    'end_address': partner.street or '',
                })
            # Between delivery types the addresses stay: the user may have corrected them.
            waybill.with_context(rs_from_picking=True).write(dict(vals, **{
                'waybill_type': new_type,
                'source_warehouse_id': False,
                'dest_warehouse_id': False,
                'buyer_id': partner.id,
                'buyer_name': partner.name or '',
                'buyer_tin': partner.vat or '',
                'sales_order_id': self.sale_id.id if self.sale_id else False,
            }))

        # Already saved on RS.GE as a draft: no RS call from the delivery save (it would skip the waybill's checks
        # and block when RS is slow); the waybill is flagged and its own Save sends it.
        if waybill.rs_internal_id:
            waybill.rs_needs_resave = True
            waybill.message_post(body=_(
                "The delivery's operation type changed, so the waybill was updated in Odoo. "
                "Click Save on the waybill to send it to RS.GE."))


    def _create_backorder(self, backorder_moves=None, from_manual_backorder=False):
        """ Create the backorder's waybill at once so the user can prepare extra fields while waiting for stock;
            Save/Activate stay blocked until Ready. Forwards both arguments so the Split flow keeps working. """
        backorders = super()._create_backorder(backorder_moves=backorder_moves,
                                               from_manual_backorder=from_manual_backorder)
        for backorder in backorders:
            backorder._rs_try_create_waybill()
        # Moves that left for the backorder must also leave the original's draft waybill.
        for picking in self.filtered('waybill_id'):
            picking._rs_sync_waybill_lines()
        return backorders


    def _action_done(self):
        """ Cascade validation to the linked waybill: refuse if Draft or Cancelled; Active: close it on RS;
            completed or none: untouched. Validated without a backorder: the order is lowered as for a cancelled
            backorder (its lines are locked by the waybill). """
        # Seller direction only: closing a vendor's waybill is rejected by RS ("belongs to another taxpayer");
        # the buyer lifecycle runs via Receive/Reject and the sync.
        for picking in self.filtered(lambda p: p.waybill_id and p.waybill_id.waybill_direction == 'seller'):
            waybill = picking.waybill_id
            if not waybill.rs_internal_id:
                raise UserError(_("Cannot validate delivery '%(name)s': its waybill is not saved on RS.GE yet. "
                                  "Fill in the waybill, save it to RS.GE and activate it, then validate the delivery.")
                                  % {'name': picking.name})
            if waybill.state == 'draft':
                raise UserError(_("Cannot validate delivery '%(name)s': linked waybill is still "
                                  "Draft. Open the waybill and activate it on RS.GE "
                                  "then validate the delivery.") % {'name': picking.name})
            if waybill.state == 'cancelled':
                raise UserError(_("Cannot validate delivery '%(name)s': linked waybill was "
                                  "cancelled on RS.GE. Create a new waybill or restore on RS.") % {'name': picking.name})
            picking._rs_check_waybill_qty()
        self._rs_check_return_quantities()
        closed_short = {}
        if self.env.context.get('cancel_backorder') and not self.env.context.get('rs_order_cancel'):
            for picking in self.filtered(lambda p: p.waybill_id.waybill_direction == 'seller'
                                         and p.sale_id.state == 'sale'):
                owed = picking._rs_open_sale_qty(minus_picked=True)
                if owed:
                    closed_short[picking] = owed
        result = super()._action_done()
        # Batch: each close is isolated (a failure goes to the waybill banner + picking chatter), else an unguarded one
        # leaves later pickings done but Active on RS. A single record raises before the commit and rolls back.
        targets = self.filtered(lambda p: p.waybill_id and p.waybill_id.waybill_direction == 'seller')
        isolate = len(targets) > 1
        for picking in targets:
            waybill = picking.waybill_id
            if waybill.state == 'active':
                if not isolate:
                    waybill.action_close_waybill()
                    continue
                try:
                    waybill.action_close_waybill()
                except Exception as e:
                    _logger.warning("Close cascade failed for picking %s (waybill %s): %s",
                                    picking.name, waybill.display_name, e)
                    waybill.rs_post_commit_error = _("Complete failed on RS.GE: %s. Fix the cause and "
                                                    "click Complete on the waybill again.") % e
                    picking.message_post(body=Markup(_(
                        "This transfer is validated, but its waybill <b>%(waybill)s</b> could NOT be "
                        "closed on RS.GE (%(error)s). RS still shows it as Active — open the waybill "
                        "and click Complete."
                    )) % {'waybill': waybill.display_name, 'error': e})
            elif waybill.state == 'completed':
                picking.message_post(body=Markup(_("Note: linked waybill <b>%(waybill)s</b> was already Completed on "
                                            "RS.GE before this delivery was validated. No RS action taken."
                                            )) % {'waybill': waybill.display_name})
        for picking in self.filtered(lambda p: p.state == 'done' and p.return_id.picking_type_code == 'outgoing'):
            picking._rs_ask_order_after_return()
        for picking, owed in closed_short.items():
            if picking.state == 'done':
                picking._rs_reduce_sale_order(picking.sale_id, owed, False, closed_short=True)
        return result


    def _rs_check_return_quantities(self):
        """ A return of our delivery can bring back at most what each move shipped minus earlier returns (open or done);
            core does not check, so a second return would count the goods twice. """
        for picking in self.filtered(lambda p: p.return_id.picking_type_code == 'outgoing'):
            for move in picking.move_ids.filtered(lambda m: m.state != 'cancel' and m.origin_returned_move_id):
                origin = move.origin_returned_move_id
                if origin.state != 'done':
                    continue
                left = origin._rs_returnable_qty(exclude=move)
                this = move.uom_id._compute_quantity(max(move.product_uom_qty, move.quantity), origin.uom_id)
                if origin.uom_id.compare(this, left) > 0:
                    raise UserError(_(
                        "%(picking)s shipped %(shipped)s %(unit)s of %(product)s and %(returned)s "
                        "already came back, so at most %(left)s can be returned, not %(qty)s.") % {
                            'picking': origin.picking_id.name, 'shipped': origin.quantity,
                            'unit': origin.uom_id.name, 'product': origin.product_id.display_name,
                            'returned': origin.quantity - left, 'left': left, 'qty': this})


    def _rs_ask_order_after_return(self):
        """ Validated return of a sales delivery with a return waybill (not an Adjustment): asks deliver later or reduce
            the order on the waybill (banner and popup); without one, the salesperson gets an activity. """
        self.ensure_one()
        entries = []
        for move in self.move_ids.filtered(lambda m: m.state == 'done' and m.sale_line_id):
            sol = move.sale_line_id
            unit = move.product_id.uom_id
            back = move.uom_id._compute_quantity(move.quantity, unit)
            open_qty = sol.product_uom_id._compute_quantity(sol.product_uom_qty - sol.qty_delivered, unit)
            qty = min(back, open_qty)
            if unit.compare(qty, 0) > 0:
                entries.append({'product_id': move.product_id.id, 'qty': qty,
                                'sale_line_id': sol.id, 'chunks': [], 'returned': True})
        if not entries:
            return
        waybill = self.waybill_id
        if waybill:
            waybill._rs_add_pending_corrections(entries)
            waybill.message_post(body=Markup(_(
                "Return %s is done. Click <b>Reconcile Delivery</b> to say whether the customer "
                "still wants these goods.")) % self.name)
            return
        order = self.env['sale.order.line'].browse([e['sale_line_id'] for e in entries]).order_id
        for so in order:
            so.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_("Goods returned: deliver again or reduce the order"),
                note=_("Return %s is done. Deliver the goods again (Exchange on the return) or "
                       "lower the ordered quantities.") % self.name,
                user_id=(so.user_id or self.env.user).id)


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _rs_returnable_qty(self, exclude=None):
        """ What this done move can still give back, in its unit: shipped minus every non-cancelled return of it
            (done by quantity, open by demand). `exclude` leaves out one return (the one being checked). """
        self.ensure_one()
        returns = self.returned_move_ids.filtered(lambda m: m.state != 'cancel')
        if exclude:
            returns -= exclude
        returned = sum(
            m.uom_id._compute_quantity(m.quantity if m.state == 'done' else max(m.product_uom_qty, m.quantity),
                                       self.uom_id)
            for m in returns)
        return max(self.quantity - returned, 0.0)

    def _action_assign(self, force_qty=False):
        """ Create the waybill after Odoo reserves stock: procurement calls this method, not action_assign, so the
            automatic reservation after SO confirm is caught here. """
        result = super()._action_assign(force_qty=force_qty)
        pickings = self.mapped('picking_id').filtered(
            lambda p: p.state in ('assigned', 'partially_available')
        )
        for picking in pickings:
            picking._rs_try_create_waybill()
        return result

    def _action_cancel(self):
        """ A move cancelled without re-reservation (e.g. SO line set to 0) must leave the draft waybill too. """
        result = super()._action_cancel()
        for picking in self.picking_id.filtered('waybill_id'):
            waybill = picking.waybill_id
            if waybill.state != 'draft' or any(m.state != 'cancel' for m in picking.move_ids):
                picking._rs_sync_waybill_lines()
            elif not waybill.rs_internal_id:
                waybill.unlink()
            else:
                # As Cancel on the delivery does (StockPicking.action_cancel): the draft goes from RS.GE too. An RS.GE
                # error stops the change, which can be made again, instead of leaving a draft nobody can delete.
                waybill.action_delete_waybill()
        return result

    def unlink(self):
        """ A deleted move takes its line off a local draft waybill; otherwise the link
            is nulled and the line stays behind as if added by hand. """
        self.env['rs.waybill.line'].search([
            ('stock_move_id', 'in', self.ids),
            ('rs_waybill_id.state', '=', 'draft'),
            ('rs_waybill_id.rs_internal_id', '=', False),
        ]).unlink()
        return super().unlink()
