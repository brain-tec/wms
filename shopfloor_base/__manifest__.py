# Copyright 2020 Camptocamp SA (http://www.camptocamp.com)
# Copyright 2020 Akretion (http://www.akretion.com)
# Copyright 2020 BCIM
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

{
    "name": "Shopfloor Base",
    "summary": "Core module for creating mobile apps",
    "version": "13.0.1.0.0",
    "development_status": "Alpha",
    "category": "Inventory",
    "website": "https://github.com/OCA/wms",
    "author": "Camptocamp, BCIM, Akretion, Odoo Community Association (OCA)",
    "maintainers": ["guewen", "simahawk", "sebalix"],
    "license": "AGPL-3",
    "application": True,
    "depends": [
        "base_jsonify",
        "base_rest",
        "rest_log",
        "base_sparse_field",
        "auth_api_key",
    ],
    "data": [
        "data/module_category_data.xml",
        "security/groups.xml",
        "security/ir.model.access.csv",
        "views/shopfloor_menu.xml",
        "views/shopfloor_profile_views.xml",
        "views/menus.xml",
    ],
    "demo": [
        "demo/auth_api_key_demo.xml",
        "demo/shopfloor_menu_demo.xml",
        "demo/shopfloor_profile_demo.xml",
    ],
}
