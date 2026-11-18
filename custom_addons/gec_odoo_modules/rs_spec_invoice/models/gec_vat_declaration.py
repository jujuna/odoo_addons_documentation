from collections import defaultdict

from odoo import Command, fields, models
from odoo.tools import float_is_zero

STOCK_USAGES = ('internal', 'transit')


class GecVatDeclaration(models.Model):
    _inherit = 'gec.vat.declaration'

    def action_generate(self):
        """Tabs 13 and 14 are the petroleum rows of the ბ I and ბ II scans, with the ნსაფ columns added."""
        result = super().action_generate()
        for declaration in self:
            (declaration.spec_line_ids | declaration.spec_purchase_line_ids).filtered('move_id').unlink()
            sale_rows, _moves, warnings = declaration._gec_b1_scan(spec=True)
            purchase_rows, purchase_warnings = declaration._gec_b2_scan(spec=True)
            rows = [declaration._gec_spec_row(row, 'spec_sale') for row in sale_rows]
            rows += [declaration._gec_spec_row(row, 'spec_purchase') for row in purchase_rows]
            self.env['gec.vat.invoice.line'].create(rows)
            declaration.stock_line_ids.filtered('product_ids').unlink()
            stock_rows, stock_warnings = declaration._gec_spec_stock_rows(sale_rows)
            self.env['gec.vat.stock.line'].create(stock_rows)
            warnings = (declaration.scan_warnings or '').splitlines() + warnings + purchase_warnings + stock_warnings
            declaration.scan_warnings = '\n'.join(warnings) or False
        return result

    def _gec_spec_row(self, row, part):
        """The ნსაფ columns: tab 13 reads litres / kg from the invoice, tab 14 from the bill's rs.ge line snapshot. Sudo, as the
        scans: the move may belong to a same-VAT branch the user does not see."""
        move = self.env['account.move'].sudo().browse(row['move_id'])
        original = move.rs_einv_replaces_id if row['korect_number'] else move.browse()
        snap = move.rs_einv_pulled_line_ids[:1]
        sale = part == 'spec_sale'
        return dict(row, part=part, operation_date=move.invoice_date, korect_date=original.invoice_date or False,
            station_from=move.rs_spec_start_site_id.code or False, station_to=move.rs_spec_end_site_id.code or False,
            product_code=move._rs_spec_line()[:1].product_id.rs_spec_ssf_code or False, quantity_l=move.rs_spec_quantity_l if sale else snap.g_number,
            quantity_kg=move.rs_spec_quantity_kg if sale else snap.rs_g_number_alt)

    def _gec_spec_stock_rows(self, sale_rows):
        """Tab 15: stock from done move lines (as Romania SAF-T, also for untracked fuel), sales from tab 13 rows and plain invoices.
        Invoices are read sudo, as the scans: they may belong to a same-VAT branch the user does not see."""

        def row_of(product):
            """Row key: the 4-digit code (portal rows); return `product` for one row per product."""
            return product.rs_spec_ssf_code or product

        companies = self.company_id._gec_vat_companies()
        units = {'_kg': self.env.ref('uom.product_uom_kgm'), '_l': self.env.ref('uom.product_uom_litre')}
        values = defaultdict(float)
        products = defaultdict(self.env['product.product'].browse)

        def suffix(product):
            uom = product.uom_id
            return '_kg' if uom._has_common_reference(units['_kg']) and not uom._has_common_reference(units['_l']) else '_l'

        def add(product, name, qty, uom=None):
            sfx = suffix(product)
            if uom and uom._has_common_reference(units[sfx]):
                qty = uom._compute_quantity(qty, units[sfx], round=False)
            key = row_of(product)
            products[key] |= product
            values[key, name + sfx] += qty

        def stock(location):
            return location.usage == 'internal' or (location.usage == 'transit' and location.company_id)

        def outside(location):
            return location.usage == 'supplier' or (location.usage == 'transit' and not location.company_id)

        # sudo: accountants may lack Inventory rights; the companies are pinned in the domain
        MoveLine = self.env['stock.move.line'].sudo()
        before = self.company_id._to_datetime_upper_bound(fields.Date.subtract(self.date_from, days=1))
        end = self.company_id._to_datetime_upper_bound(self.date_to)
        domain = [
            ('company_id', 'in', companies.ids),
            ('state', '=', 'done'),
            ('product_id.rs_spec_rs_id', '!=', False),
            '|',
            ('location_id.usage', 'in', STOCK_USAGES),
            ('location_dest_id.usage', 'in', STOCK_USAGES),
        ]
        groupby = ['product_id', 'location_id', 'location_dest_id']
        for product, source, dest, qty in MoveLine._read_group(domain + [('date', '<=', before)], groupby, ['quantity_product_uom:sum']):
            if stock(dest):
                add(product, 'opening', qty, product.uom_id)
            if stock(source):
                add(product, 'opening', -qty, product.uom_id)
        month = [('date', '>', before), ('date', '<=', end)]
        for product, source, dest, qty in MoveLine._read_group(domain + month, groupby, ['quantity_product_uom:sum']):
            if outside(source) and stock(dest):
                add(product, 'received', qty, product.uom_id)
            elif stock(source) and outside(dest):
                add(product, 'received', -qty, product.uom_id)

        for row, move in zip(sale_rows, self.env['account.move'].sudo().browse([row['move_id'] for row in sale_rows])):
            original = move.rs_einv_replaces_id if row['korect_number'] else move.browse()
            product = move._rs_spec_line()[:1].product_id
            field = 'rs_spec_quantity' + suffix(product)
            add(product, 'spec_sold', move[field] - original[field])

        lines = self.env['account.move.line'].sudo().search(self._gec_period_domain() + [
            ('parent_state', '=', 'posted'),
            ('display_type', '=', 'product'),
            ('move_id.move_type', 'in', ('out_invoice', 'out_refund')),
            ('move_id.rs_einv_is_spec', '=', False),
            ('product_id.rs_spec_rs_id', '!=', False),
        ])
        refunds = lines.move_id.filtered(lambda move: move.move_type == 'out_refund')
        orphans = refunds.filtered(lambda move: not move.reversed_entry_id)
        skipped = orphans | refunds.filtered('reversed_entry_id.rs_einv_is_spec')
        warnings = [self.env._("%s: a petroleum credit note without an original invoice is not in tab 15.", move.display_name) for move in orphans]
        for line in lines.filtered(lambda line: line.move_id not in skipped):
            move, product = line.move_id, line.product_id
            sign = -1 if move.move_type == 'out_refund' else 1
            sold, amount = ('discount_sold', 'discount_amount') if line.discount > 0 else ('sold', 'sold_amount')
            add(product, sold, sign * line.quantity, line.product_uom_id)
            add(product, amount, sign * move._rs_amount_to_gel(line.price_total))

        rows = {}
        for (key, name), value in values.items():
            if not float_is_zero(value, precision_digits=4):
                row = rows.setdefault(key, {
                    'declaration_id': self.id,
                    'product_ids': [Command.set(products[key].ids)],
                    'product_code': products[key][:1].rs_spec_ssf_code or False,
                })
                row[name] = value
        return list(rows.values()), warnings
