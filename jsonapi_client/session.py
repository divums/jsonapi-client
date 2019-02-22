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

import collections
import logging
from itertools import chain
from typing import TYPE_CHECKING, Set, Optional, Tuple, Dict, Union, Awaitable, AsyncIterator, Iterator, List
from urllib.parse import ParseResult, urlparse
import jsonschema

from .document import Document
from .modifiers import BaseModifier
from .resourceobject import ResourceObject
from .relationships import ResourceTuple
from .objects import ResourceIdentifier
from .exceptions import AsyncError
from .utils import jsonify_name

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop


logger = logging.getLogger(__name__)


class Schema:
    """
    Container for model schemas with associated methods.
    Session contains Schema.
    """

    def __init__(self, schema_data: dict=None) -> None:
        self._schema_data = schema_data

    def find_spec(self, model_name: str, attribute_name: str) -> dict:
        """
        Find specification from model_name for attribute_name which can
        be nested format, i.e. 'attribute-group1.attribute-group2.attribute-item'
        """

        # We need to support meta, which can contain whatever schemaless metadata
        if attribute_name == 'meta' or (attribute_name and attribute_name.endswith('.meta')):
            return {}

        model = self.schema_for_model(model_name)
        if not model:
            return {}
        if not attribute_name:
            return model
        attr_struct = attribute_name.split('.')
        for a in attr_struct:
            model = model['properties'].get(a)
            if model is None:
                return {}
        return model

    def add_model_schema(self, data: dict) -> None:
        self._schema_data.update(data)

    @property
    def is_enabled(self):
        return bool(self._schema_data)

    def schema_for_model(self, model_type: str) -> dict:
        return self._schema_data.get(model_type) if self.is_enabled else {}

    def validate(self, model_type: str, data: dict) -> None:
        """
        Validate model data against schema.
        """
        schema = self.schema_for_model(model_type)
        if not schema:
            return
        jsonschema.validate(data, schema)


class Session:
    """
    Resources are fetched and cached in a session.

    :param server_url: Server base url
    :param is_async: Toggle AsyncIO mode for session
    :param schema: Schema in jsonschema format. See example from :ref:`usage-schema`.
    :param request_kwargs: Additional keyword arguments that are passed to requests.request or
        aiohttp.request functions (such as authentication object)
    """
    def __init__(self,
                 server_url: str=None,
                 is_async: bool=False,
                 schema: dict=None,
                 request_kwargs: dict=None,
                 loop: 'AbstractEventLoop'=None,
                 use_relationship_iterator=False) \
            -> None:
        self.resources_by_resource_identifier: 'Dict[Tuple[str, str], ResourceObject]' = {}
        self.resources_by_link: 'Dict[str, ResourceObject]' = {}
        self.documents_by_link: 'Dict[str, Document]' = {}
        self.schema: Schema = Schema(schema)
        self.use_relationship_iterator = use_relationship_iterator

        self._server: ParseResult = urlparse(server_url) if server_url else None
        self._is_async = is_async

        from .sessionhelpers import AsyncModeHelper, SyncModeHelper
        if is_async:
            self._handler = AsyncModeHelper(self, request_kwargs, loop)
        else:
            self._handler = SyncModeHelper(self, request_kwargs)

    @property
    def is_async(self):
        return self._is_async

    def add_resources(self, *resources: 'ResourceObject') -> None:
        """
        Add resources to session cache.
        """
        for res in resources:
            self.resources_by_resource_identifier[(res.type, res.id)] = res
            lnk = res.links.self.url if res.links.self else res.url
            if lnk:
                self.resources_by_link[lnk] = res

    def remove_resource(self, res: 'ResourceObject') -> None:
        """
        Remove resource from session cache.

        :param res: Resource to be removed
        """
        del self.resources_by_resource_identifier[(res.type, res.id)]
        del self.resources_by_link[res.url]

    @staticmethod
    def _value_to_dict(value: 'Union[ResourceObject, ResourceIdentifier, ResourceTuple]',
                       resource_types: 'List[str]') \
            -> Dict[str, str]:
        res_type = resource_types[0] if len(resource_types) == 1 else None

        if isinstance(value, (ResourceObject, ResourceIdentifier, ResourceTuple)):
            if res_type and value.type != res_type:
                raise TypeError(f'Invalid resource type {value.type}. '
                                f'Should be {res_type}')
            elif resource_types and value.type not in resource_types:
                raise TypeError(f'Invalid resource type {value.type}. '
                                f'Should be one of {resource_types}')
            return {'id': value.id, 'type': value.type}
        else:
            if not res_type:
                raise ValueError('Use ResourceTuple to identify types '
                                 'if there are more than 1 type')
            return {'id': value, 'type': resource_types[0]}

    def create(self, resource_type: str, fields: dict=None, **more_fields) -> 'ResourceObject':
        """
        Create a new ResourceObject of resource_type. This requires schema to
        be defined.

        If you have field names that have underscores, you can pass those
        fields in fields dictionary.

        """
        if fields is None:
            fields = {}

        attrs: dict = {}
        rels: dict = {}
        schema = self.schema.schema_for_model(resource_type)
        more_fields.update(fields)

        for key, value in more_fields.items():
            if key not in fields:
                key = jsonify_name(key)
            props = schema['properties'].get(key, {})
            if 'relation' in props:
                res_types = props['resource']
                if isinstance(value, (ResourceObject, ResourceIdentifier, ResourceTuple, str)):
                    value = self._value_to_dict(value, res_types)
                elif isinstance(value, collections.Iterable):
                    value = [self._value_to_dict(id_, res_types) for id_ in value]
                rels[key] = {'data': value}
            else:
                key = key.split('.')
                a = attrs
                for k in key[:-1]:
                    a_ = a[k] = a.get(k, {})
                    a = a_

                a[key[-1]] = value

        data = {'type': resource_type,
                'id': None,
                'attributes': attrs,
                'relationships': rels,
                }

        res = ResourceObject(self, data)
        return res

    def create_and_commit(self,
                          resource_type: str,
                          fields: dict=None,
                          **more_fields) \
            -> 'Union[Awaitable[ResourceObject], ResourceObject]':
        """
        Create resource and commit (PUSH) it into server.
        This must be awaited in async mode.
        """
        return self._handler.create_and_commit(resource_type, fields, **more_fields)

    def __enter__(self):
        logger.info('Entering session')
        return self

    async def __aenter__(self):
        logger.info('Entering session')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        logger.info('Exiting session')
        if not exc_type:
            self.commit()
        self.close()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        logger.info('Exiting session')
        if not exc_type:
            await self.commit()
        self.close()

    def close(self) -> None:
        """
        Close session and invalidate resources.
        This must be awaited in async mode.
        """
        self._handler.close()
        self.invalidate()

    def invalidate(self) -> None:
        """
        Invalidate resources and documents associated with this Session.
        """
        for resource in chain(self.documents_by_link.values(),
                              self.resources_by_link.values(),
                              self.resources_by_resource_identifier.values()):
            resource.mark_invalid()

        self.documents_by_link.clear()
        self.resources_by_link.clear()
        self.resources_by_resource_identifier.clear()

    @property
    def server_url(self) -> str:
        return f'{self._server.scheme}://{self._server.netloc}'

    @property
    def url_prefix(self) -> str:
        return self._server.geturl().rstrip('/')

    def _url_for_resource(self,
                          resource_type: str,
                          resource_id: str=None,
                          filter: 'BaseModifier'=None) -> str:
        url = f'{self.url_prefix}/{resource_type}'
        if resource_id is not None:
            url = f'{url}/{resource_id}'
        if filter:
            url = filter.url_with_modifiers(url)
        return url

    @staticmethod
    def _resource_type_and_filter(resource_id_or_filter: 'Union[BaseModifier, str]'=None) \
            -> 'Tuple[Optional[str], Optional[BaseModifier]]':
        if isinstance(resource_id_or_filter, BaseModifier):
            resource_id = None
            filter = resource_id_or_filter
        else:
            resource_id = resource_id_or_filter
            filter = None
        return resource_id, filter

    def get(self,
            resource_type: str,
            resource_id_or_filter: 'Union[BaseModifier, str]'=None) \
            -> 'Union[Awaitable[Document], Document]':
        """
        Request (GET) Document from server.

        :param resource_type: Name of resource type.
        :param resource_id_or_filter: Resource id or BaseModifier instance to filter resulting resources.

        This must be awaited in async mode.
        """
        return self._handler.get(resource_type, resource_id_or_filter)

    def iterate(self, resource_type: str, filter: 'BaseModifier'=None) \
            -> 'Union[AsyncIterator[ResourceObject], Iterator[ResourceObject]]':
        """
        Request (GET) Document from server and iterate through resources.
        If Document uses pagination, fetch results as long as there are new
        results.

        This must be iterated through with async for when in async mode.

        :param filter: BaseModifier instance to filter resulting resources.
        """
        return self._handler.iterate(resource_type, filter)

    def read(self, json_data: dict, url='', no_cache=False)-> 'Document':
        """
        Read document from json_data dictionary instead of fetching it from the server.

        :param json_data: JSON API document as dictionary.
        :param url: Set source url to resulting document.
        :param no_cache: do not store results into Session's cache.
        """
        doc = self.documents_by_link[url] = Document(self, json_data, url,
                                                     no_cache=no_cache)
        return doc

    def _fetch_resource_by_resource_identifier(
                self,
                resource: 'Union[ResourceIdentifier, ResourceObject, ResourceTuple]',
                cache_only=False,
                force=False) \
            -> 'Optional[ResourceObject]':
        """
        Internal use.

        Fetch resource from server by resource identifier.
        """
        return self._handler.fetch_resource_by_resource_identifier(resource, cache_only, force)

    def _fetch_document_by_url(self, url: str) -> 'Document':
        """
        Internal use.

        Fetch Document from server by url.
        """
        # TODO: should we try to guess type, id from url?
        return self._handler.fetch_document_by_url(url)


    def _http_request(self, http_method: str, url: str, send_json: dict) -> Tuple[int, dict, str]:
        """
        Internal use.

        Method to make PATCH/POST requests to server using requests library.
        """
        return self._handler.http_request(http_method, url, send_json)

    @property
    def dirty_resources(self) -> 'Set[ResourceObject]':
        """
        Set of all resources in Session cache that are marked as dirty,
        i.e. waiting for commit.
        """
        return {i for i in self.resources_by_resource_identifier.values() if i.is_dirty}

    @property
    def is_dirty(self) -> bool:
        return bool(self.dirty_resources)

    def commit(self) -> Optional[Awaitable]:
        """
        Commit (PATCH) all dirty resources to server.

        If session is used with is_async=True, this needs to be awaited.
        """
        return self._handler.commit()

    def _assert_sync(self, msg=None):
        """
        Internal method to assert that async is not enabled.
        """
        msg = msg or 'In synchronous mode, resources shall be fetched manually'
        if self.is_async:
            logger.error(msg)
            raise AsyncError(msg)

    def _assert_async(self, msg=None):
        """
        Internal method to assert that async is enabled.
        """
        msg = msg or 'Call this method only in asynchronous mode'
        if not self.is_async:
            logger.error(msg)
            raise AsyncError(msg)
