import { patch } from '@web/core/utils/patch';
import { CustomerAddress } from '@portal/interactions/address';

patch(CustomerAddress.prototype, {
    async _onChangeCountry(init=false) {
        await super._onChangeCountry(...arguments);

        if (this.addressForm.l10n_mx_edi_colony) {
            const countryCode = this._getSelectedCountryCode();

            if (countryCode === "MX") {
                this._showInput("l10n_mx_edi_colony");
            } else {
                this._hideInput("l10n_mx_edi_colony");
            }
        }
    },
});
