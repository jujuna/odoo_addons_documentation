# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from datetime import datetime

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import BinaryBytes

_logger = logging.getLogger(__name__)


class HrPayrollDeclarationMixin(models.AbstractModel):
    _name = 'hr.payroll.declaration.mixin'
    _description = 'Payroll Declaration Mixin'

    @api.model
    def default_get(self, fields):
        """
        Raise a ``UserError`` if :meth:`_country_restriction` is set and differs from the
        country of the current company.
        """
        country_restriction = self._country_restriction()
        if country_restriction and self.env.company.country_id.code != country_restriction:
            raise UserError(_('You must be logged in a %s company to use this feature', country_restriction))
        return super().default_get(fields)

    def _get_year_selection(self):
        current_year = datetime.now().year
        return [(str(i), i) for i in range(1990, current_year + 1)]

    create_date = fields.Datetime(string='Created on', readonly=True)
    year = fields.Selection(
        selection='_get_year_selection', string='Year', required=True,
        default=lambda x: str(datetime.now().year - 1))
    line_ids = fields.One2many(
        'hr.payroll.employee.declaration', 'res_id', string='Declarations')
    lines_count = fields.Integer(compute='_compute_lines_count', string="Eligible Employees")
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    pdf_error = fields.Text('PDF Error Message')

    def unlink(self):
        """Delete the sheets and their employee declarations."""
        self.line_ids.unlink()  # We need to unlink the child line_ids as well to prevent orphan records
        return super().unlink()

    def action_generate_declarations(self):
        """
        Fill ``line_ids`` with one ``hr.payroll.employee.declaration`` per eligible employee.

        To override: write the lines (``employee_id``, ``res_model`` and ``res_id`` of the sheet),
        then call ``super()``, which raises if the sheet has no line.

        :raise UserError: if there is no declaration
        """
        for sheet in self:
            if not sheet.line_ids:
                raise UserError(_('There is no declaration to generate for the given period'))

    @api.depends('line_ids')
    def _compute_lines_count(self):
        for sheet in self:
            sheet.lines_count = len(sheet.line_ids)

    def action_open_declarations(self):
        self.ensure_one()
        return {
            'name': _('Employee Declarations'),
            'res_model': 'hr.payroll.employee.declaration',
            'type': 'ir.actions.act_window',
            'views': [(False, 'list'), (False, 'form')],
            'view_mode': 'list,form',
            'domain': [('res_id', '=', self.id), ('res_model', '=', self._name)],
            'context': {'default_res_model': self._name, 'default_res_id': self.id},
        }

    def _country_restriction(self):
        """
        Hook: code of the country (e.g. ``'KE'``) the current company must have to use the
        sheet, or ``False``.
        """
        return False

    def action_generate_pdf(self):
        """
        Queue the PDF generation of all the declarations of the sheets
        (``hr.payroll.employee.declaration.action_generate_pdf``).
        """
        if not self.line_ids:
            # on an empty recordset, all the draft declarations of the database would be generated
            return False
        return self.line_ids.action_generate_pdf()

    def _post_process_rendering_data_pdf(self, rendering_data):
        """
        Hook to adapt the result of :meth:`_get_rendering_data` before the PDFs are rendered.

        :param dict rendering_data: result of :meth:`_get_rendering_data`
        :return: the rendering data to use
        :rtype: dict
        """
        return rendering_data

    def _get_rendering_data(self, employees):
        """
        Return the data rendered in the PDF of each employee. To override.

        :param employees: ``hr.employee`` records whose PDF must be generated
        :return: ``{employee: data}``; ``data`` is given to the report as ``report_data``. Special
            keys: ``'error'`` (message: no PDF is generated for the sheet and the message is
            stored in ``pdf_error``) and ``'employees_with_error'`` (``{employee: message}``,
            stored in the ``declaration_error`` of their declarations; these employees should
            not be keys of the result)
        :rtype: dict
        :raise UserError: handled like an ``'error'`` key
        """
        return {}

    def _process_files(self, files):
        """
        Store the generated PDFs on the declarations of the sheet and clear ``pdf_error``.

        :param list files: ``(employee, filename, PDF content)`` tuples
        """
        self.ensure_one()
        self.pdf_error = False
        lines_by_employee = self.line_ids.grouped('employee_id')
        for employee, filename, data in files:
            line = lines_by_employee.get(employee, self.env['hr.payroll.employee.declaration'])
            line.write({
                'pdf_file': BinaryBytes(data),
                'pdf_filename': filename,
            })

    def _get_pdf_report(self):
        """
        Hook: ``ir.actions.report`` rendering the PDF of each employee. Must be overridden to
        generate PDFs: ``hr.payroll.employee.declaration._generate_pdf`` reads its ``id``.
        """
        return False

    def _get_pdf_filename(self, employee):
        """
        Return the file name of the PDF of ``employee``.

        :rtype: str
        """
        self.ensure_one()
        return _('%(employee_name)s-declaration-%(year)s', employee_name=employee.legal_name, year=self.year)
