/** @odoo-module **/

import { Component, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";

/** The user guide: frames the HTML page served by /bsc_strategy/guide so the menu and breadcrumbs stay. */
export class BscUserGuide extends Component {
    static template = "bsc_strategy.UserGuide";

    props = useProps();

    get url() {
        const anchor = this.props.action?.params?.anchor;
        return "/bsc_strategy/guide" + (anchor ? `#${anchor}` : "");
    }
}

registry.category("actions").add("bsc_user_guide", BscUserGuide);
