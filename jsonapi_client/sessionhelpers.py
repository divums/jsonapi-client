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

import aiohttp
import requests
import json
import logging
from urllib.parse import urlparse
from typing import TYPE_CHECKING, Optional, Tuple, Union, AsyncIterator, Iterator

from .document import Document
from .modifiers import BaseModifier
from .resourceobject import ResourceObject
from .relationships import ResourceTuple
from .objects import ResourceIdentifier
from .http import error_from_response, HTTPStatus, HTTPMethod, HTTP_HEADER_FIELDS, is_success
from .exceptions import DocumentError

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop
    from .session import Session


logger = logging.getLogger(__name__)


class SyncModeHelper:

    def __init__(
            self,
            session: 'Session',
            request_kwargs: dict=None) \
            -> None:
        self.session = session
        self.request_kwargs = request_kwargs or {}

    def create_and_commit(
            self,
            resource_type: str,
            fields: dict=None,
            **more_fields) \
            -> 'ResourceObject':
        res = self.session.create(resource_type, fields, **more_fields)
        res.commit()
        return res

    def commit(self) -> None:
        logger.info('Committing dirty resources')
        for res in self.session.dirty_resources:
            res.commit()

    def close(self) -> None:
        """
        Close session.
        """
        pass

    def get(self,
            resource_type: str,
            resource_id_or_filter: 'Union[BaseModifier, str]'=None) \
            -> 'Document':
        resource_id, filter_ = self.session._resource_type_and_filter(resource_id_or_filter)
        url = self.session._url_for_resource(resource_type, resource_id, filter_)
        return self.fetch_document_by_url(url)

    def iterate(
            self,
            resource_type: str,
            filter: 'BaseModifier'=None) \
            -> 'Iterator[ResourceObject]':
        doc = self.get(resource_type, filter)
        yield from doc._iterator_sync()

    def fetch_resource_by_resource_identifier(
            self,
            resource: 'Union[ResourceIdentifier, ResourceObject, ResourceTuple]',
            cache_only=False,
            force=False) \
            -> 'Optional[ResourceObject]':
        """
        Fetch resource from server by resource identifier.
        """
        type_, id_ = resource.type, resource.id
        new_res = not force and self.session.resources_by_resource_identifier.get((type_, id_))
        if new_res:
            return new_res
        elif cache_only:
            return None
        else:
            # Note: Document creation will add its resources to cache via .add_resources,
            # no need to do it manually here
            url = resource.url
            return self.session.read(self.fetch_json(url), url).resource

    def fetch_document_by_url(
            self,
            url: str) \
            -> 'Document':
        """
        Fetch Document from server by url.
        """
        # TODO: should we try to guess type, id from url?
        return (self.session.documents_by_link.get(url) or
                self.session.read(self.fetch_json(url), url))

    def fetch_json(
            self,
            url: str) \
            -> dict:
        """
        Fetch document raw json from server using requests library.
        """
        parsed_url = urlparse(url)
        logger.info('Fetching document from url %s', parsed_url)
        response = requests.get(parsed_url.geturl(), **self.request_kwargs)
        if response.status_code == HTTPStatus.OK:
            return response.json()
        else:

            raise DocumentError(f'Error {response.status_code}: '
                                f'{error_from_response(response)}',
                                errors={'status_code': response.status_code},
                                response=response)

    def http_request(
            self,
            http_method: str,
            url: str,
            send_json: dict) \
            -> Tuple[int, dict, str]:
        """
        Method to make PATCH/POST requests to server using requests library.
        """
        logger.debug('%s request: %s', http_method.upper(), send_json)
        response = requests.request(http_method,
                                    url,
                                    json=send_json,
                                    headers=HTTP_HEADER_FIELDS,
                                    **self.request_kwargs)

        if not is_success(response.status_code):  # TODO: handle HTTP 3xx
            raise DocumentError(f'Could not {http_method.upper()} '
                                f'({response.status_code}): '
                                f'{error_from_response(response)}',
                                errors={'status_code': response.status_code},
                                response=response,
                                json_data=send_json)

        return (
            response.status_code,
            response.json() if response.content else {},
            response.headers.get('Location')
        )


class AsyncModeHelper:

    def __init__(
            self,
            session: 'Session',
            request_kwargs: dict=None,
            loop: 'AbstractEventLoop' = None) \
            -> None:
        self.session = session
        self.request_kwargs = request_kwargs or {}
        self.session = session
        self.aiohttp_session = aiohttp.ClientSession(loop=loop)

    async def create_and_commit(
            self,
            resource_type: str,
            fields: dict=None,
            **more_fields) \
            -> 'ResourceObject':
        res = self.session.create(resource_type, fields, **more_fields)
        await res.commit()
        return res

    async def commit(self) -> None:
        logger.info('Committing dirty resources')
        for res in self.session.dirty_resources:
            await res._commit_async()

    async def close(self) -> None:
        """
        Close session.
        """
        await self.aiohttp_session.close()

    async def get(
            self,
            resource_type: str,
            resource_id_or_filter: 'Union[BaseModifier, str]'=None) \
            -> 'Document':
        resource_id, filter_ = self.session._resource_type_and_filter(resource_id_or_filter)
        url = self.session._url_for_resource(resource_type, resource_id, filter_)
        return await self.fetch_document_by_url(url)

    async def iterate(
            self,
            resource_type: str,
            filter: 'BaseModifier'=None) \
            -> 'AsyncIterator[ResourceObject]':
        doc = await self.get(resource_type, filter)
        async for res in doc._iterator_async():
            yield res

    async def fetch_resource_by_resource_identifier(
            self,
            resource: 'Union[ResourceIdentifier, ResourceObject, ResourceTuple]',
            cache_only=False,
            force=False) \
            -> 'Optional[ResourceObject]':
        type_, id_ = resource.type, resource.id
        new_res = not force and self.session.resources_by_resource_identifier.get((type_, id_))
        if new_res:
            return new_res
        elif cache_only:
            return None
        else:
            # Note: Document creation will add its resources to cache via .add_resources,
            # no need to do it manually here
            url = resource.url
            doc = self.session.read(await self.fetch_json(url), url)
            return doc.resource

    async def fetch_document_by_url(
            self,
            url: str) \
            -> 'Document':
        """
        Fetch Document from server by url.
        """
        # TODO: should we try to guess type, id from url?
        return self.session.documents_by_link.get(url) or self.session.read(await self.fetch_json(url), url)

    async def fetch_json(
            self,
            url: str) \
            -> dict:
        """
        Fetch document raw json from server using requests library.
        """
        parsed_url = urlparse(url)
        logger.info('Fetching document from url %s', parsed_url)
        async with self.aiohttp_session.get(parsed_url.geturl(),
                                            **self.request_kwargs) as response:
            if response.status == HTTPStatus.OK:
                return await response.json(content_type=HTTP_HEADER_FIELDS['Content-Type'])
            else:
                raise DocumentError(f'Error {response.status}: '
                                    f'{error_from_response(response)}',
                                    errors={'status_code': response.status},
                                    response=response)

    async def http_request(
            self,
            http_method: str,
            url: str,
            send_json: dict) \
            -> Tuple[int, dict, str]:
        """
        Method to make PATCH/POST requests to server using requests library.
        """
        logger.debug('%s request: %s', http_method.upper(), send_json)
        content_type = '' if http_method == HTTPMethod.DELETE else HTTP_HEADER_FIELDS['Content-Type']
        async with self.aiohttp_session.request(
                http_method, url, data=json.dumps(send_json),
                headers=HTTP_HEADER_FIELDS,
                **self.request_kwargs) as response:

            if not is_success(response.status):  # TODO: handle HTTP 3xx
                raise DocumentError(f'Could not {http_method.upper()} '
                                    f'({response.status}): '
                                    f'{error_from_response(response)}',
                                    errors={'status_code': response.status},
                                    response=response,
                                    json_data=send_json)

            response_json = await response.json(content_type=content_type)
            return response.status, response_json or {}, response.headers.get('Location')
