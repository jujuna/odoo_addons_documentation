from odoo import models, release


class PosOrderReceipt(models.AbstractModel):
    _inherit = 'pos.order.receipt'
    _description = 'Point of Sale Order Receipt Generator'

    def _order_receipt_generate_line_data(self):
        lines = super()._order_receipt_generate_line_data()
        if not self.config_id.l10n_be_blackbox_be_id:
            return lines
        for line_data, line in zip(lines, self.lines):
            taxes = line.tax_ids
            labels = list(dict.fromkeys(
                tax.tax_group_id.pos_receipt_label
                for tax in taxes
                if tax.tax_group_id.pos_receipt_label
            ))
            line_data['tax_group_labels'] = ' '.join(labels)
        return lines

    def order_receipt_generate_data(self, basic_receipt=False):
        data = super().order_receipt_generate_data(basic_receipt)
        if not self.config_id.l10n_be_blackbox_be_id:
            return data
        copy_event_data = self.env.context.get('l10n_be_copy_event_data')

        is_signed = bool(self.l10n_be_short_signature) and self.state != 'draft'
        data['conditions']['l10n_be_blackbox_be_id'] = bool(self.config_id.l10n_be_blackbox_be_id)
        data['conditions']['l10n_be_is_pro_forma'] = not is_signed

        data['extra_data']['l10n_be_order_type_string'] = self.get_order_type_blackbox()
        data['extra_data']['establishment_number'] = self.config_id.establishment_number
        data['extra_data']['posSwVersion'] = release.version
        data['extra_data']['fdmSwVersion'] = self.l10n_be_fdm_sw_version
        if self.refunded_order_id:
            refunded = self.refunded_order_id
            data['extra_data']['refunded_order_id'] = {
                'pos_reference': refunded.pos_reference,
                'l10n_be_fdm_id': refunded.l10n_be_fdm_id,
                'l10n_be_pos_id': refunded.l10n_be_pos_id,
                'l10n_be_terminal_id': refunded.l10n_be_terminal_id,
                'l10n_be_device_id': refunded.l10n_be_device_id,
                'l10n_be_fdm_date_time': refunded.l10n_be_fdm_date_time.strftime('%Y-%m-%d %H:%M:%S') if refunded.l10n_be_fdm_date_time else False,
                'l10n_be_event_label': refunded.l10n_be_event_label,
                'l10n_be_event_counter': refunded.l10n_be_event_counter,
                'l10n_be_total_counter': refunded.l10n_be_total_counter,
                'l10n_be_short_signature': refunded.l10n_be_short_signature,
            }

        if copy_event_data is not None:
            data['order']['l10n_be_copy_event_data'] = copy_event_data

        data['image']['l10n_be_verification_qr'] = self._order_receipt_generate_qr_code(self.l10n_be_verification_url)
        return data
