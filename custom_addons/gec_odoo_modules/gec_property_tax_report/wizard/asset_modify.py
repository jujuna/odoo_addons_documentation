from odoo import models


class AssetModify(models.TransientModel):
    _inherit = 'asset.modify'

    def activate_depreciation(self):
        """Hand the property tax tags over to the asset activation creates, so the next
        declaration does not stop on an untagged asset."""
        origin = self.asset_variant_id.asset_id
        derived_before = origin.derived_asset_ids
        result = super().activate_depreciation()
        for asset in origin.derived_asset_ids - derived_before:
            asset._rs_form15_inherit_from(origin)
        return result
