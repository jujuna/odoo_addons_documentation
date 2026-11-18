from odoo import http
from odoo.http import request

from odoo.addons.web.controllers.report import ReportController


class ReportAccess(ReportController):

    @http.route()
    def report_routes(self, reportname, docids=None, converter=None, **data):
        """ Refuse a hidden report before it is rendered; /report/download goes through here too. """
        request.env['ir.actions.report']._gec_check_report_access(reportname)
        return super().report_routes(reportname, docids=docids, converter=converter, **data)
