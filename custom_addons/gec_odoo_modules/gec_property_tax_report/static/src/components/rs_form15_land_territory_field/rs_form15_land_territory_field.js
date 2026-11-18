/** @odoo-module **/

import { Component, onWillStart, proxy, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useOwnedDialogs, useService } from "@web/core/utils/hooks";
import { computeM2OProps, Many2One } from "@web/views/fields/many2one/many2one";
import {
    buildM2OFieldDescription,
    many2OneFieldProps,
} from "@web/views/fields/many2one/many2one_field";

/** "/region/municipality/zone" to its levels; rs.ge writes a few names as "region/ municipality". */
function pathOf(name) {
    return name
        .split("/")
        .map((part) => part.trim())
        .filter(Boolean);
}

function sortTree(nodes) {
    nodes.sort((a, b) => a.label.localeCompare(b.label));
    for (const node of nodes) {
        sortTree(node.children);
    }
    return nodes;
}

/** Land territorial units as the portal shows them (region > municipality > zone), rebuilt from the names.
 * A level with no record of its own can only be opened; a level that is a record can be picked, even with children. */
export class LandTerritoryTreeDialog extends Component {
    static template = "gec_property_tax_report.LandTerritoryTreeDialog";
    static components = { Dialog };
    props = useProps({
        close: t.function(),
        domain: t.array().optional([]),
        selectedId: t.or([t.number(), t.literal(false)]).optional(false),
        onSelect: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.title = _t("Territorial unit, location");
        this.roots = [];
        this.state = proxy({ search: "", expanded: {} });
        onWillStart(async () => {
            const records = await this.orm.searchRead(
                "rs.form15.land.territory",
                this.props.domain,
                ["name"]
            );
            this.roots = this.buildTree(records);
            this.expandTo(this.props.selectedId);
        });
    }

    buildTree(records) {
        const roots = [];
        const nodes = new Map();
        for (const record of records) {
            let siblings = roots;
            let node = null;
            let key = "";
            for (const label of pathOf(record.name)) {
                key += `/${label}`;
                node = nodes.get(key);
                if (!node) {
                    node = { key, label, id: false, name: "", children: [] };
                    nodes.set(key, node);
                    siblings.push(node);
                }
                siblings = node.children;
            }
            if (node) {
                node.id = record.id;
                node.name = record.name;
            }
        }
        return sortTree(roots);
    }

    /** Open every level above the current value, so the dialog starts where the row is. */
    expandTo(recordId) {
        const visit = (nodes, ancestors) => {
            for (const node of nodes) {
                if (node.id === recordId) {
                    for (const key of ancestors) {
                        this.state.expanded[key] = true;
                    }
                    return true;
                }
                if (visit(node.children, [...ancestors, node.key])) {
                    return true;
                }
            }
            return false;
        };
        if (recordId) {
            visit(this.roots, []);
        }
    }

    subtreeMatches(node, query) {
        return (
            node.key.toLocaleLowerCase().includes(query) ||
            node.children.some((child) => this.subtreeMatches(child, query))
        );
    }

    /** The tree flattened to the rows on screen; a search opens every level that matches. */
    get rows() {
        const query = this.state.search.trim().toLocaleLowerCase();
        const rows = [];
        const walk = (nodes, depth) => {
            for (const node of nodes) {
                if (query && !this.subtreeMatches(node, query)) {
                    continue;
                }
                const isOpen = Boolean(query) || Boolean(this.state.expanded[node.key]);
                rows.push({ node, depth, isOpen });
                if (isOpen) {
                    walk(node.children, depth + 1);
                }
            }
        };
        walk(this.roots, 0);
        return rows;
    }

    onSearch(event) {
        this.state.search = event.target.value;
    }

    toggle(node) {
        if (node.children.length) {
            this.state.expanded[node.key] = !this.state.expanded[node.key];
        }
    }

    select(node) {
        this.props.onSelect(node.id, node.name);
        this.props.close();
    }
}

/** The standard many2one, plus a button that opens the territory tree. */
export class RsForm15LandTerritoryField extends Component {
    static template = "gec_property_tax_report.LandTerritoryField";
    static components = { Many2One };
    props = useProps({ ...many2OneFieldProps });

    setup() {
        this.addDialog = useOwnedDialogs();
    }

    get m2oProps() {
        return computeM2OProps(this.props);
    }

    openTree() {
        const m2oProps = this.m2oProps;
        const value = this.props.record.data[this.props.name];
        this.addDialog(LandTerritoryTreeDialog, {
            domain: m2oProps.domain() || [],
            selectedId: value?.id || false,
            onSelect: (id, displayName) => m2oProps.update({ id, display_name: displayName }),
        });
    }
}

registry.category("fields").add("rs_form15_land_territory", {
    ...buildM2OFieldDescription(RsForm15LandTerritoryField),
});
