import { _t } from "@web/core/l10n/translation";
import { Plugin } from "@html_editor/plugin";
import { firstLeaf, lastLeaf, getCommonAncestor } from "@html_editor/utils/dom_traversal";
import { withSequence } from "@html_editor/utils/resource";
import { isContentEditable } from "@html_editor/utils/dom_info";
import { nodeSize } from "@html_editor/utils/position";
import { MAIN_PLUGINS } from "@html_editor/plugin_sets";
import { user } from "@web/core/user";
import { MAIL_CORE_PLUGINS } from "@mail/core/common/plugin/plugin_sets";

export class ChatGPTPlugin extends Plugin {
    static id = "chatgpt";
    static dependencies = [
        "baseContainer",
        "selection",
        "history",
        "dom",
        "sanitize",
        "dialog",
        "split",
        "format",
        "delete",
    ];
    static shared = ["openDialog"];
    resources = {
        user_commands: [
            {
                id: "openChatGPTDialog",
                title: _t("AI"),
                description: _t("Generate or transform content with AI"),
                run: this.openDialog.bind(this),
                isAvailable: () => user.isInternalUser,
            },
        ],
        toolbar_groups: withSequence(50, {
            id: "ai",
        }),
        toolbar_items: [
            {
                id: "chatgpt",
                groupId: "ai",
                commandId: "openChatGPTDialog",
                namespaces: ["compact", "expanded"],
                icon: "o_ai_icon",
                isDisabled: this.isNotReplaceableByAI.bind(this),
            },
        ],
        powerbox_categories: withSequence(70, { id: "ai", name: _t("AI Tools") }),
        powerbox_items: {
            keywords: [_t("AI")],
            categoryId: "ai",
            commandId: "openChatGPTDialog",
            icon: "wand_stars",
        },
        power_buttons: withSequence(20, {
            commandId: "openChatGPTDialog",
            icon: "o_ai_icon",
        }),
    };

    setup() {
        this.cachedSelections = {};
    }

    isNotReplaceableByAI(selection = this.dependencies.selection.getEditableSelection()) {
        if (selection.isCollapsed) {
            return false;
        }
        const isEmpty = !selection.toString().replace(/\s+/g, "");
        const cannotReplace = this.dependencies.selection
            .getTargetedNodes()
            .find((el) => this.dependencies.split.isUnsplittable(el) || !isContentEditable(el));
        return cannotReplace || isEmpty;
    }

    // TODO Remove in master
    createSelectBlock(nodes) {
        const connectedNodes = nodes.filter((node) => node.isConnected);
        if (!connectedNodes.length) {
            return;
        }
        const firstInsertedNode = connectedNodes[0];
        const lastInsertedNode = connectedNodes[connectedNodes.length - 1];
        const anchorNode = firstLeaf(firstInsertedNode);
        const focusNode = lastLeaf(lastInsertedNode);
        const commonAncestor = getCommonAncestor([anchorNode, focusNode]);
        return {
            anchorNode: anchorNode,
            anchorOffset: 0,
            focusNode: focusNode,
            focusOffset: nodeSize(focusNode),
            startContainer: anchorNode,
            startOffset: 0,
            endContainer: focusNode,
            endOffset: nodeSize(focusNode),
            commonAncestorContainer: commonAncestor,
        };
    }

    async openDialog(params = {}) {
        const selection = this.dependencies.selection.getEditableSelection();
        const dialogParams = {
            insert: (content, selection) => {
                if (selection) {
                    selection.restore();
                    this.dependencies.format.removeSelectionFormats();
                    this.dependencies.delete.deleteSelection();
                }
                const isTextLines = content.textContent.includes("\n") && !content.children.length; // text nodes only
                if (isTextLines) {
                    const fragment = this.document.createDocumentFragment();
                    for (const line of content.textContent.split("\n")) {
                        const textNode = this.document.createTextNode(line.trim());
                        const container = this.document.createElement(
                            // First line inline
                            fragment.children.length ? "p" : "span"
                        );
                        container.appendChild(textNode);
                        fragment.appendChild(container);
                    }
                    content = fragment;
                }
                const insertedNodes = this.dependencies.dom.insert(content);
                this.dependencies.history.commit();
                // Add a frame around the inserted content to highlight it for 2
                // seconds.
                if (insertedNodes?.length) {
                    const divContainer = this.editable.parentElement;
                    let editorLeftOffset = 0;
                    let offsetEl = divContainer;
                    while (offsetEl) {
                        editorLeftOffset += offsetEl.offsetLeft;
                        offsetEl = offsetEl.offsetParent;
                    }
                    const rectangleOf = (node) => {
                        const range = this.document.createRange();
                        range.selectNodeContents(node);
                        return range.getBoundingClientRect();
                    };
                    const bigRect = { left: Infinity, right: 0, top: Infinity, bottom: 0 };
                    for (const node of insertedNodes) {
                        if (!node.isConnected) {
                            continue;
                        }
                        const rect = rectangleOf(node);
                        if (!rect.left || !rect.top) {
                            continue;
                        }
                        bigRect.left = Math.min(bigRect.left, rect.left);
                        bigRect.right = Math.max(bigRect.right, rect.right);
                        bigRect.top = Math.min(bigRect.top, rect.top);
                        bigRect.bottom = Math.max(bigRect.bottom, rect.bottom);
                    }
                    const rectDiv = rectangleOf(divContainer);
                    const div = document.createElement("div");
                    div.classList.add("o-chatgpt-content");
                    const FRAME_PADDING = 3;
                    div.style.left = `${bigRect.left - editorLeftOffset - FRAME_PADDING}px`;
                    div.style.top = `${bigRect.top - rectDiv.top - FRAME_PADDING}px`;
                    div.style.width = `${bigRect.right - bigRect.left + FRAME_PADDING * 2}px`;
                    div.style.height = `${bigRect.bottom - bigRect.top + FRAME_PADDING * 2}px`;
                    divContainer.prepend(div);
                    setTimeout(() => div.remove(), 2000);
                    const selectionAfterInsert = this.dependencies.selection.getEditableSelection();
                    this.dependencies.selection.setSelection(
                        {
                            anchorNode: insertedNodes[0],
                            anchorOffset: 0,
                            focusNode: selectionAfterInsert.anchorNode,
                            focusOffset: selectionAfterInsert.anchorOffset,
                        },
                        { normalize: false }
                    );
                }
                return this.dependencies.selection.preserveSelection();
            },
            selectPreviousInsertion: (selectionId) => this.cachedSelections[selectionId],
            setCursor: (selectionId, cursor) => (this.cachedSelections[selectionId] = cursor),
            ...params,
        };
        dialogParams.baseContainer = this.dependencies.baseContainer.getDefaultNodeName();
        // collapse to end
        let callerComp,
            recordModel,
            recordId,
            recordData,
            recordFields,
            callerId,
            channelTitle,
            textSelection;
        const { resModel, resId, data, fields, id } = this.config.getRecordInfo();
        const textOfEditable = this.editable.innerText;
        if (selection.isCollapsed) {
            if (resModel === "mail.compose.message") {
                callerComp = "mail_composer";
                recordModel = data.model;
                recordId = Number(data.res_ids.slice(1, -1)); // resIds should look like so `[id]`, the slice and cast allows to extract the id
                recordData = data;
                channelTitle = data.subject;
                callerId = id;
            } else {
                callerComp = params.callerComp || "html_field_record";
                recordModel = resModel;
                recordId = resId;
                recordData = data;
                recordFields = fields;
                channelTitle = params.channelTitle || data?.display_name || _t("Editor");
                callerId = resId || id;
            }
            textSelection = {
                selectionId: `ai-selection-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
            };
        } else {
            callerComp = "html_field_text_select";
            recordModel = resModel;
            recordId = resId;
            recordData = data;
            recordFields = fields;
            channelTitle = _t("Text Selection");
            callerId = resId || id;

            const textOfSelection = selection.toString();
            const selectionId = `ai-selection-${Date.now()}-${Math.floor(Math.random() * 1000)}`;

            textSelection = {
                selectionId: selectionId,
                textContent: textOfSelection,
            };
        }
        this.cachedSelections[textSelection.selectionId] =
            this.dependencies.selection.preserveSelection();
        await this.services.aiChatLauncher.launchAIChat({
            interfaceKey: callerComp,
            recordModel: recordModel,
            recordId: recordId,
            originalRecordData: recordData,
            originalRecordFields: recordFields,
            aiSpecialActions: {
                insert: dialogParams.insert,
                selectPreviousInsertion: dialogParams.selectPreviousInsertion,
                setCursor: dialogParams.setCursor,
            },
            channelTitle: channelTitle,
            aiChatSourceId: callerId,
            textSelection: textSelection,
            textOfEditable: textOfEditable,
        });
        if (this.services.ui.isSmall) {
            // TODO: Find a better way and avoid modifying range
            // HACK: In the case of opening through dropdown:
            // - when dropdown open, it keep the element focused before the open
            // - when opening the dialog through the dropdown, the dropdown closes
            // - upon close, the generic code of the dropdown sets focus on the kept element (in our case, the editable)
            // - we need to remove the range after the generic code of the dropdown is triggered so we hack it by removing the range in the next tick
            Promise.resolve().then(() => {
                // If the dialog is opened on a small screen, remove all selection
                // because the selection can be seen through the dialog on some devices.
                this.document.getSelection()?.removeAllRanges();
            });
        }
    }

    destroy() {
        const { resModel } = this.config.getRecordInfo();
        if (resModel !== "mail.compose.message") {
            this.services["mail.store"].aiInsertButtonTarget = false;
        }
        super.destroy();
    }
}

MAIN_PLUGINS.push(ChatGPTPlugin);
MAIL_CORE_PLUGINS.push(ChatGPTPlugin);
