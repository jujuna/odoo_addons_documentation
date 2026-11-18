from odoo import models

# Georgian IBAN bank code (positions 5-6) -> (bank name, BIC).
GE_BANKS = {
    'BG': ('Bank of Georgia', 'BAGAGE22'),
    'BS': ('BasisBank', 'CBASGE22'),
    'BT': ('Silk Bank', 'DISNGE22'),
    'CR': ('Cartu Bank', 'CRTUGE22'),
    'HB': ('Halyk Bank Georgia', 'HABGGE22'),
    'KS': ('Terabank', 'TEBAGE22'),
    'LB': ('Liberty Bank', 'LBRTGE22'),
    'PC': ('ProCredit Bank', 'MIBGGE22'),
    'TB': ('TBC Bank', 'TBCBGE22'),
    'VT': ('VTB Bank Georgia', 'UGEBGE22'),
    'ZB': ('Ziraat Bank Georgia', 'TCZBGE22'),
    'PB': ('Pasha Bank Georgia', 'PAHAGE22'),
    'IS': ('Isbank Georgia', 'ISBKGE22'),
    'CD': ('Credo Bank', 'JSCRGE22'),
    'PS': ('Paysera Bank Georgia', 'PSRAGE22'),
    'HS': ('HASH Bank', 'HAJSGE22'),
    'PV': ('Pave Bank Georgia', 'PAVEGE22'),
    'MB': ('Microbank MBC', 'MOMBGE22'),
    'BC': ('Microbank Crystal', 'BCRYGE22'),
}


class ResPartnerBank(models.Model):
    _inherit = 'res.partner.bank'

    def _sanitize_vals(self, vals):
        """Fill the bank name and BIC of a Georgian IBAN from its bank code.
        A value typed in the same save wins; an empty one counts as not typed."""
        super()._sanitize_vals(vals)
        account_number = vals.get('sanitized_account_number') or ''
        bank = account_number.startswith('GE') and GE_BANKS.get(account_number[4:6])
        if not bank:
            return
        if not vals.get('bank_name'):
            vals['bank_name'] = bank[0]
        if not vals.get('bank_bic'):
            vals['bank_bic'] = bank[1]
