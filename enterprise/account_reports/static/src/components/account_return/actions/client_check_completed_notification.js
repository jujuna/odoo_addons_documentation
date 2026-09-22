import { EventBus } from "@odoo/owl";
import { registry } from "@web/core/registry";


export async function AccountReturnRefreshHandler(_, action) {
    const params = action.params || {};
    const bus = new EventBus();
    bus.trigger("return_reload_model", {resIds: params.return_ids});
    return params.next_action;
}

registry.category("actions").add("action_return_refresh", AccountReturnRefreshHandler)
