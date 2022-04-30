# Copyright 2021 Camptocamp SA (http://www.camptocamp.com)
# @author Simone Orsi <simahawk@gmail.com>
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html).
from functools import partial

from odoo import api, fields, models
from odoo.http import request
from odoo.tools import DotDict

from odoo.addons.base_rest.controllers.main import RestController
from odoo.addons.base_rest.tools import _inspect_methods
from odoo.addons.component.core import _component_databases

from ..utils import APP_VERSION, RUNNING_ENV


def _process_endpoint(
    self, app_id, service_name, service_method_name, *args, collection=None, **kwargs
):
    """Wrapper for  `_process_method` call.

    Behavior is the same for the methods automatically generated by `rest.service.registration`.
    """
    collection = collection or request.env["shopfloor.app"].browse(app_id)
    # TODO: in base_rest `*args` is passed based on on the type of route (eg: /<int:id>/update)
    return self._process_method(
        service_name, service_method_name, *args, collection=collection, params=kwargs
    )


RestController._process_endpoint = _process_endpoint


class ShopfloorApp(models.Model):
    """Backend for a Shopfloor app."""

    _name = "shopfloor.app"
    _inherit = "collection.base"
    _description = "A Shopfloor application"

    name = fields.Char(required=True, translate=True)
    short_name = fields.Char(
        required=True, translate=True, help="Needed for app manifest"
    )
    # Unique name
    tech_name = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    category = fields.Selection(selection=[("", "None")])
    api_route = fields.Char(
        compute="_compute_api_route",
        compute_sudo=True,
        help="Base route for endpoints attached to this app, public version.",
    )
    api_route = fields.Char(
        compute="_compute_api_route",
        compute_sudo=True,
        help="""
        Base route for endpoints attached to this app,
        internal controller-ready version.
        """,
    )
    url = fields.Char(compute="_compute_url", help="Public URL to use the app.")
    api_docs_url = fields.Char(compute="_compute_url", help="Public URL for api docs.")
    auth_type = fields.Selection(
        selection="_selection_auth_type", default="user_endpoint"
    )
    registered_routes = fields.Text(
        compute="_compute_registered_routes",
        compute_sudo=True,
        help="Technical field to allow developers to check registered routes on the form",
        groups="base.group_no_one",
    )
    profile_ids = fields.Many2many(
        comodel_name="shopfloor.profile",
        string="Profiles",
        help="Profiles used by this app. "
        "This will determine menu items too."
        "However this field is not required "
        "in case you don't need profiles and menu items from the backend.",
    )
    profile_required = fields.Boolean(compute="_compute_profile_required", store=True)
    app_version = fields.Char(compute="_compute_app_version")

    _sql_constraints = [("tech_name", "unique(tech_name)", "tech_name must be unique")]

    _api_route_path = "/shopfloor/api/"

    @api.depends("tech_name")
    def _compute_api_route(self):
        for rec in self:
            rec.api_route = rec._api_route_path + rec.tech_name

    _base_url_path = "/shopfloor/app/"
    _base_api_docs_url_path = "/shopfloor/api-docs/"

    @api.depends("tech_name")
    def _compute_url(self):
        for rec in self:
            rec.url = rec._base_url_path + rec.tech_name
            rec.api_docs_url = rec._base_api_docs_url_path + rec.tech_name

    @api.depends("tech_name")
    def _compute_registered_routes(self):
        for rec in self:
            routes = sorted(rec._registered_routes())
            vals = []
            for __, endpoint_rule in routes:
                vals.append(
                    f"{endpoint_rule.route} ({', '.join(endpoint_rule.routing['methods'])})"
                )
            rec.registered_routes = "\n".join(vals)

    @api.depends("profile_ids")
    def _compute_profile_required(self):
        for rec in self:
            rec.profile_required = bool(rec.profile_ids)

    def _compute_app_version(self):
        # Override this to choose your own versioning policy
        for rec in self:
            rec.app_version = APP_VERSION

    def _selection_auth_type(self):
        return self.env["endpoint.route.handler"]._selection_auth_type()

    def api_url_for_service(self, service_name, endpoint=None):
        """Handy method to generate services' API URLs for current app."""
        return f"{self.api_route}/{service_name}/{endpoint or ''}".rstrip("/")

    def action_open_app(self):
        return {
            "type": "ir.actions.act_url",
            "name": self.name,
            "url": self.url,
            "target": "new",
        }

    def action_open_app_docs(self):
        return {
            "type": "ir.actions.act_url",
            "name": self.name,
            "url": self.api_docs_url,
            "target": "new",
        }

    def action_view_menu_items(self):
        xid = "shopfloor_base.action_shopfloor_menu"
        action = self.env["ir.actions.act_window"]._for_xml_id(xid)
        action["domain"] = [
            "|",
            ("id", "in", self.profile_ids.menu_ids.ids),
            ("profile_id", "=", False),
        ]
        return action

    # TODO: move to shopfloor_app_base? or just `app_base`?
    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        for rec in res:
            rec._register_endpoints()
        return res

    def write(self, vals):
        res = super().write(vals)
        if any([x in vals for x in self._endpoint_impacting_fields()]):
            for rec in self:
                rec._register_endpoints()
        return res

    def _endpoint_impacting_fields(self):
        return ["tech_name", "auth_type"]

    def unlink(self):
        for rec in self:
            rec._unregister_endpoints()
        return super().unlink()

    def _register_hook(self):
        super()._register_hook()
        for rec in self.search([]):
            rec._register_endpoints()

    def _register_endpoints(self):
        services = self._get_services()
        for service in services:
            self._prepare_non_decorated_endpoints(service)
            self._generate_endpoints(service)
        self.env["rest.service.registration"]._register_rest_route(self.api_route)

    def _unregister_endpoints(self):
        registry = self.env["endpoint.route.handler"]._endpoint_registry
        for key, __ in self._registered_routes():
            registry.drop_rule(key)

    def _registered_routes(self):
        registry = self.env["endpoint.route.handler"]._endpoint_registry
        return registry.get_rules_by_group(self._route_group())

    @api.model
    def _prepare_non_decorated_endpoints(self, service):
        # Autogenerate routing info where missing
        self.env["rest.service.registration"]._prepare_non_decorated_endpoints(service)

    def _generate_endpoints(self, service):
        rest_endpoint_handler = RestController()._process_endpoint
        values = self._generate_endpoints_values(service, self.api_route)
        for vals in values:
            self._generate_endpoints_routes(service, rest_endpoint_handler, vals)

    def _generate_endpoints_values(self, service, api_route):
        values = []
        root_path = api_route.rstrip("/") + "/" + service._usage
        for name, method in _inspect_methods(service.__class__):
            if not hasattr(method, "routing"):
                continue
            routing = method.routing
            for routes, http_method in routing["routes"]:
                # TODO: why on base_rest we have this instead of pure method name?
                # method_name = "{}_{}".format(http_method.lower(), name)
                method_name = name
                default_route = root_path + "/" + routes[0].lstrip("/")
                route_params = dict(
                    route=["{}{}".format(root_path, r) for r in routes],
                    methods=[http_method],
                )
                # TODO: get this params from self?
                for attr in {"auth", "cors", "csrf", "save_session"}:
                    if attr in routing:
                        route_params[attr] = routing[attr]
                # {'route': ['/foo/testing/app/user_config'], 'methods': ['POST']}
                values.append(
                    self._prepare_endpoint_vals(
                        service, method_name, default_route, route_params
                    )
                )
        return values

    def _generate_endpoints_routes(self, service, rest_endpoint_handler, vals):
        route_handler = self.env["endpoint.route.handler"]
        endpoint_handler = partial(
            rest_endpoint_handler, self.id, service._usage, vals.pop("_method_name")
        )
        new_route = route_handler.new(vals)
        new_route._refresh_endpoint_data()
        # Endpoints' rule might be duplicated
        # because we generate them all for all apps.
        # TODO: TESTS!!
        new_route._register_controller(
            endpoint_handler=endpoint_handler, key=vals["name"]
        )

    def _prepare_endpoint_vals(self, service, method_name, route, routing_params):
        request_method = routing_params["methods"][0]
        name = (
            f"{self.tech_name}::{service._name}/{method_name}__{request_method.lower()}"
        )
        endpoint_vals = dict(
            name=name,
            request_method=request_method,
            route=route,
            route_group=self._route_group(),
            auth_type=self.auth_type,
            _method_name=method_name,
        )
        return endpoint_vals

    def _route_group(self):
        return f"{self._name}:{self.tech_name}"

    def _is_component_registry_ready(self):
        comp_registry = _component_databases.get(self.env.cr.dbname)
        return comp_registry and comp_registry.ready

    def _get_services(self):
        if not self._is_component_registry_ready():
            # No service is available before the registry has been loaded.
            # This is a very special case, when the odoo registry is being
            # built, it calls odoo.modules.loading.load_modules().
            return []
        return self.env["rest.service.registration"]._get_services(self._name)

    def _make_app_info(self, demo=False):
        base_url = self.api_route.rstrip("/") + "/"
        return DotDict(
            name=self.name,
            short_name=self.short_name,
            base_url=base_url,
            manifest_url=self.url + "/manifest.json",
            auth_type=self.auth_type,
            profile_required=self.profile_required,
            demo_mode=demo,
            version=self.app_version,
            running_env=RUNNING_ENV,
        )
