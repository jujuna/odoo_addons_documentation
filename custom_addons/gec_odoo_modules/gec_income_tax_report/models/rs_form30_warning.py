import re
from functools import partial

from odoo.tools import LazyTranslate

_lt = LazyTranslate(__name__)

ISSUE_RANK = {'note': 1, 'warning': 2, 'blocker': 3}
USAGE_TRANSLATIONS = {'payslips': _lt("payslips"), 'journal entries': _lt("journal entries"), 'vendor bills': _lt("vendor bills")}
PLACEHOLDER = re.compile(r"%(?:\(\w+\))?s")
# One row per warning the row builders store in English; %s and %(name)s stand for a value. Rows are translated in this order.
WARNINGS = [
    (_lt("Employee ID taken from the work contact Tax ID, verify it."), 'note'),
    (_lt("Relief derived from the withheld tax, verify on the portal."), 'note'),
    (_lt("Category/residency defaulted to 1.1/Georgia, confirm on the employee contact."), 'note'),
    (_lt("No payment matched, date taken from the payslip."), 'note'),
    (_lt("Payslip lines were edited manually."), 'note'),
    (_lt("Set the Form 30 category and residency on the partner."), 'blocker'),
    (_lt("No Form 30 category covers the payment date; update the partner's category history."), 'blocker'),
    (_lt("Payment has no journal entry, the withholding is not booked."), 'warning'),
    (_lt("Legal form not detected in the company name."), 'note'),
    (_lt("Residency and category disagree: non-resident categories (3.x) need a foreign country, resident ones Georgia."), 'warning'),
    (_lt("Several withholding taxes in one entry: split it per tax."), 'blocker'),
    (_lt("Recipients of different status in one entry (own tax and withheld): split the entry."), 'blocker'),
    (_lt("The rs.ge classifier does not allow this category, income type and rate for the month."), 'blocker'),
    (_lt("Set a Form 30 service type on the Withholding Tax or on the contact."), 'blocker'),
    (_lt("Payment not matched with a bank transaction yet: dated on the payment date."), 'warning'),
    (_lt("Partly settled without a payment (write-off or another entry): check the amount."), 'warning'),
    (_lt("Settled by an offset entry: declare it in this month unless the advance was already taxed, and keep the signed offset act."), 'warning'),
    (_lt("Paid in advance, before the document: declared in the document's month unless the advance was already taxed."), 'warning'),
    (_lt("The booked tax differs from the Withholding Tax rate on net + tax."), 'warning'),
    (_lt("Reversed after payment: correct the declaration."), 'warning'),
    (_lt("Also withheld at payment: check for a double declaration."), 'warning'),
    (_lt("Pension below zero on this entry: set to 0, check the pension accounts."), 'warning'),
    (_lt("A manual row exists for this recipient and income type: check for a double declaration."), 'warning'),
    (_lt("Zero net pay: the row is dated on the payslip entry."), 'warning'),
    (_lt("Includes an advance: confirm the month."), 'note'),
    (_lt("Tax was withheld from a recipient who pays their own tax: it is not in annex E, check the document."), 'note'),
    (_lt("Filed, but its payment or source changed after the export: check this row."), 'blocker'),
    (_lt("Tax %s has no Form 30 income type."), 'blocker'),
    (_lt("Tax %s is not a percentage, set the rate manually."), 'warning'),
    (_lt("No version of %s is valid for Form 30 on the payment date."), 'blocker'),
    (_lt("Booked with an old tax version: this row uses %s, valid on the payment date."), 'warning'),
    (_lt("Late: the tax was due with the payment on %s and is not paid yet."), 'note'),
    (_lt("Corrected by %(correction)s: figures follow the corrected payslip, split by the months its net was paid."), 'note'),
    (_lt("Corrected by %s after earlier months were filed: the row holds the difference to what was filed."), 'note'),
    (_lt("Correction %(correction)s changes figures already declared for %(employee)s: correct that declaration, then generate this month again."),
        'warning'),
    (_lt("Correction %s: generate the declaration of %s again before exporting it."), 'warning'),
    (_lt("Correction %s: export the declaration of %s first, then generate this month again."), 'warning'),
    (_lt("Entry %(entry)s was reversed and no payment of it was found: if its recipient was paid from the bank, declare the payment by hand."),
        'warning'),
    (_lt("%s: already declared in %s, paid in %s: correct one of the declarations."), 'warning'),
    (_lt("Category %(category)s is not meant for %(usage)s (category guide)."), 'warning'),
]
WARNING_PATTERNS = [(re.compile("(.+?)".join(map(re.escape, PLACEHOLDER.split(text._source)))), text._source, level) for text, level in WARNINGS]


def _translate_match(env, source, match):
    names = re.findall(r"%\((\w+)\)s", source)
    if not names:
        return env._(source, *match.groups())
    values = dict(zip(names, match.groups()))
    if values.get('usage') in USAGE_TRANSLATIONS:
        values['usage'] = env._(USAGE_TRANSLATIONS[values['usage']])
    return env._(source, **values)


def _localize_warning(env, warning):
    """Translate stored warning text at display time."""
    if not warning:
        return False
    for pattern, source, _level in WARNING_PATTERNS:
        warning = pattern.sub(partial(_translate_match, env, source), warning)
    return warning
