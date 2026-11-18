from odoo import http
from odoo.http import request

from odoo.addons.web.controllers.webclient import ModelTranslations


class ModelTranslationsAccess(ModelTranslations):

    @http.route()
    def get_translation_for_field(self, res_model, field_name, res_id, target_lang=None, context=None):
        """ Refuse the terms of a hidden field, which the xml and html modes read without the field guard. """
        model = request.env[res_model]
        if rules := model._gec_field_rules():
            model._gec_check_path(rules, field_name)
        return super().get_translation_for_field(
            res_model, field_name, res_id, target_lang=target_lang, context=context)
