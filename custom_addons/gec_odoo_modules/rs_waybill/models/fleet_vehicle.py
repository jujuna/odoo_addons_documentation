from odoo import models, fields, api, _
from odoo.exceptions import UserError


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    rs_imported = fields.Boolean(string='Imported from RS.GE', default=False, copy=False, index=True,
                                 help='True for vehicles auto-created by the RS.GE car-numbers sync.',)
    rs_synced_date = fields.Datetime(string='Last RS.GE Sync', copy=False,)

    driver_vat = fields.Char(string='Driver VAT', related='driver_id.vat', store=True, index=True, readonly=True,
                             copy=False, help='TIN of the assigned driver — pulled from the driver partner.')


    @api.depends('license_plate')
    @api.depends_context('rs_plate_only')
    def _compute_display_name(self):
        """ The waybill's Car Plate field (context rs_plate_only) shows the bare plate, like rs.ge. """
        if self.env.context.get('rs_plate_only'):
            for v in self:
                v.display_name = v.license_plate or v.name
            return
        super()._compute_display_name()


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('license_plate'):
                vals['license_plate'] = vals['license_plate'].strip().upper()
        return super().create(vals_list)


    def write(self, vals):
        if vals.get('license_plate'):
            vals = dict(vals, license_plate=vals['license_plate'].strip().upper())
        return super().write(vals)


    def action_rs_send_car_number(self):
        """ Adds the plate to the RS.GE car list. RS answers -1 for a plate it already has. """
        self.ensure_one()
        plate = (self.license_plate or '').strip().upper()
        if not plate:
            raise UserError(_("Set the License Plate first"))
        service = self.env['rs.waybill.soap.service'].with_company(self.company_id or self.env.company)
        if plate in {p.upper() for p in service.get_car_numbers()}:
            message = _("%s is already on RS.GE.", plate)
        else:
            service._check_rs_result('save_car_numbers', service.save_car_number(plate))
            message = _("%s was added to RS.GE.", plate)
        self.write({'rs_imported': True, 'rs_synced_date': fields.Datetime.now()})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _('RS Vehicle Sync'), 'message': message, 'type': 'success'},
        }

    @api.model
    def action_update_rs_vehicle(self):
        """ Pull car numbers from RS.GE and upsert them as fleet.vehicle records
            (placeholder model 'Unknown (RS Import)'). """
        service = self.env['rs.waybill.soap.service']
        car_numbers = service.get_car_numbers() or []
        placeholder = self._ensure_rs_placeholder_model()
        created = newly_flagged = already = 0
        for plate in car_numbers:
            if not plate:
                continue
            existing = self.with_context(active_test=False).search([('license_plate', '=ilike', plate)], limit=1)
            if existing:
                vals = {'rs_synced_date': fields.Datetime.now()}
                if not existing.rs_imported:
                    vals['rs_imported'] = True
                    newly_flagged += 1
                else:
                    already += 1
                existing.write(vals)
            else:
                self.create({'license_plate': plate, 'model_id': placeholder.id, 'rs_imported': True,
                             'rs_synced_date': fields.Datetime.now()})
                created += 1

        parts = [f'{created} new vehicle(s) imported']
        if newly_flagged:
            parts.append(f'{newly_flagged} linked to RS')
        if already:
            parts.append(f'{already} already on file')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'RS Vehicle Sync',
                'message': ', '.join(parts) + '.',
                'type': 'success',
                'sticky': False,
            },
        }


    @api.model
    def _ensure_rs_placeholder_model(self):
        """ Return the 'Unknown (RS Import)' vehicle model, creating it and its brand once. """
        Model = self.env['fleet.vehicle.model']
        Brand = self.env['fleet.vehicle.model.brand']
        model = Model.search([('name', '=', 'Unknown (RS Import)')], limit=1)
        if model:
            return model
        brand = Brand.search([('name', '=', 'Unknown')], limit=1)
        if not brand:
            brand = Brand.create({'name': 'Unknown'})
        return Model.create({
            'name': 'Unknown (RS Import)',
            'brand_id': brand.id,
        })