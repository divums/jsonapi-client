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

import logging
from typing import Union, TYPE_CHECKING, NamedTuple
from .utils import jsonify_name

if TYPE_CHECKING:
    from .session import Session

logger = logging.getLogger(__name__)


class RelationType:
    TO_ONE = 'to-one'
    TO_MANY = 'to-many'


class AbstractJsonObject:
    """
    Base for all JSON API specific objects
    """
    def __init__(self, session: 'Session', data: Union[dict, list]) -> None:
        self._invalid = False
        self._session = session
        self._handle_data(data)

    @property
    def session(self):
        return self._session

    def _handle_data(self, data: Union[dict, list]) -> None:
        """
        Store data
        """
        raise NotImplementedError

    def __repr__(self):
        return f'<{self.__class__.__name__}: {str(self)} ({id(self)})>'

    def __str__(self):
        raise NotImplementedError

    @property
    def url(self) -> str:
        raise NotImplementedError

    def mark_invalid(self):
        self._invalid = True


class AttributeProxy:
    """
    Attribute proxy used in ResourceObject.fields etc.
    """
    def __init__(self, target_object=None):
        self._target_object = target_object

    def __getitem__(self, item):
        return self._target_object[item]

    def __setitem__(self, key, value):
        self._target_object[key] = value

    def __getattr__(self, item):
        try:
            return self[jsonify_name(item)]
        except KeyError:
            raise AttributeError

    def __setattr__(self, key, value):
        if key == '_target_object':
            return super().__setattr__(key, value)
        try:
            self[jsonify_name(key)] = value
        except KeyError:
            raise AttributeError


class ResourceTuple(NamedTuple):
    id: str
    type: str

