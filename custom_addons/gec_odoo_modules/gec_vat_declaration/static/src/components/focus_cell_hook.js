import { onPatched, useScope } from "@odoo/owl";

/** After a render, focus and select `findInput(component.cellToFocus)` once that input exists. */
export function useFocusCell(component, findInput) {
    const scope = useScope();
    onPatched(async () => {
        await Promise.resolve();
        if (scope.isDestroyed() || !component.cellToFocus) {
            return;
        }
        const input = findInput(component.cellToFocus);
        if (input) {
            input.focus();
            input.select();
            component.cellToFocus = null;
        }
    });
}
