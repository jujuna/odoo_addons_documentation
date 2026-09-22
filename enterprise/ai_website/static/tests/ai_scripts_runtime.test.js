import { click, describe, expect, test, microTick, queryFirst } from "@odoo/hoot";
import { defineWebsiteModels } from "@website/../tests/builder/website_helpers";
import { defineAIModels } from "@ai/../tests/ai_test_helpers";
import { loadBundle } from "@web/core/assets";
import { setupAiWebsiteBuilder } from "./ai_website_test_helpers";

defineAIModels();
defineWebsiteModels({
    includeMailModels: false,
});

async function setupScriptsManager(websiteContent) {
    await setupAiWebsiteBuilder(websiteContent, { openEditor: false });
    await loadBundle("website.website_builder_assets");
    const doc = queryFirst(":iframe");
    const runtime = doc.defaultView.__aiScriptsManager__.runtime;
    return {
        doc,
        runtime,
        addScript(scriptId) {
            const scriptEl = doc.createElement("script");
            scriptEl.dataset.aiScriptId = scriptId;
            doc.querySelector("#wrap").appendChild(scriptEl);
            return scriptEl;
        },
        aiRun(fn) {
            runtime.protectMutations(fn)();
        },
    };
}

describe("AI scripts runtime", () => {
    // TODO SERU: find a way to make this work functionally.
    test.todo("stopping one of two scripts should keep the other script's changes", async () => {
        const { runtime, addScript, aiRun } = await setupScriptsManager(
            `<section><div class="target" style="color: blue;">content</div></section>`
        );
        const target = queryFirst(":iframe .target");
        const scriptA = addScript("script_a");
        const scriptB = addScript("script_b");

        aiRun(() => {
            runtime.trackElement(target, scriptA);
            target.style.color = "red";
        });
        aiRun(() => {
            runtime.trackElement(target, scriptB);
            target.classList.add("from-b");
        });

        runtime.disposeScript(scriptB);
        expect(target).not.toHaveClass("from-b");
        expect(target.style.color).toBe("red");
    });

    test("stopping a script should leave the element usable by the script still running", async () => {
        const { runtime, addScript, aiRun } = await setupScriptsManager(
            `<section><div class="target" style="color: blue;">content</div></section>`
        );
        const target = queryFirst(":iframe .target");
        const original = target.outerHTML;
        const scriptA = addScript("script_a");
        const scriptB = addScript("script_b");

        aiRun(() => {
            runtime.trackElement(target, scriptA);
            target.style.color = "red";
        });
        aiRun(() => {
            runtime.trackElement(target, scriptB);
            target.classList.add("from-b");
        });

        runtime.disposeScript(scriptA);
        expect(target.outerHTML).toBe(original);

        aiRun(() => {
            runtime.trackElement(target, scriptB);
            target.style.opacity = "0.5";
        });
        expect(target.outerHTML).not.toBe(original);
        runtime.disposeScript(scriptB);
        expect(target.outerHTML).toBe(original);
    });

    test("a user edit on an AI-owned property should save this change", async () => {
        const { runtime, addScript, aiRun } = await setupScriptsManager(
            `<section><div class="target" style="color: blue;">content</div></section>`
        );
        const target = queryFirst(":iframe .target");
        const scriptEl = addScript("script_a");

        aiRun(() => {
            runtime.trackElement(target, scriptEl);
            target.style.color = "red";
        });
        await microTick();

        // The user overrides the property the AI made.
        target.style.color = "green";
        await microTick();

        // The script then writes it again: the value to restore is now the
        // user's one, not the original one.
        aiRun(() => {
            target.style.color = "purple";
        });
        await microTick();

        runtime.disposeScript(scriptEl);
        expect(target.style.color).toBe("green");
    });

    test("disposeAll should leave the page clean and trackable again", async () => {
        const { runtime, addScript, aiRun } = await setupScriptsManager(
            `<section><div class="target" style="color: blue;">content</div></section>`
        );
        const target = queryFirst(":iframe .target");
        const original = target.outerHTML;
        const scriptA = addScript("script_a");

        aiRun(() => {
            runtime.trackElement(target, scriptA);
            target.style.color = "red";
        });

        runtime.disposeAll();
        expect(target.outerHTML).toBe(original);
        expect(":iframe [data-ai-tracked]").toHaveCount(0);

        // The scripts are restarted (e.g. when leaving the editor): tracking
        // must work again on the same element.
        const scriptB = addScript("script_b");
        aiRun(() => {
            runtime.trackElement(target, scriptB);
            target.style.color = "green";
        });
        runtime.disposeScript(scriptB);
        expect(target.outerHTML).toBe(original);
    });

    test("should correctly handle ai and non-ai mutations done together", async () => {
        const { runtime, addScript } = await setupScriptsManager(
            `<section><button class="target" style="color: blue; font-size: 10px;">Click</button></section>`
        );
        const target = queryFirst(":iframe .target");
        const scriptEl = addScript("script_a");

        // Both listeners answer the same click, but the AI's one should be
        // revertable.
        target.addEventListener(
            "click",
            runtime.protectMutations(() => {
                runtime.trackElement(target, scriptEl);
                target.style.color = "red";
            })
        );
        target.addEventListener("click", () => {
            target.style.fontSize = "20px";
        });

        await click(target);
        await microTick();
        expect(target.style.color).toBe("red");
        expect(target.style.fontSize).toBe("20px");

        // Should revert ai script's changes, while keeping the normal ones.
        runtime.disposeScript(scriptEl);
        expect(target.style.color).toBe("blue");
        expect(target.style.fontSize).toBe("20px");
    });
});
