from . import bsc_common
from . import bsc_perspective
from . import bsc_scorecard
from . import bsc_objective
from . import bsc_objective_rating
from . import bsc_objective_link
from . import bsc_kpi
from . import bsc_period
from . import bsc_measurement
from . import bsc_initiative
from . import bsc_review

# Automation: each extends a model above, so it is imported after it.
from . import bsc_kpi_source
from . import bsc_kpi_recipes
from . import bsc_kpi_automation
from . import bsc_period_automation
from . import bsc_measurement_automation
from . import bsc_strategy_map
from . import bsc_kpi_connect

from . import bsc_initiative_project
from . import project_project

from . import bsc_demo
from . import bsc_dashboard

# Keeps the module visible in the Apps menu.
from . import ir_module
from . import bsc_security
