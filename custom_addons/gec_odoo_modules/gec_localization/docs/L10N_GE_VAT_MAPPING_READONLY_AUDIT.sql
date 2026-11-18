-- Georgian localization VAT mapping investigation, Odoo 20.
-- Validated on gec20_prod1, which the user confirmed is a TEST database.
-- Modules have not been deployed to production; document rows are test examples.
-- Run with psql -X -v ON_ERROR_STOP=1 -f <this file> against a chosen database.
-- Every statement is read-only. This does not repair or classify any document.
-- Stock identity uses company-prefixed account XML IDs, not translated names.
-- Candidate detection finds multiple named special-category taxes on one line.
-- Other queries expose missing domestic flags and unclassified foreign bills.
-- None establishes legal VAT eligibility or proves intended tax treatment.

BEGIN TRANSACTION READ ONLY;

-- 1. Georgian root companies and standard tax defaults.
SELECT c.id AS company_id, c.name, c.chart_template, cp.country_id,
       c.domestic_fiscal_position_id, c.account_sale_tax_id, c.account_purchase_tax_id
FROM res_company c JOIN res_partner cp ON cp.id = c.partner_id
WHERE c.chart_template = 'ge' AND c.parent_id IS NULL
ORDER BY c.id;

-- 1b. All ten domestic sales taxes: flags and proposed additional memberships.
WITH sales_taxes(suffix) AS (
    VALUES ('ge_vat_sale_18'), ('ge_vat_sale_18_sp_sale'),
           ('ge_vat_sale_18_adv'), ('ge_vat_sale_18_building'),
           ('ge_vat_sale_18_repairs'), ('ge_vat_sale_18_barter'),
           ('ge_vat_sale_18_other'), ('ge_vat_sale_exempt_financial'),
           ('ge_vat_sale_exempt_land'), ('ge_vat_sale_exempt_other')
)
SELECT c.id AS company_id, s.suffix, t.id AS tax_id,
       t.name->>'en_US' AS tax, t.active, t.is_domestic,
       ARRAY(
           SELECT r.account_fiscal_position_id
           FROM account_fiscal_position_account_tax_rel r
           WHERE r.account_tax_id = t.id ORDER BY r.account_fiscal_position_id
       ) AS position_ids,
       EXISTS (
           SELECT 1 FROM account_fiscal_position_account_tax_rel r
           JOIN ir_model_data fd ON fd.module = 'account'
               AND fd.model = 'account.fiscal.position' AND fd.res_id = r.account_fiscal_position_id
               AND fd.name = c.id::text || '_ge_fiscal_position_nonvat'
           WHERE r.account_tax_id = t.id
       ) AS available_nonvat,
       EXISTS (
           SELECT 1 FROM account_fiscal_position_account_tax_rel r
           JOIN ir_model_data fd ON fd.module = 'account'
               AND fd.model = 'account.fiscal.position' AND fd.res_id = r.account_fiscal_position_id
               AND fd.name = c.id::text || '_ge_fiscal_position_domestic'
           WHERE r.account_tax_id = t.id
       ) AS available_manual_domestic
FROM res_company c CROSS JOIN sales_taxes s
LEFT JOIN ir_model_data d ON d.module = 'account' AND d.model = 'account.tax'
    AND d.name = c.id::text || '_' || s.suffix
LEFT JOIN account_tax t ON t.id = d.res_id
WHERE c.chart_template = 'ge' AND c.parent_id IS NULL
ORDER BY c.id, s.suffix;

-- 2. Known replacement edges, including missing or customized identities.
WITH policy(destination, source, expected_position) AS (
    VALUES
        ('ge_vat_sale_18_sp_sale', 'ge_vat_sale_18', 'ge_fiscal_position_vat'),
        ('ge_vat_sale_18_adv', 'ge_vat_sale_18', 'ge_fiscal_position_vat'),
        ('ge_vat_sale_18_other', 'ge_vat_sale_18', 'ge_fiscal_position_vat'),
        ('ge_vat_sale_exempt_financial', 'ge_vat_sale_18', 'ge_fiscal_position_vat'),
        ('ge_vat_sale_exempt_land', 'ge_vat_sale_18', 'ge_fiscal_position_vat'),
        ('ge_vat_sale_exempt_other', 'ge_vat_sale_18', 'ge_fiscal_position_vat'),
        ('ge_rcvat_18_ser', 'ge_vat_purchase_18', 'ge_fiscal_position_foreign'),
        ('ge_rcvat_18_goods_customs', 'ge_vat_purchase_18', 'ge_fiscal_position_foreign'),
        ('ge_rcvat_18_goods_fiz', 'ge_vat_purchase_18', 'ge_fiscal_position_foreign')
)
SELECT c.id AS company_id, p.destination, p.source, p.expected_position,
       dest.id AS destination_id, src.id AS source_id, fp.id AS position_id,
       dest.company_id AS destination_owner, src.company_id AS source_owner,
       dest.active AS destination_active,
       EXISTS (
           SELECT 1 FROM account_tax_alternatives a
           WHERE a.dest_tax_id = dest.id AND a.src_tax_id = src.id
       ) AS source_link_present,
       ARRAY(
           SELECT a.src_tax_id FROM account_tax_alternatives a
           WHERE a.dest_tax_id = dest.id ORDER BY a.src_tax_id
       ) AS all_source_ids,
       ARRAY(
           SELECT r.account_fiscal_position_id
           FROM account_fiscal_position_account_tax_rel r
           WHERE r.account_tax_id = dest.id ORDER BY r.account_fiscal_position_id
       ) AS all_position_ids
FROM res_company c
CROSS JOIN policy p
LEFT JOIN ir_model_data dd
    ON dd.module = 'account' AND dd.model = 'account.tax'
    AND dd.name = c.id::text || '_' || p.destination
LEFT JOIN account_tax dest ON dest.id = dd.res_id
LEFT JOIN ir_model_data sd
    ON sd.module = 'account' AND sd.model = 'account.tax'
    AND sd.name = c.id::text || '_' || p.source
LEFT JOIN account_tax src ON src.id = sd.res_id
LEFT JOIN ir_model_data fd
    ON fd.module = 'account' AND fd.model = 'account.fiscal.position'
    AND fd.name = c.id::text || '_' || p.expected_position
LEFT JOIN account_fiscal_position fp ON fp.id = fd.res_id
WHERE c.chart_template = 'ge' AND c.parent_id IS NULL
ORDER BY c.id, p.source, p.destination;

-- 3. All replacements active in each source tax's available fiscal positions.
-- Includes unexpected extra destinations; manual review decides their purpose.
WITH standard_sources AS (
    SELECT t.id, t.company_id, d.name AS source_xmlid
    FROM res_company c
    JOIN ir_model_data d ON d.module = 'account' AND d.model = 'account.tax'
        AND d.name IN (c.id::text || '_ge_vat_sale_18',
                       c.id::text || '_ge_vat_purchase_18')
    JOIN account_tax t ON t.id = d.res_id
    WHERE c.chart_template = 'ge' AND c.parent_id IS NULL
)
SELECT s.company_id, s.source_xmlid, fp.id AS position_id,
       fp.name->>'en_US' AS position, fp.auto_apply, fp.sequence,
       dest.id AS destination_id, dest.name->>'en_US' AS destination,
       dest.active, dest.amount, dest.type_tax_use
FROM standard_sources s
JOIN account_tax_alternatives a ON a.src_tax_id = s.id
JOIN account_tax dest ON dest.id = a.dest_tax_id
JOIN account_fiscal_position_account_tax_rel r ON r.account_tax_id = dest.id
JOIN account_fiscal_position fp ON fp.id = r.account_fiscal_position_id
ORDER BY s.company_id, s.source_xmlid, fp.sequence, dest.id;

-- 4. Accounting candidates. Shared parent taxes also identify branch documents.
WITH category_suffixes(suffix, category_group) AS (
    VALUES
        ('ge_vat_sale_18_sp_sale', 'domestic_sale'),
        ('ge_vat_sale_18_adv', 'domestic_sale'),
        ('ge_vat_sale_18_other', 'domestic_sale'),
        ('ge_vat_sale_exempt_financial', 'domestic_sale'),
        ('ge_vat_sale_exempt_land', 'domestic_sale'),
        ('ge_vat_sale_exempt_other', 'domestic_sale'),
        ('ge_rcvat_18_ser', 'foreign_purchase'),
        ('ge_rcvat_18_goods_customs', 'foreign_purchase'),
        ('ge_rcvat_18_goods_fiz', 'foreign_purchase')
), category_taxes AS (
    SELECT DISTINCT t.id, s.category_group
    FROM res_company c CROSS JOIN category_suffixes s
    JOIN ir_model_data d ON d.module = 'account' AND d.model = 'account.tax'
        AND d.name = c.id::text || '_' || s.suffix
    JOIN account_tax t ON t.id = d.res_id AND t.company_id = c.id
    WHERE c.chart_template = 'ge' AND c.parent_id IS NULL
), suspect_lines AS (
    SELECT ml.id, ml.move_id, ct.category_group,
           array_agg(DISTINCT r.account_tax_id ORDER BY r.account_tax_id) AS tax_ids
    FROM account_move_line ml
    JOIN account_move_line_account_tax_rel r ON r.account_move_line_id = ml.id
    JOIN category_taxes ct ON ct.id = r.account_tax_id
    WHERE ml.display_type = 'product'
    GROUP BY ml.id, ct.category_group
    HAVING count(DISTINCT r.account_tax_id) > 1
)
SELECT m.company_id, m.id AS document_id, m.name, m.state, m.move_type,
       m.date, m.amount_untaxed, m.amount_tax, m.amount_total,
       m.fiscal_position_id, s.id AS line_id, s.category_group, s.tax_ids
FROM suspect_lines s JOIN account_move m ON m.id = s.move_id
ORDER BY m.company_id, m.state, m.move_type, m.id, s.id;

-- 5. Sales order candidates, including confirmed orders still to invoice.
WITH category_suffixes(suffix) AS (
    VALUES ('ge_vat_sale_18_sp_sale'), ('ge_vat_sale_18_adv'),
           ('ge_vat_sale_18_other'), ('ge_vat_sale_exempt_financial'),
           ('ge_vat_sale_exempt_land'), ('ge_vat_sale_exempt_other')
), category_taxes AS (
    SELECT DISTINCT t.id
    FROM res_company c CROSS JOIN category_suffixes s
    JOIN ir_model_data d ON d.module = 'account' AND d.model = 'account.tax'
        AND d.name = c.id::text || '_' || s.suffix
    JOIN account_tax t ON t.id = d.res_id AND t.company_id = c.id
    WHERE c.chart_template = 'ge' AND c.parent_id IS NULL
), suspect_lines AS (
    SELECT sl.id, sl.order_id,
           array_agg(DISTINCT r.account_tax_id ORDER BY r.account_tax_id) AS tax_ids
    FROM sale_order_line sl
    JOIN account_tax_sale_order_line_rel r ON r.sale_order_line_id = sl.id
    JOIN category_taxes ct ON ct.id = r.account_tax_id
    WHERE sl.display_type IS NULL
    GROUP BY sl.id
    HAVING count(DISTINCT r.account_tax_id) > 1
)
SELECT so.company_id, so.id AS order_id, so.name, so.state, so.invoice_status,
       so.date_order, so.amount_untaxed, so.amount_tax, so.amount_total,
       so.fiscal_position_id, s.id AS line_id, s.tax_ids
FROM suspect_lines s JOIN sale_order so ON so.id = s.order_id
ORDER BY so.company_id, so.id, s.id;

-- 6. Purchase order candidates: the three foreign classifications together.
WITH category_suffixes(suffix) AS (
    VALUES ('ge_rcvat_18_ser'), ('ge_rcvat_18_goods_customs'), ('ge_rcvat_18_goods_fiz')
), category_taxes AS (
    SELECT DISTINCT t.id
    FROM res_company c CROSS JOIN category_suffixes s
    JOIN ir_model_data d ON d.module = 'account' AND d.model = 'account.tax'
        AND d.name = c.id::text || '_' || s.suffix
    JOIN account_tax t ON t.id = d.res_id AND t.company_id = c.id
    WHERE c.chart_template = 'ge' AND c.parent_id IS NULL
), suspect_lines AS (
    SELECT pl.id, pl.order_id,
           array_agg(DISTINCT r.account_tax_id ORDER BY r.account_tax_id) AS tax_ids
    FROM purchase_order_line pl
    JOIN account_tax_purchase_order_line_rel r ON r.purchase_order_line_id = pl.id
    JOIN category_taxes ct ON ct.id = r.account_tax_id
    WHERE pl.display_type IS NULL
    GROUP BY pl.id
    HAVING count(DISTINCT r.account_tax_id) > 1
)
SELECT po.company_id, po.id AS order_id, po.name, po.state, po.invoice_status,
       po.date_order, po.amount_untaxed, po.amount_tax, po.amount_total,
       po.fiscal_position_id, s.id AS line_id, s.tax_ids
FROM suspect_lines s JOIN purchase_order po ON po.id = s.order_id
ORDER BY po.company_id, po.id, s.id;

-- 7. Foreign-address commercial vendors: inventory stored partner defaults.
-- This shows the company-specific JSON value, not a calculated ORM fallback.
-- Supplier rank/address does not establish reverse-charge or exemption eligibility.
SELECT c.id AS company_id, p.id AS partner_id, p.name,
       country.code AS vendor_country, p.vat,
       p.property_purchase_tax_id ->> c.id::text AS stored_purchase_tax_id,
       t.name->>'en_US' AS stored_purchase_tax,
       p.property_sale_tax_id AS saved_sale_defaults,
       p.property_purchase_tax_id AS saved_purchase_defaults
FROM res_company c
JOIN res_partner p ON p.id = p.commercial_partner_id AND p.supplier_rank > 0
    AND p.active AND (p.company_id IS NULL OR p.company_id = c.id)
JOIN res_country country ON country.id = p.country_id AND country.code <> 'GE'
LEFT JOIN account_tax t ON t.id = (p.property_purchase_tax_id ->> c.id::text)::integer
WHERE c.chart_template = 'ge' AND c.parent_id IS NULL
ORDER BY c.id, p.id;

-- 8. Monthly review: posted Non-Georgia bill/refund lines without a VAT category.
-- Includes lines with only withholding; zero/exempt tax selections are not listed.
-- Filter accounting_date to the filing period; no date range is imposed here.
-- Correctly untaxed lines can appear. Review rather than assigning a tax in bulk.
SELECT m.company_id, m.id AS document_id, m.name, m.move_type,
       m.date AS accounting_date, m.invoice_date, m.partner_id,
       p.name AS vendor, ml.id AS line_id, ml.name AS description,
       ml.price_subtotal, ml.balance,
       ARRAY(
           SELECT r.account_tax_id FROM account_move_line_account_tax_rel r
           WHERE r.account_move_line_id = ml.id ORDER BY r.account_tax_id
       ) AS selected_tax_ids
FROM res_company c
JOIN ir_model_data fd ON fd.module = 'account' AND fd.model = 'account.fiscal.position'
    AND fd.name = c.id::text || '_ge_fiscal_position_foreign'
JOIN account_move m ON m.fiscal_position_id = fd.res_id
JOIN account_move_line ml ON ml.move_id = m.id AND ml.display_type = 'product'
JOIN res_partner p ON p.id = m.partner_id
WHERE c.chart_template = 'ge' AND c.parent_id IS NULL
    AND m.state = 'posted' AND m.move_type IN ('in_invoice', 'in_refund')
    AND NOT EXISTS (
        SELECT 1 FROM account_move_line_account_tax_rel r
        JOIN account_tax t ON t.id = r.account_tax_id
        WHERE r.account_move_line_id = ml.id
            AND COALESCE(t.is_withholding_tax, false) = false
    )
ORDER BY m.company_id, m.date, m.id, ml.id;

-- 9. VAT-only import taxes: inspect the three price settings separately.
WITH import_taxes(suffix) AS (
    VALUES ('ge_import_duty_18'), ('ge_import_duty_12'), ('ge_import_duty_5')
)
SELECT c.id AS company_id, s.suffix, t.id AS tax_id,
       t.name->>'en_US' AS tax, t.amount, t.amount_type,
       t.price_include_override, c.account_price_include AS company_price_policy
FROM res_company c CROSS JOIN import_taxes s
LEFT JOIN ir_model_data d ON d.module = 'account' AND d.model = 'account.tax'
    AND d.name = c.id::text || '_' || s.suffix
LEFT JOIN account_tax t ON t.id = d.res_id
WHERE c.chart_template = 'ge' AND c.parent_id IS NULL
ORDER BY c.id, s.suffix;

-- Deliberately make no changes, even if the file is run against a live database.
ROLLBACK;
