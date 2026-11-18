from datetime import datetime
from lxml import etree

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import cleanup_xml_node, float_round
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

INVOICE_TYPE_MAP = {
    'REQ01': (_lt("REQUEST FOR QUOTATION"), "REQ01 - Request for quotation"),
    'QUO01': (_lt("QUOTATION"), "QUO01 - Quotation"),
    'ORD01': (_lt("ORDER"), "ORD01 - Order"),
    'ORC01': (_lt("ORDER CONFIRMATION"), "ORC01 - Order Confirmation"),
    'INV01': (_lt("INVOICE"), "INV01 - Invoice"),
    'INV02': (_lt("CREDIT NOTE"), "INV02 - Credit note"),
    'INV03': (_lt("INTEREST NOTE"), "INV03 - Interest note"),
    'INV04': (_lt("INTERNAL INVOICE"), "INV04 - Internal invoice"),
    'INV05': (_lt("COLLECT NOTE"), "INV05 - Collect note"),
    'INV06': (_lt("PRO FORMA INVOICE"), "INV06 - Pro forma invoice"),
    'INV07': (_lt("SELFBILLING"), "INV07 - Self billing"),
    'INV08': (_lt("REMINDER INVOICE"), "INV08 - Reminder invoice"),
    'INV09': (_lt("DIRECT PAYMENT"), "INV09 - Direct payment"),
    'TES01': (_lt("TEST INVOICE"), "TES01 - Test invoice"),
    'PRI01': (_lt("PRICE LIST"), "PRI01 - Price list"),
    'INF01': (_lt("INFORMATION"), "INF01 - Information"),
    'DEN01': (_lt("DELIVERY ERROR NOTIFICATION"), "DEN01 - Delivery error notification"),
    'SDD01': (_lt("DIRECT DEBIT PRELIMINARY NOTIFICATION"), "SDD01 - Direct debit preliminary notification"),
}


class AccountMove(models.Model):
    _inherit = 'account.move'

    l10n_fi_edi_invoice_type_code = fields.Selection(
        selection=[(key, value[1]) for key, value in INVOICE_TYPE_MAP.items()],
        string="Invoice Type Code",
        help="The invoice type code required by the Finnish government to define the type of transaction.",
        compute='_compute_l10n_fi_edi_codes',
        init_storage=lambda model: None,  # avoid MemoryError on large databases
        readonly=False, store=True, copy=False,
    )
    l10n_fi_edi_epi_charge = fields.Selection(
        selection=[
            ('SHA', "SHA"),
            ('OUR', "OUR"),
            ('BEN', "BEN"),
            ('SLEV', "SLEV"),
        ],
        string="Epi Charge",
        help="The code that defines the payment method, based on Finnish government.",
        copy=False,
    )
    l10n_fi_edi_origin_code = fields.Selection(
        string="Origin Code",
        help="The invoice status on Finvoice side.",
        selection=[
            ('Original', "Original"),
            ('Cancel', "Cancel"),
            ('Copy', "Copy"),
        ],
        compute='_compute_l10n_fi_edi_codes',
        init_storage=lambda model: None,  # avoid MemoryError on large databases
        readonly=False, store=True, copy=False,
    )

    @api.depends('move_type')
    def _compute_l10n_fi_edi_codes(self):
        for move in self:
            if move.is_outbound():
                move.l10n_fi_edi_invoice_type_code = 'INV02'
                move.l10n_fi_edi_origin_code = 'Cancel'
            else:
                move.l10n_fi_edi_invoice_type_code = 'INV01'
                move.l10n_fi_edi_origin_code = 'Original'

    def _l10n_fi_edi_create_edi_document(self) -> None:
        for move in self:
            if move.state != 'posted':
                return

            if not move.partner_bank_id:
                raise UserError(self.env._("You can't send a finvoice format invoice without setting a partner bank on the move."))

            # We need to delete the previous document as only one document per edi format is allowed
            finvoice_edi_document = move.edi_document_ids.filtered(lambda doc: doc.edi_format_id.code == 'finvoice')
            finvoice_edi_document.attachment_id.unlink()
            finvoice_edi_document.unlink()

            doc = move.edi_document_ids = self.env['account.edi.document'].create({
                'l10n_fi_document_identifier': move.name,
                'move_id': move.id,
                'edi_format_id': self.env['account.edi.format'].search([('code', '=', 'finvoice')], limit=1).id,
            })

            move_values = {
                'amount_total': self._format_numerical_value_for_finvoice(move.amount_total),
                'name': move.name,
                'invoice_date': move.invoice_date,
                'due_date': move.invoice_date_due,
                'epi_charge': move.l10n_fi_edi_epi_charge,
                'origin_code': move.l10n_fi_edi_origin_code,
                'currency_name': move.currency_id.name,
                'partner_name': move.partner_id.name,
                'partner_vat': move.partner_id.vat,
                'time_stamp': datetime.isoformat(fields.Datetime.now()),
                'payment_ref': move.payment_reference,
                'partner_address': {
                    'street': move.partner_id.street,
                    'city': move.partner_id.city,
                    'zip': move.partner_id.zip,
                },
                'bank': {
                    'bic': move.partner_bank_id.bank_bic,
                    'name': move.partner_bank_id.bank_name,
                    'acc_number': move.partner_bank_id.account_number.replace(' ', ''),
                    'acc_type': move.partner_bank_id.account_type.upper(),
                },
                'lines': [{
                    'product_name': line.product_id.name or line.name,
                    'product_uom': self.env.ref('uom.product_uom_unit').name,
                    'quantity': line.quantity,
                    'currency_name': line.currency_id.name,
                    'price_unit': self._format_numerical_value_for_finvoice(line.price_unit),
                    'is_discount': line.discount > 0,
                    'discount': self._format_numerical_value_for_finvoice(line.price_total / (1 - (line.discount / 100)) - line.price_total),
                    'price_subtotal': self._format_numerical_value_for_finvoice(line.price_subtotal),
                    'price_total': self._format_numerical_value_for_finvoice(line.price_total),
                    'reversed_entry': move.reversed_entry_id,
                } for line in move.invoice_line_ids.filtered(lambda line: line.display_type == 'product')],
                'invoice_type': {
                    'code': move.l10n_fi_edi_invoice_type_code,
                    'text': INVOICE_TYPE_MAP.get(move.l10n_fi_edi_invoice_type_code, ('', ''))[0],
                },
            }

            file_content = self.env['ir.qweb']._render('l10n_fi_edi.finvoice_3_export', {
                'move': move_values,
                'company': move.company_id,
                'doc': doc,
            })

            doc.attachment_id = self.env['ir.attachment'].create([{
                'name': f"{move.name.replace('/', '_')}_finvoice.xml",
                'res_id': move.id,
                'res_model': 'account.move',
                'type': 'binary',
                'raw': etree.tostring(cleanup_xml_node(file_content, remove_blank_nodes=False), encoding='ISO-8859-15'),
            }])

            doc.invalidate_recordset(['attachment_id'])

    def _format_numerical_value_for_finvoice(self, value) -> str:
        # Finvoice requirements ask for digits between 2 & 5
        precision = min(max(self.currency_id.decimal_places, 2), 5)
        return format(float_round(value, precision_digits=precision), f".{precision}f").replace('.', ',')

    def _get_edi_decoder(self, file_data, new=False) -> dict:
        # EXTENDS 'account'
        if file_data.get('xml_tree') is not None and file_data['xml_tree'].tag == 'Finvoice':
            return {
                'priority': 20,
                'decoder': self._l10n_fi_edi_import_invoice,
            }

        return super()._get_edi_decoder(file_data, new=new)

    def _l10n_fi_edi_import_invoice(self, invoice, file_data, new=False) -> bool | str:
        with invoice._get_edi_creation() as invoice:
            if invoice.journal_id.type not in {'sale', 'purchase'}:
                return self.env._("The journal type is neither a sale nor a purchase journal.")

            tree = file_data.get('xml_tree')
            if tree is None:
                return self.env._("No XML tree found in this file.")

            invoice.move_type = f"{'out_' if invoice.journal_id.type == 'sale' else 'in_'}{'refund' if tree.find('.//OriginalInvoiceNumber') is not None else 'invoice'}"

            invoice_details_node = tree.find('InvoiceDetails')
            if invoice_details_node is None:
                return self.env._("Node InvoiceDetails not found.")

            currency_name = invoice_details_node.find('InvoiceTotalVatIncludedAmount').attrib.get('AmountCurrencyIdentifier')
            currency = self.env['res.currency'].search([('name', '=', currency_name)], limit=1)
            invoice.currency_id = currency.id
            invoice_date_node = invoice_details_node.find('InvoiceDate')
            if invoice_date_node is not None:
                invoice.invoice_date = datetime.strptime(invoice_date_node.text, '%Y%m%d').date()

            self._l10n_fi_edi_fill_invoice_data(tree, invoice)
            self._l10n_fi_edi_create_invoice_lines_for_import(tree, invoice)

            return True

    def _l10n_fi_edi_create_invoice_lines_for_import(self, tree, invoice) -> None:
        product_names_found = [line_vals.find('ArticleName').text for line_vals in tree.findall('InvoiceRow')]

        existing_products = self.env['product.product'].search([('name', 'in', product_names_found)]).grouped('name')

        new_line_vals = []
        for line_vals in tree.findall('InvoiceRow'):
            product_name = line_vals.find('ArticleName').text
            price_unit = line_vals.find('UnitPriceAmount').text.replace(',', '.')
            new_line = {
                'quantity': line_vals.find('OrderedQuantity').text,
                'price_unit': price_unit,
                'move_id': invoice.id,
            }
            if product_name in existing_products:
                new_line['product_id'] = existing_products[product_name].id
            else:
                new_line['name'] = product_name

            new_line_vals.append(new_line)

        self.env['account.move.line'].create(new_line_vals)

    def _l10n_fi_edi_fill_invoice_data(self, tree, invoice) -> None:
        partner_node = tree.find('BuyerPartyDetails')
        partner = self.env['res.partner']
        if partner_node is not None:
            partner_name_node = partner_node.find('BuyerOrganisationName')
            partner_vat_node = partner_node.find('BuyerOrganisationTaxCode')
            partner_name = partner_name_node is not None and partner_name_node.text or ''
            partner_vat = partner_vat_node is not None and partner_vat_node.text or ''

            partner = self.env['res.partner'].search([
                ('name', '=ilike', partner_name),
                ('vat', '=', partner_vat),
            ], limit=1)
            if not partner:
                partner = self.env['res.partner'].search([
                    ('name', '=ilike', partner_name),
                ], limit=1)
            if not partner:
                partner_address_node = partner_node.find('BuyerPostalAddressDetails')
                if partner_address_node is not None:
                    partner_country_code_node = partner_address_node.find('CountryCode')
                    partner_country_code = partner_country_code_node is not None and partner_country_code_node.text or ''
                    partner = self.env['res.partner'].create([{
                        'name': partner_name,
                        'vat': partner_vat,
                        'country_id': self.env['res.country'].search([('code', '=', partner_country_code.upper())], limit=1).id,
                        'street': partner_address_node.find('BuyerStreetName').text,
                        'city': partner_address_node.find('BuyerTownName').text,
                        'zip': partner_address_node.find('BuyerPostCodeIdentifier').text,
                    }])

        invoice.write({
            'l10n_fi_edi_epi_charge': tree.find('.//EpiDetails//EpiPaymentInstructionDetails//EpiCharge').attrib.get('ChargeOption'),
            'l10n_fi_edi_invoice_type_code': tree.find('.//InvoiceDetails//InvoiceTypeCode').text,
            'l10n_fi_edi_origin_code': tree.find('.//InvoiceDetails//OriginCode').text,
            'partner_id': partner.id,
            'invoice_date_due': datetime.strptime(tree.find('.//EpiDetails//EpiPaymentInstructionDetails//EpiDateOptionDate').text, '%Y%m%d').date(),
        })

    def _check_finvoice_requirement(self):
        error_messages = set()
        moves = self.env['account.move']
        for move in self:
            if not move.partner_id.street or not move.partner_id.zip or not move.partner_id.city:
                error_messages.add(self.env._("You need to set a full address on the partner."))
                moves |= move
            if not move.l10n_fi_edi_epi_charge:
                error_messages.add(self.env._("You need to set an EPI charge on the move."))
                moves |= move
            if not all(line_map for line_map in move.invoice_line_ids.mapped(lambda line: line.product_id.id or line.name)):
                error_messages.add(self.env._("Each Journal Item must either have a label or a product set."))
                moves |= move

        return moves, error_messages
