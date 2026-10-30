import { LoginScreen } from "@point_of_sale/app/screens/login_screen/login_screen";
import { patch } from "@web/core/utils/patch";
import { useNfcReader } from "@pos_mobile/app/hooks/nfc_reader";

patch(LoginScreen.prototype, {
    setup() {
        super.setup(...arguments);
        if (this.pos.config.module_pos_hr) {
            useNfcReader((uid, payload) => this.loginWithNfcBadge(uid, payload), {
                secure: () => this.pos.config.nfc_secure_login,
            });
        }
    },
    async loginWithNfcBadge(uid, payload) {
        const verifiedId =
            payload &&
            (await this.pos.data
                .call("pos.config", "verify_nfc_badge", [this.pos.config.id, payload])
                .catch(() => false));
        return this.loginWithBadge(
            uid,
            (employee) =>
                employee.id !== verifiedId ||
                (this.pos.config.nfc_manager_pin_required && employee._role === "manager")
        );
    },
});
