import { Plugin, useListener } from "@odoo/owl";
import { rpcBus } from "@web/core/network/rpc";
import { UPDATE_METHODS } from "@web/core/orm_plugin";
import { services } from "@web/core/services";

export class SalaryBenefitViewsPlugin extends Plugin {
    setup() {
        // (un)archiving a benefit (un)archives its related views server side
        useListener(rpcBus, "RPC:RESPONSE", (ev) => {
            const { data, error } = ev.detail;
            const { model, method } = data.params;
            if (!error && model === "hr.contract.salary.benefit" && UPDATE_METHODS.includes(method)) {
                rpcBus.trigger("CLEAR-CACHES", "get_views");
            }
        });
    }
}

services.add(SalaryBenefitViewsPlugin);
