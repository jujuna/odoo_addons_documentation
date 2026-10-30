import { setupPosBlackboxEnv } from "@l10n_be_pos_blackbox/../tests/unit/utils";
import { registry } from "@web/core/registry";
import { unpatchPrepDataPlugin } from "@pos_enterprise/app/plugins/pos_data_plugin";
import { unpatchDataServiceOptions } from "@pos_enterprise/override/point_of_sale/data_service_options";

export const setupPosBlackboxUrbanPiperEnv = async (...args) => {
    unpatchPrepDataPlugin();
    unpatchDataServiceOptions();
    registry.category("services").remove("preparation_display");
    return setupPosBlackboxEnv(...args);
};
