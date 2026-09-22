/** @odoo-module **/

import { Component, proxy, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { user } from "@web/core/user";

export class SwissdecInteroperabilityClient extends Component {
    static template = "l10n_ch_hr_payroll.SwissdecInteroperabilityClient";

    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.company = user.activeCompany;
        this.state = proxy({
            ping_response: false,
            check_interoperability_response: false,
            second_operand: ""
        });
    }

    async PingRequest(){
        this.state.ping_response = await this.orm.call('res.company', 'l10n_ch_hr_payroll_action_ping', [[this.company.id]]);
    }

    async CheckInteroperabilityRequest(ev){
        this.state.check_interoperability_response = await this.orm.call('res.company', 'l10n_ch_hr_payroll_action_check_interoperability', [
            [this.company.id],
            this.state.second_operand
        ]);
    }

    onOperandInput(ev){
        this.state.second_operand = ev.target.value
    }
}

registry.category("actions").add("swissdec_interoperability_client", SwissdecInteroperabilityClient);
