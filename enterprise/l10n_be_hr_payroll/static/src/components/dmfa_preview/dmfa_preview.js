import { Component, onWillStart, proxy, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { Layout } from "@web/search/layout";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";

/**
 * Preview of a DmfA declaration, for the whole company or one of its branches, restricted to the
 * employees the user can access.
 */
export class DmfaPreview extends Component {
    static template = "l10n_be_hr_payroll.DmfaPreview";
    static components = { Layout };
    props = useProps(standardActionServiceProps);

    setup() {
        useSetupAction();
        this.orm = useService("orm");
        this.action = useService("action");
        this.dmfaId = this.props.action.params?.dmfa_id;
        this.state = proxy({
            companies: [],
            companyId: false,
            html: "",
            loading: true,
            printing: false,
        });
        onWillStart(async () => {
            this.state.companies = await this.orm.call("l10n_be.dmfa", "get_preview_companies", [
                [this.dmfaId],
            ]);
            await this.loadPreview();
        });
    }

    async loadPreview() {
        this.state.loading = true;
        try {
            this.state.html = await this.orm.call("l10n_be.dmfa", "get_preview_html", [[this.dmfaId]], {
                company_id: this.state.companyId,
            });
        } finally {
            this.state.loading = false;
        }
    }

    async onCompanyChange(ev) {
        this.state.companyId = parseInt(ev.target.value) || false;
        await this.loadPreview();
    }

    async onPrint() {
        this.state.printing = true;
        try {
            const action = await this.orm.call("l10n_be.dmfa", "action_print_preview", [[this.dmfaId]], {
                company_id: this.state.companyId,
            });
            await this.action.doAction(action);
        } finally {
            this.state.printing = false;
        }
    }
}

registry.category("actions").add("l10n_be_hr_payroll.dmfa_preview", DmfaPreview);
