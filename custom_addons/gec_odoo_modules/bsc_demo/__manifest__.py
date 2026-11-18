{
    'name': 'Balanced Scorecard - Demo Data',
    'version': '20.0.1.2.0',
    'category': 'Services/Strategy',
    'summary': 'A complete worked example: a strategy, closed quarters, a live one',
    'description': """
Balanced Scorecard - Demo Data
==============================

Installs one fully worked scorecard and then actually runs it, so that every
feature is visible in a real state instead of as an empty form.

What you get after installing:

* a strategy for the current year, quarterly, with 8 objectives across the four
  perspectives - one of them qualitative, with no KPI at all;
* a strategy map with 9 cause-effect links, each written down as a hypothesis
  with a believed strength;
* 12 KPIs covering all three directions (higher is better, lower is better, and
  a target range), two of them filled automatically from Odoo data;
* **every quarter before today's closed**, with a full set of figures, variance
  comments on the red ones, and the strategy review that each closing opened;
* **the current quarter open and half-collected**, with one figure held back by
  the deviation guard and one source that matched nothing - the two guards you
  cannot see until they fire;
* initiatives across the whole lifecycle, including one that came out of a
  review, and one that runs as an Odoo project.

The story the numbers tell is deliberate: delivery is failing in the process
perspective, which is dragging customer retention, which is dragging revenue.
Open the strategy map and you can read that chain off the picture.

In January to March the demo runs the previous year, with its Q4 as the live
quarter, because the current year has no closed quarter yet.

**For testing only.** It writes ordinary records, not XML data, so uninstalling
the module does not remove them. Install it on a scratch database.
""",
    'author': 'GEC',
    'license': 'LGPL-3',
    'depends': ['bsc_strategy'],
    'data': [],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
