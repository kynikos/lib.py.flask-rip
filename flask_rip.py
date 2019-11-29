# This file is part of Flask RIP - Create Flask REST APIs in peace.
# Copyright (C) 2018-present Dario Giovannetti <dev@dariogiovannetti.net>
# Licensed under MIT
# https://github.com/kynikos/lib.py.flask-rip/blob/master/LICENSE

from functools import wraps, partialmethod
from collections import defaultdict, namedtuple
import inspect
import re
from flask import request
from marshmallow import post_load, ValidationError
try:
    # Marshmallow 2 (old)
    from marshmallow import UnmarshalResult
except ImportError:
    UnmarshalResult = None
from flask_marshmallow import Marshmallow, Schema as MASchema
from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin
from apispec_webframeworks.flask import FlaskPlugin

IMPLICIT = 0b01
EXPLICIT = 0b10

# Adapted from https://stackoverflow.com/a/1176023/645498
# Don't store in the Resource class to not pollute its namespace
_FIRST_CAP_RE = re.compile('([A-Z]+)([A-Z][a-z])')
_ALL_CAP_RE = re.compile('([a-z0-9])([A-Z])')


def camel_to_kebab(name):
    name1 = _FIRST_CAP_RE.sub(r'\1-\2', name)
    name2 = _ALL_CAP_RE.sub(r'\1-\2', name1).lower()
    return name2.replace('_', '-')


class API:
    ENDPOINT_GLUE = ':'

    def __init__(self, app, base_path=None, base_endpoint=None,
                 parent_api=None, path_from_endpoint=camel_to_kebab,
                 base_method_path=IMPLICIT,
                 # TODO: Deprecate the openapi_spec option in a following major
                 #       release, only use openapi_conf
                 openapi_spec=None,
                 openapi_conf=None):
        self.app = app
        self.parent_api = parent_api

        if openapi_conf:
            openapi_conf.update(plugins=(
                FlaskPlugin(),
                MarshmallowPlugin(),
            ))
            self.openapi_spec = APISpec(**openapi_conf)
        elif openapi_spec:
            # TODO: Deprecate the openapi_spec option in a following major
            #       release, only use openapi_conf
            self.openapi_spec = openapi_spec
        else:
            self.openapi_spec = None

        if parent_api:
            self.path_from_endpoint = (path_from_endpoint or
                                       parent_api.path_from_endpoint)
            self.base_method_path = (base_method_path or
                                     parent_api.base_method_path)

            base_endpoint = base_endpoint or self.__class__.__name__
            if parent_api.base_endpoint:
                # Do use the parent glue here
                self.base_endpoint = parent_api.ENDPOINT_GLUE.join((
                    parent_api.base_endpoint, base_endpoint))
            else:
                self.base_endpoint = base_endpoint

            # Don't try to normalize leading/trailing slashes,
            # "we're all consenting adults here"
            base_path = base_path or '/' + path_from_endpoint(
                self.__class__.__name__)
            if parent_api.base_path:
                self.base_path = ''.join((parent_api.base_path, base_path))
            else:
                self.base_path = base_path
        else:
            self.path_from_endpoint = path_from_endpoint
            self.base_method_path = base_method_path
            self.base_endpoint = base_endpoint
            # Don't try to normalize leading/trailing slashes,
            # "we're all consenting adults here"
            self.base_path = base_path

        self.ma = Marshmallow(app)

        self.subapis = []

        self.resource_from_class = ResourceFromClass(self)
        self.delete = self.resource_from_class.delete
        self.get = self.resource_from_class.get
        self.head = self.resource_from_class.head
        self.options = self.resource_from_class.options
        self.patch = self.resource_from_class.patch
        self.post = self.resource_from_class.post
        self.put = self.resource_from_class.put

        # Convenience attributes to allow importing directly from the API
        # instance
        self.Schema = Schema
        self.MASchema = MASchema

    def append_api(self, base_endpoint, base_path=None):
        subapi = self.__class__(self.app, parent_api=self, base_path=base_path,
                                base_endpoint=base_endpoint)
        self.subapis.append(subapi)
        return subapi

    def add_resource(self, Resource_, *args, **kwargs):
        resource = Resource_()
        self.resource_from_class.post_init(resource, *args, **kwargs)
        return resource

    def resource(self, *args, **kwargs):
        def decorator(Resource_):
            self.add_resource(Resource_, *args, **kwargs)

            @wraps(Resource_)
            def inner(*fargs, **fkwargs):
                return Resource_(*fargs, **fkwargs)
            return inner
        return decorator

    def create_resource(self, *args, **kwargs):
        return ResourceFromFunctions(self, *args, **kwargs)


class _Resource:
    REQUESTMETHOD_TO_GETDATA = {
        'DELETE': lambda: request.args,
        'GET': lambda: request.args,
        'HEAD': lambda: request.args,
        'OPTIONS': lambda: request.args,
        'PATCH': lambda: request.get_json(),
        'POST': lambda: request.get_json(),
        'PUT': lambda: request.get_json(),
    }

    def __init__(self, api):
        self.api = api

    def post_init(self, endpoint, res_path, resvar_path):
        # Don't try to normalize leading/trailing slashes,
        # "we're all consenting adults here"
        self.baseabsrule = ''.join((self.api.base_path or '', res_path,
                                    resvar_path or ''))

        self.res_endpoint = self.api.ENDPOINT_GLUE.join(
            (self.api.base_endpoint, endpoint)
        ) if self.api.base_endpoint else endpoint

    def _route_function(self, function, var_path, http_method, action):
        action = action or function.__name__

        # Don't try to normalize leading/trailing slashes,
        # "we're all consenting adults here"
        baseabsrule = ''.join((self.baseabsrule, var_path or ''))
        absrule = '/'.join((baseabsrule, action))

        endpoint = self.api.ENDPOINT_GLUE.join((self.res_endpoint,
                                                function.__name__))

        if action == http_method.lower():
            if self.api.base_method_path & IMPLICIT:
                self.api.app.add_url_rule(
                    baseabsrule,
                    endpoint=endpoint,
                    view_func=function,
                    methods=(http_method, ))

            if self.api.base_method_path & EXPLICIT:
                self.api.app.add_url_rule(
                    absrule,
                    endpoint=endpoint,
                    view_func=function,
                    methods=(http_method, ))

        else:
            self.api.app.add_url_rule(
                absrule,
                endpoint=endpoint,
                view_func=function,
                methods=(http_method, ))

        if self.api.openapi_spec:
            with self.api.app.test_request_context():
                self.api.openapi_spec.path(view=function)

    def _route_function_hook(self, function, var_path, http_method, action):
        raise NotImplementedError()

    def _call_function(self, function, indata, *args, **kwargs):
        raise NotImplementedError()

    def _make_decorator(self, in_method, in_schema, out_schema,
                        var_path=None, action=None, in_get_data=None,
                        out_code=200):
        if in_get_data:
            get_data = in_get_data
        else:
            get_data = self.REQUESTMETHOD_TO_GETDATA[in_method]

        if in_schema:
            unmarshal_data = lambda: in_schema.load(get_data())  # noqa
        else:
            unmarshal_data = lambda: get_data()   # noqa

        if out_schema:
            marshal_data = lambda outdata: out_schema.jsonify(outdata)  # noqa
        else:
            marshal_data = lambda outdata: outdata  # noqa

        if in_schema and self.api.openapi_spec:
            self.api.openapi_spec.components.schema(
                in_schema.__class__.__name__, schema=in_schema.__class__)

        def decorator(function):

            @wraps(function)
            def inner(*args, **kwargs):
                # This might also be a class method, i.e. the first argument
                # could be a class instance
                # def inner(inself, *args, **kwargs):

                indata = unmarshal_data()

                if UnmarshalResult and type(indata) is UnmarshalResult:
                    # Marshmallow<3
                    if indata.errors:
                        raise ValidationError(indata.errors)
                    indata = indata.data
                # else it's Marshmallow>=3, which returns the data directly

                outdata = self._call_function(function, indata, *args,
                                              **kwargs)

                return marshal_data(outdata), out_code

            self._route_function_hook(inner, var_path, in_method, action)
            inner._var_path = var_path
            inner._http_method = in_method
            inner._action = action

            return inner
        return decorator

    delete = partialmethod(_make_decorator, 'DELETE')
    get = partialmethod(_make_decorator, 'GET')
    head = partialmethod(_make_decorator, 'HEAD')
    options = partialmethod(_make_decorator, 'OPTIONS')
    patch = partialmethod(_make_decorator, 'PATCH')
    post = partialmethod(_make_decorator, 'POST')
    put = partialmethod(_make_decorator, 'PUT')

class ResourceFromFunctions(_Resource):
    def __init__(self, api, endpoint, res_path=None, resvar_path=None):
        super().__init__(api)
        respath = res_path or '/' + api.path_from_endpoint(endpoint)
        super().post_init(endpoint, res_path=respath, resvar_path=resvar_path)

    def _route_function_hook(self, function, var_path, http_method, action):
        self._route_function(function, var_path, http_method, action)

    def _call_function(self, function, indata, *args, **kwargs):
        return function(indata, *args, **kwargs)


class ResourceFromClass(_Resource):
    def __init__(self, api):
        super().__init__(api)

    def post_init(self, resource, res_path=None, resvar_path=None):
        respath = res_path or '/' + self.api.path_from_endpoint(
            resource.__class__.__name__)

        super().post_init(endpoint=resource.__class__.__name__,
                          res_path=respath, resvar_path=resvar_path)

        for fname, function in inspect.getmembers(resource,
                                                  predicate=inspect.ismethod):
            try:
                func_var_path = function._var_path
                http_method = function._http_method
                action = function._action
            except AttributeError:
                continue

            self._route_function(function, func_var_path, http_method, action)

    def _route_function_hook(self, function, var_path, http_method, action):
        pass

    def _call_function(self, function, indata, *args, **kwargs):
        return function(args[0], indata, *args[1:], **kwargs)


class Schema(MASchema):
    @post_load
    # **kwargs is needed because in Marshmallow 3 decorated methods and
    # handle_error receive many and partial as keyword arguments
    # https://marshmallow.readthedocs.io/en/stable/upgrading.html#decorated-methods-and-handle-error-receive-many-and-partial
    def make_namedtuple(self, data, **kwargs):
        # Yes, the order of keys() and values() are ensured to correspond
        # https://docs.python.org/3/library/stdtypes.html#dict-views
        return namedtuple("UnmarshalNamedTuple", data.keys())(*data.values())
