import { registry } from "@web/core/registry";
import { FSMProductCatalogKanbanRecord } from "./kanban_record";
import { FSMProductCatalogKanbanController } from "./kanban_controller";
import { FSMProductCatalogKanbanModel } from "./kanban_model";
import { productCatalogKanbanView } from "@product/product_catalog/kanban_view";
import { ProductCatalogKanbanRenderer } from "@product/product_catalog/kanban_renderer";
import { FSMProductCatalogSearchPanel } from "./search/search_panel";
import { FSMProductCatalogSearchModel } from "./search/search_model";

export class FSMProductCatalogKanbanRenderer extends ProductCatalogKanbanRenderer {
    static components = {
        ...ProductCatalogKanbanRenderer.components,
        KanbanRecord: FSMProductCatalogKanbanRecord,
    };

    get createProductContext() {
        return { default_invoice_policy: "delivery" };
    }
}

export const fsmProductCatalogKanbanView = {
    ...productCatalogKanbanView,
    Renderer: FSMProductCatalogKanbanRenderer,
    Controller: FSMProductCatalogKanbanController,
    Model: FSMProductCatalogKanbanModel,
    SearchPanel: FSMProductCatalogSearchPanel,
    SearchModel: FSMProductCatalogSearchModel,
};

registry.category("views").add("field_service_product_kanban", fsmProductCatalogKanbanView);
