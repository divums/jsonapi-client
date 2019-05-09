#
# JSON API Client for Python
# Project home: https://github.com/qvantel/jsonapi-client
#
# Copyright (c) 2017-2019, Qvantel
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# - Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# - Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# - Neither the name of Qvantel nor the names of its contributors may be used
#   to endorse or promote products derived from this software without specific
#   prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL QVANTEL BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
# OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,EVEN IF ADVISED
# OF THE POSSIBILITY OF SUCH DAMAGE.
#

from typing import TYPE_CHECKING, Union, Dict, Sequence
from .utils import jsonify_name

if TYPE_CHECKING:
    NamedParameters = Dict[str, Union[str, int, float, Sequence[Union[str, int, float]]]]
    ValueParameters = Sequence[str]


class BaseModifier:
    """
    Base class for query modifiers.
    You can derive your own class and use it if you have custom syntax.
    """
    def url_with_modifiers(self, base_url: str) -> str:
        """
        Returns url with modifiers appended.

        Example:
            Modifier('filter[attr1]=1,2&filter[attr2]=2').url_with_modifiers('doc')
              -> 'GET doc?filter[attr1]=1,2&filter[attr2]=2'
        """
        return f'{base_url}?{self.appended_query}'

    @property
    def appended_query(self) -> str:
        raise NotImplementedError

    def __add__(self, other: 'BaseModifier') -> 'BaseModifier':
        mods = []
        for m in [self, other]:
            if isinstance(m, ModifierSum):
                mods += m.modifiers
            else:
                mods.append(m)
        return ModifierSum(mods)


class ModifierSum(BaseModifier):
    def __init__(self, modifiers: Sequence['BaseModifier']) -> None:
        self.modifiers = modifiers

    @property
    def appended_query(self) -> str:
        return '&'.join(m.appended_query for m in self.modifiers)


class Modifier(BaseModifier):
    """
    Enables the input of query modifiers in a fully manual fashion.
    """
    def __init__(self, query_str: str) -> None:
        """
        :param query_str: Query string. Value is passed to backend as is.
        """
        self._query_str = query_str

    @property
    def appended_query(self) -> str:
        return self._query_str


class Filter(BaseModifier):
    """
    Implements query filtering as per https://jsonapi.org/format/1.0/#fetching-filtering

    Filtering scheme follows JSON API recommendations
    (https://jsonapi.org/recommendations/#filtering)

    You can derive your own modifier from this class if your use case requires
    separate named parameters.
    In your subclass overwrite `modifier_keyword` and you are good to go.
    """
    modifier_keyword = 'filter'

    def __init__(self, query_str: str = '', **kwargs: 'NamedParameters') -> None:
        """
        :param query_str: Manually specified modifier. Value may be passed as
            is if not merged with the named parameters. If the same named
            parameter is specified multiple times, the latest occurrence is
            taken into account, all previous ones are ignored.
            Example: Filter('filter[attr1]=1,2&filter[attr2]=1,filter[rel1.attr1]=2')
        :param kwargs: Filters via named parameters. Values will be added to
            the ones from query_str. If the same named parameter appears
            multiple times in the kwargs, the latest occurrence is taken into
            account, all previous ones are ignored. However, if a named
            parameter appeared via `query_str` already, the values passed via
            this attribute are added to the already known ones via comma.
            Example: Filter(attr1=[1, 2], attr2=1, rel1__attr1='2')
        """
        self._parameters = {}
        # split the parameters received via query_str
        for param in query_str.split('&'):
            if param:
                k, v = param.split('=', maxsplit=1)
                # latest occurrence of a key takes precedence
                self._parameters[k] = v

        # flatten down the parameters received via kwargs and add them to the
        # already parsed ones
        for k, v in kwargs.items():
            value = ','.join([str(i) for i in v]) if isinstance(v, list) else str(v)
            key = f'{self.modifier_keyword}[{jsonify_name(k)}]'
            v_old = self._parameters.get(key)
            # if a key already exists, combine values with comma
            self._parameters[key] = f'{v_old},{value}' if v_old else value

    @property
    def appended_query(self) -> str:
        flattened = [f'{k}={v}' for k, v in self._parameters.items()]
        return '&'.join(flattened)


class Include(BaseModifier):
    """
    Implements related resource inclusion as per https://jsonapi.org/format/1.0/#fetching-includes

    You can derive your own modifier from this class if your use case is to
    pass all modifier values as comma separated list.
    In your subclass overwrite `modifier_keyword` and you are good to go.
    """
    modifier_keyword = 'include'

    def __init__(self, *args: 'ValueParameters') -> None:
        """
        :param args: Include list as value parameters.
            Example: Include('relation1', 'relation1.relation3')
        """
        self._values: 'ValueParameters' = args

    @property
    def appended_query(self) -> str:
        valueslist = ','.join(self._values)
        return f'{self.modifier_keyword}={valueslist}'


class SparseFieldset(Filter):
    """
    Implements requesting limited fields per resource type as per  https://jsonapi.org/format/1.0/#fetching-sparse-fieldsets
    """
    modifier_keyword = 'fields'


class Sort(Include):
    """
    Implements resource collection sorting as per https://jsonapi.org/format/1.0/#fetching-sorting
    """
    modifier_keyword = 'sort'
