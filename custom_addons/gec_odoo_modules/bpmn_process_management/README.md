# BPMN Process Management (`bpmn_process_management`)

ბიზნესპროცესების საცავი, BPMN 2.0 რედაქტორი/დამთვალიერებელი და ცოდნის ბაზა Odoo-სთვის.
იმპორტი: **draw.io**, **Microsoft Visio (.vsdx)**, **BPMN 2.0** (Camunda, Signavio, bpmn.io...). ექსპორტი: BPMN, draw.io, SVG, PNG.

| | |
|---|---|
| Odoo | **19.0** და **20.0** (ერთი საკოდო ბაზა) |
| გამოცემა | Community და Enterprise |
| დამოკიდებულებები | `base`, `web`, `mail` (არჩევითი: `hr`, `knowledge`, `documents`) |
| Python | მხოლოდ `lxml` (Odoo-ს ნაწილია) |
| ლიცენზია | LGPL-3; bpmn-js — bpmn.io License (იხ. `static/lib/bpmn-js/LICENSE-bpmn-js`) |

დოკუმენტაცია:
- [`doc/user_guide.html`](doc/user_guide.html) — მომხმარებლის სახელმძღვანელო (ერთი ფაილი, სურათები ჩაშენებულია). იგივე ფაილი მოდულშია
  (`static/doc/user_guide.html`): მენიუ *პროცესები → სახელმძღვანელო* და რედაქტორის „?“ ღილაკი. წყარო: `doc/user_guide_src.html` + `doc/images/`,
  აწყობა: `python3 doc/build_user_guide.py`;
- [`doc/technical_specification.md`](doc/technical_specification.md) — შესწორებული ტექნიკური დავალება და რა შეიცვალა საწყისთან შედარებით.

## ინსტალაცია

1. დააკოპირეთ `bpmn_process_management` ფოლდერი Odoo-ს addons path-ში.
2. Odoo: *Apps → Update Apps List* → მოძებნეთ „BPMN Process Management“ → *Install*.
3. ქართული ინტერფეისისთვის: *Settings → Languages* → ქართული; მომხმარებელი ენას ირჩევს *My Preferences*-ში.
4. პროცესების მენეჯერის როლი: მომხმარებლის ფორმა → *ბიზნესპროცესები → პროცესების მენეჯერი*. ყველა შიდა მომხმარებელი ავტომატურად დამთვალიერებელია.

ბრძანების სტრიქონიდან:

```bash
odoo-bin -c odoo.conf -d DB -i bpmn_process_management          # ინსტალაცია
odoo-bin -c odoo.conf -d DB -u bpmn_process_management          # განახლება
odoo-bin -c odoo.conf -d DB -u bpmn_process_management \
         --test-tags /bpmn_process_management --stop-after-init  # ტესტები
```

## სტრუქტურა

```
bpmn_process_management/
├── __manifest__.py            # version 1.4.0 — Odoo თავად ამატებს სერიას (19.0./20.0.)
├── models/
│   ├── business_process.py          # პროცესი, ვერსიები, სტატუსები, ბარათი, გადახედვა, RPC მეთოდები
│   ├── business_process_element.py  # დიაგრამის ელემენტების საძიებო ინდექსი
│   ├── business_process_extra.py    # თეგი, KPI, გაცნობის დადასტურება
│   ├── business_process_dashboard.py # დეშბორდის მონაცემები (RPC bpmn_dashboard)
│   └── business_process_demo.py # დემო მონაცემების ჩატვირთვა / წაშლა (იმპორტის ოსტატიდან)
├── wizard/business_process_import.py # იმპორტის ოსტატი (bpmn / draw.io / Visio)
├── controllers/main.py         # /bpmn_process_management/export/<id>/<bpmn|drawio>
├── lib/                        # სუფთა Python (Odoo-ს გარეშე ტესტირებადი)
│   ├── bpmn_common.py          # namespace-ები, უსაფრთხო პარსერი, odoo:* extension helper-ები
│   ├── bpmn_builder.py         # შუალედური მოდელი → ვალიდური BPMN 2.0 + DI
│   ├── drawio_import.py        # mxGraph → შუალედური მოდელი
│   ├── visio_import.py         # .vsdx → შუალედური მოდელი
│   ├── drawio_export.py        # BPMN → .drawio
│   ├── bpmn_index.py           # ელემენტების ამოღება, ზოლების ავტომატური შესაბამისობა
│   ├── bpmn_stats.py           # დიაგრამის სტრუქტურა დეშბორდისთვის (როლები, ნაბიჯები, გადაცემები)
│   └── demo_data.py            # დემო პროცესების დიაგრამები (ქართულად)
├── security/
│   ├── security.xml            # ჯგუფები + <function> ვერსიის შესაბამისი უფლებების ჩასატვირთად
│   ├── odoo19/                 # ir.model.access.csv, ir_rule.xml
│   └── odoo20/                 # ir.access.csv
├── data/                       # ყოველდღიური cron: პერიოდული გადახედვის შეხსენება
├── views/, demo/, i18n/ (ka.po, .pot)
├── static/
│   ├── lib/bpmn-js/            # odoo-bpmn.min.js (bpmn-js 18.30.0 + დამატებები), CSS, ფონტი, build_src/
│   ├── src/bpmn_field/         # bpmn_field.js (OWL ფენა), bpmn_app.js (რედაქტორი + პანელი), bpmn_terms.js, scss
│   ├── src/dashboard/          # მენეჯმენტის დეშბორდი (client action, SVG დიაგრამები)
│   ├── doc/user_guide.html     # მოდულიდან ხელმისაწვდომი სახელმძღვანელო
│   └── description/            # icon.png / icon.svg (Odoo-ს სტილის ხატულა GEC-ის ფერებით)
├── tests/                      # 40 ტესტი + fixtures (draw.io-ს ოფიციალური შაბლონები, Visio)
└── doc/
```

## არქიტექტურული გადაწყვეტილებები

- **XML ერთადერთი წყაროა.** პასუხისმგებლები, ბმულები და გადასახედი ნიშნები ინახება
  `<bpmn:extensionElements>`-ში (`xmlns:odoo="http://gecbusiness.com/schema/bpmn/odoo/1.0"`), ამიტომ ექსპორტ-იმპორტისას არ იკარგება.
  ცხრილი `business.process.element` მხოლოდ ინდექსია და ყოველი შენახვისას თავიდან იგება.
- **ბმულები XML ID-ით** (ID მხოლოდ სარეზერვოდ) — ბაზებს შორის გადატანისას არ გადაადგილდება.
- **ვერსიის ადაპტაცია:** Odoo 20-მა `ir.model.access`/`ir.rule` შეცვალა `ir.access`-ით, OWL 2 → OWL 3, Binary ველები → `BinaryValue`,
  Font Awesome → Material Symbols. ყველა შემთხვევა მოგვარებულია გაშვების დროს (იხ. ტექ. დავალება II.9) — ცალკე ბრენჩი არ სჭირდება.
- **OWL-დამოუკიდებელი ვიჯეტი:** `bpmn_field.js` არ იყენებს `static props`, `useState`, `t-ref`; მთელი ლოგიკა `bpmn_app.js`-შია (ჩვეულებრივი JS კლასი).
- **bpmn-js ზარმაცად იტვირთება** (`loadJS`) მხოლოდ დიაგრამის გახსნისას; backend bundle არ მძიმდება.
- **უსაფრთხოება:** XXE-დაცული პარსერი, ზომის ლიმიტები, URL თეთრი სია, სერვერული აკრძალვა გამოქვეყნებულის შეცვლაზე, DOM-ში მხოლოდ `textContent`.

## bpmn-js ბანდლის თავიდან აწყობა

```bash
cd static/lib/bpmn-js/build_src
npm install          # package.json: bpmn-js 18.30.0, bpmn-auto-layout, bpmn-js-create-append-anything,
                     # bpmn-js-color-picker, diagram-js-minimap, diagram-js-grid (ყველა MIT), esbuild
npx esbuild entry.js --bundle --minify --format=iife --target=es2020 \
    --legal-comments=eof --outfile=../odoo-bpmn.min.js
cp -r node_modules/bpmn-js/dist/assets ../
cp node_modules/diagram-js-minimap/assets/diagram-js-minimap.css ../assets/
cp node_modules/bpmn-js-color-picker/colors/color-picker.css ../assets/
```

`entry.js` აქვეყნებს `window.OdooBpmn = { Modeler, NavigatedViewer, layoutProcess, odooModdle, modelerModules, viewerModules }`;
`odoo_ux.js` — საკუთარი დამატებები (დასაკავშირებელი ფიგურების განათება, შეერთების წერტილები, გვერდის მიხედვით მარშრუტი,
ისრების გადახტომა, აუზების მიწებება, პალიტრა, მალსახმობები, წარწერების სიგანე).
ბანდლის შეცვლის შემდეგ გაზარდეთ `LIB_V` `bpmn_app.js`-ში (ბრაუზერის ქეში).

> bpmn-js-ის ლიცენზია მოითხოვს, რომ დიაგრამაზე „bpmn.io“ ლოგო ხილული დარჩეს — არ დამალოთ CSS-ით.

## შემოწმებულია

| | Odoo 19 CE | Odoo 20 CE |
|---|---|---|
| ინსტალაცია / განახლება (`-u`) | ✔ | ✔ |
| ავტომატური ტესტები (40) | ✔ | ✔ |
| შეერთების წერტილები, გვერდის მიხედვით მარშრუტი, გადახტომა, აუზების მიწებება, დეშბორდი (Playwright) | ✔ | ✔ |
| ინტერფეისი ბრაუზერში (Playwright): viewer და ნაბიჯ-ნაბიჯ გავლა, modeler, პასუხისმგებელი (ავტო-სახელი, კომენტარი), ფერები, ტიპის შეცვლა, დასაკავშირებელი ფიგურების განათება, მალსახმობები (`?`, `M`, `P`, `Ctrl+S`), რამდენიმე ელემენტის განლაგება, შენახვა/გაუქმება, გამოქვეყნება, kanban | ✔ | ✔ |
| ქართული თარგმანი | ✔ | ✔ |

**არ არის შემოწმებული:** Enterprise ბაზაზე (წვდომა არ იყო; Enterprise-ის მოდულებზე დამოკიდებულება არ არის, Knowledge/Documents ბმულები ჩნდება მხოლოდ მათი არსებობისას)
და ფაილები, რომლებიც შენახულია თავად Microsoft Visio-ს BPMN შაბლონით — ტესტი ეყრდნობა ამ ფორმატის სინთეზურ ფაილს და Lucidchart/Apache POI-ს რეალურ .vsdx ფაილებს.
რეკომენდებულია ჩაბარებამდე 3–5 თქვენი რეალური Visio და draw.io ფაილით შემოწმება.

## ცნობილი შეზღუდვები

- Visio `.vsd` (ორობითი) არ იკითხება — საჭიროა `.vsdx`; Visio-ში ექსპორტი არ არის.
- BPMN Choreography/Conversation დიაგრამები (bpmn-js-ის შეზღუდვა).
- იმპორტისას გადმოდის შევსებისა და ხაზის ფერი, მაგრამ არა შრიფტები და ხაზების ზუსტი ფორმა; შემაერთებლები ორთოგონალურად გადაიხაზება.
- რედაქტორი ცვლილებებს ფორმაში ~0.4 წამში გადასცემს; თუ ბრაუზერის ჩანართს ამ დროში დახურავთ, ბოლო ცვლილება შეიძლება დაიკარგოს.
- `.drawio` ექსპორტი იღებს ბოლო **შენახულ** ვერსიას.
- დიაგრამის შინაარსი (სახელები, ინსტრუქციები) არ არის მრავალენოვანი.
