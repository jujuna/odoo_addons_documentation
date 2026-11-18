from . import controllers, models, wizard


def uninstall_hook(env):
    """Delete the generated SCSS attachments; the ir.asset rows are module data and go with the module."""
    env['ir.attachment'].sudo().search([('res_model', '=', 'gec.brand.kit')]).unlink()
    env['ir.config_parameter'].sudo().search([('key', '=', 'gec_brand_kit.web_app_name_set')]).unlink()
