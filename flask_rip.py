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
from flask import request
from flask.views import MethodView
from marshmallow import post_load, UnmarshalResult, ValidationError
from flask_marshmallow import Marshmallow, Schema as MASchema


class API:
    REQUESTMETHOD_TO_GETDATA = {
        'delete': lambda request: request.args,
        'get': lambda request: request.args,
        'head': lambda request: request.args,
        'options': lambda request: request.args,
        'patch': lambda request: request.get_json(),
        'post': lambda request: request.get_json(),
        'put': lambda request: request.get_json(),
    }

    def __init__(self, app, endpoint='/api'):
        self.app = app
        sep = endpoint.strip('/')
        # Later I rely on base_endpoint to also *end* with a slash
        self.base_endpoint = sep.join(('/', '/')) if sep else '/'
        self.ma = Marshmallow(app)

        # Convenience attributes to allow importing directly from the API
        # instance
        self.Resource = Resource
        self.Schema = Schema
        self.MASchema = MASchema

    def add_resource(self, View, *rules, **options):
        view = View.as_view(View.__name__)
        for rule in rules:
            # The following must also work when base_endpoint is simply '/'
            # Preserve the original slash (or lack thereof) on the right end
            absrule = ''.join((self.base_endpoint, rule.lstrip('/')))
            self.app.add_url_rule(absrule, view_func=view, **options)
        return view

    def route(self, *rules, **options):
        def decorator(View):
            self.add_resource(View, *rules, **options)

            @wraps(View)
            def inner(*args, **kwargs):
                return View(*args, **kwargs)
            return inner
        return decorator

    def marshal(self, in_schema, out_schema, out_code=200):
        def decorator(function):
            get_data = self.REQUESTMETHOD_TO_GETDATA[function.__name__]

            @wraps(function)
            def inner(self, *args, **kwargs):
                sdata = get_data(request)
                indata = in_schema.load(sdata)
                if type(indata) is UnmarshalResult:
                    # Marshmallow<3
                    if indata.errors:
                        raise ValidationError(indata.errors)
                    indata = indata.data
                # else it's Marshmallow>=3, which returns the data directly
                outdata = function(self, indata, *args, **kwargs)
                return out_schema.jsonify(outdata), out_code
            return inner
        return decorator


class Resource(MethodView):
    pass


class Schema(MASchema):
    @post_load
    def make_namedtuple(self, data):
        # Yes, the order of keys() and values() are ensured to correspond
        # https://docs.python.org/3/library/stdtypes.html#dict-views
        return namedtuple("UnmarshalNamedTuple", data.keys())(*data.values())
