import { AccountProductCatalogSearchModel } from "@account/components/product_catalog/search/search_model";

export class FSMProductCatalogSearchModel extends AccountProductCatalogSearchModel {
    _getSectionInfoParams(config) {
        return {
            ...super._getSectionInfoParams(config),
            intervention_id: config.context.intervention_id,
        };
    }
}
