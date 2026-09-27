# Researching a module for its checklist

The checklist is only as good as its labels: the user's first instruction was "don't hallucinate
buttons or menu names". Every button, menu, field, tab and message in the file must come from the
module's code, core `addons/`, or the live database.

## 1. Understand the flows (15-30 minutes for a big module)

1. Read `documentations/<module>.md` if it exists, then the module's `CODE_REVIEW.md` or
   `KNOWN_ISSUES` if present — they tell you the flows and the known traps fast.
2. Run the inventory:
   ```bash
   python3 .claude/skills/odoo-manual-tests/scripts/module_inventory.py custom_addons/<root>/<module> --db gec20_prod1 --full > <scratchpad>/inv.md
   ```
   (`<scratchpad>` = the session scratchpad directory from the system prompt, not `/tmp`.)
   It lists every button with its label, method, `confirm=` text and `invisible=` rule, the tabs,
   coloured boxes, ribbons, filters, crons, state selections, every UserError/ValidationError
   message with file:line, and the live menu paths. It ends with a suggested size.
3. Draw the state machine for the main document from the `invisible=` rules and the action
   methods: which button is visible in which state, and which state each button leads to. The
   flows are the paths through this table; most bugs sit at its edges.
4. Read each action method the flows use (not every helper). For each one note the single visible
   result that proves it worked: a status value, a number, a coloured box, a ribbon, a smart
   button, a new record. That becomes `You should see`.

## 2. Pick the test cases

- **Flows**: the normal day first, then every way a user changes, cancels, corrects or reverses
  the main document, then the incoming side (if the module has one), then options that change what
  is sent (notes, currencies, tax types, special document types). Merge scenarios only when the
  second adds no new outcome.
- **Safety cases**: from the error list, keep the ones a user can actually reach through the UI.
  Check reachability: the button must be *visible* in that state (read its `invisible=`), and the
  guard must run before anything is saved or sent. Prefer guards that protect money, tax filings,
  links to external systems and live records. Skip messages that only a script or a race can hit.
- **Scheduled jobs**: include only the ones a tester can run by hand and see (Settings › Technical ›
  Scheduled Actions › [Run Manually], developer mode), and only if they matter to the business.
  A job that processes *every* record of a kind (daily sync to an external system, mass send,
  digest mails) acts on all the data of a shared database, not just the test records — leave it
  out or test it only on a copy of the database, and say so in "Never". (employee_registry_rs:
  Daily Sync would push every Automatic employee of gec20_prod1 to rs.ge.)
- **Absence is a valid safety check**: when a guard is a hidden button, the case checks that the
  button is not there ("Look for [Delete on RS] › *Not there*").
- **Leave out** anything that leaves records stuck or unfixable, moves real money, or needs a
  timing accident (timeouts). Mention the stuck/unsafe path in "Never" instead.

## 3. Check the words on the screen

- Button labels: the `string=` in the view (the inventory shows them). Stat buttons show their
  field `string=` or `o_stat_text` span.
- Field labels: `string=` in the view, else the field's `string=` in Python.
- Section titles and custom labels: the text inside the module's own `<div>`/`<span>` classes in
  the view (open the XML; the inventory does not cover free text).
- Messages: quote only the start of the text; formatting arguments and translations change the
  rest. Georgian UI: labels come from `i18n/ka_GE.po` — check the user's language first
  (`SELECT p.lang FROM res_users u JOIN res_partner p ON p.id = u.partner_id WHERE u.login = 'admin';`).
- Core Odoo labels: `references/odoo20-ui.md`; anything else, grep `addons/` for the view.
- Menus: live paths from the inventory's `--db` section (the XML alone does not give the full path).

## 4. Check the data the tests rely on (psql SELECT only, never write)

- Module installed (`ir_module_module.state`), company Tax ID and currency, default sale/purchase
  taxes (`res_company.account_sale_tax_id`), which crons are active, which test partners/products
  already exist. Fixed test data (e.g. TEST Service 100 + 18%) should produce round numbers.
- External systems: find the endpoint in the code. If there is no test switch, say so in "Never"
  and require test users only.
- **Identifiers of real people** (personal numbers, TINs of individuals, IBANs, phone numbers) are
  never copied from the database into the checklist, not even as examples. When a test needs one
  that the external system validates, add an admin fill-in row ("Test personal number accepted by
  the rs.ge test login: ____") and refer to it in the steps.

## 5. Traps found while building the rs_einvoice checklist

- **The form saves before a button runs.** A value typed just before a failing button stays saved
  (`form_controller.js` `beforeExecuteActionButton`). If the module then locks that value, the
  record can end up stuck — check before writing a negative test around a button.
- **Visibility decides what is testable.** A guard behind a hidden button cannot be reached; test
  that the button is *absent* instead ("Look for [Delete on RS] › Not there").
- **Wizards pre-select options** (`default_get`): say which option is already chosen.
- **Messages sometimes name menus that do not exist** in Odoo 20. Use the real path in the steps and
  tell the user about the mismatch.
- **Quick Look previews** skip bold runs and show formulas as 0; Excel and Numbers are fine.
