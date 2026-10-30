/** @ts-check */

import { ModelNotFoundError } from "@spreadsheet/data_sources/data_source";
import { globalFieldMatchingRegistry } from "@spreadsheet/global_filters/helpers";

/**
 * Load the metadata of all the data sources which can be matched with a global filter.
 *
 * @param {object} getters
 * @returns {Promise<boolean>} false if at least one data source targets a model that does not exist
 */
export async function waitForDataSourcesToBeReady(getters) {
    try {
        const promises = globalFieldMatchingRegistry
            .getAll()
            .flatMap((matcher) => matcher.waitForReady(getters));
        await Promise.all(promises);
    } catch (e) {
        if (e instanceof ModelNotFoundError) {
            if (odoo.debug) {
                console.error(e);
            }
            return false;
        }
        throw e;
    }
    return true;
}
