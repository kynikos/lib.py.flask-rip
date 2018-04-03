# Flask RIP - Create Flask REST APIs in peace.
# Copyright (C) 2018 Dario Giovannetti <dev@dariogiovannetti.net>
#
# This file is part of Flask RIP.
#
# Flask RIP is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Flask RIP is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Flask RIP.  If not, see <http://www.gnu.org/licenses/>.

from functools import wraps
from collections import namedtuple
import inspect
import re
from flask import request
from marshmallow import post_load, UnmarshalResult, ValidationError
from flask_marshmallow import Marshmallow, Schema as MASchema

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
                 base_method_path=IMPLICIT):
        self.app = app
        self.parent_api = parent_api

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

        self.delete = ResourceFromClass.delete
        self.get = ResourceFromClass.get
        self.head = ResourceFromClass.head
        self.options = ResourceFromClass.options
        self.patch = ResourceFromClass.patch
        self.post = ResourceFromClass.post
        self.put = ResourceFromClass.put

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
        ResourceFromClass(self, resource, *args, **kwargs)
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

    def __init__(self, api, endpoint, res_path, var_path):
        self.api = api

        # Don't try to normalize leading/trailing slashes,
        # "we're all consenting adults here"
        self.baseabsrule = ''.join((api.base_path or '', res_path,
                                    var_path or ''))

        self.res_endpoint = api.ENDPOINT_GLUE.join((
            api.base_endpoint, endpoint)) if api.base_endpoint else endpoint

    def _route_function(self, function, var_path, http_method):
        fname = function.__name__

        # Don't try to normalize leading/trailing slashes,
        # "we're all consenting adults here"
        baseabsrule = ''.join((self.baseabsrule, var_path or ''))
        absrule = '/'.join((baseabsrule, fname))

        endpoint = self.api.ENDPOINT_GLUE.join((self.res_endpoint, fname))
        if fname == http_method.lower():
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

    # This function may be called as a method or classmethod
    def _route_function_hook(self_or_cls, function, var_path, http_method):
        raise NotImplementedError()

    # This function may be called as a method or classmethod
    def _call_function(self_or_cls, function, indata, *args, **kwargs):
        raise NotImplementedError()

    # This function may be called as a method or classmethod
    def _make_decorator(self_or_cls, in_method, in_schema, out_schema,
                        var_path=None, in_get_data=None, out_code=200):
        if in_get_data:
            get_data = in_get_data
        else:
            get_data = self_or_cls.REQUESTMETHOD_TO_GETDATA[in_method]

        if in_schema:
            unmarshal_data = lambda: in_schema.load(get_data())  # noqa
        else:
            unmarshal_data = lambda: get_data()   # noqa

        if out_schema:
            marshal_data = lambda outdata: out_schema.jsonify(outdata)  # noqa
        else:
            marshal_data = lambda outdata: outdata  # noqa

        def decorator(function):
            self_or_cls._route_function_hook(function, var_path, in_method)
            function._var_path = var_path
            function._http_method = in_method

            @wraps(function)
            def inner(*args, **kwargs):
                # This might also be a class method, i.e. the first argument
                # could be a class instance
                # def inner(inself, *args, **kwargs):

                indata = unmarshal_data()

                if type(indata) is UnmarshalResult:
                    # Marshmallow<3
                    if indata.errors:
                        raise ValidationError(indata.errors)
                    indata = indata.data
                # else it's Marshmallow>=3, which returns the data directly

                outdata = self_or_cls._call_function(function, indata, *args,
                                                     **kwargs)

                return marshal_data(outdata), out_code
            return inner
        return decorator


class ResourceFromFunctions(_Resource):
    def __init__(self, api, endpoint, res_path=None, var_path=None):
        respath = res_path or '/' + api.path_from_endpoint(endpoint)
        super().__init__(api, endpoint, res_path=respath, var_path=var_path)

    def delete(self, *args, **kwargs):
        return self._make_decorator('DELETE', *args, **kwargs)

    def get(self, *args, **kwargs):
        return self._make_decorator('GET', *args, **kwargs)

    def head(self, *args, **kwargs):
        return self._make_decorator('HEAD', *args, **kwargs)

    def options(self, *args, **kwargs):
        return self._make_decorator('OPTIONS', *args, **kwargs)

    def patch(self, *args, **kwargs):
        return self._make_decorator('PATCH', *args, **kwargs)

    def post(self, *args, **kwargs):
        return self._make_decorator('POST', *args, **kwargs)

    def put(self, *args, **kwargs):
        return self._make_decorator('PUT', *args, **kwargs)

    def _route_function_hook(self, function, var_path, http_method):
        self._route_function(function, var_path, http_method)

    def _call_function(self, function, indata, *args, **kwargs):
        return function(indata, *args, **kwargs)


class ResourceFromClass(_Resource):
    def __init__(self, api, resource, res_path=None, var_path=None):
        respath = res_path or '/' + api.path_from_endpoint(
            resource.__class__.__name__)

        super().__init__(api, endpoint=resource.__class__.__name__,
                         res_path=respath, var_path=var_path)

        for fname, function in inspect.getmembers(resource,
                                                  predicate=inspect.ismethod):
            try:
                func_var_path = function._var_path
                http_method = function._http_method
            except AttributeError:
                continue

            self._route_function(function, func_var_path, http_method)

    @classmethod
    def delete(cls, *args, **kwargs):
        return cls._make_decorator(cls, 'DELETE', *args, **kwargs)

    @classmethod
    def get(cls, *args, **kwargs):
        return cls._make_decorator(cls, 'GET', *args, **kwargs)

    @classmethod
    def head(cls, *args, **kwargs):
        return cls._make_decorator(cls, 'HEAD', *args, **kwargs)

    @classmethod
    def options(cls, *args, **kwargs):
        return cls._make_decorator(cls, 'OPTIONS', *args, **kwargs)

    @classmethod
    def patch(cls, *args, **kwargs):
        return cls._make_decorator(cls, 'PATCH', *args, **kwargs)

    @classmethod
    def post(cls, *args, **kwargs):
        return cls._make_decorator(cls, 'POST', *args, **kwargs)

    @classmethod
    def put(cls, *args, **kwargs):
        return cls._make_decorator(cls, 'PUT', *args, **kwargs)

    @classmethod
    def _route_function_hook(cls, function, var_path, http_method):
        pass

    @classmethod
    def _call_function(cls, function, indata, *args, **kwargs):
        return function(args[0], indata, *args[1:], **kwargs)


class Schema(MASchema):
    @post_load
    def make_namedtuple(self, data):
        # Yes, the order of keys() and values() are ensured to correspond
        # https://docs.python.org/3/library/stdtypes.html#dict-views
        return namedtuple("UnmarshalNamedTuple", data.keys())(*data.values())
