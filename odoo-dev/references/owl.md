# OWL 3 & Frontend — Odoo 20

Odoo 20 ships **OWL 3** (`addons/web/static/lib/owl/owl.js` reports `3.0.0-alpha.49`).
This is a new reactivity model — signals and proxies — not a version bump. Anything you
remember from OWL 2 (`useState`, `reactive`, `t-esc`, implicit `this` in templates) is
either gone or moved to a compatibility layer.

**Working rule: before writing a component, open the nearest equivalent in
`addons/web/static/src/` and copy its shape.** OWL 3 is still alpha and the idioms are set
by what core does, not by external documentation.

1. [What changed from OWL 2](#1-what-changed-from-owl-2)
2. [Canonical component](#2-canonical-component)
3. [Reactivity: proxy, signal, computed](#3-reactivity-proxy-signal-computed)
4. [Props with `useProps` and `t`](#4-props-with-useprops-and-t)
5. [Effects and lifecycle](#5-effects-and-lifecycle)
6. [Templates](#6-templates)
7. [Services and registries](#7-services-and-registries)
8. [Asset bundles](#8-asset-bundles)
9. [Common patterns](#9-common-patterns)
10. [Inheriting core OWL templates](#10-inheriting-core-owl-templates)
11. [Migrating v19 frontend code](#11-migrating-v19-frontend-code)
12. [Review checklist](#12-review-checklist)

---

## 1. What changed from OWL 2

| OWL 2 | OWL 3 | Import |
|---|---|---|
| `useState(obj)` | `proxy(obj)` | `@odoo/owl` |
| `reactive(obj)` | `proxy(obj)` | `@odoo/owl` |
| — | `signal(v)`, `signal.ref()` | `@odoo/owl` |
| computed getter | `computed(() => ...)`, **called**: `this.pages()` | `@odoo/owl` |
| `static props = {...}` | `props = useProps(schema)` with `t.*` types — `static props` **throws** | `@odoo/owl` |
| `useEffect(fn, deps)` | `useLayoutEffect(fn, () => deps)` | `@web/owl2/utils` |
| `onWillRender` | same name | `@web/owl2/utils` |
| `useEnv`, `useSubEnv` | same names | `@web/owl2/utils` |
| `useRef("x")` + `ref.el` | `x = signal.ref()` + `this.x()` | `@odoo/owl` |
| `useExternalListener(t, ev, fn)` | `useListener(t, ev, fn)` | `@odoo/owl` |
| `useComponent`, `useChildSubEnv`, `onRendered` | **gone** — 0 imports in core | — |
| `t-esc` | `t-out` | — |
| `t-slot="x"` | `t-call-slot="x"` | — |
| implicit `props.x` in templates | explicit `this.props.x` | — |
| `t-portal` | `t-custom-portal` | compat layer |

Counts in `addons/web/static/src`: `useState` 0, `proxy(` 146, `useProps(` 320,
`signal.ref()` 143, `computed(` 73, `t-esc` 2, `t-slot=` 0, `t-call-slot=` 95.

### What each module actually exports (verified)

- **`@odoo/owl`**: `App Component ErrorBoundary EventBus OwlError Plugin Portal Registry
  Resource Scope Suspense TemplateSet applyDefaults assertType asyncComputed batched blockDom
  computed config effect getDefault getScope globalTemplates htmlEscape immediateEffect
  markRaw markup mount onError onMounted onPatched onWillDestroy onWillPatch onWillStart
  onWillUnmount onWillUpdateProps plugin props providePlugins proxy shallowEqual signal
  status t toRaw types untrack useApp useConfig useEffect useListener useOnChange usePlugin
  useProps useScope validateType whenReady xml` — the `__export` block at the top of
  [owl.js](../../../../addons/web/static/lib/owl/owl.js).
- **`@web/owl2/utils`**: `render`, `onWillRender`, `useLayoutEffect`, `useEnv`, `useSubEnv`
  — nothing else ([owl2/utils.js](../../../../addons/web/static/src/owl2/utils.js)).

Importing any other name (`useState`, `useRef`, `reactive`, `useComponent`,
`useExternalListener`, `onRendered`, `useChildSubEnv`) does **not** fail the bundle: the
binding is `undefined` and the component crashes when `setup()` calls it. Grep for them.

`useEffect` is a trap: it still exists in `@odoo/owl`, but as `useEffect(fn)` — a reactive
effect with no dependency list. An OWL 2 `useEffect(fn, () => [deps])` keeps compiling and
the deps are ignored. Use `useLayoutEffect` from `@web/owl2/utils` for the OWL 2 behaviour.

**`static props` / `static defaultProps` crash the component.** The compatibility layer
throws in the constructor — "defines a static "props" or "defaultProps", which Owl 3
ignores" — for every component that has either
([owl3_compatibility_layer.js:45](../../../../addons/web/static/src/owl2/owl3_compatibility_layer.js#L45)).
Core has none left. Replace by the matching core schema:

| Component | v20 declaration |
|---|---|
| field widget | `props = useProps(standardFieldProps)` (78 core uses), or `useProps({ ...standardFieldProps, extra: t.string().optional() })` |
| client action (`static props = ["*"]`) | `props = useProps(standardActionServiceProps)` from `@web/webclient/actions/action_plugin` |
| dialog / any component | `props = useProps({ close: t.function(), x: t.number(), y: t.any().optional() })` |

`static propsSchema` in core `dialog.js` is a different, temporary mechanism for dialog
subclasses — not a replacement for `static props`.

---

## 2. Canonical component

Straight from [addons/web/static/src/core/notebook/notebook.js](../../../../addons/web/static/src/core/notebook/notebook.js):

```js
import { useLayoutEffect } from "@web/owl2/utils";
import { Component, computed, proxy, signal, t, useOnChange, useProps } from "@odoo/owl";

export const notebookProps = {
    slots: t.object().optional(),
    pages: t.array().optional(),
    className: t.string().optional(""),
    defaultPage: t.string().optional(),
    onPageUpdate: t.function().optional(() => () => {}),
};

export class Notebook extends Component {
    static template = "web.Notebook";
    props = useProps(notebookProps);

    activePane = signal.ref();

    setup() {
        this.pages = computed(() => this.computePages(this.props));
        this.state = proxy({ currentPage: null });
        this.state.currentPage = this.computeActivePage(this.props.defaultPage, true);

        useLayoutEffect(
            () => { this.props.onPageUpdate(this.state.currentPage); },
            () => [this.state.currentPage],
        );

        useOnChange(
            () => [this.props.defaultPage],
            (defaultPage) => { this.state.currentPage = this.computeActivePage(defaultPage, true); },
            { initialRun: false },
        );
    }

    get navItems() {
        return this.pages().filter((e) => e[1].isVisible);
    }
}
```

Shape rules:
- `static template = "module.ComponentName"`
- `props = useProps(schema)` as a class field, schema exported for reuse
- refs as class fields: `myRef = signal.ref()`
- everything reactive created in `setup()`
- getters for derived values used once; `computed()` for derived values used repeatedly or
  in dependency lists

---

## 3. Reactivity: proxy, signal, computed

```js
// mutable reactive object — the replacement for useState
this.state = proxy({ count: 0, items: [] });
this.state.count++;                   // triggers a re-render

// a single reactive value
const count = signal(0);
count(1);                             // write
count();                              // read

// a DOM/component ref
this.inputRef = signal.ref();         // template: t-ref="this.inputRef"
this.inputRef()?.focus();

// derived value — lazily evaluated, cached, called like a function
this.total = computed(() => this.state.items.reduce((a, i) => a + i.price, 0));
this.total();
```

- `proxy()` for an object you mutate in place (component state, a form buffer)
- `signal()` for one value passed around or shared between components
- `computed()` when the derivation is non-trivial or read from several places — a plain
  getter re-runs on every access, `computed()` caches until a dependency changes
- `computed()` and `signal()` results are **called**: `this.total()`, not `this.total`.
  This is the most common OWL 3 mistake — a forgotten `()` renders the function.

---

## 4. Props with `useProps` and `t`

```js
export const myProps = {
    record: t.object(),                       // required
    readonly: t.boolean().optional(false),    // optional with default
    label: t.string().optional(),
    onChange: t.function().optional(() => () => {}),
    slots: t.object().optional(),
    extra: t.any().optional(),
};

export class MyField extends Component {
    static template = "my_module.MyField";
    props = useProps(myProps);
}
```

- export the schema so other components can spread it (`{ ...myProps, extra: t.string() }`)
- `.optional(defaultValue)` replaces the OWL 2 `static defaultProps`
- `t.any()` only when the type genuinely varies — it disables validation

---

## 5. Effects and lifecycle

```js
import { useLayoutEffect, onWillRender } from "@web/owl2/utils";
import { onWillStart, onMounted, onWillUnmount, useOnChange } from "@odoo/owl";

setup() {
    onWillStart(async () => { this.data = await this.orm.call(...); });  // before first render
    onMounted(() => { ... });                                            // DOM is live
    onWillUnmount(() => { ... });                                        // cleanup

    useLayoutEffect(
        () => { const id = setInterval(tick, 1000); return () => clearInterval(id); },
        () => [this.state.enabled],     // dependency list, as a function
    );

    useOnChange(
        () => [this.props.resId],       // deps
        (resId) => { this.load(resId); },
        { initialRun: false },
    );
}
```

- `useLayoutEffect` takes `(effect, () => deps)` — the deps are a **function**
- return a cleanup function from the effect; never leave a listener or interval behind
- `useOnChange` is for "react to a prop changing", `useLayoutEffect` for "sync the DOM"
- `onWillStart` for the initial async load; do not fetch in `setup()` directly

---

## 6. Templates

```xml
<t t-name="my_module.MyField">
    <div t-attf-class="o_my_field {{ this.props.readonly ? 'o_readonly' : '' }}">
        <span t-out="this.displayValue"/>
        <t t-foreach="this.items()" t-as="item" t-key="item.id">
            <button t-on-click="() => this.select(item)" t-out="item.name"/>
        </t>
        <input t-ref="this.inputRef" t-att-value="this.state.value"/>
        <t t-if="this.props.slots" t-call-slot="default"/>
        <MyChild prop="this.state.value" t-props="this.childProps"/>
    </div>
</t>
```

Non-negotiable in OWL 3 templates:

- **explicit `this.`** — `this.props.x`, `this.state.x`, `this.myGetter`
- `t-out`, never `t-esc`
- `computed`/`signal` values are **called**: `this.items()`
- `t-key` on every `t-foreach`
- `t-call-slot="name"` to render a slot, `t-set-slot="name"` to fill one
- `t-ref="this.someSignalRef"` — the ref is a signal, not a string name
- `t-custom-click="handler"` is an Odoo custom directive that also binds `auxclick`
  (middle-click) — [addons/web/static/src/env.js:47](../../../../addons/web/static/src/env.js#L47)

QWeb server-side templates follow the same `t-out` rule and additionally changed `t-call`
parameter passing — see `views.md`.

---

## 7. Services and registries

Unchanged in shape from v19:

```js
import { registry } from "@web/core/registry";

registry.category("services").add("myService", {
    dependencies: ["orm", "notification"],
    start(env, { orm, notification }) {
        return {
            async doThing(id) { return orm.call("my.model", "do_thing", [[id]]); },
        };
    },
});
```

```js
import { useService } from "@web/core/utils/hooks";
this.orm = useService("orm");
this.notification = useService("notification");
```

Common categories: `services`, `actions`, `fields`, `view_widgets`, `systray`, `main_components`,
`formatters`, `parsers`, `command_provider`.

v20 also introduces **plugins** (`usePlugin`, `*_plugin.js` in core, e.g. `orm_plugin`,
`dialog_plugin`). Use a plugin only when you are extending a core feature that is already
plugin-based; otherwise a service is still the right unit.

---

## 8. Asset bundles

```python
'assets': {
    'web.assets_backend': [
        'my_module/static/src/**/*',
    ],
    'web.assets_frontend': [
        'my_module/static/src/public/**/*',
    ],
    'web.assets_unit_tests': [
        'my_module/static/tests/**/*',
    ],
},
```

- `web.assets_backend` — the webclient
- `web.assets_frontend` — website / portal
- `web.assets_unit_tests` — hoot tests
- glob the directory; do not list files one by one unless order matters
- `('replace', old, new)`, `('remove', path)`, `('before', ref, path)` for surgical edits

### Dark mode

`web.assets_web_dark` is `('include', 'web.assets_web')` plus every `*.dark.scss`
([web manifest](../../../../addons/web/__manifest__.py)); `web_enterprise` loads the dark
values of the primary variables first, so **every backend SCSS file is compiled twice**.
A hard-coded `#fff` card or `#333` text stays light in dark mode, and light text lands on
a light box (the RS e-invoice tab was unreadable for exactly this reason).

- Neutrals come from Odoo variables, never hex: `$o-view-background-color` (card/surface),
  `$o-gray-100` (inset boxes, table header/footer, toolbars), `$o-gray-300` (borders),
  `$o-gray-400` (input borders), `$o-main-text-color`, `$o-gray-600` (muted text). Their
  light values equal the usual Bootstrap greys, so the light theme does not move.
- Tints that must work on both backgrounds: `rgba($o-info, 0.08)` for hover, Bootstrap
  `text-bg-*` / `alert-*` classes for badges and banners.
- Colours of your own that need a different shade on dark (dark-toned text such as
  `#92400e`, pale backgrounds such as `#fef3c7`, brand text such as `#2563eb`) get both
  values in the token block, with the switch core uses in
  [mass_mailing.scss:220](../../../../addons/mass_mailing/static/src/scss/mass_mailing.scss#L220):

```scss
$my-dark: $o-webclient-color-scheme == dark;      // 'bright' in light, 'dark' in dark
$my-primary:      #2563eb;                         // fill: white text on it reads on both
$my-primary-text: if($my-dark, #60a5fa, #2563eb);  // text/icon/border on the page
$my-soft:         if($my-dark, mix(#2563eb, $o-view-background-color, 18%), #eaf1fe);
```

  The light value stays the original hex, so the light theme cannot move. Keep a
  separate token for fills and for text: a mid-tone fill is fine on both themes, the
  same colour as text on a dark background is not. Tints: `mix(<colour>, $o-view-background-color, 10–45%)`.
- `*.dark.scss` in `web.assets_web_dark` (core `account`, `web_enterprise`) is for
  overriding selectors you do not own. For your own stylesheet, one token block is
  easier to keep correct than a parallel file of selectors.
- `var(--o-component-background)`, `var(--o-text-color)`, `var(--o-border-color)`,
  `var(--o-text-color-muted)`, `var(--o-brand-primary)`, `var(--o-view-background-color)`,
  `var(--o-main-text-color)` do **not exist** in v20 (`--o-input-background-color` is only
  set locally, to `transparent`, in two core views) — a `var(--x, #fff)` always renders its
  light fallback.
- Components that route colours through their own CSS custom properties get both values
  by interpolation, so only the property block changes:
  `--grid-surface: #{if($my-dark, $o-view-background-color, #fff)};`
- A module that is not installed can still be checked: compile its SCSS with `sass`
  (libsass, in the venv) after a prelude that sets the light, then the dark, values of the
  `$o-*` variables it uses, and compare the resolved colours.
- `$o-gray-200` equals the view background in dark mode — for a light border use
  `mix($o-gray-200, $o-gray-300)` (light `#e3e7ea`, dark `#35373e`) or `$o-gray-300`.
- HTML that is also sent by email (`body_html`, `message_post` bodies) keeps its inline
  light styles; make sure every text node in it sets its own `color`, so it reads as a
  light card in the dark chatter, as core emails do.
- Verify: before editing, compile `web.assets_web` and `web.assets_web_dark`
  (`env['ir.qweb']._get_asset_bundle(name).css()`), keep your module's rules; after editing,
  the light set must be identical and the dark set must have no light background or
  near-black text left.

---

## 9. Common patterns

```js
// ORM call
const records = await this.orm.searchRead("my.model", [["state", "=", "draft"]], ["name"]);

// notification
this.notification.add(_t("Saved"), { type: "success" });

// dialog
this.dialog.add(ConfirmationDialog, {
    body: _t("Delete this record?"),
    confirm: () => this.delete(),
});

// debounce
import { debounce } from "@web/core/utils/timing";
this.onSearch = debounce(this.search.bind(this), 300);

// translation
import { _t } from "@web/core/l10n/translation";
```

`_t()` marks a translatable string; never build it from concatenation.

---

## 10. Inheriting core OWL templates

Core templates were rewritten with explicit `this.`, so every xpath written against v19
attribute text is dead:

```xml
<!-- v19 — matches nothing in v20, view crashes "cannot be located in element tree" -->
<xpath expr="//t[@t-component='props.Renderer']" position="replace">

<!-- v20 — copy the attribute text from the current core template -->
<xpath expr="//t[@t-component='this.props.Renderer']" position="replace">
```

- Open the core template and copy the attribute **as it is now**
  ([list_controller.xml:84](../../../../addons/web/static/src/views/list/list_controller.xml#L84)
  for `web.ListView`). Never write an xpath from memory.
- `replace` of a node that carries `t-if`: check the next sibling. In `web.ListView` the
  renderer is followed by `<t t-elif="this.model.couldNotLoadRootOffline">`; a replacement
  without the `t-if` leaves an orphan `t-elif` and the template fails to compile. Put the
  condition on your wrapper.
- Props you duplicate from a core node must match the v20 node exactly, with `this.`.
- Templates rendered through `t-call` with a `t-set` (e.g. account report warnings:
  `<t t-set="warningParams" .../>` in
  [account_report.xml:71](../../../../enterprise/account_reports/static/src/components/account_report/account_report.xml#L71))
  receive **locals** — keep `warningParams` without `this.`.
- Core component refs are signals: `FormController.rootRef = signal.ref()`
  ([form_controller.js:164](../../../../addons/web/static/src/views/form/form_controller.js#L164)).
  A subclass or patch reading `this.rootRef.el` gets `undefined` — call `this.rootRef()`.
- Test every xpath against the core template before shipping:

```python
# data_venv/bin/python, repo root — prints OK/MISS per xpath
from lxml import etree
core = etree.parse('addons/web/static/src/views/list/list_controller.xml')
tpl = next(t for t in core.iter('t') if t.get('t-name') == 'web.ListView')
print(bool(tpl.xpath("//t[@t-component='this.props.Renderer']")))
```

---

## 11. Migrating v19 frontend code

Odoo ships `odoo/upgrade_code/owl3-migration.py`. **Do not run it wholesale** — in this
checkout it is ahead of core: it rewrites `t-ref` to `t-custom-ref` and
`useService("action")` to `usePlugin(ActionManagerPlugin)`, while core has 887 `t-ref` /
0 `t-custom-ref` and 434 `useService("action")` / 0 `usePlugin(ActionManagerPlugin)`, and
`t-custom-ref` is not a registered directive in
[env.js](../../../../addons/web/static/src/env.js). Run on core, it would change 1650
already-migrated files.

Procedure that matches core:

1. Run only these steps: `upgrade_usestate`, `upgrade_reactive`, `upgrade_t_esc`,
   `upgrade_this`, `upgrade_t_slot`, `upgrade_parametric_tcall`.
2. `odoo-bin upgrade_code` always adds `odoo/addons`, and `upgrade_this` needs the core
   templates to know each parent template's locals. So load `addons` + `enterprise` +
   custom into one `FileManager` (`odoo.cli.upgrade_code`), call the steps through
   `MigrationCollector.run_sub`, and `_save()` **only** files under `custom_addons/`.
3. Review the diff. `upgrade_this` wrongly prefixes `t-call` locals it cannot see (it
   produced `this.warningParams`) — revert those.
4. Fix by hand what the script leaves: `static props` → `useProps` (§1 — it throws),
   `useRef` → `signal.ref()` (template `t-ref="this.x"`, JS `this.x()`), `.el` on core
   refs, xpaths into core templates (§10).
5. Verify: every `this.x` in a template exists on the component or its core parent; every
   import resolves and every named import is exported by the target file; every `patch()`
   target method still exists in the v20 class.
6. Server QWeb is not covered by this script: replace `t-esc` → `t-out` in `views/`,
   `report/`, `wizard/` XML (v20 renders an unknown `t-esc` as nothing).

---

## 12. Review checklist

- [ ] No `useState` / `reactive` — `proxy()` instead
- [ ] Only `render`, `onWillRender`, `useLayoutEffect`, `useEnv`, `useSubEnv` come from
      `@web/owl2/utils`; no import of a name `@odoo/owl` does not export (§1)
- [ ] No `static props` / `static defaultProps` anywhere — they throw; `props = useProps(...)`
- [ ] Refs are `signal.ref()`, read as `this.x()` — no `.el`, no string `t-ref`
- [ ] No OWL 2 `useEffect(fn, deps)` — `useLayoutEffect` instead
- [ ] Every xpath into a core template matches the **current** core attribute text (§10)
- [ ] Icons are Material Symbols (`class="oi" data-icon="..."`), never `fa fa-*` — `views.md`
- [ ] `computed` / `signal` values are called with `()` in JS **and** in templates
- [ ] `props = useProps(schema)` with `t.*` types; schema exported
- [ ] Every `t-foreach` has `t-key`
- [ ] `t-out` everywhere, no `t-esc`
- [ ] Explicit `this.` in every template expression
- [ ] Effects return their cleanup; no leaked listeners or timers
- [ ] Async loading in `onWillStart`, not in `setup()`
- [ ] User-facing strings wrapped in `_t()`
- [ ] Component shape matches the nearest core component you copied from
