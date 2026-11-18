from odoo import api, fields, models

RS_SPEC_KG_SSN_CODES = frozenset({'27132000000', '27139090000', '27150000000'})


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    rs_spec_rs_id = fields.Integer('RS Petroleum ID', copy=False, index='btree_not_null',
        help="rs.ge petroleum product id, set by Sync from rs.ge: its presence makes the product a petroleum product, its customer invoice lines are "
        "filed on rs.ge as petroleum invoices (ნსაფ).")

    rs_spec_ssf_code = fields.Char('RS Product Code', copy=False)

    _rs_spec_rs_id_unique = models.UniqueIndex('(rs_spec_rs_id) WHERE rs_spec_rs_id > 0', 'This rs.ge petroleum product already exists.')

    @api.model
    def action_rs_spec_sync(self):
        """rs.ge gives no unit: the accountant's rule is that these three SSN codes are sold by weight.
        The document check runs sudo: core's own unit guards look across companies.
        """
        service = self.env['rs.spec.soap.service'].with_company(self.env.company)
        un_id = service._rs_base()._rs_company_un_id()
        rows = service._rs_table('get_spec_products_n', p_like='', p_un_id=un_id, p_series='')
        rows_by_id = {int(row['id']): row for row in rows}
        products = self.with_context(active_test=False).search([('rs_spec_rs_id', '!=', False)])
        existing = {product.rs_spec_rs_id: product for product in products}
        litre = self.env.ref('uom.product_uom_litre')
        kg = self.env.ref('uom.product_uom_kgm')
        new_vals = []
        for rs_id, row in rows_by_id.items():
            ssn, ssf = row.get('ssn_code'), row.get('ssf_code')
            vals = {'name': row['goods_name'], 'barcode': ssn or False, 'rs_spec_ssf_code': ssf or False}
            unit = kg if ssn in RS_SPEC_KG_SSN_CODES else litre
            product = existing.get(rs_id)
            if not product:
                new_vals.append(dict(vals, rs_spec_rs_id=rs_id, uom_id=unit.id))
                continue
            changed = {name: value for name, value in vals.items() if product[name] != value}
            if product.uom_id in (litre, kg) and product.uom_id != unit:
                variants = product.product_variant_ids
                posted = [('parent_state', '=', 'posted'), ('product_id', 'in', variants.ids)]
                lines = self.env['account.move.line'].sudo()
                if variants._trigger_uom_warning() or lines.search_count(posted, limit=1):
                    product.message_post(body=self.env._("Unit left as %s: documents already use it.", product.uom_id.name))
                else:
                    changed['uom_id'] = unit.id
            if changed:
                product.write(changed)
        self.create(new_vals)
        products.filtered(lambda product: not product.active and product.rs_spec_rs_id in rows_by_id).action_unarchive()
        products.filtered(lambda product: product.active and product.rs_spec_rs_id not in rows_by_id).action_archive()
        Site = self.env['rs.spec.site']
        Site._rs_sync(service, un_id)
        Site._rs_sync(service, 0)
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Petroleum Products"),
            'res_model': 'product.template',
            'view_mode': 'list,form',
            'domain': [('rs_spec_rs_id', '!=', False)],
        }
