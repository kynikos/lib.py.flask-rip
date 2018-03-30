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

from functools import wraps, partialmethod
from collections import namedtuple
import inspect
import re
from flask import request
from marshmallow import post_load, UnmarshalResult, ValidationError
from flask_marshmallow import Marshmallow, Schema as MASchema

IMPLICIT = 0b01
EXPLICIT = 0b10


class API:
    REQUESTMETHOD_TO_GETDATA = {
        'DELETE': lambda: request.args,
        'GET': lambda: request.args,
        'HEAD': lambda: request.args,
        'OPTIONS': lambda: request.args,
        'PATCH': lambda: request.get_json(),
        'POST': lambda: request.get_json(),
        'PUT': lambda: request.get_json(),
    }

    def __init__(self, app, root_path=None, base_method_path=IMPLICIT):
        self.app = app
        # Don't try to normalize leading/trailing slashes,
        # "we're all consenting adults here"
        self.root_path = root_path or ''
        self.base_method_path = base_method_path
        self.ma = Marshmallow(app)

        self.resources = []

        # Convenience attributes to allow importing directly from the API
        # instance
        self.Resource = Resource
        self.Schema = Schema
        self.MASchema = MASchema

    def add_resource(self, Resource_, *args, **kwargs):
        resource = Resource_(self, *args, **kwargs)
        self.resources.append(resource)
        return resource

    def resource(self, *args, **kwargs):
        def decorator(Resource_):
            self.add_resource(Resource_, *args, **kwargs)

            @wraps(Resource_)
            def inner(*fargs, **fkwargs):
                return Resource_(*fargs, **fkwargs)
            return inner
        return decorator

    def _marshal(self, in_method, in_schema, out_schema, in_get_data=None,
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

        def decorator(function):
            function._http_method = in_method

            @wraps(function)
            def inner(inself, *args, **kwargs):
                indata = unmarshal_data()

                if type(indata) is UnmarshalResult:
                    # Marshmallow<3
                    if indata.errors:
                        raise ValidationError(indata.errors)
                    indata = indata.data
                # else it's Marshmallow>=3, which returns the data directly

                outdata = function(inself, indata, *args, **kwargs)

                return marshal_data(outdata), out_code
            return inner
        return decorator

    delete = partialmethod(_marshal, 'DELETE')
    get = partialmethod(_marshal, 'GET')
    head = partialmethod(_marshal, 'HEAD')
    options = partialmethod(_marshal, 'OPTIONS')
    patch = partialmethod(_marshal, 'PATCH')
    post = partialmethod(_marshal, 'POST')
    put = partialmethod(_marshal, 'PUT')


# Adapted from https://stackoverflow.com/a/1176023/645498
# Don't store in the Resource class to not pollute its namespace
_FIRST_CAP_RE = re.compile('([A-Z]+)([A-Z][a-z])')
_ALL_CAP_RE = re.compile('([a-z0-9])([A-Z])')


def camel_to_kebab(name):
    name1 = _FIRST_CAP_RE.sub(r'\1-\2', name)
    name2 = _ALL_CAP_RE.sub(r'\1-\2', name1).lower()
    return '/' + name2.replace('_', '-')


class Resource():
    def __init__(self, api, super_endpoint=None, super_path=None,
                 res_path=camel_to_kebab, var_path=None):
        # NOTE: Do not pollute the class' namespace, which holds the route
        #       handlers' names
        # self.__api = api

        try:
            respath = res_path(self.__class__.__name__)
        except TypeError:
            # url_name isn't callable, I suppose it's a string or None
            respath = res_path or '/' + self.__class__.__name__

        for fname, func in inspect.getmembers(self,
                                              predicate=inspect.ismethod):
            try:
                http_method = func._http_method
            except AttributeError:
                continue
            else:
                # Don't try to normalize leading/trailing slashes,
                # "we're all consenting adults here"
                baseabsrule = ''.join((api.root_path, super_path or '',
                                       respath, var_path or ''))
                absrule = '/'.join((baseabsrule, fname))

                endpoint = ':'.join((self.__class__.__name__, fname))
                if super_endpoint:
                    endpoint = ':'.join((super_endpoint, endpoint))

                if fname == http_method.lower():
                    if api.base_method_path & IMPLICIT:
                        api.app.add_url_rule(
                            baseabsrule,
                            endpoint=endpoint,
                            view_func=func,
                            methods=(http_method, ))

                    if api.base_method_path & EXPLICIT:
                        api.app.add_url_rule(
                            absrule,
                            endpoint=endpoint,
                            view_func=func,
                            methods=(http_method, ))
                else:
                    api.app.add_url_rule(
                        absrule,
                        endpoint=endpoint,
                        view_func=func,
                        methods=(http_method, ))


class Schema(MASchema):
    @post_load
    def make_namedtuple(self, data):
        # Yes, the order of keys() and values() are ensured to correspond
        # https://docs.python.org/3/library/stdtypes.html#dict-views
        return namedtuple("UnmarshalNamedTuple", data.keys())(*data.values())
