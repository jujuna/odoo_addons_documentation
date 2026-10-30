import { user } from "@web/core/user";
import { onWillStart } from "@odoo/owl";

import { AccountProductCatalogSearchPanel } from "@account/components/product_catalog/search/search_panel/search_panel";

export class FSMProductCatalogSearchPanel extends AccountProductCatalogSearchPanel {
    setup() {
        super.setup();
        onWillStart(async () => {
            this.canCreateSections = await user.hasGroup("sales_team.group_sale_salesman");
        });
    }
}
