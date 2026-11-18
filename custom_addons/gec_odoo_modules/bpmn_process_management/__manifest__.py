{
    "name": "BPMN Process Management",
    "summary": "Process repository, BPMN 2.0 modeler/viewer and knowledge hub "
               "(import from draw.io, Visio, Camunda, Signavio)",
    "version": "1.5.0",
    "category": "Productivity",
    "author": "GEC Business",
    "website": "https://gecbusiness.com",
    "license": "LGPL-3",
    "depends": ["base", "web", "mail"],
    "external_dependencies": {"python": ["lxml"]},
    "data": [
        "security/security.xml",
        "data/business_process_cron.xml",
        "data/business_process_data.xml",
        "views/business_process_views.xml",
        "views/business_process_config_views.xml",
        "views/business_process_element_views.xml",
        "wizard/business_process_import_views.xml",
        "wizard/business_process_publish_views.xml",
        "views/menus.xml",
    ],
    "demo": [
        "demo/business_process_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "bpmn_process_management/static/src/bpmn_field/*.js",
            "bpmn_process_management/static/src/bpmn_field/*.scss",
            "bpmn_process_management/static/src/dashboard/*.js",
            "bpmn_process_management/static/src/dashboard/*.scss",
        ],
    },
    "images": ["static/description/icon.png"],
    "uninstall_hook": "uninstall_hook",
    "application": True,
    "installable": True,
}
