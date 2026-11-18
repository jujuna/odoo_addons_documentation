from odoo import api, fields, models


class RsSpecSite(models.Model):
    _name = 'rs.spec.site'
    _description = 'RS Petroleum Site'
    _order = 'code'
    _rec_names_search = ('code', 'address')

    rs_un_id = fields.Integer('RS Taxpayer ID', required=True, index=True)
    code = fields.Char(required=True)
    address = fields.Char()

    _rs_un_id_code_unique = models.Constraint('UNIQUE(rs_un_id, code)', 'This site already exists for the taxpayer.')

    @api.depends('code', 'address')
    def _compute_display_name(self):
        for site in self:
            site.display_name = f"{site.code} — {site.address}" if site.address else site.code

    def _rs_sync(self, service, un_id):
        if un_id:
            rows = service._rs_table('get_v_org_objects_by_un_id_n', p_un_id=un_id, invoiceType=1)
        else:
            rows = service._rs_table('get_rs_org_objects')
        sites = {site.code: site for site in self.search([('rs_un_id', '=', un_id)])}
        new_vals = []
        for row in rows:
            code, address = row['ob_ident_no'], row.get('address') or False
            site = sites.get(code)
            if not site:
                new_vals.append({'rs_un_id': un_id, 'code': code, 'address': address})
            elif site.address != address:
                site.address = address
        return self.create(new_vals)
