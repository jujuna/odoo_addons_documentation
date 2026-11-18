from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .rs_waybill_soap_service import TBILISI_TZ, UTC_TZ
from markupsafe import Markup
import logging
import json


_logger = logging.getLogger(__name__)


WAYBILL_TYPE = [('1', 'Internal Transport'), ('2', 'With Transport'),('3', 'Without Transport'), ('4', 'Distribution'),
                ('5', 'Return'), ('6', 'Sub Waybill'), ]

TRANSPORT_TYPE = [('1', 'Auto'), ('2', 'Railway'), ('3', 'Air'),('4', 'Other'), ('6', 'Auto-Foreign country'),
                  ('7', 'Carrier'), ('8', 'Moped/Motorcycle'),]

WAYBILL_STATUS = [('0', 'Saved'), ('1', 'Active'),('2', 'Completed'), ('8', 'Sent To Transporter'),
                  ('-1', 'Deleted'), ('-2', 'Cancelled'),]

STATE = [('draft', 'Draft'), ('active', 'Active'),('completed', 'Completed'), ('cancelled', 'Cancelled'),]


class RsWaybill(models.Model):
    _name = 'rs.waybill'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Rs Waybill'
    _order = 'create_date desc, id desc'
    _create_date_id_idx = models.Index("(create_date desc, id desc)")
    _check_company_auto = True


    waybill_direction = fields.Selection([('seller', 'Seller'),('buyer', 'Buyer'),('transporter', 'Transporter'),],
                                         string='Direction', default='seller')
    waybill_type = fields.Selection(WAYBILL_TYPE)
    transport_type = fields.Selection(TRANSPORT_TYPE)
    waybill_status = fields.Selection(WAYBILL_STATUS)
    is_medicine = fields.Selection([('0', 'Normal'),('1', 'Medicine'),], default='0')
    state = fields.Selection(STATE, default='draft', tracking=True, readonly=True)
    category = fields.Selection([('0', 'Normal'),('1', 'Wood'),], default='0')

    # Menu routing uses the ACTIVE company, not waybill_direction: an intercompany waybill is "Sent" for the seller
    # and "Received" for the buyer, matched by TIN (_search_rs_menu_side); an internal (type 1) waybill matches both.
    rs_menu_side = fields.Selection([('sent', 'Sent'), ('received', 'Received'), ('none', 'None')],
                                    string='Menu Side', compute='_compute_rs_menu_side',
                                    search='_search_rs_menu_side', compute_sudo=True)

    rs_internal_id = fields.Integer(string='Internal ID', readonly=True, index=True)
    rs_waybill_number = fields.Char(string='Waybill Number', readonly=True, index=True)
    s_user_id = fields.Char(string='Sub-User ID')
    # Sub-waybill: a child carved out of a Distribution (type 4) parent;
    # parent_waybill_id drives RS PAR_ID and the remainder write-back.
    parent_waybill_id = fields.Many2one('rs.waybill', string='Parent Distribution Waybill',
                                        copy=False, readonly=True, index=True)
    sub_waybill_ids = fields.One2many('rs.waybill', 'parent_waybill_id', string='Sub-Waybills')
    # Remainder waybill: a separate distribution (type 4, no buyer) for the undistributed
    # leftover. Linked locally only (no RS PAR_ID); creates a return transfer.
    remainder_origin_id = fields.Many2one('rs.waybill', string='Remainder Of Distribution',
                                          copy=False, readonly=True, index=True)
    rs_template_id = fields.Integer(string='Template ID', copy=False,
                                    help='Remote template ID on RS.GE, if this record was created from or saved as a template.')
    is_template = fields.Boolean(string='Is Template', default=False, copy=False,
                                 help='Marks this record as a reusable template, not an actual waybill.')
    template_name = fields.Char(string='Template Name',copy=False)
    # True when the form is locked: non-draft and not opened via the Adjustment button
    # (context edit_mode). Only the fields RS lets you change live stay editable.
    is_locked = fields.Boolean(compute='_compute_is_locked')

    line_ids = fields.One2many('rs.waybill.line', 'rs_waybill_id', string='Goods')
    # One field per form tab, split by the product's Excise flag (a view domain cannot
    # hide one2many rows). RS.GE always gets line_ids, both kinds.
    goods_line_ids = fields.One2many('rs.waybill.line', 'rs_waybill_id', string='Goods (Normal)',
                                     domain=[('is_excise_line', '=', False)])
    excise_line_ids = fields.One2many('rs.waybill.line', 'rs_waybill_id', string='Goods (Excise)',
                                      domain=[('is_excise_line', '=', True)])
    full_amount = fields.Float(compute='_compute_full_amount', string='Full Amount', store=True)
    total_quantity = fields.Float(compute='_compute_total_quantity', string='Goods Quantity')
    picking_id = fields.Many2one('stock.picking', string='Stock Picking', copy=False, readonly=True, check_company=True,
                                 index='btree_not_null')
    return_origin_picking_id = fields.Many2one(
        'stock.picking', string='Original Delivery', copy=False, check_company=True,
        help="Return waybill made on RS.GE: the delivery these goods come back from. The "
             "return is built from it, so the sales order counts the goods as returned.")
    return_origin_candidate_ids = fields.Many2many(
        'stock.picking', compute='_compute_return_origin_candidate_ids')
    rs_needs_return_origin = fields.Boolean(compute='_compute_return_origin_candidate_ids')
    unresolved_count = fields.Integer(string='Goods Needing Mapping', compute='_compute_unresolved_count')

    activation_date = fields.Datetime(string='Activation Date')
    customs_status = fields.Selection([('1', 'Confirmed'),('2', 'Rejected'),])
    is_confirmed = fields.Selection([('0', 'Unconfirmed'),('1', 'Confirmed'),('2', 'Rejected'),('-1', 'Refused'),])
    buyer_status = fields.Selection([('0', 'Without Status'),('1', 'Micro Business Status'),('2', 'Small Business Status'), ])
    payer_type = fields.Selection([('1', 'Physical'),('2', 'Legal Entity'),('3', 'Individual Entrepreneur'), ])

    seller_name = fields.Char(string='Seller Name/Surname', default=lambda self: self.env.company.name, readonly=True, index='trigram')
    seller_tin = fields.Char(string='Seller Tin', default=lambda self: self.env.company.vat, readonly=True, index=True)
    start_address = fields.Char(string='Start Address', default=lambda self: self.env.company.street)
    source_warehouse_id = fields.Many2one('stock.warehouse', string='From Warehouse', domain="[('company_id', '=', company_id)]", check_company=True)
    dest_warehouse_id = fields.Many2one('stock.warehouse', string='To Warehouse', domain="[('company_id', '=', company_id)]", check_company=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, index=True,
                                 required=True)

    buyer_id = fields.Many2one('res.partner', string='Buyer', check_company=True)
    buyer_name = fields.Char(string='Buyer Name', index='trigram')
    buyer_tin = fields.Char(string='Buyer Tin', index=True)
    end_address = fields.Char(string='End Address')
    citizen = fields.Boolean(string='Citizen')
    buyer_contact_email = fields.Many2one('res.partner', string='Buyer Email Contact', domain="[('email', '!=', False)]")
    buyer_contact_email_address = fields.Char(related='buyer_contact_email.email', string='Email Address')

    other_transport = fields.Char(string='Other Transport')
    transporter_tin = fields.Char(string='Transporter Tin')
    transporter_name = fields.Char(string='Transporter Name', index='trigram')
    # True when the carrier is one of OUR companies: unlocks the driver/vehicle fields and the
    # transporter buttons even if we are also seller/buyer. Stored so menu domains can filter on it.
    is_our_carrier = fields.Boolean(compute='_compute_is_our_carrier', store=True, string='We Are The Carrier')
    driver_tin = fields.Char(string='Driver Tin', index=True)
    driver_name = fields.Char(string='Driver Name')
    driver_is_foreigner = fields.Boolean(string='Driver Citizen')
    car_number = fields.Char(string='Car Number', index=True)
    vehicle_id = fields.Many2one('fleet.vehicle', string='Car Plate', check_company=True,
                                 context={'rs_plate_only': True},
                                 help='Pick a plate from Car Plates. Fills the Car Number sent to RS.GE.')
    driver_partner_id = fields.Many2one('res.partner', string='Driver (Partner)', domain=[('rs_is_driver', '=', True)], check_company=True,
                                        context={'rs_driver_name_create': True, 'show_partner_tin': True},
                                        help='Pick a driver from registered RS drivers. Auto-fills the driver fields below.')
    trailer = fields.Char(string='Trailer')
    transport_cost = fields.Float(string='Transport Cost')
    transport_cost_payer = fields.Selection([('1', 'Buyer'),('2', 'Seller'),])
    transport_start_date = fields.Datetime(string='Transport Start Date')
    delivery_date = fields.Datetime(string='Delivery Date')

    #Extra Information
    # account_move_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False,
    #                                   help='Invoice created from this waybill')
    # is_invoiced: restore it with the invoice bridge, not before (a stored compute with no
    # method breaks any upgrade that recomputes it).
    is_buyer_reconfirm_needed = fields.Boolean(string="Buyer Re-confirmation Required", default=False, copy=False,
                                               help="True if seller edited the waybill after the buyer confirmed. "
                                                    "Cleared when the buyer re-confirms.")
    reception_info = fields.Char(string='Handed Over By')
    receiver_info = fields.Char(string='Received By')
    comment = fields.Text(string='Notes')
    # cancel_date is set only on a real cancellation (action_refuse_waybill); RS's CLOSE_DATE
    # goes to close_date, since RS sets it on a normal close too.
    cancel_date = fields.Datetime(string='Cancel Date')
    close_date = fields.Datetime(string='Close Date', readonly=True,
                                 help='RS.GE CLOSE_DATE — when the waybill was closed on RS, '
                                      'whether by delivery completion or by cancellation.')
    trans_postpone_date = fields.Datetime(string='Transport Postpone Date', default=fields.Datetime.now)
    adjustment_count = fields.Integer(string='Adjustment Count', compute='_compute_adjustment_count',)
    # Internal: JSON snapshot of the line state when the edit popup opens; diffed on activate
    # adjustment to apply side effects (return picking, new delivery, in-place picking update).
    edit_snapshot_json = fields.Text(string='Edit Snapshot (internal)', copy=False)
    # RS.GE's refusal of the last Adjustment: while set, the popup's changes exist only in Odoo (edit_snapshot_json
    # keeps what RS.GE has, syncs leave goods lines alone); cleared by a successful submit or Discard.
    rs_adjustment_error = fields.Text(string='Adjustment Not Sent', readonly=True, copy=False)
    rs_needs_resave = fields.Boolean(string='Changed in Odoo, Not on RS.GE', readonly=True, copy=False)
    # Set by auto-sync when RS reduced/removed goods on a delivered waybill: {product_id: qty}
    # awaiting the return-vs-adjust decision. Cleared by "Reconcile Delivery".
    pending_return_json = fields.Text(string='Pending Return (internal)', copy=False)
    # Buyer: signed delta {product_id: qty} from vendor edits on RS (+ receive more, - return some).
    # Applied to PO and receipt on Receive (action_confirm_waybill); cleared on Reject.
    pending_goods_json = fields.Text(string='Pending Goods Delta (internal)', copy=False)
    # Buyer: {po_line_id: qty in the PO line's unit} the vendor took off after we received, on a
    # purchaser's PO. Waits for the purchaser: Expect later (new receipt) or Reduce the order.
    pending_vendor_short_json = fields.Text(string='Vendor Lowered (internal)', copy=False)
    rs_vendor_short_summary = fields.Char(compute='_compute_rs_vendor_short_summary')
    # Set when one side went through and the other did not: a LOCAL step failed after RS accepted (drift retries)
    # or an RS step failed after Odoo committed (operator only). Last failure reason; cleared when none is outstanding.
    rs_post_commit_error = fields.Text(string='Unfinished Step', readonly=True, copy=False,
                                       help='Part of this operation did not complete, so Odoo and RS.GE '
                                            'may disagree. Local follow-up steps are retried automatically '
                                            'by the drift job; a failed RS.GE step needs you to retry it.')
    rs_drifted_checked = fields.Datetime(string='Last Drift Check', copy=False, index=True,
                                         help='When the drift cron last compared this waybill against RS. The cron '
                                              'takes the least-recently-checked first, so it sweeps fairly across all '
                                              'non-terminal waybills over time instead of re-scanning the same 200 each run.')
    # Seller cancel -> delivery + SO follow-up. 'pending' until done, so the drift job retries;
    # empty on waybills cancelled before this existed.
    rs_cancel_cascade = fields.Selection([('pending', 'Pending'), ('done', 'Done')],
                                         string='Cancel Follow-up', readonly=True, copy=False)
    # Lines as the delivery/order still show them while an RS.GE goods change could not be
    # applied (see _apply_rs_goods_diff_auto). Retried until it goes in.
    rs_goods_pending_snapshot = fields.Text(string='RS Goods Change Not Applied', readonly=True, copy=False)
    purchase_id = fields.Many2one('purchase.order', string='Purchase Order', copy=False, check_company=True,
                                  index='btree_not_null')
    # PO created from this waybill (no vendor PO matched): its ordered quantities follow the
    # waybill. A PO the purchaser made keeps its own.
    purchase_created = fields.Boolean(string='PO Created From Waybill', readonly=True, copy=False)
    purchase_pick_id = fields.Many2one(
        'purchase.order', string='Purchase Order to Link', copy=False, check_company=True,
        help="Vendor waybill that fits several open purchase orders: the one these goods "
             "belong to.")
    purchase_candidate_ids = fields.Many2many(
        'purchase.order', compute='_compute_purchase_candidate_ids')
    rs_needs_purchase_pick = fields.Boolean(compute='_compute_purchase_candidate_ids')

    sales_order_id = fields.Many2one('sale.order', string='Sales Order', check_company=True,
                                     index='btree_not_null')
    sales_order_state = fields.Selection(related='sales_order_id.state', readonly=True, string='SO Status')
    sales_order_date = fields.Datetime(related='sales_order_id.date_order', readonly=True, string='Order Date')
    sales_order_user_id = fields.Many2one(related='sales_order_id.user_id', readonly=True, string='Salesperson')
    sales_order_amount_untaxed = fields.Monetary(related='sales_order_id.amount_untaxed', readonly=True,
                                                 string='SO Untaxed', currency_field='currency_id')
    sales_order_amount_tax = fields.Monetary(related='sales_order_id.amount_tax', readonly=True, string='SO Tax',
                                             currency_field='currency_id')
    sales_order_amount_total = fields.Monetary(related='sales_order_id.amount_total', readonly=True, string='SO Total',
                                               currency_field='currency_id')
    sales_order_invoice_status = fields.Selection(related='sales_order_id.invoice_status', readonly=True,
                                                  string='Invoice Status')
    sales_order_prepayment_percent = fields.Float(related='sales_order_id.prepayment_percent', readonly=True,
                                                  string='Prepayment %')
    sales_order_delivery_status = fields.Selection(related='sales_order_id.delivery_status', readonly=True,
                                                   string='Delivery Status')
    sales_order_commitment_date = fields.Datetime(related='sales_order_id.commitment_date', readonly=True,
                                                  string='SO Delivery Date')
    sales_order_warehouse_id = fields.Many2one(related='sales_order_id.warehouse_id', readonly=True, string='Warehouse')
    sales_order_payment_term_id = fields.Many2one(related='sales_order_id.payment_term_id', readonly=True,
                                                  string='SO Payment Terms')
    sales_order_partner_id = fields.Many2one(related='sales_order_id.partner_id', readonly=True, string='Customer')
    currency_id = fields.Many2one(related='sales_order_id.currency_id', readonly=True)

    purchase_order_state = fields.Selection(related='purchase_id.state', readonly=True,
                                            string='PO Status')
    purchase_order_date = fields.Datetime(related='purchase_id.date_approve', readonly=True,
                                          string='Confirmation Date')
    purchase_order_user_id = fields.Many2one(related='purchase_id.user_id', readonly=True,
                                             string='Purchase Representative')
    purchase_order_payment_term_id = fields.Many2one(related='purchase_id.payment_term_id',
                                                     readonly=True, string='PO Payment Terms')
    purchase_order_amount_untaxed = fields.Monetary(related='purchase_id.amount_untaxed', readonly=True,
                                                    string='PO Untaxed', currency_field='purchase_currency_id')
    purchase_order_amount_tax = fields.Monetary(related='purchase_id.amount_tax', readonly=True,
                                                string='PO Tax', currency_field='purchase_currency_id')
    purchase_order_amount_total = fields.Monetary(related='purchase_id.amount_total', readonly=True,
                                                  string='PO Total', currency_field='purchase_currency_id')
    purchase_order_invoice_status = fields.Selection(related='purchase_id.invoice_status', readonly=True,
                                                     string='Billing Status')
    purchase_order_partner_id = fields.Many2one(related='purchase_id.partner_id', readonly=True, string='Vendor')
    purchase_order_deadline = fields.Datetime(related='purchase_id.date_order', readonly=True, string='Order Deadline')
    purchase_order_receipt_date = fields.Datetime(related='purchase_id.date_planned', readonly=True, string='Receipt Date')
    purchase_order_receipt_status = fields.Selection(related='purchase_id.receipt_status', readonly=True, string='Receipt Status')
    purchase_currency_id = fields.Many2one(related='purchase_id.currency_id', readonly=True, string='PO Currency')

    picking_state = fields.Selection(related='picking_id.state', readonly=True, string='Delivery State')
    picking_scheduled_date = fields.Datetime(related='picking_id.scheduled_date', readonly=True,
                                             string='Scheduled Date')
    picking_date_done = fields.Datetime(related='picking_id.date_done', readonly=True, string='Done On')
    picking_operation_type_id = fields.Many2one(related='picking_id.picking_type_id', readonly=True, string='Operation Type')
    picking_location_id = fields.Many2one(related='picking_id.location_id', readonly=True, string='Source Location')
    picking_location_dest_id = fields.Many2one(related='picking_id.location_dest_id', readonly=True, string='Destination')
    picking_backorder_id = fields.Many2one(related='picking_id.backorder_id', readonly=True, string='Backorder')


    @api.depends('transport_type', 'transporter_tin')
    def _compute_is_our_carrier(self):
        own_tins = set()
        for c in self.env['res.company'].sudo().search([]):
            tin = (c.vat or '').strip()
            if tin:
                own_tins.add(tin)
        for rec in self:
            rec.is_our_carrier = (rec.transport_type == '7' and (rec.transporter_tin or '').strip() in own_tins)


    # Depends on the TINs as well as the active company, else the label stays stale after a TIN edit.
    @api.depends('seller_tin', 'buyer_tin')
    @api.depends_context('company')
    def _compute_rs_menu_side(self):
        """ Per active-company role: seller -> 'sent', buyer -> 'received', else 'none'. Display only;
            menus filter on the search method, where internal (type-1) waybills match both. """
        tin = (self.env.company.vat or '').strip()
        for rec in self:
            if tin and (rec.seller_tin or '').strip() == tin:
                rec.rs_menu_side = 'sent'
            elif tin and (rec.buyer_tin or '').strip() == tin:
                rec.rs_menu_side = 'received'
            else:
                rec.rs_menu_side = 'none'

    def _search_rs_menu_side(self, operator, value):
        """ Menu-side selection as a TIN domain for the ACTIVE company: 'sent' = we are the seller,
            'received' = we are the buyer, 'none' = neither. Internal (type-1) waybills match both. """
        if operator not in ('=', '!='):
            raise UserError(_("Unsupported operator '%s' for Menu Side.") % operator)
        tin = (self.env.company.vat or '').strip()
        if not tin:
            positive = [('id', '=', False)]
        elif value == 'sent':
            positive = [('seller_tin', '=', tin)]
        elif value == 'received':
            positive = [('buyer_tin', '=', tin)]
        elif value == 'none':
            positive = ['&', ('seller_tin', '!=', tin), ('buyer_tin', '!=', tin)]
        else:
            positive = [('id', '=', False)]
        return positive if operator == '=' else (['!'] + positive)


    @api.depends('line_ids.unresolved', 'line_ids.uom_review')
    def _compute_unresolved_count(self):
        # A line whose unit needs review blocks Receive like an unmapped one: both are settled in Resolve Now.
        for rec in self:
            rec.unresolved_count = sum(1 for line in rec.line_ids if line.unresolved or line.uom_review)


    @api.depends('template_name', 'rs_waybill_number', 'rs_internal_id', 'is_template')
    def _compute_display_name(self):
        for rec in self:
            if rec.is_template:
                rec.display_name = rec.template_name or f"Template {rec.rs_template_id or rec.id}"
            else:
                rec.display_name = rec.rs_waybill_number or f"Waybill {rec.rs_internal_id or rec.id}"


    @api.depends('line_ids.amount', 'goods_line_ids.amount', 'excise_line_ids.amount', 'transport_cost')
    def _compute_full_amount(self):
        for record in self:
            record.full_amount = sum(record.line_ids.mapped('amount')) + (record.transport_cost or 0.0)


    @api.depends('line_ids.quantity', 'goods_line_ids.quantity', 'excise_line_ids.quantity')
    def _compute_total_quantity(self):
        for record in self:
            record.total_quantity = sum(record.line_ids.mapped('quantity'))


    @api.depends('state')
    def _compute_is_locked(self):
        edit_mode = self.env.context.get('edit_mode')
        for record in self:
            record.is_locked = bool(record.state) and record.state != 'draft' and not edit_mode


    @api.depends('rs_internal_id')
    def _compute_adjustment_count(self):
        """ Lazy, for the smart button only. It does network I/O, so it runs for a single record:
            a list or kanban would fire one SOAP call per row. Multi-record reads get 0. """
        if len(self) > 1:
            self.adjustment_count = 0
            return
        for rec in self:
            if not rec.rs_internal_id:
                rec.adjustment_count = 0
                continue
            try:
                rec.adjustment_count = len(rec._rs_service().get_adjusted_waybills(rec.rs_internal_id))
            except Exception as e:
                # Log, don't raise: a raising compute makes the form unopenable during an RS outage.
                _logger.warning("Adjustment count unavailable for waybill %s (RS id %s): %s",
                                rec.id, rec.rs_internal_id, e)
                rec.adjustment_count = 0

    def _rs_service(self):
        """ The RS.GE service of this waybill's company, whatever company is active;
            legacy rows without a company use the active one. """
        self.ensure_one()
        return self.env['rs.waybill.soap.service'].with_company(self.company_id or self.env.company)


    @api.onchange('source_warehouse_id')
    def _onchange_source_warehouse_id(self):
        if self.source_warehouse_id and self.waybill_type == '1':
            self.start_address = self.env['stock.picking']._rs_warehouse_address(self.source_warehouse_id)


    @api.onchange('dest_warehouse_id')
    def _onchange_dest_warehouse_id(self):
        if self.dest_warehouse_id and self.waybill_type == '1':
            self.end_address = self.env['stock.picking']._rs_warehouse_address(self.dest_warehouse_id)


    @api.onchange('buyer_id')
    def _onchange_buyer_fields(self):
        if self.buyer_id:
            self.buyer_name = self.buyer_id.name
            self.buyer_tin = self.buyer_id.vat or False
            self.end_address = self.buyer_id.street or False
        else:
            self.buyer_tin = False
            self.end_address = False


    @api.onchange('citizen')
    def _onchange_buyer_id(self):
        if self.citizen:
            self.buyer_id = False
            self.buyer_name = False
            self.end_address = False


    @api.onchange('is_medicine')
    def _onchange_product_code(self):
        """ Line codes are barcodes for Normal, registry codes for Medicine: a real switch clears the lines.
            Blank is sent as Normal, so blank -> Normal changes nothing. """
        if (self._origin.is_medicine or '0') == (self.is_medicine or '0') or not self.line_ids:
            return
        self.line_ids = False
        return {'warning': {
            'title': _("Goods lines removed"),
            'message': _("Goods codes differ between Normal and Medicine waybills: add the goods again."),
        }}


    @api.onchange('transporter_tin')
    def _onchange_transporter_tin(self):
        """ Fill the transporter's name from RS.GE; RS.GE down or no login: left for the user to type. """
        if self.transporter_tin and len(self.transporter_tin) >= 9:
            try:
                name = self._rs_service().get_transporter_info(self.transporter_tin)
            except Exception as e:
                _logger.warning("RS transporter name lookup failed for %s: %s", self.transporter_tin, e)
                name = ''
            if name:
                self.transporter_name = name


    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        """ Picking a plate fills car_number, and the car's driver only while no driver is typed. """
        if self.vehicle_id:
            # Capitals: older vehicles may still carry a lower-case plate, RS.GE gets it as is.
            self.car_number = (self.vehicle_id.license_plate or '').upper()
            if self.vehicle_id.driver_id and not self.driver_tin:
                self.driver_partner_id = self.vehicle_id.driver_id
                self.driver_tin = self.vehicle_id.driver_id.vat
                self.driver_name = self.vehicle_id.driver_id.name
                self.driver_is_foreigner = self.vehicle_id.driver_id.rs_is_foreigner


    @api.onchange('driver_partner_id')
    def _onchange_driver_partner_id(self):
        """ Fill the driver fields from the contact, and the driver's car while no plate is picked. """
        if self.driver_partner_id:
            self.driver_tin = self.driver_partner_id.vat
            self.driver_name = self.driver_partner_id.name
            self.driver_is_foreigner = self.driver_partner_id.rs_is_foreigner
            vehicle = not self.vehicle_id and self.env['fleet.vehicle'].search(
                [('driver_id', '=', self.driver_partner_id.id),
                 ('company_id', 'in', [False, (self.company_id or self.env.company).id])], limit=1,
            )
            if vehicle:
                self.vehicle_id = vehicle
                if vehicle.license_plate:
                    self.car_number = vehicle.license_plate
        else:
            self.driver_tin = self.driver_name = False
            self.driver_is_foreigner = False


    @api.onchange('driver_tin')
    def _onchange_driver_tin_lookup(self):
        """ Type a TIN to look up the driver: link an existing partner, else only show the RS name.
            The partner and vehicle are created at save (_rs_resolve_driver_and_vehicle), so no orphans. """
        tin = (self.driver_tin or '').strip()
        if not tin or len(tin) < 9:
            return
        if self.driver_partner_id and self.driver_partner_id.vat == tin:
            return
        partner = self.env['res.partner'].search(
            [('vat', '=', tin), ('company_id', 'in', [False, (self.company_id or self.env.company).id])], limit=1)
        if partner:
            self.driver_partner_id = partner
        else:
            self.driver_partner_id = False
            try:
                name = self._rs_service().get_transporter_info(tin)
            except Exception:
                name = ''
            if name:
                self.driver_name = name


    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('rs_skip_resolve'):
            records._rs_resolve_driver_and_vehicle()
        return records


    def write(self, vals):
        if vals.get('is_confirmed') in ('1', '2', '-1') and 'is_buyer_reconfirm_needed' not in vals:
            # Our edit reset the customer's RS.GE confirmation; once they confirm or reject again, the reminder is done.
            # A vendor's waybill keeps its flag: our own Received is still needed.
            answered = self.filtered(lambda w: w.waybill_direction == 'seller'
                                     and w.is_buyer_reconfirm_needed
                                     and w.is_confirmed != vals['is_confirmed'])
            if answered:
                super(RsWaybill, answered).write({'is_buyer_reconfirm_needed': False})
        old_types = {}
        if 'waybill_type' in vals and not self.env.context.get('rs_from_picking'):
            old_types = {w.id: w.waybill_type for w in self}
            if not self.env.context.get('rs_from_rs'):
                self._rs_check_type_change(vals['waybill_type'])
        res = super().write(vals)
        if not self.env.context.get('rs_skip_resolve') and (
                'driver_tin' in vals or 'car_number' in vals or 'driver_partner_id' in vals):
            self._rs_resolve_driver_and_vehicle()
        if old_types:
            self._rs_follow_type_change(old_types)
        return res


    def _rs_check_type_change(self, new_type):
        """ A sale's waybill switches only between With Transport (2) and Without Transport (3);
            Internal (1), Distribution (4) and Return (5) are other kinds of document. """
        if new_type in ('2', '3'):
            return
        for waybill in self.filtered(lambda w: w.waybill_direction == 'seller'
                                     and w.waybill_type != new_type):
            if waybill.sales_order_id or waybill.picking_id.sale_id:
                raise UserError(_(
                    "Waybill %s belongs to a sale, so it can only be With Transport or "
                    "Without Transport. For another kind (internal transport, distribution, "
                    "return) create that document instead.") % waybill.display_name)


    def _rs_follow_type_change(self, old_types):
        """ Draft switched between types 2 and 3: type 3 carries no transport data and the open delivery
            moves to the matching Operation Type. A draft on RS.GE follows with its next Save. """
        for waybill in self.filtered(lambda w: w.waybill_direction == 'seller'):
            new_type = waybill.waybill_type
            if new_type == old_types.get(waybill.id) or new_type not in ('2', '3'):
                continue
            if new_type == '3':
                waybill.with_context(rs_skip_resolve=True).write({
                    'driver_partner_id': False, 'driver_tin': False, 'driver_name': False,
                    'vehicle_id': False, 'car_number': False, 'trailer': False,
                    'transport_cost': 0.0, 'transport_type': False,
                })
            picking = waybill.picking_id
            warehouse = picking.picking_type_id.warehouse_id
            if picking and warehouse and picking.state not in ('done', 'cancel'):
                target = warehouse._rs_pickup_type() if new_type == '3' else warehouse.out_type_id
                if target and picking.picking_type_id != target:
                    picking.with_context(rs_from_waybill=True).picking_type_id = target
            if (waybill.rs_internal_id and waybill.state == 'draft'
                    and not self.env.context.get('rs_from_rs')):
                waybill.rs_needs_resave = True


    @api.model
    def rs_list_kpis(self, domain, today_start):
        """ The eight waybill list card numbers in one request: per state, and per state "today"
            (created / activated / cancelled / delivered since today_start, the user's day start in UTC).
            Record rules apply. """
        by_state = dict(self._read_group(domain, ['state'], ['__count']))
        today = {
            'totalToday': [('create_date', '>=', today_start)],
            'activeToday': [('state', '=', 'active'), ('activation_date', '>=', today_start)],
            'cancelledToday': [('state', '=', 'cancelled'), ('cancel_date', '>=', today_start)],
            'completedToday': [('state', '=', 'completed'), ('delivery_date', '>=', today_start)],
        }
        kpis = {'total': sum(by_state.values()),
                **{state: by_state.get(state, 0) for state in ('active', 'cancelled', 'completed')}}
        kpis.update({key: self.search_count(domain + extra) for key, extra in today.items()})
        return kpis


    @api.ondelete(at_uninstall=False)
    def _unlink_except_on_rs(self):
        """ A waybill on RS.GE is not deleted (the next sync would re-import it with a second order and delivery).
            Deletable: never sent, cancelled, templates, and the Delete button (deletes on RS.GE first). """
        if self.env.context.get('rs_deleted_on_rs'):
            return
        blocked = self.filtered(lambda w: w.rs_internal_id and not w.is_template
                                and w.state != 'cancelled')
        if not blocked:
            return
        hints = {
            'draft': _("use the Delete button on the waybill"),
            'completed': _("the goods were delivered: correct it with Adjustment, or use "
                           "Return on the delivery"),
        }
        raise UserError(_("These waybills are on RS.GE, so they cannot be deleted here. Use "
                          "the button that updates RS.GE and Odoo together:\n%s") % '\n'.join(
            "%s: %s" % (waybill.display_name,
                        hints.get(waybill.state, _("use the Cancel button on the waybill")))
            for waybill in blocked))


    def _auto_init(self):
        res = super()._auto_init()
        # Uniqueness of rs_internal_id is enforced only here, atomically: a Python constraint would
        # search() per record on every write and still race between concurrent workers.
        self.env.cr.execute("""
              CREATE UNIQUE INDEX IF NOT EXISTS rs_waybill_rs_internal_id_unique
              ON rs_waybill (rs_internal_id)
              WHERE rs_internal_id IS NOT NULL AND rs_internal_id != 0
          """)
        return res


    @staticmethod
    def _tbilisi_date(dt):
        """ Georgian calendar date of a UTC datetime: .date() on the raw value puts 20:00-24:00 UTC a day early. """
        if not dt:
            return None
        return dt.replace(tzinfo=UTC_TZ).astimezone(TBILISI_TZ).date()


    def _mapping_enabled(self):
        """ True when the waybill was created on or after the configured cutoff date (new product rules). """
        self.ensure_one()
        # Per company: companies can start the product rules on different dates; no company -> active one.
        cutoff = (self.company_id or self.env.company).rs_mapping_cutoff_date
        if not cutoff:
            return False
        ref_date = self._tbilisi_date(self.create_date)
        if not ref_date:
            return False
        return ref_date >= cutoff


    def _in_integration_scope(self):
        """ True when on/after the stock-integration cutoff: only then do the sync and drift crons auto-create
            or cascade Odoo documents. Earlier waybills stay data-only; manual buttons still work.
            Uses activation_date (the RS truth), else create_date. """
        self.ensure_one()
        # Per company (Settings → Enable Stock Integration + start date): off means its waybills stay waybills only.
        company = self.company_id or self.env.company
        if not company.rs_enable_stock:
            return False
        cutoff = company.rs_stock_integration_date
        if not cutoff:
            return False
        ref_date = self._tbilisi_date(self.activation_date or self.create_date)
        if not ref_date:
            return False
        return ref_date >= cutoff


    def _get_seller_partner(self):
        """ Resolve seller_tin to a res.partner; empty recordset if not found. """
        self.ensure_one()
        if not self.seller_tin:
            return self.env['res.partner']
        # A contact of another company is not this company's vendor.
        company = self.company_id or self.env.company
        return self.env['res.partner'].sudo().search(
            [('vat', '=', self.seller_tin), ('company_id', 'in', [company.id, False])], limit=1)


    def _get_or_create_vendor_partner(self):
        """ Resolve seller_tin / seller_name to the PO vendor partner; create one (supplier_rank=1, logged
            on chatter) if none matches. Returns an empty recordset when seller_tin is missing. """
        self.ensure_one()
        if not self.seller_tin:
            return self.env['res.partner']
        partner = self._get_seller_partner()
        if partner:
            return partner
        partner = self.env['res.partner'].sudo().create({'name': self.seller_name or self.seller_tin,
                                                         'vat': self.seller_tin,
                                                         'supplier_rank': 1,})
        self.message_post(body=Markup(_("Vendor partner auto-created from waybill seller: <b>%(name)s</b> (TIN: %(tin)s)")) %
                               {'name': partner.name, 'tin': self.seller_tin})
        return partner


    def _resolve_product(self, bar_code, seller_partner):
        """ Resolve a seller barcode to OUR product via the seller-scoped rs.product.external.ref (barcodes are not
            globally unique, so product.barcode is never matched).
            No mapping: empty recordset; the operator maps it via 'Resolve Now'. """
        if not bar_code or not seller_partner:
            return self.env['product.product']
        ref = self._rs_product_ref(bar_code, seller_partner)
        if not ref:
            return self.env['product.product']
        # Stamp last_seen_date only when the mapping resolved, so stale mappings stay findable.
        product = ref.variant_id
        if not product:
            variants = ref.product_id.product_variant_ids
            if len(variants) == 1:
                product = variants
            else:
                _logger.warning("External ref %s maps to template %s which has %d variants and no specific "
                                "variant set; marking line as unresolved.",
                                ref.id, ref.product_id.display_name, len(variants))
                return self.env['product.product']
        ref.last_seen_date = fields.Datetime.now()
        return product


    def _rs_product_ref(self, bar_code, seller_partner):
        """ This waybill's company's mapping of the seller's barcode; never another company's. """
        return self.env['rs.product.external.ref'].sudo().search(
            [('seller_partner_id', '=', seller_partner.id), ('external_barcode', '=', bar_code),
             ('company_id', '=', (self.company_id or self.env.company).id)], limit=1)


    def _get_notification_users(self):
        """ Per-company recipients, read from a Many2many (no comma-separated id string to break). """
        company = self.company_id if len(self) == 1 and self.company_id else self.env.company
        return company.sudo().rs_notification_user_ids


    def _rs_match_warehouse_by_address(self, address):
        """ Best-effort: match an RS address string to one of the company's warehouses by partner
            street/city or warehouse name (case/space-insensitive). Empty recordset on no match or several. """
        self.ensure_one()
        addr = (address or '').strip().lower()
        if not addr or addr == 'null':
            return self.env['stock.warehouse']
        matches = self.env['stock.warehouse']
        for wh in self.env['stock.warehouse'].search([('company_id', '=', self.company_id.id)]):
            p = wh.partner_id
            candidates = {wh.name or '',
                          p.street or '',
                          ('%s %s' % (p.street or '', p.city or '')).strip(),
                          ('%s, %s' % (p.street or '', p.city or '')).strip(', ')}
            if addr in {c.strip().lower() for c in candidates if c}:
                matches |= wh
        return matches if len(matches) == 1 else self.env['stock.warehouse']


    def _rs_resolve_driver_and_vehicle(self):
        """ At save: find or create the driver from driver_tin and the car from car_number, in the waybill's company.
            rs_skip_resolve in the context stops write() recursion. """
        Partner = self.env['res.partner']
        Vehicle = self.env['fleet.vehicle']
        for wb in self:
            if wb.is_template:
                continue
            vals = {}
            driver = wb.driver_partner_id
            tin = (wb.driver_tin or '').strip()
            if tin and len(tin) >= 9 and not driver:
                driver = Partner._rs_driver_from_tin(tin, wb.driver_name, wb.company_id)
                if driver:
                    vals['driver_partner_id'] = driver.id
            if wb.car_number and driver and (
                    not wb.vehicle_id or (wb.vehicle_id.license_plate or '').upper() != wb.car_number.strip().upper()):
                # A plate is unique across all companies: another company's car is not linked (RS.GE needs only
                # car_number), never created twice.
                veh = Vehicle.sudo().with_context(active_test=False).search(
                    [('license_plate', '=ilike', wb.car_number.strip())], limit=1)
                if not veh:
                    veh = Vehicle.create({
                        'driver_id': driver.id,
                        'license_plate': wb.car_number,
                        'model_id': Vehicle._ensure_rs_placeholder_model().id,
                        'company_id': wb.company_id.id,
                        'rs_imported': True,
                        'rs_synced_date': fields.Datetime.now(),
                    })
                own = not veh.company_id or veh.company_id == wb.company_id
                vals['vehicle_id'] = veh.id if own else False
            if vals:
                wb.with_context(rs_skip_resolve=True).write(vals)


    def _sync_buyer_to_so_and_picking(self):
        """ Seller waybill buyer changed: nothing shipped or invoiced -> SO customer and delivery contact follow
            (partner_id only); else all keep the old customer and the salesperson gets an activity.
            Never raises: failure noted. """
        self.ensure_one()
        buyer = self.buyer_id
        if not buyer or self.waybill_direction != 'seller':
            return
        order, picking = self.sales_order_id, self.picking_id
        if (not order or order.partner_id == buyer) and (not picking or picking.partner_id == buyer):
            return
        try:
            with self.env.cr.savepoint():
                if order and order.partner_id != buyer:
                    invoices = order.invoice_ids.filtered(lambda i: i.state != 'cancel')
                    shipped = (picking.state == 'done'
                               or any(line.qty_delivered for line in order.order_line))
                    if shipped or invoices:
                        self._rs_flag_buyer_change_after_delivery(order, invoices)
                        return
                    old = order.partner_id
                    order.partner_id = buyer
                    order.message_post(body=_("Customer changed from %(old)s to %(new)s by waybill "
                                              "%(waybill)s.") % {'old': old.display_name,
                                                                 'new': buyer.display_name,
                                                                 'waybill': self.display_name})
                if picking and picking.state != 'done' and picking.partner_id != buyer:
                    picking.partner_id = buyer
        except Exception as e:
            _logger.warning("Buyer change of waybill %s not applied to its order/delivery: %s",
                            self.id, e)
            self.message_post(body=_("The buyer change could not be applied to the sales order "
                                     "or delivery: %s. Please review.") % e)


    def _rs_flag_buyer_change_after_delivery(self, order, invoices):
        """ One activity per order and new buyer, so repeated syncs do not stack them. """
        summary = _("Waybill buyer changed to %s after delivery") % self.buyer_id.display_name
        if order.activity_ids.filtered(lambda a: a.summary == summary):
            return
        order.activity_schedule(
            'mail.mail_activity_data_todo', summary=summary,
            note=_("Waybill %(waybill)s now has buyer %(new)s, but %(order)s was already "
                   "delivered or invoiced for %(old)s, so it was not changed (invoices: "
                   "%(invoices)s). Issue a credit note to %(old)s and invoice %(new)s, or "
                   "change the waybill back.") % {
                'waybill': self.display_name, 'new': self.buyer_id.display_name,
                'order': order.name, 'old': order.partner_id.display_name,
                'invoices': ', '.join(invoices.mapped('display_name')) or _('none')},
            user_id=(order.user_id or self.env.user).id)


    def _validate_before_save(self):
        """Validate required fields before sending to RS.GE."""
        self.ensure_one()
        errors = []

        if self.picking_id and self.picking_id.state not in ('assigned', 'done'):
            state_label = dict(self.picking_id._fields['state'].selection).get(self.picking_id.state, self.picking_id.state)
            errors.append(_("Cannot send to RS.GE: the linked delivery '%(name)s' is in state "
                            "'%(state)s'. Reserve stock (Check Availability) until it is Ready, "
                            "then try again."
                            ) % {'name': self.picking_id.name, 'state': state_label})

        if self.buyer_id and self.buyer_id == (self.company_id or self.env.company).partner_id:
            errors.append(_("Buyer cannot be your own company."))

        if not self.waybill_type:
            errors.append(_("Waybill Type is required."))
        if not self.start_address:
            errors.append(_("Start Address is required."))

            # Type 1,3,4 (Internal Transport, Without Transport, Distribution) doesn't need buyer/end_address/driver
        if self.waybill_type not in ('1', '3', '4'):
            if not self.buyer_tin:
                errors.append(_("Buyer TIN is required."))
            if not self.end_address:
                errors.append(_("End Address is required."))
        elif self.waybill_type == '1' and not self.parent_waybill_id:
            if not self.source_warehouse_id:
                errors.append(_("Source Warehouse is required for Internal Transport"))
            if not self.dest_warehouse_id:
                errors.append(_("Destination Warehouse is required for Internal Transport"))
            if not self.end_address:
                errors.append(_("End Address is required."))
        if (self.waybill_type == '1' and self.source_warehouse_id
                and self.source_warehouse_id == self.dest_warehouse_id):
            errors.append(_("From and To warehouses must be different."))

        # Only road transport (1, 6, 8) needs driver + car; the carrier fills type 7, a sub inherits its parent's.
        # Type 3 needs none, whatever transport type RS.GE echoes back.
        needs_transport_info = (self.transport_type in ('1', '6', '8') and self.waybill_type != '3'
                                and not self.parent_waybill_id)
        if needs_transport_info:
            if not self.driver_tin and not self.driver_is_foreigner:
                errors.append(_("Driver TIN is required (or mark as foreigner)."))
            if not self.car_number:
                errors.append(_("Car Number is required."))

        if not self.line_ids:
            errors.append(_("At least one product line is required."))
        else:
            missing = self.line_ids.filtered(lambda line: not line.product_id)
            if missing:
                errors.append(_("Every line must have a product selected. "
                                "%d line(s) are missing a product.") % len(missing))
            # RS.GE refuses a product on two lines. Never merged: two prices would need an averaged,
            # rounded price that no longer matches the invoice.
            products = self.line_ids.product_id
            twice = products.filtered(lambda p: len(self.line_ids.filtered(
                lambda line: line.product_id == p)) > 1)
            for product in twice:
                errors.append(_("%s is on this waybill more than once. RS.GE allows each product "
                                "only once per waybill: put it on one order line, and for a second "
                                "price make a separate sales order.") % product.display_name)

        if self.parent_waybill_id:
            for line in self.line_ids:
                label = line.name or (line.product_id and line.product_id.display_name) or _('line')
                if (line.quantity or 0) <= 0:
                    errors.append(_("Set a quantity greater than 0 for '%s'.") % label)
                elif line.parent_remaining and line.quantity > line.parent_remaining:
                    errors.append(_("Quantity for '%(name)s' exceeds the available %(avail)s.")
                                  % {'name': label, 'avail': line.parent_remaining})
            if self.waybill_type == '4':
                if not self.buyer_tin:
                    errors.append(_("Buyer TIN is required."))
                if not self.buyer_name:
                    errors.append(_("Buyer Name/Surname is required."))
                if not self.end_address:
                    errors.append(_("Delivery Address is required."))
            elif self.waybill_type == '1':
                if not self.source_warehouse_id:
                    errors.append(_("From Warehouse is required."))
                if not self.dest_warehouse_id:
                    errors.append(_("To Warehouse is required."))

        if errors:
            raise UserError('\n'.join(errors))


    def _require_rs_id(self):
        """ Refuse an RS.GE call on a waybill never saved there (else waybill_id 0 goes to RS, which
            answers with a generic failure code). """
        self.ensure_one()
        if not self.rs_internal_id:
            raise UserError(_("Please save the waybill to RS.GE first."))


    def _validate_transporter_driver_fields(self):
        self.ensure_one()
        missing = []
        if not self.driver_tin:
            missing.append(_("Driver TIN"))
        if not self.driver_name:
            missing.append(_("Driver Name"))
        if not self.car_number:
            missing.append(_("Car Number"))
        if missing:
            raise UserError(_("Please fill the following before continuing: %s") % ", ".join(missing))


    def _rs_build_documents(self):
        """ Build the missing order and transfer of a waybill seen by sync, Update or drift. All or
            nothing (savepoint): a failure is shown on the waybill and retried by the drift job and Retry. """
        self.ensure_one()
        builder = (self._rs_create_buyer_documents_if_missing if self.waybill_direction == 'buyer'
                   else self._rs_create_documents_if_missing)
        return self._rs_post_commit(_("Create the linked Odoo documents"), builder)


    def action_retry_local_steps(self):
        """ Banner button: retry the Odoo steps that did not complete. """
        self.ensure_one()
        self._rs_repair_local_state()
        if self.rs_post_commit_error:
            raise UserError(self.rs_post_commit_error)


    def _rs_create_documents_if_missing(self):
        """ Seller waybill with no linked transfer: build the READY documents; type 1 internal transfer, type 5 incoming
            return (no SO), types 2/3/4 SO -> delivery. Called by Save/Activate/Send-to-Transporter/Complete;
            no-op once linked or cancelled. """
        self.ensure_one()
        if (self.picking_id or self.is_template or self.waybill_direction != 'seller'
                or self.state == 'cancelled'):
            return
        if not self.line_ids or self.line_ids.filtered(lambda l: not l.product_id):
            return  # need resolved products — skip silently, don't block the RS save
        if self.remainder_origin_id:
            # Remainder: a Return brings the leftover back from the truck; a Distribution keeps it there.
            if self.waybill_type == '5':
                self._rs_create_truck_return_from_waybill()
        elif self.waybill_type == '4' and not self.parent_waybill_id:
            self._rs_create_truck_take_out()
        elif self.waybill_type == '1':
            self._rs_create_internal_transfer_from_waybill()
        elif self.waybill_type == '5':
            if self._rs_return_origin_candidates():
                self._rs_ask_return_origin()
            else:
                self._rs_create_return_transfer_from_waybill()
        elif self.buyer_id:
            self._rs_create_so_and_delivery_from_waybill()


    @api.depends('waybill_type', 'waybill_direction', 'picking_id', 'remainder_origin_id',
                 'is_template', 'state', 'buyer_id', 'line_ids.product_id')
    def _compute_return_origin_candidate_ids(self):
        for waybill in self:
            waits = (waybill.waybill_direction == 'seller' and waybill.waybill_type == '5'
                     and not waybill.picking_id and not waybill.remainder_origin_id
                     and not waybill.is_template and waybill.state != 'cancelled')
            candidates = waybill._rs_return_origin_candidates() if waits else self.env['stock.picking']
            waybill.return_origin_candidate_ids = candidates
            waybill.rs_needs_return_origin = bool(candidates)


    def _rs_return_origin_candidates(self):
        """ Done deliveries a return waybill can come from: same customer (delivery contact or
            waybill buyer), at least one returned product, newest first. RS.GE does not say which,
            so the operator picks. """
        self.ensure_one()
        products = self.line_ids.product_id
        if not self.buyer_id or not products:
            return self.env['stock.picking']
        buyer = self.buyer_id.commercial_partner_id
        return self.env['stock.picking'].search([
            ('company_id', '=', self.company_id.id),
            ('picking_type_code', '=', 'outgoing'),
            ('state', '=', 'done'),
            ('return_id', '=', False),
            ('move_ids.product_id', 'in', products.ids),
            '|', ('partner_id', 'child_of', buyer.id), ('waybill_id.buyer_id', 'child_of', buyer.id),
        ], order='date_done desc, id desc').filtered(
            lambda p: any(not move.uom_id.is_zero(move._rs_returnable_qty())
                          for move in p.move_ids if move.product_id in products))


    def _rs_return_origin_summary(self):
        return _("Pick the original delivery for this return")


    def _rs_ask_return_origin(self):
        """ The return waits for the operator to pick its original delivery: one activity
            for the customer's salesperson, not repeated by later syncs. """
        summary = self._rs_return_origin_summary()
        if self.activity_ids.filtered(lambda a: a.summary == summary):
            return
        self.activity_schedule(
            'mail.mail_activity_data_todo', summary=summary,
            note=_("Return waybill %s came from RS.GE. Open it, pick the delivery the goods come "
                   "back from and click Create Return, so the sales order counts the return.")
                 % self.display_name,
            user_id=(self.buyer_id.user_id or self.env.user).id)


    def _rs_finish_return_link(self):
        """ Close the 'pick the original delivery' activity and, when RS already completed
            the return, validate the new receipt as the completion would have. """
        summary = self._rs_return_origin_summary()
        self.activity_ids.filtered(lambda a: a.summary == summary).action_feedback()
        if self.picking_id and self.state == 'completed':
            self._cascade_validate_picking()


    def action_create_return_from_origin(self):
        """ Build the return from the picked delivery via core's return, so moves carry the SO line and the delivered
            quantity goes down. Refused when that delivery has too little left to return (shipped - returned). """
        self.ensure_one()
        origin = self.return_origin_picking_id
        if self.picking_id:
            raise UserError(_("This waybill already has a transfer: %s.") % self.picking_id.name)
        if not origin:
            raise UserError(_("Pick the Original Delivery first."))
        if origin not in self._rs_return_origin_candidates():
            raise UserError(_("Delivery %s is not a done delivery of this customer with these "
                              "products.") % origin.name)
        wanted = {}
        for line in self.line_ids.filtered('product_id'):
            wanted[line.product_id] = wanted.get(line.product_id, 0.0) + line._rs_base_qty()
        return_picking = self._create_return_picking(
            {product.id: qty for product, qty in wanted.items()}, create_waybill=False, delivery=origin)
        returned = {}
        for move in return_picking.move_ids if return_picking else []:
            returned[move.product_id] = returned.get(move.product_id, 0.0) + move.uom_id._compute_quantity(
                move.product_uom_qty, move.product_id.uom_id)
        short = [product.display_name for product, qty in wanted.items()
                 if product.uom_id.compare(returned.get(product, 0.0), qty) < 0]
        if short:
            raise UserError(_("Delivery %(picking)s has not enough left to return of: "
                              "%(products)s (shipped minus already returned). Pick another "
                              "delivery.") % {'picking': origin.name,
                                                           'products': ', '.join(short)})
        return_picking.waybill_id = self.id
        self.picking_id = return_picking.id
        # Each line to its return move, so later goods changes reach it (_rs_line_move skips return moves unlinked).
        for line in self.line_ids.filtered('product_id'):
            line.stock_move_id = return_picking.move_ids.filtered(
                lambda m: m.product_id == line.product_id and m not in self.line_ids.stock_move_id)[:1]
        self.message_post(body=_("Return %(return)s created from delivery %(origin)s.")
                          % {'return': return_picking.name, 'origin': origin.name})
        self._rs_finish_return_link()


    def action_create_plain_return(self):
        """ Goods from no Odoo delivery: plain receipt, no sales order change. """
        self.ensure_one()
        if self.picking_id:
            raise UserError(_("This waybill already has a transfer: %s.") % self.picking_id.name)
        self.return_origin_picking_id = False
        self._rs_create_return_transfer_from_waybill()
        self._rs_finish_return_link()


    def _rs_create_so_and_delivery_from_waybill(self):
        """ Seller delivery (types 2/3/4): once the waybill is active (status 8), build a confirmed SO + delivery,
            linked both ways, under skip_rs_auto_create; no-op once an SO is linked. """
        self.ensure_one()
        if not self.buyer_id or self.sales_order_id:
            return
        # Draft = sketch → create nothing until the waybill is active.
        if self.state == 'draft' and (self.waybill_status or '0') != '8':
            return
        warehouse = self.source_warehouse_id or self.env['stock.warehouse'].search(
            [('company_id', '=', self.company_id.id)], limit=1)
        so_vals = {
            'partner_id': self.buyer_id.id,
            'order_line': [(0, 0, {
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'product_uom_id': line._rs_unit().id,
                'price_unit': line.unit_price,
            }) for line in self.line_ids if line.product_id],
        }
        if warehouse:
            so_vals['warehouse_id'] = warehouse.id
        # In the waybill's company, whatever company the switcher shows.
        so = self.env['sale.order'].with_company(self.company_id or self.env.company).with_context(
            skip_rs_auto_create=True).create(so_vals)
        for line, sol in zip(self.line_ids.filtered('product_id'), so.order_line.sorted('id')):
            sol.price_unit = self._rs_order_price(line.unit_price, sol)
        self.sales_order_id = so.id
        so.with_context(skip_rs_auto_create=True).action_confirm()
        delivery = so.picking_ids.filtered(
            lambda p: p.picking_type_code == 'outgoing' and p.state != 'cancel')[:1]
        if delivery:
            if self.waybill_type == '3' and warehouse:
                delivery.with_context(rs_from_waybill=True, skip_rs_auto_create=True
                                      ).picking_type_id = warehouse._rs_pickup_type()
            self.picking_id = delivery.id
            delivery.waybill_id = self.id
            truck = self._rs_truck_location()
            if truck:
                # A distribution's sub-waybill: the goods are already on the truck.
                delivery.do_unreserve()
                delivery.write({'location_id': truck.id,
                                'rs_distribution_id': self._rs_distribution_root().id})
                delivery.move_ids.write({'location_id': truck.id})
                delivery.with_context(skip_rs_auto_create=True).action_assign()
            # One SO line per waybill line, same order: link each to its delivery move so later
            # RS.GE / Adjustment changes reach the delivery.
            for line, sol in zip(self.line_ids.filtered('product_id'), so.order_line.sorted('id')):
                line.stock_move_id = delivery.move_ids.filtered(lambda m: m.sale_line_id == sol)[:1]


    def _rs_create_purchase_from_waybill(self):
        """ Buyer types 2/3/4: link the vendor's one open PO holding every product, create one if none, ask if several.
            Skipped while a line is unmapped or there is no seller TIN. Returns the PO or empty. """
        self.ensure_one()
        PO = self.env['purchase.order']
        if (self.purchase_id or self.picking_id or self.waybill_direction != 'buyer'
                or self.waybill_type not in ('2', '3', '4') or self.state == 'cancelled'
                or not self.line_ids):
            return PO
        if self._rs_lines_need_mapping():
            _logger.info("Skipping PO for waybill %s: %d line(s) need a product or unit",
                         self.id, sum(1 for l in self.line_ids if not l.product_id or l.uom_review))
            return PO
        vendor = self._get_or_create_vendor_partner()
        if not vendor:
            _logger.info("Skipping PO for waybill %s: no seller_tin", self.id)
            return PO
        candidates = self._rs_purchase_candidates(vendor)
        if len(candidates) > 1:
            self._rs_ask_purchase(candidates)
            return PO
        if candidates:
            return self._rs_link_purchase(candidates)
        return self._rs_link_purchase(self._rs_create_own_purchase(vendor))


    def _rs_create_own_purchase(self, vendor):
        """ A new PO holding the waybill's goods at the waybill prices, in the waybill's
            company (not the user's active one). Marks it as made from this waybill. """
        self.ensure_one()
        purchase_order = self.env['purchase.order'].with_company(self.company_id).with_context(
            skip_rs_auto_create=True).create({
                'partner_id': vendor.id,
                'company_id': self.company_id.id,
                'origin': self.rs_waybill_number or _('Waybill %s') % (self.rs_internal_id or self.id),
                'order_line': [(0, 0, self._rs_purchase_line_vals(line.product_id, line.quantity,
                                                                   line.unit_price, line.name, line._rs_unit()))
                               for line in self.line_ids if line.product_id]})
        for line, po_line in zip(self.line_ids.filtered('product_id'), purchase_order.order_line.sorted('id')):
            po_line.price_unit = self._rs_order_price(line.unit_price, po_line)
            line.purchase_line_id = po_line
        self.purchase_created = True
        self.message_post(body=Markup(_("Purchase order created from this waybill: <b>%(po)s</b> "
                                 "(vendor: %(vendor)s).")) % {'po': purchase_order.name, 'vendor': vendor.name})
        return purchase_order


    def _rs_order_price(self, waybill_price, order_line):
        """ An order line's price from a waybill price. The waybill price is in GEL with the
            VAT in it: take out the VAT the line's own taxes add on top of their price, and
            convert to the order's currency at the waybill's date. """
        added = order_line.tax_ids.filtered(lambda t: t.amount_type == 'percent' and not t.price_include)
        net = waybill_price / (1 + sum(added.mapped('amount')) / 100.0)
        date = (self.activation_date or self.create_date or fields.Datetime.now()).date()
        return self.env.ref('base.GEL')._convert(net, order_line.currency_id, self.company_id, date,
                                                 round=False)


    def _rs_purchase_line_vals(self, product, qty, price, name=None, uom=None):
        """ PO line values for a waybill product: the WAYBILL price, in uom (default: the product's unit). """
        return {
            'product_id': product.id,
            'name': name or product.display_name,
            'product_qty': qty,
            'price_unit': price,
            'uom_id': (uom or product.uom_id).id,
            'date_planned': fields.Datetime.now(),
        }


    def _rs_purchase_candidates(self, vendor=None):
        """ The vendor's RFQs and confirmed POs of the waybill's company, not cancelled or fully received, holding
            every product of the waybill (a PO with only some of them is another order). """
        self.ensure_one()
        vendor = vendor or self._get_seller_partner()
        products = self.line_ids.product_id
        if not vendor or not products:
            return self.env['purchase.order']
        orders = self.env['purchase.order'].search([
            ('partner_id', 'child_of', vendor.commercial_partner_id.id),
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ('draft', 'sent', 'to approve', 'purchase')),
        ], order='date_order desc, id desc')
        return orders.filtered(
            lambda po: products <= po.order_line.product_id
            and (po.state != 'purchase' or any(
                l.uom_id.compare(l.qty_received, l.product_qty) < 0
                for l in po.order_line if not l.display_type)))


    @api.depends('waybill_type', 'waybill_direction', 'purchase_id', 'picking_id',
                 'is_template', 'state', 'line_ids.product_id', 'line_ids.uom_review', 'seller_tin')
    def _compute_purchase_candidate_ids(self):
        for waybill in self:
            waits = (waybill.waybill_direction == 'buyer' and waybill.waybill_type in ('2', '3', '4')
                     and not waybill.purchase_id and not waybill.picking_id
                     and not waybill.is_template and waybill.state != 'cancelled'
                     and waybill.line_ids and not waybill._rs_lines_need_mapping())
            candidates = waybill._rs_purchase_candidates() if waits else self.env['purchase.order']
            waybill.purchase_candidate_ids = candidates
            waybill.rs_needs_purchase_pick = len(candidates) > 1


    def _rs_purchase_pick_summary(self):
        return _("Pick the purchase order for vendor waybill %s") % self.display_name


    def _rs_ask_purchase(self, candidates):
        """ Several open POs fit: one activity for the purchaser, not repeated by later
            syncs. The waybill shows a picker limited to these POs. """
        summary = self._rs_purchase_pick_summary()
        if self.activity_ids.filtered(lambda a: a.summary == summary):
            return
        self.activity_schedule(
            'mail.mail_activity_data_todo', summary=summary,
            note=_("Vendor waybill %(waybill)s fits several open purchase orders: %(orders)s. "
                   "Open the waybill, pick the one these goods belong to and click Link.")
                 % {'waybill': self.display_name, 'orders': ', '.join(candidates.mapped('name'))},
            user_id=(candidates[:1].user_id or self.env.user).id)


    def _rs_link_purchase(self, purchase_order):
        """ Link the waybill to its PO (an RFQ is confirmed first); the receipt only for a PO made from this waybill,
            else the open receipt is taken at Received time. """
        self.ensure_one()
        if purchase_order.state in ('draft', 'sent'):
            purchase_order.with_context(skip_rs_auto_create=True).button_confirm()
        self.purchase_id = purchase_order
        self.purchase_pick_id = False
        if self.purchase_created:
            receipt = purchase_order.picking_ids.filtered(
                lambda p: p.picking_type_code == 'incoming' and p.state not in ('done', 'cancel'))[:1]
            if receipt:
                self.picking_id = receipt
                receipt.waybill_id = self.id
        else:
            self.message_post(body=Markup(_("Linked to purchase order <b>%s</b>.")) % purchase_order.name)
            purchase_order.message_post(body=_("Vendor waybill %s linked to this order.") % self.display_name)
        if purchase_order.state == 'to approve':
            self.message_post(body=_("Purchase order %s waits for approval: Received works once "
                                     "it is approved.") % purchase_order.name)
        self.activity_ids.filtered(
            lambda a: a.summary == self._rs_purchase_pick_summary()).action_feedback()
        return purchase_order


    def _rs_check_lines_mapped(self):
        if any(not l.product_id for l in self.line_ids):
            raise UserError(_("Map the products first (Resolve Now)."))
        if any(l.uom_review for l in self.line_ids):
            raise UserError(_("Pick the unit of the goods lines marked 'Unit Needs Review' first."))


    def _rs_lines_need_mapping(self):
        return any(not l.product_id or l.uom_review for l in self.line_ids)


    def action_link_purchase(self):
        """ Picker button: link the purchase order the purchaser chose. """
        self.ensure_one()
        self._rs_check_lines_mapped()
        if not self.purchase_pick_id:
            raise UserError(_("Pick the purchase order first."))
        if self.purchase_pick_id not in self.purchase_candidate_ids:
            raise UserError(_("%s is not an open order of this vendor holding these products.")
                            % self.purchase_pick_id.name)
        self._rs_link_purchase(self.purchase_pick_id)


    def action_create_purchase_from_waybill(self):
        """ Picker button: none of the open orders is this one, make a new PO. """
        self.ensure_one()
        if self.purchase_id:
            raise UserError(_("This waybill is already linked to %s.") % self.purchase_id.name)
        self._rs_check_lines_mapped()
        self._rs_link_purchase(self._rs_create_own_purchase(self._get_or_create_vendor_partner()))


    def _rs_create_return_delivery_from_waybill(self):
        """ Buyer type 5 (vendor return): outgoing delivery only, no PO/SO, created Ready and linked before reserving
            (skip_rs_auto_create); validated on Receive. Skips when linked, not buyer/type 5, no lines, unmapped line,
            no warehouse/supplier location. """
        self.ensure_one()
        if self.picking_id or self.purchase_id:
            return self.env['stock.picking']
        if self.waybill_direction != 'buyer' or self.waybill_type != '5':
            return self.env['stock.picking']
        if not self.line_ids:
            return self.env['stock.picking']
        if any(not l.product_id or l.uom_review for l in self.line_ids):
            _logger.info("Skipping return-delivery auto-create for waybill %s: %d line(s) need a product or unit",
                         self.id, sum(1 for l in self.line_ids if not l.product_id or l.uom_review))
            return self.env['stock.picking']
        wh = self.env['stock.warehouse'].search([('company_id', '=', self.company_id.id)], limit=1)
        if not wh or not wh.out_type_id:
            _logger.warning("No warehouse/outgoing type for company %s; cannot mirror return waybill %s.",
                            self.company_id.name, self.id)
            return self.env['stock.picking']
        vendor = self._get_or_create_vendor_partner()
        # Destination must be usage='supplier' (a company partner's property may point at transit).
        dst_loc = vendor.property_stock_supplier if vendor else self.env['stock.location']
        if not dst_loc or dst_loc.usage != 'supplier':
            dst_loc = self.env.ref('stock.stock_location_suppliers', raise_if_not_found=False) \
                or self.env['stock.location'].search([('usage', '=', 'supplier')], limit=1)
        if not dst_loc:
            _logger.warning("No supplier-usage location; cannot mirror return waybill %s.", self.id)
            return self.env['stock.picking']
        src_loc = wh.lot_stock_id
        picking = self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': wh.out_type_id.id,
            'partner_id': vendor.id if vendor else False,
            'location_id': src_loc.id,
            'location_dest_id': dst_loc.id,
            'origin': self.rs_waybill_number or _('Waybill %s') % (self.rs_internal_id or self.id),
            'company_id': self.company_id.id,
            'waybill_id': self.id,           # link BEFORE reserving — forward hook no-ops
        })
        self.picking_id = picking.id
        self._rs_build_moves_on_picking(picking, src_loc, dst_loc)
        picking.with_context(skip_rs_auto_create=True).action_confirm()
        picking.with_context(skip_rs_auto_create=True).action_assign()
        self.message_post(body=Markup(_("Return delivery auto-created from vendor return waybill: <b>%(name)s</b>"
                                 )) % {'name': picking.name})
        return picking


    def _rs_documents_after_mapping(self):
        """ Create the missing Odoo documents (PO+receipt buyer, SO+delivery/transfer seller) once every line has its
            product and unit. The helpers no-op when already linked or out of scope. A failure never blocks the
            mapping and leaves nothing half-built (savepoint): banner, and the drift job builds them again. """
        for wb in self:
            if (wb.picking_id or wb.purchase_id
                    or any(l.unresolved or l.uom_review for l in wb.line_ids)
                    or not wb._in_integration_scope()):
                continue
            if wb.waybill_direction == 'buyer':
                wb._rs_post_commit(_("Create the linked Odoo documents"), wb._rs_create_buyer_documents_if_missing)
            elif wb.waybill_direction == 'seller':
                wb._rs_post_commit(_("Create the linked Odoo documents"), wb._rs_create_documents_if_missing)


    def _rs_create_buyer_documents_if_missing(self):
        """ Buyer dispatcher (sync/backfill), mirror of _rs_create_documents_if_missing: types 2/3/4 -> PO + receipt;
            type 5 -> outgoing return delivery; type 1 never reaches here. Idempotent;
            nothing for a cancelled waybill. """
        self.ensure_one()
        if self.state == 'cancelled':
            return self.env['purchase.order']
        if self.waybill_type == '5':
            return self._rs_create_return_delivery_from_waybill()
        return self._rs_create_purchase_from_waybill()


    def _rs_create_internal_transfer_from_waybill(self):
        """ Internal transport (type 1): a Ready internal transfer from the source to the destination warehouse stock.
            No SO or buyer (we are both sides); Complete validates it. """
        self.ensure_one()
        src_wh, dst_wh = self.source_warehouse_id, self.dest_warehouse_id
        # RS-synced type-1 waybills carry address strings, not warehouse ids: match them to our
        # warehouses and save a match; else the operator sets both warehouses and the next sync backfills.
        if not src_wh or not dst_wh:
            src_wh = src_wh or self._rs_match_warehouse_by_address(self.start_address)
            dst_wh = dst_wh or self._rs_match_warehouse_by_address(self.end_address)
            if src_wh and dst_wh and src_wh != dst_wh:
                self.write({'source_warehouse_id': src_wh.id, 'dest_warehouse_id': dst_wh.id})
        if not src_wh or not dst_wh or not src_wh.int_type_id:
            return
        src_loc, dst_loc = src_wh.lot_stock_id, dst_wh.lot_stock_id
        # A distribution's internal sub-waybill carries goods already on the truck.
        truck = self._rs_truck_location()
        # Both RS addresses matched one warehouse: no movement to make (truck -> that warehouse still is one).
        if (truck or src_loc) == dst_loc:
            return
        picking = self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': src_wh.int_type_id.id,
            'location_id': (truck or src_loc).id,
            'location_dest_id': dst_loc.id,
            'company_id': self.company_id.id,
            'origin': self.rs_waybill_number or _('Waybill %s') % (self.rs_internal_id or self.id),
            'rs_distribution_id': self._rs_distribution_root().id if truck else False,
        })
        src_loc = truck or src_loc
        # Link BEFORE confirm/assign so the forward hook sees it and does not create a second waybill.
        self.picking_id = picking.id
        picking.waybill_id = self.id
        self._rs_build_moves_on_picking(picking, src_loc, dst_loc)
        picking.with_context(skip_rs_auto_create=True).action_confirm()
        picking.with_context(skip_rs_auto_create=True).action_assign()


    # ── distribution truck: the goods leave the warehouse once ──

    def _rs_distribution_root(self):
        """ The distribution whose truck carries this waybill's goods: itself, or up
            through its parent distribution and the distribution it is a remainder of. """
        self.ensure_one()
        root = self
        while root.parent_waybill_id or root.remainder_origin_id:
            root = root.parent_waybill_id or root.remainder_origin_id
        return root

    def _rs_truck_take_out(self):
        """ The done transfer that moved this distribution's goods onto its truck. """
        self.ensure_one()
        return self.env['stock.picking'].search([
            ('rs_distribution_id', '=', self.id), ('state', '=', 'done'),
            ('location_id.usage', '=', 'internal'),
        ], order='id').filtered(
            lambda p: p.location_dest_id == p.location_dest_id.warehouse_id.rs_distribution_location_id
            and p.location_id != p.location_dest_id)[:1]

    def _rs_truck_location(self):
        """ Where this waybill's distribution goods are: the truck its distribution moved
            them to at activation. Empty for an older distribution whose sub-waybills
            took their goods straight from stock. """
        self.ensure_one()
        if not (self.parent_waybill_id or self.remainder_origin_id or self.waybill_type == '4'):
            return self.env['stock.location']
        return self._rs_distribution_root()._rs_truck_take_out().location_dest_id

    def _rs_truck_transfer(self, warehouse, src, dst, quantities, validate):
        """ An internal transfer of `quantities` {product: qty} for this distribution's
            truck, not linked to any waybill (validating a waybill's own transfer closes
            that waybill on RS.GE). Validated at once, or left Ready. """
        picking = self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': warehouse.int_type_id.id,
            'location_id': src.id,
            'location_dest_id': dst.id,
            'company_id': self.company_id.id,
            'origin': self.rs_waybill_number or _('Waybill %s') % (self.rs_internal_id or self.id),
            'rs_distribution_id': self.id,
        })
        self.env['stock.move'].with_context(skip_rs_auto_create=True).create([{
            'product_id': product.id,
            'product_uom_qty': qty,
            'uom_id': product.uom_id.id,
            'picking_id': picking.id,
            'location_id': src.id,
            'location_dest_id': dst.id,
            'company_id': self.company_id.id,
        } for product, qty in quantities.items() if qty > 0])
        picking.with_context(skip_rs_auto_create=True).action_confirm()
        if validate:
            self._force_validate_moves(picking.move_ids)
        else:
            picking.with_context(skip_rs_auto_create=True).action_assign()
        return picking

    def _rs_create_truck_take_out(self):
        """ Distribution activated: the goods leave the warehouse once, onto the truck
            (the warehouse's Distribution location). Sub-waybills deliver from there. """
        self.ensure_one()
        if self.state == 'draft' or self._rs_truck_take_out():
            return
        if self.sub_waybill_ids.filtered('picking_id'):
            # An older distribution: its subs took their goods straight from stock, so
            # taking the whole lot now would count them twice.
            return
        warehouse = self.source_warehouse_id or self.env['stock.warehouse'].search(
            [('company_id', '=', self.company_id.id)], limit=1)
        if not warehouse or not warehouse.int_type_id:
            return
        quantities = {}
        for line in self.line_ids.filtered('product_id'):
            quantities[line.product_id] = quantities.get(line.product_id, 0.0) + line._rs_base_qty()
        self._rs_truck_transfer(warehouse, warehouse.lot_stock_id,
                                warehouse._rs_distribution_location(), quantities, validate=True)

    def _rs_create_truck_return_from_waybill(self):
        """ Remainder made as a Return (type 5): the leftover goes from the truck back to
            the warehouse, Ready; Complete validates it. Nothing for an older distribution
            without a truck: its leftover never left the stock. """
        self.ensure_one()
        truck = self._rs_truck_location()
        if not truck:
            return
        picking = self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': truck.warehouse_id.int_type_id.id,
            'location_id': truck.id,
            'location_dest_id': truck.warehouse_id.lot_stock_id.id,
            'company_id': self.company_id.id,
            'origin': self.rs_waybill_number or _('Waybill %s') % (self.rs_internal_id or self.id),
            'rs_distribution_id': self._rs_distribution_root().id,
        })
        self.picking_id = picking.id
        picking.waybill_id = self.id
        self._rs_build_moves_on_picking(picking, truck, truck.warehouse_id.lot_stock_id)
        picking.with_context(skip_rs_auto_create=True).action_confirm()
        picking.with_context(skip_rs_auto_create=True).action_assign()

    def _rs_on_truck(self):
        """ {product: qty} of this distribution still on its truck and not promised:
            what came onto it, minus what left it or waits to leave it (an open
            sub-waybill delivery). """
        self.ensure_one()
        truck = self._rs_truck_take_out().location_dest_id
        left = {}
        moves = self.env['stock.picking'].search([('rs_distribution_id', '=', self.id)]).move_ids
        for move in moves.filtered(lambda m: m.state != 'cancel'):
            qty = move.uom_id._compute_quantity(
                move.quantity if move.state == 'done' else move.product_uom_qty, move.product_id.uom_id)
            if move.location_dest_id == truck and move.state == 'done':
                left[move.product_id] = left.get(move.product_id, 0.0) + qty
            elif move.location_id == truck:
                left[move.product_id] = left.get(move.product_id, 0.0) - qty
        return {product: qty for product, qty in left.items()
                if product.uom_id.compare(qty, 0.0) > 0}

    def _rs_bring_back_from_truck(self):
        """ Cancelled distribution: what is still on its truck goes back to the
            warehouse. Run again as each sub-waybill's open delivery is cancelled, so
            goods it held come back too; never brings anything back twice. """
        self.ensure_one()
        take_out = self._rs_truck_take_out()
        if self.state != 'cancelled' or not take_out:
            return
        quantities = self._rs_on_truck()
        if quantities:
            truck = take_out.location_dest_id
            self._rs_truck_transfer(truck.warehouse_id, truck, take_out.location_id,
                                    quantities, validate=True)


    def _rs_create_return_transfer_from_waybill(self):
        """ Return (type 5): create an incoming transfer bringing the goods back from the
            customer to our warehouse, in READY state. No SO. Complete validates it. """
        self.ensure_one()
        dst_wh = self.dest_warehouse_id or self.env['stock.warehouse'].search(
            [('company_id', '=', self.company_id.id)], limit=1)
        if not dst_wh or not dst_wh.in_type_id:
            return
        customer_loc = (self.buyer_id and self.buyer_id.property_stock_customer) \
                       or self.env.ref('stock.stock_location_customers', raise_if_not_found=False)
        if not customer_loc:
            return
        src_loc, dst_loc = customer_loc, dst_wh.lot_stock_id
        picking = self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': dst_wh.in_type_id.id,
            'location_id': src_loc.id,
            'location_dest_id': dst_loc.id,
            'partner_id': self.buyer_id.id if self.buyer_id else False,
            'company_id': self.company_id.id,
            'origin': self.rs_waybill_number or _('Waybill %s') % (self.rs_internal_id or self.id),
        })
        self.picking_id = picking.id
        picking.waybill_id = self.id
        self._rs_build_moves_on_picking(picking, src_loc, dst_loc)
        picking.with_context(skip_rs_auto_create=True).action_confirm()
        picking.with_context(skip_rs_auto_create=True).action_assign()


    def _rs_build_moves_on_picking(self, picking, src_loc, dst_loc):
        """ Create one stock.move per resolved waybill line on the given picking, linked
            to the line so later goods changes reach it. """
        self.ensure_one()
        Move = self.env['stock.move']
        for line in self.line_ids:
            if not line.product_id:
                continue
            line.stock_move_id = Move.with_context(skip_rs_auto_create=True).create({
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'uom_id': line._rs_unit().id,
                'picking_id': picking.id,
                'location_id': src_loc.id,
                'location_dest_id': dst_loc.id,
                'company_id': self.company_id.id,
                'description_picking': line.name or line.product_id.name or '',
            })


    def _build_line_snapshot(self):
        """ JSON snapshot of the current goods lines, used to diff what changed — by the
            Edit Waybill flow and by the RS-driven auto-sync. """
        self.ensure_one()
        return json.dumps([{
            'line_id': line.id,
            'product_id': line.product_id.id,
            'quantity': line.quantity,
            'base_quantity': line._rs_base_qty(),
            'unit_price': line.unit_price,
            'name': line.name,
            'rs_good_id': line.rs_good_id,
            'stock_move_id': line.stock_move_id.id if line.stock_move_id else None,
        } for line in self.line_ids])


    def _compute_line_diff(self, snapshot_json):
        """ Diff snapshot_json (the lines before the change) against line_ids, unchanged lines omitted. Returns dicts {type: qty_down|qty_up|
            added|removed, product_id, old_qty, new_qty, qty_diff (positive), line, snap};
            a product swap splits into removed + added. Quantities are in the product's unit, so a line whose unit
            changed (2 x Pack of 12 -> 24 Units) is no change. """
        self.ensure_one()
        if not snapshot_json:  # a Retry from a stale page: the RS.GE change was already applied
            return []
        snapshot = json.loads(snapshot_json)
        diffs = []
        snap_ids = {s['line_id'] for s in snapshot}

        def snap_qty(snap, line=None):
            # A snapshot saved before base_quantity existed holds the line's own unit.
            if 'base_quantity' in snap:
                return snap['base_quantity']
            return line._rs_base_qty(snap['quantity']) if line else snap['quantity']

        def removed(snap):
            old = snap_qty(snap)
            return {'type': 'removed', 'product_id': snap['product_id'], 'old_qty': old, 'new_qty': 0,
                    'qty_diff': old, 'line': None, 'snap': snap}

        def added(line):
            # An added line has no snapshot counterpart (never reuse the previous loop's `snap`).
            new = line._rs_base_qty()
            return {'type': 'added', 'product_id': line.product_id.id, 'old_qty': 0, 'new_qty': new,
                    'qty_diff': new, 'line': line, 'snap': None}

        for snap in snapshot:
            line = self.line_ids.filtered(lambda l: l.id == snap['line_id'])
            if not line:
                diffs.append(removed(snap))
                continue
            if line.product_id.id != snap['product_id']:
                diffs.append(removed(snap))
                diffs.append(added(line))
                continue
            old, new = snap_qty(snap, line), line._rs_base_qty()
            change = line.product_id.uom_id.compare(new, old) if line.product_id else (new > old) - (new < old)
            if change:
                diffs.append({
                    'type': 'qty_up' if change > 0 else 'qty_down',
                    'product_id': line.product_id.id,
                    'old_qty': old,
                    'new_qty': new,
                    'qty_diff': abs(new - old),
                    'line': line,
                    'snap': snap,
                })
        for line in self.line_ids:
            if line.id not in snap_ids:
                diffs.append(added(line))

        return diffs


    def _rs_unlock_orders(self, picking):
        """ Lock Confirmed Sales: the waybill is the legal document, so a locked order still follows its goods
            changes. Unlocked only for that change; the caller locks it again. """
        orders = (self.sales_order_id | picking.sale_id | picking.move_ids.sale_line_id.order_id).filtered('locked')
        orders.locked = False
        return orders


    def _rs_note_followed_orders(self, orders):
        for order in orders:
            order.message_post(body=_("Changed to follow waybill %s; the order stays locked.") % self.display_name)


    def _apply_line_diffs_to_picking_in_place(self, diffs):
        """ Goods changes on the linked picking while not done (caller checks): demand changed, move added or removed.
            The SO line follows; a locked order is unlocked for this change only. """
        self.ensure_one()
        picking = self.picking_id
        if not picking:
            return
        Move = self.env['stock.move']
        # A return (type 5) changes what came back, never what was ordered: Odoo lowers the delivered qty itself.
        returning = self.waybill_type == '5'

        orders = self._rs_unlock_orders(picking) if not returning else self.env['sale.order']
        try:
            for d in diffs:
                dtype = d['type']

                if dtype in ('qty_down', 'qty_up'):
                    line = d['line']
                    move = self._rs_line_move(line)
                    if move:
                        # Diffs are in the product's unit; the move and the SO line keep their own.
                        unit = move.product_id.uom_id
                        move.product_uom_qty = unit._compute_quantity(d['new_qty'], move.uom_id)
                        # Move the SO line by the same delta, not to the waybill qty (it may be split over several
                        # deliveries). skip_procurement stops Odoo re-adjusting the open move.
                        if move.sale_line_id and not returning:
                            move.sale_line_id.with_context(skip_procurement=True).product_uom_qty += (
                                unit._compute_quantity(d['new_qty'] - d['old_qty'], move.sale_line_id.product_uom_id))

                elif dtype == 'added':
                    # New product: a move on this picking and an SO line (skip_procurement: no duplicate move), linked
                    # so qty_delivered attaches at validation.
                    line = d['line']
                    new_move = Move.create({
                        'product_id': line.product_id.id,
                        'product_uom_qty': line.quantity,
                        'uom_id': line._rs_unit().id,
                        'picking_id': picking.id,
                        'location_id': picking.location_id.id,
                        'location_dest_id': picking.location_dest_id.id,
                        'company_id': picking.company_id.id,
                        'description_picking': line.name or line.product_id.name or '',
                    })
                    so = (self.sales_order_id or picking.sale_id) if not returning else False
                    if so:
                        so_line = self.env['sale.order.line'].with_context(
                            skip_procurement=True
                        ).create({
                            'order_id': so.id,
                            'product_id': line.product_id.id,
                            'product_uom_qty': line.quantity,
                            'product_uom_id': line._rs_unit().id,
                            'price_unit': line.unit_price,
                        })
                        so_line.price_unit = self._rs_order_price(line.unit_price, so_line)
                        new_move.sale_line_id = so_line.id
                    new_move._action_confirm()
                    new_move._action_assign()
                    line.stock_move_id = new_move.id

                elif dtype == 'removed':
                    # Removed in the popup: cancel + unlink its move and reduce/remove the SO line so both drop
                    # together. skip_procurement on the SO write stops Odoo re-procuring the move.
                    snap = d.get('snap') or {}
                    move_id = snap.get('stock_move_id')
                    move = Move.browse(move_id) if move_id else self._rs_line_move(
                        None, self.env['product.product'].browse(snap.get('product_id')))
                    so_line = move.sale_line_id if move.exists() and not returning else False
                    if move.exists():
                        # Cancel first so Odoo releases any reservation, then delete the move
                        move._action_cancel()
                        move.unlink()
                    if so_line and so_line.exists():
                        # Odoo forbids deleting a confirmed SO line: zero it instead (its move is already cancelled);
                        # skip_procurement stops re-procurement.
                        removed_qty = self.env['product.product'].browse(d['product_id']).uom_id._compute_quantity(
                            d['qty_diff'], so_line.product_uom_id)
                        remaining = max(so_line.product_uom_qty - removed_qty, 0.0)
                        so_line.with_context(skip_procurement=True).write(
                            {'product_uom_qty': remaining})


            picking.action_assign()
        finally:
            orders.locked = True
        self._rs_note_followed_orders(orders)


    def _apply_line_diffs_increase_on_done(self, diffs):
        """ More goods than the done delivery recorded (qty up / product added): that delivery and its SO line follow,
            no second waybill. A lot product without a lot raises. """
        self.ensure_one()
        picking = self.picking_id
        if not picking or picking.state != 'done':
            return
        returning = self.waybill_type == '5'

        orders = self._rs_unlock_orders(picking) if not returning else self.env['sale.order']
        try:
            for d in diffs:
                if d['type'] == 'qty_up':
                    move = self._rs_line_move(d['line'])
                    if not move or move.state != 'done':
                        continue
                    unit = move.product_id.uom_id
                    move.quantity = unit._compute_quantity(d['new_qty'], move.uom_id)
                    self._rs_check_tracked_lines(move)
                    move.product_uom_qty = move.quantity
                    # SO line + the same delta (it may cover other deliveries too); a return leaves the order alone
                    if move.sale_line_id and not returning:
                        move.sale_line_id.with_context(skip_procurement=True).product_uom_qty += (
                            unit._compute_quantity(d['qty_diff'], move.sale_line_id.product_uom_id))

                elif d['type'] == 'added':
                    line = d['line']
                    if not line.product_id:
                        self.message_post(body=_(
                            "Line '%s' was added on the waybill without a product, so the "
                            "delivery was not changed. Map the product and record the stock "
                            "movement manually.") % (line.name or _('product')))
                        continue
                    so = (self.sales_order_id or picking.sale_id) if not returning else False
                    so_line = self.env['sale.order.line']
                    if so:
                        so_line = so_line.with_context(skip_procurement=True, skip_rs_auto_create=True).create({
                            'order_id': so.id,
                            'product_id': line.product_id.id,
                            'product_uom_qty': line.quantity,
                            'product_uom_id': line._rs_unit().id,
                            'price_unit': line.unit_price,
                        })
                        so_line.price_unit = self._rs_order_price(line.unit_price, so_line)
                    move = self.env['stock.move'].with_context(skip_rs_auto_create=True).create({
                        'product_id': line.product_id.id,
                        'product_uom_qty': line.quantity,
                        'uom_id': line._rs_unit().id,
                        'picking_id': picking.id,
                        'location_id': picking.location_id.id,
                        'location_dest_id': picking.location_dest_id.id,
                        'company_id': picking.company_id.id,
                        'sale_line_id': so_line.id,
                    })
                    move.quantity = line.quantity
                    move.picked = True
                    self._rs_check_tracked_lines(move)
                    line.stock_move_id = move
        finally:
            orders.locked = True
        self._rs_note_followed_orders(orders)


    def _rs_line_move(self, line, product=None):
        """ The delivery move of a goods line; without a stored link, the only move of that product is taken and linked.
            None or several raise (held: banner + Retry). A line without product: empty. """
        Move = self.env['stock.move']
        if line and line.stock_move_id:
            return line.stock_move_id
        product = product or (line.product_id if line else self.env['product.product'])
        if not product or not self.picking_id:
            return Move
        linked = self.line_ids.stock_move_id
        moves = self.picking_id.move_ids.filtered(
            lambda m: m.state != 'cancel' and m.product_id == product
            and not m.origin_returned_move_id and m not in linked)
        if not moves:
            raise UserError(_("Delivery %(picking)s has no line of %(product)s, so the waybill "
                              "change cannot be applied to it. Fix the delivery, then try again.")
                            % {'picking': self.picking_id.name, 'product': product.display_name})
        if len(moves) > 1:
            raise UserError(_("Delivery %(picking)s has %(count)s lines of %(product)s, so Odoo "
                              "cannot tell which one this waybill line is. Fix the delivery, "
                              "then try again.")
                            % {'picking': self.picking_id.name, 'count': len(moves),
                               'product': product.display_name})
        if line:
            line.stock_move_id = moves
        return moves


    def _rs_check_tracked_lines(self, move):
        """ The extra quantity of a lot/serial product must carry a lot: core falls back
            to a line without one when no lot in stock covers it. """
        if move.product_id.tracking not in ('lot', 'serial'):
            return
        if move.move_line_ids.filtered(lambda ml: not ml.lot_id and not ml.lot_name):
            raise UserError(_(
                "%(product)s is tracked by lot/serial number, but no lot in stock covers the "
                "extra %(qty)s on delivery %(picking)s. Receive or select the lot/serial "
                "number first, then apply the change again.") % {
                    'product': move.product_id.display_name,
                    'qty': move.quantity - sum(move.move_line_ids.filtered('lot_id').mapped('quantity')),
                    'picking': move.picking_id.name})


    def _qty_to_return_from_diffs(self, diffs):
        """ Aggregate {product_id: qty} to return from qty_down / removed diffs.
            qty_diff is always the positive magnitude of the decrease. """
        qty_to_return = {}
        for d in diffs:
            if d['type'] in ('qty_down', 'removed'):
                pid = d['product_id']
                qty_to_return[pid] = qty_to_return.get(pid, 0.0) + d['qty_diff']
        return qty_to_return


    def _rs_lower_done_delivery(self, qty_by_product):
        """ Decrease on a completed waybill ({product_id: qty}): lowers the done delivery in place, goods return to
            where each move line took them; no return document or type-5 waybill. Returns per move the corrections:
            {product_id, qty, sale_line_id, chunks: [[location_id, lot_id, qty]]}. """
        self.ensure_one()
        picking = self.picking_id
        if not picking or picking.state != 'done':
            return []
        entries = []
        changes = []
        for pid, qty in qty_by_product.items():
            product = self.env['product.product'].browse(pid)
            unit = product.uom_id
            moves = picking.move_ids.filtered(lambda m: m.state == 'done' and m.product_id == product)
            for move in moves.sorted('id', reverse=True):
                if unit.compare(qty, 0) <= 0:
                    break
                take = min(qty, move.uom_id._compute_quantity(move.quantity, unit))
                if unit.is_zero(take):
                    continue
                before = {ml.id: (ml.location_id.id, ml.lot_id.id, ml.uom_id._compute_quantity(ml.quantity, unit))
                          for ml in move.move_line_ids}
                old_qty = move.quantity
                move.quantity = old_qty - unit._compute_quantity(take, move.uom_id)
                move.product_uom_qty = move.quantity
                qty -= take
                after = {ml.id: ml.uom_id._compute_quantity(ml.quantity, unit) for ml in move.move_line_ids}
                chunks = []
                for ml_id, (location_id, lot_id, ml_qty) in before.items():
                    back = ml_qty - after.get(ml_id, 0.0)
                    if not unit.is_zero(back):
                        chunks.append([location_id, lot_id or False, back])
                changes.append("%s: %s → %s" % (product.display_name, old_qty, move.quantity))
                entries.append({'product_id': product.id, 'qty': take,
                                'sale_line_id': move.sale_line_id.id or False, 'chunks': chunks})
        if changes:
            picking.message_post(body=Markup(_(
                "Waybill %(waybill)s was lowered, so this delivery was lowered with it and the "
                "difference is back in stock:<br/>%(changes)s")) % {
                    'waybill': self.display_name, 'changes': Markup('<br/>').join(changes)})
        return entries


    def _rs_load_pending_corrections(self):
        """ The corrections waiting for the operator, as a list. A legacy dict {product_id: qty} is
            lowered now, so a waybill synced by old code ends in the same state. """
        self.ensure_one()
        if not self.pending_return_json:
            return []
        try:
            data = json.loads(self.pending_return_json)
        except (ValueError, TypeError):
            data = []
        if isinstance(data, dict):
            data = self._rs_lower_done_delivery({int(k): v for k, v in data.items() if v})
            self.pending_return_json = json.dumps(data) if data else False
        return data if isinstance(data, list) else []


    def _rs_refresh_return_question(self):
        """ A done return changed on RS.GE: its waiting 'deliver later or reduce?' question is asked again about what
            came back now (10 -> 8 returned: about 8). Already answered: the order is not changed twice; say so. """
        self.ensure_one()
        receipt = self.picking_id
        if self.waybill_type != '5' or not receipt or not receipt.move_ids.sale_line_id:
            return
        entries = self._rs_load_pending_corrections()
        if not any(e.get('returned') for e in entries):
            self.message_post(body=_("The goods of this return changed on RS.GE after the sales order was "
                                     "settled. Check %s: it was settled for the old quantity.")
                              % ', '.join(receipt.move_ids.sale_line_id.order_id.mapped('name')))
            return
        others = [e for e in entries if not e.get('returned')]
        self.pending_return_json = json.dumps(others) if others else False
        receipt._rs_ask_order_after_return()


    def _rs_add_pending_corrections(self, entries):
        """ Keep the corrections until the popup is answered: closing it leaves the
            'Reconcile Delivery' banner instead of losing the decision. """
        self.ensure_one()
        if not entries:
            return
        self.pending_return_json = json.dumps(self._rs_load_pending_corrections() + entries)


    def _rs_scrap_correction(self, product, chunks):
        """ Goods lowered off a completed waybill that were lost or damaged: scrap them from exactly where the lowering
            put them back (location, lot), so they leave stock as a loss. """
        self.ensure_one()
        scrap_location = self.company_id.scrap_location_id
        if not scrap_location:
            raise UserError(_("Company %s has no scrap location.") % self.company_id.name)
        scraps = self.env['stock.move']
        for location_id, lot_id, qty in chunks:
            scraps |= self.env['stock.move'].create({
                'product_id': product.id,
                'product_uom_qty': qty,
                'uom_id': product.uom_id.id,
                'location_id': location_id,
                'location_dest_id': scrap_location.id,
                'picking_id': self.picking_id.id,
                'company_id': self.company_id.id,
                'origin': self.picking_id.name,
                'move_line_ids': [(0, 0, {
                    'product_id': product.id,
                    'location_id': location_id,
                    'location_dest_id': scrap_location.id,
                    'lot_id': lot_id,
                    'quantity': qty,
                    'uom_id': product.uom_id.id,
                })],
            })
        # One at a time: Odoo's _action_scrap handles a single move (two lots or two locations would crash).
        for scrap in scraps:
            scrap._action_scrap()
        return scraps


    def _rs_deliver_later(self, sale_lines):
        """ The customer still wants what was lowered: the SO keeps its quantity and procurement creates a delivery
            for the uncovered part (own waybill). A locked order is not procured: activity for its salesperson. """
        self.ensure_one()
        locked = sale_lines.order_id.filtered('locked')
        for order in locked:
            order.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_("Deliver the rest: waybill quantity lowered"),
                note=_("Waybill %s was lowered and the customer still wants the rest. The order "
                       "is locked, so no new delivery was created: unlock it and create one.")
                     % self.display_name,
                user_id=(order.user_id or self.env.user).id)
        open_lines = sale_lines.filtered(lambda l: not l.order_id.locked)
        if not open_lines:
            return
        before = open_lines.order_id.picking_ids
        open_lines._action_launch_stock_rule()
        for order in open_lines.order_id:
            new = order.picking_ids - before
            order.message_post(body=_("Waybill %(waybill)s was lowered; the rest will be delivered "
                                      "later: %(pickings)s.") % {
                'waybill': self.display_name,
                'pickings': ', '.join(new.mapped('name')) or _('added to an open delivery')})


    def _rs_lower_sale_lines(self, lowered):
        """ Lower each SO line by {sale.order.line: qty} ("Reduce the order"), never below delivered,
            under skip_procurement. A locked order, or one invoiced above the new quantity (credit note needed),
            gets an activity instead. """
        for order in self.env['sale.order'].union(*(sol.order_id for sol in lowered)):
            user = order.user_id or self.env.user
            if order.locked:
                order.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_("Adjust the order: waybill quantity lowered"),
                    note=_("Waybill %s was lowered on RS.GE. The order is locked, so it was not "
                           "changed: unlock it and lower the quantities.") % self.display_name,
                    user_id=user.id)
                continue
            changes = []
            for sol, qty in lowered.items():
                if sol.order_id != order:
                    continue
                new_qty = max(sol.product_uom_qty - qty, sol.qty_delivered)
                if not sol.product_uom_id.compare(new_qty, sol.product_uom_qty):
                    continue
                changes.append("%s: %s → %s" % (sol.product_id.display_name,
                                                sol.product_uom_qty, new_qty))
                sol.with_context(skip_procurement=True).product_uom_qty = new_qty
            if changes:
                order.message_post(body=Markup(_(
                    "Ordered quantities lowered with waybill %(waybill)s:<br/>%(changes)s")) % {
                        'waybill': self.display_name, 'changes': Markup('<br/>').join(changes)})
            over_invoiced = order.order_line.filtered(
                lambda l: l.product_uom_id.compare(l.qty_invoiced, l.product_uom_qty) > 0)
            if over_invoiced:
                order.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_("Credit note needed: waybill quantity lowered"),
                    note=_("Waybill %(waybill)s was lowered and the order with it. Invoiced more "
                           "than ordered on: %(products)s. Issue a credit note.")
                         % {'waybill': self.display_name,
                            'products': ', '.join(over_invoiced.mapped('product_id.display_name'))},
                    user_id=user.id)


    def _create_return_picking(self, qty_to_return, create_waybill=True, delivery=None):
        """ Return picking for {product_id: qty} against the linked done delivery, or `delivery`.
            create_waybill=True: physical return, auto type-5 waybill; False: skip_rs_auto_create (documented on RS).
            Returns the picking, or False if nothing to return. """
        self.ensure_one()
        picking = delivery or self.picking_id
        if not picking or picking.state != 'done' or not qty_to_return:
            return False
        skip = not create_waybill
        # _create_return() copies every non-cancelled move at quantity 0, picking in draft: set quantities, drop
        # unreturned lines, confirm, assign, same skip flag. Returnable qty (shipped - returned) is read first.
        returnable = {move: move._rs_returnable_qty() for move in picking.move_ids}
        return_picking = picking.with_context(skip_rs_auto_create=skip)._create_return()
        remaining = dict(qty_to_return)
        for move in return_picking.move_ids:
            unit = move.product_id.uom_id
            want = remaining.get(move.product_id.id, 0.0)
            origin = move.origin_returned_move_id
            # Per-move share, capped at what that move can still give back: two moves of one product
            # must not return it twice, nor a delivery returned once be returned again.
            left = origin.uom_id._compute_quantity(returnable.get(origin, 0.0), unit)
            take = min(want, left) if want else 0.0
            move.product_uom_qty = unit._compute_quantity(take, move.uom_id)
            if take:
                remaining[move.product_id.id] = want - take
        return_picking.move_ids.filtered(lambda m: not m.product_uom_qty).unlink()
        if not return_picking.move_ids:
            return_picking.unlink()
            return False
        return_picking.with_context(skip_rs_auto_create=skip).action_confirm()
        return_picking.with_context(skip_rs_auto_create=skip).action_assign()
        return return_picking


    def _open_return_decision_wizard(self, entries):
        """ Open the correction popup for lowered goods: back in stock or lost (scrap) and, with a sales order,
            deliver later or reduce the order. """
        self.ensure_one()
        if not entries:
            return {'type': 'ir.actions.act_window_close'}
        wizard = self.env['rs.waybill.return.decision.wizard'].create({
            'waybill_id': self.id,
            'entry_count': len(entries),
            'line_ids': [(0, 0, {
                'product_id': entry['product_id'],
                'qty': entry['qty'],
                'sale_line_id': entry.get('sale_line_id') or False,
                'chunks_json': json.dumps(entry.get('chunks') or []),
                'returned': bool(entry.get('returned')),
            }) for entry in entries],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Goods No Longer on the Waybill'),
            'res_model': 'rs.waybill.return.decision.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }


    def _apply_rs_goods_diff_auto(self, snapshot_json):
        """ RS-driven goods change down to SO/PO + transfer (snapshot_json = old lines); all or nothing;
            a refusal stays in rs_goods_pending_snapshot for Retry/drift. Seller: undelivered or up/added: applied;
            delivered down/removed: lowered (pending_return_json). Buyer: deferred to Receive. True if docs follow. """
        self.ensure_one()
        if not self.picking_id:
            return True
        if self.rs_adjustment_error:
            # The lines hold an Adjustment RS.GE did not take, not RS.GE's goods: nothing to apply until it is sent or discarded
            return False
        # An open Adjustment started from the old lines: its Submit must refuse and reload, not apply this RS.GE change again
        self.edit_snapshot_json = False
        # A change that failed earlier is still missing from the documents: diff from the state
        # they still show, so the old and the new RS change go in together.
        snapshot_json = self.rs_goods_pending_snapshot or snapshot_json
        blocked = self._rs_auto_apply_blocked()
        if blocked and self._compute_line_diff(snapshot_json):
            # e.g. attached to an invoice: the documents must keep matching it.
            self._rs_hold_goods_change(snapshot_json, blocked)
            return False
        try:
            # All or nothing: a refusal on one line (e.g. no lot covers it) must not leave the others applied;
            # the lines already show the RS state, so a half-applied change could never be seen or retried.
            with self.env.cr.savepoint():
                self._rs_apply_goods_diffs(snapshot_json)
        except Exception as e:
            _logger.warning("RS goods change not applied to the documents of waybill %s: %s", self.id, e)
            self._rs_hold_goods_change(snapshot_json, str(e))
            return False
        if self.rs_goods_pending_snapshot:
            self.rs_goods_pending_snapshot = False
            self.message_post(body=_("The goods change made on RS.GE is now applied to the "
                                     "delivery / order."))
            if self.rs_post_commit_error and not self._rs_has_outstanding_step():
                self.rs_post_commit_error = False
        return True


    def _rs_auto_apply_blocked(self):
        """ Why a goods change made on RS.GE must not reach the delivery / order now, or
            False. Hook: rs_base_methods holds it while an invoice holds the waybill. """
        return False


    def _rs_hold_goods_change(self, snapshot_json, reason):
        """ Keep a goods change made on RS.GE that did not reach the delivery / order:
            shown on the waybill, retried by Retry and by the drift job. """
        first = not self.rs_goods_pending_snapshot
        self.rs_goods_pending_snapshot = snapshot_json
        self.rs_post_commit_error = _("Apply the RS.GE goods change: %s") % reason
        if first:
            self.message_post(body=_(
                "The goods change made on RS.GE could not be applied to the delivery / "
                "order: %s. Nothing was changed. Fix the cause and click Retry; the drift "
                "job also retries it.") % reason)


    def _rs_apply_goods_diffs(self, snapshot_json):
        """ Body of _apply_rs_goods_diff_auto, run inside its savepoint: raises on refusal. """
        diffs = self._compute_line_diff(snapshot_json)
        if not diffs:
            return
        # BUYER direction: defer ALL goods changes to the buyer's Receive click.
        # Receive then applies it: received in full, or the done receipt corrected.
        if self.waybill_direction == 'buyer':
            delta = self._signed_delta_from_diffs(diffs)
            if delta:
                self._accumulate_pending_goods_delta(delta)
                self.is_buyer_reconfirm_needed = True
                self.message_post(body=Markup(_(
                    "Vendor changed goods on this waybill. Click <b>Receive</b> to apply "
                    "the change to the PO and receipt, or <b>Reject</b> to decline.")))
            return
        if self.picking_id.state == 'done':
            self._apply_line_diffs_increase_on_done(diffs)
            # qty_down / removed: the delivery follows at once (stock right); where the
            # goods are and what the order does is asked via 'Reconcile Delivery'.
            entries = self._rs_lower_done_delivery(self._qty_to_return_from_diffs(diffs))
            # Fewer goods came back on a return: lowering its receipt is the whole correction (Odoo counts
            # the delivered qty back up). Nothing went back to a shelf, so there is nothing to ask.
            if entries and self.waybill_type != '5':
                self._rs_add_pending_corrections(entries)
                self.message_post(body=Markup(_(
                    "RS lowered goods on this delivered waybill. The delivery was lowered "
                    "with it. Open the waybill and click <b>Reconcile Delivery</b> to say "
                    "where the goods are and whether the customer still wants them.")))
            self._rs_refresh_return_question()
        else:
            self._apply_line_diffs_to_picking_in_place(diffs)


    def action_retry_rs_goods_change(self):
        """ Banner button: apply the RS.GE goods change that was refused before. """
        self.ensure_one()
        if self.rs_adjustment_error:
            raise UserError(_("Click Discard Adjustment first, then Retry."))
        if not self._apply_rs_goods_diff_auto(False):
            raise UserError(self.rs_post_commit_error)


    def _signed_delta_from_diffs(self, diffs):
        """ BUYER direction: per-line diffs to a {product_id: signed qty} map (+ vendor added or
            increased, - vendor reduced or removed), accumulated into pending_goods_json for Receive. """
        delta = {}
        for d in diffs:
            pid = d['product_id']
            if d['type'] == 'qty_up':
                delta[pid] = delta.get(pid, 0.0) + d['qty_diff']
            elif d['type'] == 'qty_down':
                delta[pid] = delta.get(pid, 0.0) - d['qty_diff']
            elif d['type'] == 'added':
                delta[pid] = delta.get(pid, 0.0) + d['new_qty']
            elif d['type'] == 'removed':
                delta[pid] = delta.get(pid, 0.0) - d['old_qty']
        return delta


    def _accumulate_pending_goods_delta(self, delta):
        """ BUYER direction: merge a delta into pending_goods_json, additive per product (several vendor
            edits before one Receive net out); zero-net entries are dropped. """
        self.ensure_one()
        existing = {}
        if self.pending_goods_json:
            try:
                existing = {int(k): v for k, v in json.loads(self.pending_goods_json).items()}
            except (ValueError, TypeError):
                existing = {}
        for pid, q in delta.items():
            existing[pid] = existing.get(pid, 0.0) + q
        existing = {pid: q for pid, q in existing.items() if abs(q) > 0.0001}
        self.pending_goods_json = json.dumps(existing) if existing else False


    def _rs_owns_purchase(self):
        """ True when the PO was made from this waybill (also by the code before the
            purchase_created flag: its origin is the waybill number). Only such a PO has
            its ordered quantities follow the waybill. """
        self.ensure_one()
        po = self.purchase_id
        return bool(po) and (self.purchase_created or bool(
            self.rs_waybill_number and po.origin == self.rs_waybill_number))


    def _rs_buyer_target(self):
        """ {product: quantity in the product's unit} the vendor declares on this waybill. """
        self.ensure_one()
        target = {}
        for line in self.line_ids.filtered('product_id'):
            target[line.product_id] = target.get(line.product_id, 0.0) + line._rs_base_qty()
        return target


    def _rs_receive_waybill_goods(self):
        """ Buyer Received: book this waybill's goods on the PO's open receipt, or correct the done one in place.
            Raises without approval or an open receipt; lot products wait for the purchaser (to-do). """
        self.ensure_one()
        po = self.purchase_id
        if self.waybill_direction != 'buyer' or self.is_confirmed != '1' or not po:
            return
        if po.state != 'purchase':
            raise UserError(_("Purchase order %s is not confirmed (it may wait for approval): "
                              "approve it, then the goods are received.") % po.name)
        target = self._rs_buyer_target()
        if self.picking_id.state == 'done':
            self._rs_correct_received_goods(self.picking_id, target)
            return
        PoLine = self.env['purchase.order.line'].with_context(skip_rs_auto_create=True)
        for product, qty in target.items():
            if self._rs_owns_purchase():
                for po_line, want in self._rs_own_po_lines(product):
                    po_line.product_qty = product.uom_id._compute_quantity(want, po_line.uom_id)
                continue
            line = po.order_line.filtered(lambda l: l.product_id == product and not l.display_type)[:1]
            waybill_line = self.line_ids.filtered(lambda l: l.product_id == product)[:1]
            if not line:
                # The vendor added a product the PO does not have: it comes at the waybill
                # price; core puts its move on the open receipt.
                added = PoLine.create(dict(self._rs_purchase_line_vals(
                    product, qty, waybill_line._rs_base_price(), waybill_line.name), order_id=po.id))
                added.price_unit = self._rs_order_price(waybill_line._rs_base_price(), added)
        receipt = self.picking_id if self.picking_id.state not in ('done', 'cancel') else False
        receipt = receipt or po.picking_ids.filtered(
            lambda p: p.picking_type_code == 'incoming' and p.state not in ('done', 'cancel'))[:1]
        if not receipt:
            raise UserError(_("Purchase order %s has no open receipt left for these goods.") % po.name)
        self.picking_id = receipt
        receipt.waybill_id = self.id
        moves = receipt.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
        tracked = moves.filtered(lambda m: m.product_id in target and m.product_id.tracking in ('lot', 'serial'))
        if tracked:
            self._rs_ask_lots(receipt, tracked.product_id)
            return
        for product in moves.product_id:
            # RS.GE has one line per product, the PO may have several (two prices or
            # dates): fill each in order up to its demand, any extra on the last one.
            qty = target.pop(product, 0.0)
            product_moves = moves.filtered(lambda m: m.product_id == product).sorted('id')
            for move in product_moves:
                demand = move.uom_id._compute_quantity(move.product_uom_qty, product.uom_id)
                give = qty if move == product_moves[-1] else min(qty, demand)
                move.quantity = product.uom_id._compute_quantity(give, move.uom_id)
                move.picked = not product.uom_id.is_zero(give)
                qty -= give
        if target:
            raise UserError(_("Receipt %(receipt)s has no line for: %(products)s.") % {
                'receipt': receipt.name, 'products': ', '.join(p.display_name for p in target)})
        if not moves.filtered('picked'):
            raise UserError(_("Receipt %s holds none of this waybill's goods.") % receipt.name)
        result = receipt.with_context(skip_backorder=True, skip_rs_auto_create=True).button_validate()
        if isinstance(result, dict) and result.get('type') == 'ir.actions.act_window':
            raise UserError(_("Receipt %s needs a manual confirmation: open it and validate.")
                            % receipt.name)
        self.message_post(body=_("Goods received on %(receipt)s (purchase order %(po)s).")
                          % {'receipt': receipt.name, 'po': po.name})


    def _rs_own_po_lines(self, product, **ctx):
        """ PO made from this waybill: [(po_line, qty in product unit)], each waybill line of `product` with its own PO
            line (new one at its price if missing; leftover PO lines get 0). Quantities are written by the caller. """
        self.ensure_one()
        po = self.purchase_id
        waybill_lines = self.line_ids.filtered(lambda l: l.product_id == product).sorted('id')
        po_lines = po.order_line.filtered(lambda l: l.product_id == product and not l.display_type).sorted('id')
        free = po_lines - waybill_lines.purchase_line_id
        pairs = []
        for waybill_line in waybill_lines:
            po_line = waybill_line.purchase_line_id & po_lines
            if not po_line and free:
                po_line, free = free[:1], free[1:]
            if not po_line:
                po_line = self.env['purchase.order.line'].with_context(skip_rs_auto_create=True, **ctx).create(dict(
                    self._rs_purchase_line_vals(product, waybill_line.quantity, waybill_line.unit_price,
                                                waybill_line.name, waybill_line._rs_unit()), order_id=po.id))
                po_line.price_unit = self._rs_order_price(waybill_line.unit_price, po_line)
            waybill_line.purchase_line_id = po_line
            pairs.append((po_line, waybill_line._rs_base_qty()))
        pairs += [(po_line, 0.0) for po_line in free]
        return pairs


    def _rs_correct_own_po_lines(self, receipt, product):
        """ Received PO made from this waybill: each PO line's done move, then the PO line, follow its waybill line
            (moves first, so the PO does not open a receipt for the difference). Returns the change texts. """
        changes = []
        done = receipt.move_ids.filtered(lambda m: m.state == 'done' and m.product_id == product)
        for po_line, want in self._rs_own_po_lines(product, bypass_move_update=True):
            moves = done.filtered(lambda m: m.purchase_line_id == po_line).sorted('id')
            have = sum(m.uom_id._compute_quantity(m.quantity, product.uom_id) for m in moves)
            if product.uom_id.compare(want, have):
                if product.tracking in ('lot', 'serial'):
                    raise UserError(_("%(product)s is tracked by lot/serial number: correct receipt "
                                      "%(receipt)s by hand to %(qty)s.")
                                    % {'product': product.display_name, 'receipt': receipt.name, 'qty': want})
                if moves:
                    move = moves[-1]
                    others = have - move.uom_id._compute_quantity(move.quantity, product.uom_id)
                    new_qty = move.uom_id.round(product.uom_id._compute_quantity(max(want - others, 0.0),
                                                                                  move.uom_id))
                    move.quantity = new_qty
                    move.product_uom_qty = new_qty
                else:
                    move = self.env['stock.move'].with_context(skip_rs_auto_create=True).create({
                        'description_picking': po_line.name or product.display_name,
                        'product_id': product.id,
                        'product_uom_qty': want,
                        'uom_id': product.uom_id.id,
                        'picking_id': receipt.id,
                        'location_id': receipt.location_id.id,
                        'location_dest_id': receipt.location_dest_id.id,
                        'purchase_line_id': po_line.id,
                        'company_id': receipt.company_id.id,
                    })
                    self._force_validate_moves(move)
                changes.append("%s: %s → %s" % (product.display_name, have, want))
            po_line.with_context(skip_rs_auto_create=True).product_qty = \
                product.uom_id._compute_quantity(want, po_line.uom_id)
        return changes


    def _rs_ask_lots(self, receipt, products):
        """ Lot/serial goods wait on the open receipt: one to-do for the purchaser, not repeated by drift. """
        summary = _("Enter lot/serial numbers on %s") % receipt.name
        if self.activity_ids.filtered(lambda a: a.summary == summary):
            return
        self.activity_schedule(
            'mail.mail_activity_data_todo', summary=summary,
            note=_("%(products)s need lot/serial numbers: open receipt %(receipt)s, enter them with "
                   "the quantities of this waybill and validate it.")
                 % {'products': ', '.join(products.mapped('display_name')), 'receipt': receipt.name},
            user_id=(self.purchase_id.user_id or self.env.user).id)


    def _rs_correct_received_goods(self, receipt, target):
        """ Vendor changed a received waybill: same done receipt corrected, added product received at the waybill price;
            no transfer back. A PO made from this waybill has its ordered quantities corrected too. """
        self.ensure_one()
        po = self.purchase_id
        done = receipt.move_ids.filtered(lambda m: m.state == 'done')
        changes = []
        for product in set(target) | set(done.product_id):
            if self._rs_owns_purchase() and (
                    len(self.line_ids.filtered(lambda l: l.product_id == product)) > 1
                    or len(po.order_line.filtered(lambda l: l.product_id == product and not l.display_type)) > 1):
                changes += self._rs_correct_own_po_lines(receipt, product)
                continue
            want = target.get(product, 0.0)
            moves = done.filtered(lambda m: m.product_id == product)
            have = sum(m.uom_id._compute_quantity(m.quantity, product.uom_id) for m in moves)
            if not product.uom_id.compare(want, have):
                continue
            if product.tracking in ('lot', 'serial'):
                raise UserError(_("%(product)s is tracked by lot/serial number: correct receipt "
                                  "%(receipt)s by hand to %(qty)s.")
                                % {'product': product.display_name, 'receipt': receipt.name, 'qty': want})
            line = po.order_line.filtered(lambda l: l.product_id == product and not l.display_type)[:1]
            lowered = {}
            if moves:
                # Several receipt lines of one product (the PO has it twice): a decrease
                # is taken from the last line first, an increase goes on the last line.
                need = want - have
                for move in moves.sorted('id', reverse=True):
                    current = move.uom_id._compute_quantity(move.quantity, product.uom_id)
                    change = need if need > 0 else -min(-need, current)
                    if product.uom_id.is_zero(change):
                        continue
                    new_qty = move.uom_id.round(move.quantity + product.uom_id._compute_quantity(change, move.uom_id))
                    move.quantity = new_qty
                    move.product_uom_qty = new_qty
                    if change < 0 and move.purchase_line_id:
                        lowered[move.purchase_line_id] = lowered.get(move.purchase_line_id, 0.0) - change
                    need -= change
                    if product.uom_id.is_zero(need):
                        break
            else:
                waybill_line = self.line_ids.filtered(lambda l: l.product_id == product)[:1]
                if not line:
                    line = self.env['purchase.order.line'].with_context(
                        bypass_move_update=True, skip_rs_auto_create=True).create(dict(
                            self._rs_purchase_line_vals(product, want, waybill_line._rs_base_price(),
                                                        waybill_line.name), order_id=po.id))
                    line.price_unit = self._rs_order_price(waybill_line._rs_base_price(), line)
                move = self.env['stock.move'].with_context(skip_rs_auto_create=True).create({
                    'description_picking': waybill_line.name or product.display_name,
                    'product_id': product.id,
                    'product_uom_qty': want,
                    'uom_id': product.uom_id.id,
                    'picking_id': receipt.id,
                    'location_id': receipt.location_id.id,
                    'location_dest_id': receipt.location_dest_id.id,
                    'purchase_line_id': line.id,
                    'company_id': receipt.company_id.id,
                })
                self._force_validate_moves(move)
            if line and self._rs_owns_purchase():
                line.with_context(skip_rs_auto_create=True).product_qty = \
                    product.uom_id._compute_quantity(want, line.uom_id)
            elif line:
                # The purchaser's PO keeps its quantity: whether the vendor still owes the
                # difference is theirs to say (banner on this waybill), per PO line.
                for po_line, qty in lowered.items():
                    self._rs_add_vendor_short(po_line, product.uom_id._compute_quantity(qty, po_line.uom_id))
                if want > have:
                    # Raised again: what was in question is no longer owed, last line first.
                    # back is in the product's unit, the shorts in their PO line's unit.
                    back = want - have
                    for po_line in reversed(list(self._rs_vendor_shorts())):
                        if po_line.product_id == product and back > 0:
                            take = min(product.uom_id._compute_quantity(back, po_line.uom_id),
                                       self._rs_vendor_shorts()[po_line])
                            self._rs_add_vendor_short(po_line, -take)
                            back -= po_line.uom_id._compute_quantity(take, product.uom_id)
            changes.append("%s: %s → %s" % (product.display_name, have, want))
        if changes:
            self.message_post(body=Markup(_("Receipt %(receipt)s corrected to the vendor's waybill:<br/>%(changes)s"))
                              % {'receipt': receipt.name, 'changes': Markup('<br/>').join(changes)})


    def _rs_vendor_shorts(self):
        """ {purchase.order.line: qty} still waiting for the purchaser's answer. """
        self.ensure_one()
        data = json.loads(self.pending_vendor_short_json or '{}')
        lines = self.env['purchase.order.line'].browse([int(k) for k in data]).exists()
        return {line: data[str(line.id)] for line in lines}


    def _rs_add_vendor_short(self, line, qty):
        """ Add (lowered) or take back (raised again) `qty` of `line` in the question. """
        shorts = {str(l.id): q for l, q in self._rs_vendor_shorts().items()}
        left = shorts.get(str(line.id), 0.0) + qty
        if line.uom_id.compare(left, 0) > 0:
            shorts[str(line.id)] = left
        else:
            shorts.pop(str(line.id), None)
        self.pending_vendor_short_json = json.dumps(shorts) if shorts else False


    @api.depends('pending_vendor_short_json')
    def _compute_rs_vendor_short_summary(self):
        for waybill in self:
            waybill.rs_vendor_short_summary = ', '.join(
                "%s: %s %s" % (line.product_id.display_name, qty, line.uom_id.name)
                for line, qty in waybill._rs_vendor_shorts().items())


    def action_vendor_expect_later(self):
        """ Banner button: the vendor still owes what they took off the waybill; the PO keeps its quantity and core
            opens a receipt for what no receipt covers, so the next truck is received on it. """
        self.ensure_one()
        owed = self.rs_vendor_short_summary
        self.purchase_id.with_context(skip_rs_auto_create=True)._create_picking()
        self.pending_vendor_short_json = False
        self.message_post(body=_("The vendor still owes %(owed)s: a receipt was opened for it on "
                                 "%(po)s.") % {'owed': owed, 'po': self.purchase_id.name})


    def action_vendor_reduce_order(self):
        """ Banner button: nothing more comes. The PO lines go down by what the vendor
            took off (never below received), so the PO is complete. """
        self.ensure_one()
        changes = []
        for line, qty in self._rs_vendor_shorts().items():
            new_qty = max(line.product_qty - qty, line.qty_received)
            changes.append("%s: %s → %s" % (line.product_id.display_name, line.product_qty, new_qty))
            line.with_context(skip_rs_auto_create=True).product_qty = new_qty
        self.pending_vendor_short_json = False
        if changes:
            self.purchase_id.message_post(body=Markup(_(
                "Ordered quantities lowered with vendor waybill %(waybill)s:<br/>%(changes)s")) % {
                    'waybill': self.display_name, 'changes': Markup('<br/>').join(changes)})


    def _force_validate_moves(self, moves):
        """ Validate given moves, not the whole picking (a hook-built picking may carry other lines' open moves):
            creates a missing move line per move (quantity = demand, picked) and calls _action_done(), bypassing
            wizards. """
        MoveLine = self.env['stock.move.line']
        moves = moves.filtered(lambda m: m.product_uom_qty > 0)
        for move in moves:
            if move.move_line_ids:
                move.move_line_ids[0].quantity = move.product_uom_qty
                move.move_line_ids.picked = True
            else:
                MoveLine.create({
                    'move_id': move.id,
                    'picking_id': move.picking_id.id,
                    'product_id': move.product_id.id,
                    'uom_id': move.uom_id.id,
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'quantity': move.product_uom_qty,
                    'picked': True,
                })
        moves._action_done()


    def _rs_post_commit(self, label, func, *args, **kwargs):
        """ Run a LOCAL step after a committed irreversible RS.GE call; never raises, a failure goes to
            rs_post_commit_error (retried by _rs_repair_local_state). Savepoint protects message_post from a swallowed
            DB error. True when completed. The chatter hears of a failure once; retries failing the same way only
            keep the banner. """
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                func(*args, **kwargs)
        except Exception as e:
            _logger.exception("Post-commit step '%s' failed for waybill %s", label, self.id)
            error = _("%(label)s: %(error)s") % {'label': label, 'error': e}
            if error == self.rs_post_commit_error:
                return False
            self.rs_post_commit_error = error
            self.message_post(body=Markup(_(
                "RS.GE accepted the operation, but the follow-up step <b>%(label)s</b> did not "
                "complete: %(error)s<br/>Odoo and RS.GE may disagree until this is retried — "
                "the drift job will retry it automatically.")) % {'label': label, 'error': e})
            return False
        return True


    def _rs_repair_local_state(self):
        """ Retry the local steps that should have followed an RS.GE operation, so a failed post-commit step
            self-heals. Idempotent. """
        self.ensure_one()
        if self.is_template:
            return False
        if self.state == 'cancelled':
            # Only the cancel follow-up can be outstanding on a cancelled waybill.
            if self.rs_cancel_cascade != 'pending':
                return False
            self._cascade_cancel_delivery()
            repaired = self.rs_cancel_cascade == 'done'
            if repaired and self.rs_post_commit_error:
                self.rs_post_commit_error = False
            return repaired
        repaired = False

        # picking_id is re-read before each branch (a repair can change it), so it agrees with
        # _rs_has_outstanding_step, which reads fresh.

        # Seller: RS says delivered, but our transfer never moved the goods.
        if (self.state == 'completed' and self.waybill_direction != 'buyer'
                and self.picking_id and self.picking_id.state not in ('done', 'cancel')):
            repaired = self._rs_post_commit(
                _("Validate the linked transfer"), self._cascade_validate_picking) \
                and self.picking_id.state == 'done' or repaired

        if self._rs_buyer_receive_pending():
            repaired = self._rs_post_commit(
                _("Validate the incoming receipt"), self._cascade_validate_receipt) or repaired

        # The documents themselves never got built (the step failed right after save).
        if (not self.picking_id and not self.purchase_id and self.state != 'draft'
                and self._in_integration_scope()):
            builder = (self._rs_create_buyer_documents_if_missing
                       if self.waybill_direction == 'buyer'
                       else self._rs_create_documents_if_missing)
            repaired = self._rs_post_commit(
                _("Create the linked Odoo documents"), builder) or repaired

        if self.rs_goods_pending_snapshot and self.picking_id:
            repaired = self._apply_rs_goods_diff_auto(False) or repaired

        if self.rs_post_commit_error and not self._rs_has_outstanding_step():
            self.rs_post_commit_error = False
        return repaired


    def _rs_buyer_receive_pending(self):
        """ Buyer waybill confirmed on RS whose goods are not in stock yet: receipt open, PO still awaiting approval,
            or (purchaser's PO) not chosen yet. A tracked product waiting for lots on a linked open receipt stays
            pending until validated. A cancelled PO is not: nothing would ever book it. """
        self.ensure_one()
        if self.waybill_direction != 'buyer' or self.is_confirmed != '1':
            return False
        if self.purchase_id:
            if self.purchase_id.state in ('draft', 'sent', 'to approve'):
                return True
            return self.purchase_id.state == 'purchase' and self.picking_id.state != 'done'
        return bool(self.picking_id) and self.picking_id.state not in ('done', 'cancel')


    def _rs_has_outstanding_step(self):
        """ True while some local follow-through is missing: the same three conditions
            _rs_repair_local_state acts on, so the flag clears only when nothing is left. """
        self.ensure_one()
        if self.is_template:
            return False
        if self.state == 'cancelled':
            return self.rs_cancel_cascade == 'pending'
        picking = self.picking_id
        if picking and self.rs_goods_pending_snapshot:
            return True
        if picking and picking.state not in ('done', 'cancel'):
            if self.state == 'completed' and self.waybill_direction != 'buyer':
                return True
        if self._rs_buyer_receive_pending():
            return True
        if (not picking and not self.purchase_id and self.state != 'draft'
                and self._in_integration_scope()):
            return True
        return False


    def _cascade_validate_picking(self):
        """ RS close (status 2): validate the linked delivery after the local completed write and commit, so
            _action_done posts no second RS close. Failure keeps the RS close: log + message_post, never raises.
            Skipped for buyer waybills (receipt validated only by the buyer's Receive). """
        self.ensure_one()
        if self.waybill_direction == 'buyer':
            return
        self._do_validate_linked_picking()


    def _cascade_validate_receipt(self):
        """ Buyer: WE confirmed receipt on RS (is_confirmed='1', portal or Confirm in Odoo): validate the linked
            incoming receipt. The seller's close does NOT validate our receipt. """
        self.ensure_one()
        if self.waybill_direction != 'buyer' or self.is_confirmed != '1':
            return
        if self.purchase_id:
            self._rs_receive_waybill_goods()
        else:
            self._do_validate_linked_picking()   # type 5: the vendor-return delivery


    def _do_validate_linked_picking(self):
        """ Validate the linked picking (Ready -> Done), shared by the seller close and buyer receive cascades.
            Never raises: a failure posts a chatter note; no-op without a picking or when done/cancel. """
        self.ensure_one()
        picking = self.picking_id
        if not picking or picking.state in ('done', 'cancel'):
            return
        if picking.state not in ('assigned', 'partially_available'):
            self._rs_note_validate_failure(_("Linked transfer '%(name)s' is in state '%(state)s' and could "
                                             "not be auto-validated. Please reserve stock and validate it "
                                             "manually.") % {'name': picking.name, 'state': picking.state})
            return
        try:
            # The savepoint is required: this block swallows every exception, and a swallowed database
            # error without one aborts the transaction, so message_post below would fail too.
            with self.env.cr.savepoint():
                # INCOMING: goods arrived on RS, so unreserved storable moves get quantity = demand (no zero backorder).
                # Lot/serial left alone (reported below); never for outgoing: forced demand would fabricate stock.
                tracked_unfilled = self.env['stock.move']
                if picking.picking_type_code == 'incoming':
                    for move in picking.move_ids:
                        if move.state in ('done', 'cancel') or move.quantity > 0:
                            continue
                        if not move.product_id.tracking:
                            move.quantity = move.product_uom_qty
                        else:
                            tracked_unfilled |= move
                # move.picked=True is required before _action_done.
                for move in picking.move_ids:
                    if move.quantity > 0:
                        move.picked = True
                result = picking.with_context(skip_backorder=True).button_validate()
                # button_validate may return a wizard (backorder/immediate): the move did NOT transition;
                # note it so the user finishes manually.
                if isinstance(result, dict) and result.get('type') == 'ir.actions.act_window':
                    _logger.warning("Picking %s validation returned a wizard instead of completing.", picking.name)
                    self._rs_note_validate_failure(_("Linked transfer '%(name)s' needs manual confirmation — "
                                                     "please open it and validate.") % {'name': picking.name})
                if tracked_unfilled:
                    backorder = picking.backorder_ids[:1] if 'backorder_ids' in picking._fields else \
                        self.env['stock.picking'].search([('backorder_id', '=', picking.id)], limit=1)
                    self.message_post(body=_(
                        "Product(s) %(products)s require lot/serial numbers and could not be "
                        "auto-received. Open transfer '%(name)s', enter the lot/serial and the "
                        "quantity, then validate it manually.") % {
                            'products': ', '.join(tracked_unfilled.mapped('product_id.display_name')),
                            'name': (backorder.name if backorder else picking.name)})
        except Exception as e:
            _logger.warning("Could not auto-validate picking %s for waybill %s: %s", picking.name, self.id, e)
            self._rs_note_validate_failure(_("Linked transfer '%(name)s' could not be auto-validated: "
                                             "%(error)s. Please validate manually.") % {'name': picking.name,
                                                                                         'error': str(e)})


    def _rs_note_validate_failure(self, note):
        """ Banner + one chatter message per distinct reason: the drift job retries every 15 minutes, a retry
            failing the same way only keeps the banner. """
        error = _("Validate the linked transfer: %s") % note
        if error == self.rs_post_commit_error:
            return
        self.rs_post_commit_error = error
        self.message_post(body=note)


    def _cascade_cancel_delivery(self):
        """ Seller cancel (Cancel button, Update, sync, drift): delivery done: unchanged, activity to check;
            open: cancel it, then the SO unless something else was delivered/invoiced (then reduce its lines);
            nothing sent to RS. Never raises: failure leaves rs_cancel_cascade 'pending' for drift. """
        self.ensure_one()
        if self.waybill_direction == 'seller' and self.state == 'cancelled':
            # A cancelled distribution: what is still on its truck goes back to stock.
            if self.waybill_type == '4' and not self.parent_waybill_id and not self.remainder_origin_id:
                self._rs_post_commit(_("Bring the distribution's goods back to the warehouse"),
                                     self._rs_bring_back_from_truck)
        picking = self.picking_id
        if (self.waybill_direction != 'seller' or self.state != 'cancelled' or not picking
                or self.rs_cancel_cascade == 'done'):
            return
        if picking.state == 'done':
            if not self.rs_cancel_cascade:
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_("Cancelled waybill, goods already delivered"),
                    note=_("Waybill %(waybill)s was cancelled, but delivery %(picking)s is "
                           "already done. Odoo was not changed: check what happened with "
                           "the customer.") % {'waybill': self.display_name, 'picking': picking.name},
                    user_id=(self.sales_order_id.user_id or self.env.user).id)
            self.rs_cancel_cascade = 'done'
            return
        self.rs_cancel_cascade = 'pending'
        if self._rs_post_commit(_("Cancel the linked transfer and sales order"),
                                self._rs_cancel_delivery_and_order):
            self.rs_cancel_cascade = 'done'
            root = self._rs_distribution_root()
            if root != self and root.state == 'cancelled':
                # The goods this sub's delivery held stay on the truck: bring them back too.
                self._rs_post_commit(_("Bring the distribution's goods back to the warehouse"),
                                     root._rs_bring_back_from_truck)


    def _rs_cancel_delivery_and_order(self):
        """ Body of _cascade_cancel_delivery, run inside its savepoint. """
        picking = self.picking_id
        if picking.state == 'cancel':
            # Cancelled from elsewhere (e.g. the SO was cancelled): the order is handled.
            return
        cancelled_qty = picking._rs_open_sale_qty()
        picking.action_cancel()
        picking.message_post(body=_("Cancelled because waybill %s was cancelled.")
                             % self.display_name)
        order = self.sales_order_id or picking.sale_id
        if order and order.state == 'sale' and not self.env.context.get('rs_order_cancel'):
            self._rs_cancel_reduce_order(order, picking, cancelled_qty)


    def _rs_cancel_reduce_order(self, order, picking, cancelled_qty):
        """ Bring the sales order in line with a delivery cancelled with its waybill. """
        picking._rs_reduce_sale_order(order, cancelled_qty,
                                      _("waybill %s was cancelled") % self.display_name)


    def _cascade_cancel_purchase(self):
        """ Buyer: vendor cancelled on RS. Received: Odoo unchanged, PO activity; not received and safe: cancel PO and
            receipts; unsafe: unlink the waybill, activity gives the blockers. Type 5: cancel the unshipped return
            delivery. Never raises: failure noted. """
        self.ensure_one()
        if self.waybill_direction != 'buyer':
            return
        po, picking = self.purchase_id, self.picking_id
        try:
            with self.env.cr.savepoint():
                if not po:
                    if picking and picking.state not in ('done', 'cancel'):
                        picking.with_context(skip_rs_auto_create=True).action_cancel()
                    return
                if po.state == 'cancel':
                    return
                if picking.state == 'done':
                    self._rs_purchase_cancel_activity(po, _(
                        "The vendor cancelled waybill %(waybill)s on RS.GE, but receipt "
                        "%(receipt)s is already done. Odoo was not changed: settle it with the "
                        "vendor (return or a new waybill).")
                        % {'waybill': self.display_name, 'receipt': picking.name},
                        _("Vendor cancelled waybill %s, goods already received") % self.display_name)
                    return
                blockers = self._rs_purchase_cancel_blockers(po)
                if not blockers:
                    po.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')).with_context(
                        skip_rs_auto_create=True).action_cancel()
                    po.with_context(skip_rs_auto_create=True).button_cancel()
                    po.message_post(body=_("Cancelled because the vendor cancelled waybill %s on "
                                           "RS.GE.") % self.display_name)
                    self.message_post(body=_("Purchase order %s cancelled with this waybill.") % po.name)
                    return
                if picking.waybill_id == self:
                    picking.waybill_id = False
                self.write({'purchase_id': False, 'picking_id': False})
                self._rs_purchase_cancel_activity(po, _(
                    "The vendor cancelled waybill %(waybill)s on RS.GE before the goods were "
                    "received. Purchase order %(po)s was not cancelled because %(why)s. Decide "
                    "whether to cancel it or wait for a new waybill.")
                    % {'waybill': self.display_name, 'po': po.name, 'why': '; '.join(blockers)},
                    _("Vendor cancelled waybill %s: decide on the purchase order") % self.display_name)
        except Exception as e:
            _logger.warning("Vendor cancel follow-up failed for waybill %s: %s", self.id, e)
            self.message_post(body=_("The vendor cancelled the waybill on RS.GE, but purchase order "
                                     "%(po)s could not be updated: %(error)s. Please review it.")
                              % {'po': po.name or '-', 'error': str(e)})


    def _rs_purchase_cancel_blockers(self, po):
        """ Why cancelling `po` with this vendor waybill would break something, as sentences for the purchaser;
            empty when safe: goods received, a vendor bill, made for a sales order,
            another truck's waybill still on it. """
        self.ensure_one()
        reasons = []
        lines = po.order_line.filtered(lambda l: not l.display_type)
        if any(lines.mapped('qty_received')):
            reasons.append(_("goods of it were already received"))
        if po.invoice_ids.filtered(lambda m: m.state != 'cancel'):
            reasons.append(_("it already has a vendor bill"))
        if lines.move_dest_ids or ('sale_line_id' in lines._fields and lines.sale_line_id):
            reasons.append(_("it was made for a sales order"))
        if self.search_count([('purchase_id', '=', po.id), ('id', '!=', self.id),
                              ('state', '!=', 'cancelled')]):
            reasons.append(_("another waybill of the vendor is still on it"))
        return reasons


    def _rs_purchase_cancel_activity(self, po, note, summary):
        """ One activity on the PO for its purchaser, not repeated by later syncs. """
        if po.activity_ids.filtered(lambda a: a.summary == summary):
            return
        po.activity_schedule('mail.mail_activity_data_todo', summary=summary, note=note,
                             user_id=(po.user_id or self.env.user).id)
