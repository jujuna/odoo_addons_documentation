import { makeDraggableHook } from "@web/core/utils/draggable_hook_builder_owl";
import { DRAGGED_CLASS } from "@web/core/utils/draggable_hook_builder";
import { _t } from "@web/core/l10n/translation";

export const useSuggestionsDraggable = makeDraggableHook({
    name: "useSuggestionsDraggable",
    acceptedParams: {
        component: [Object],
    },
    edgeScrolling: { enabled: true },

    onComputeParams({ ctx, params }) {
        ctx.followCursor = false;
        ctx.component = params.component;
    },

    onDragStart({ ctx, addStyle, addCleanup, addListener, removeClass }) {
        const { current, pointer, component } = ctx;
        const { element } = current;

        removeClass(element, DRAGGED_CLASS);
        component.onDragSuggestion();

        const selectedCount = component.state.selectedRows.size;
        const dragBadge = document.createElement("div");
        dragBadge.style.pointerEvents = "none";
        dragBadge.style.zIndex = "9999";
        dragBadge.style.position = "fixed";

        if (selectedCount > 1) {
            dragBadge.className = "bg-info text-white fw-bold rounded shadow px-3 py-2 z-3";
            dragBadge.innerText = _t("Add %s suggestions", selectedCount);
        } else {
            dragBadge.className = "z-3 shadow-lg rounded bg-view";
            const clone = element.cloneNode(true);
            clone.style.width = `${element.offsetWidth}px`;
            clone.style.margin = "0";
            clone.classList.remove("opacity-50", "o_keyboard_focused", "o_dragged");
            clone.querySelector(".flag")?.remove();
            clone.querySelector(".o_suggestions_suggestion_toolbar")?.remove();
            dragBadge.appendChild(clone);
        }

        document.body.appendChild(dragBadge);
        current.dragBadge = dragBadge;

        addStyle(dragBadge, {
            left: `${pointer.x + 15}px`,
            top: `${pointer.y + 15}px`,
        });

        const suggestionsPane = component.suggestionsContentRef();
        const timesheetsSection = component.timesheetsSectionRef();

        if (suggestionsPane) {
            addListener(
                suggestionsPane,
                "pointerenter",
                () => (current.scrollParentY = suggestionsPane)
            );
        }
        if (timesheetsSection) {
            addListener(
                timesheetsSection,
                "pointerenter",
                () => (current.scrollParentY = timesheetsSection)
            );
        }
        current.scrollParentY = suggestionsPane;

        const dropTargets = timesheetsSection.querySelectorAll(".o_activity_watch_drop_target");
        const onPointerEnter = (ev) => {
            ev.currentTarget.classList.add("o_drag_hover");
            ctx.dragOverTimesheetId = Number(ev.currentTarget.dataset.timesheetId);
        };
        const onPointerLeave = (ev) => {
            ev.currentTarget.classList.remove("o_drag_hover");
            ctx.dragOverTimesheetId = null;
        };

        for (const target of dropTargets) {
            addListener(target, "pointerenter", onPointerEnter);
            addListener(target, "pointerleave", onPointerLeave);
        }

        addCleanup(() => {
            current.dragBadge?.remove();
            dropTargets.forEach((target) => target.classList.remove("o_drag_hover"));
            component.state.isDraggingSuggestions = false;
            current.scrollParentY = null;
        });
    },

    onDrag({ ctx, addStyle }) {
        const { current, pointer, component } = ctx;
        component.state.pendingUnselect = null;

        if (current.dragBadge) {
            addStyle(current.dragBadge, {
                left: `${pointer.x + 15}px`,
                top: `${pointer.y + 15}px`,
            });
        }
    },

    async onDrop({ ctx }) {
        const { component, dragOverTimesheetId } = ctx;

        await component.onDropSuggestions(dragOverTimesheetId);
        ctx.dragOverTimesheetId = null;
    },
});
