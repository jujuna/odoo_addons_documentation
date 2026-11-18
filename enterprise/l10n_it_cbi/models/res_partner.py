from odoo import api, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.depends('is_company')
    def _compute_available_additional_identifiers_metadata(self):
        super()._compute_available_additional_identifiers_metadata()

        company_partner_ids = set(self.env['res.company'].sudo().search([]).mapped('partner_id.id'))

        for partner in self:
            metadata = partner.available_additional_identifiers_metadata
            if not metadata or 'IT_CUC' not in metadata:
                continue

            if partner.id in company_partner_ids:
                partner.available_additional_identifiers_metadata = {
                    **metadata,
                    'IT_CUC': {**metadata['IT_CUC'], 'display_optional': 'show'},
                }
            else:
                filtered_metadata = dict(metadata)
                filtered_metadata.pop('IT_CUC')
                partner.available_additional_identifiers_metadata = filtered_metadata
