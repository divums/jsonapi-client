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
from itertools import chain
from typing import Set, Optional, Awaitable, Union, Iterable, TYPE_CHECKING, Any, Dict

from .objects import AbstractJsonApiObject, ResourceIdentifier, ResourceTuple
from .relationships import RelationType
from .exceptions import ValidationError, DocumentInvalid
from .http import HttpMethod, HttpStatus
from .utils import pythonify_names, jsonify_name, cached_property

if TYPE_CHECKING:
    from .session import Schema, Session

logger = logging.getLogger(__name__)


class FieldProxy:
    """
    Field proxy used in ResourceObject.fields etc.
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


class AttributeDict(dict):
    """
    Container for JSON API attributes in ResourceObjects.

    In addition to features of standard dictionary, this offers:
    - access to attributes via getattr
      (NOTE: attribute names are jsonified, i.e. my_attr -> my-attr)
    - dirty-flagging attributes upon change (it keeps track of changes)
    - enables generating diff containing only changed data (useful for PATCH)
    """

    def __init__(self,
                 data: dict,
                 resource: 'ResourceObject',
                 name: str ='',
                 parent: 'AttributeDict'=None) \
            -> None:
        """
        :param data: Input data that is stored here.
        :param resource: Root ResourceObject
        :param name: Name of this attribute, if this is contained within another
            AttributeDict. Otherwise, None.
        :param parent: Parent AttributeDict if this is contained within another
            AttributeDict. Otherwise, None.
        """
        super().__init__()
        self._parent = parent
        self._name = name
        self._resource = resource
        self._schema: 'Schema' = resource.session.schema
        self._full_name: str = name
        self._invalid = False
        self._dirty_attributes: Set[str] = set()

        if self._parent is not None and self._parent._full_name:
            self._full_name = f'{parent._full_name}.{name}'

        specification = self._schema.find_spec(self._resource.type, self._full_name)

        # If there's schema for this object, we will use it to construct object.
        if specification:
            for field_name, field_spec in specification['properties'].items():
                if field_spec.get('type') == 'object':
                    field_data = data.pop(field_name, {})
                    self[field_name] = AttributeDict(data=field_data,
                                                     name=field_name,
                                                     parent=self,
                                                     resource=resource)
                elif 'relation' in field_spec:
                    pass  # Special handling for relationships
                else:
                    self[field_name] = data.pop(field_name, field_spec.get('default'))

            if data:
                logger.warning('There was extra data (not specified in schema): %s',
                               data)
        # If not, we will use the source data as it is.
        self.update(data)
        for key, value in data.items():
            if isinstance(value, dict):
                self[key] = AttributeDict(data=value, name=key, parent=self, resource=resource)
        self._dirty_attributes.clear()

    def create_map(self, attr_name: str) -> None:
        """
        Create a new map of values (i.e. child AttributeDict) within this AttributeDict

        :param attr_name: Name of this map object.
        """
        self._check_invalid()
        name = jsonify_name(attr_name)
        self[name] = AttributeDict(data={}, name=name, parent=self, resource=self._resource)

    def _check_invalid(self) -> None:
        if self._invalid:
            raise DocumentInvalid('Resource has been invalidated.')

    def __getattr__(self, name: str) -> Any:
        name = jsonify_name(name)
        if name not in self:
            raise AttributeError(f'No such attribute '
                                 f'{self._resource.type}.{self._full_name}.{name}')
        return self[name]

    def __setitem__(self, key: str, value: Any) -> None:
        if self.get(key) != value:
            self.mark_dirty(key)
        super().__setitem__(key, value)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith('_'):
            return super().__setattr__(name, value)
        name = jsonify_name(name)
        self[name] = value

    def mark_dirty(self, name: str) -> None:
        """
        Mark one attribute within this dictionary as dirty.

        :param name: Name of the attribute that is to be marked as dirty.
        """
        self._dirty_attributes.add(name)
        if self._parent:
            self._parent.mark_dirty(self._name)

    def mark_clean(self) -> None:
        """
        Mark all attributes recursively as clean..
        """
        for attr in self._dirty_attributes:
            value = self[attr]
            if isinstance(value, AttributeDict):
                value.mark_clean()
        self._dirty_attributes.clear()

    @property
    def diff(self) -> dict:
        """
        Produce JSON containing only changed elements based on dirty fields.
        """
        self._check_invalid()
        diff = {}
        for name in self._dirty_attributes:
            value = self[name]
            if isinstance(value, AttributeDict) and value.is_dirty:
                diff[name] = value.diff
            else:
                diff[name] = value
        return diff

    @property
    def post_data(self) -> dict:
        """
        Produce JSON which does not contain values which are null.
        """
        self._check_invalid()
        result = self.copy()
        for key, value in self.items():
            if isinstance(value, AttributeDict):
                result[key] = new_value = value.post_data
                if len(new_value) == 0:
                    del result[key]

            if value is None:
                del result[key]
        return result

    @property
    def is_dirty(self) -> bool:
        return bool(self._dirty_attributes)

    def mark_invalid(self) -> None:
        """
        Recursively mark this and contained objects as invalid.
        """
        self._invalid = True
        for value in self.values():
            if isinstance(value, AttributeDict):
                value.mark_invalid()

    def change_resource(self, new_resource: 'ResourceObject') -> None:
        """
        Change parent ResourceObject recursively
        :param new_resource: new resource that is used as a new root ResourceObject
        """
        self._resource = new_resource
        for value in self.values():
            if isinstance(value, AttributeDict):
                value.change_resource(new_resource)

    def keys_python(self) -> Iterable[str]:
        """
        Pythonized version of contained keys (attribute names).
        """
        yield from pythonify_names(self.keys())


class RelationshipDict(dict):
    """
    Container for relationships that is stored in ResourceObject
    """

    def __init__(self, data: dict, resource: 'ResourceObject') -> None:
        """
        :param data: Raw input data where Relationship objects are built from.
        :param resource: Parent ResourceObject
        """
        super().__init__()
        self._invalid = False
        self._resource = resource
        self.session = resource.session
        self._schema = schema = resource.session.schema
        model_schema = schema.schema_for_model(resource.type)
        if model_schema:
            for rel_name, rel_value in model_schema['properties'].items():
                rel_type = rel_value.get('relation')
                if not rel_type:
                    continue

                resource_types = rel_value['resource']
                self[rel_name] = self._make_relationship(data.pop(rel_name, {}), rel_type,
                                                         resource_types)
        else:
            relationships = {key: self._make_relationship(value)
                             for key, value in data.items()}
            self.update(relationships)

    def mark_invalid(self) -> None:
        """
        Mark invalid this dictionary and contained Relationships.
        """
        self._invalid = True
        for value in self.values():
            value.mark_invalid()

    def change_resource(self, new_resource: 'ResourceObject') -> None:
        """
        :param new_resource: Change parent ResourceObject to new_resource.
        """
        self._resource = new_resource

    @staticmethod
    def _determine_class(data: dict, relation_type: str=None):
        """
        From data and/or provided relation_type, determine Relationship class
        to be used.

        :param data: Source data dictionary
        :param relation_type: either 'to-one' or 'to-many'
        """
        from . import relationships as rel
        if 'data' in data:
            relationship_data = data['data']
            if isinstance(relationship_data, list):
                if relation_type and relation_type != RelationType.TO_MANY:
                    logger.error('Conflicting information about relationship')
                return rel.ToManyRelationship
            elif relationship_data is None or isinstance(relationship_data, dict):
                if relation_type and relation_type != RelationType.TO_ONE:
                    logger.error('Conflicting information about relationship')
                return rel.ToOneRelationship
            else:
                raise ValidationError('Relationship data key is invalid')
        elif 'links' in data:
            return rel.LinkRelationship
        elif 'meta' in data:
            return rel.MetaRelationship
        elif relation_type == RelationType.TO_MANY:
            return rel.ToManyRelationship
        elif relation_type == RelationType.TO_ONE:
            return rel.ToOneRelationship
        else:
            raise ValidationError('Must have either links, data or meta in relationship')

    def _make_relationship(self, data, relation_type=None, resource_types=None):
        cls = self._determine_class(data, relation_type)
        return cls(self.session, data, resource_types=resource_types,
                   relation_type=relation_type)

    def mark_clean(self) -> None:
        """
        Mark all relationships as clean (not dirty).
        """
        for attr in self.values():
            attr.mark_clean()

    def keys_python(self) -> Iterable[str]:
        """
        Pythonized version of contained keys (relationship names)
        """
        yield from pythonify_names(self.keys())

    @property
    def is_dirty(self) -> bool:
        return any(r.is_dirty for r in self.values())


class ResourceObject(AbstractJsonApiObject):
    """
    Basic JSON API resourceobject type. Field (attribute and relationship) access directly
    via instance attributes (__getattr__). In case of namespace collisions, there is also
    .fields attribute proxy.

    https://jsonapi.org/format/1.0/#document-resource-objects
    """

    #: Attributes (that are not starting with _) that we want to ignore in __setattr__
    __attributes = ['id', 'type', 'links', 'meta', 'commit_meta']

    def __init__(self, session: 'Session', data: Union[dict, list]) -> None:
        self._delete = False
        self._commit_metadata = {}
        super().__init__(session, data)

    @cached_property
    def fields(self) -> 'FieldProxy':
        """
        Proxy to all fields (both attributes and relationship target resources)
        """
        class Proxy(FieldProxy):
            def __getitem__(proxy, item):
                NOT_FOUND = object()
                rv = self._attributes.get(item, NOT_FOUND)
                if rv is NOT_FOUND:
                    return self.relationship_resource[item]
                else:
                    return rv

            def __setitem__(proxy, item, value):
                if item in self._relationships:
                    return self._relationships[item].set(value)
                else:
                    self._attributes[item] = value

            def __dir__(proxy):
                return chain(super().__dir__(),
                             self._attributes.keys_python(),
                             self._relationships.keys_python())

        return Proxy()

    @cached_property
    def attributes(self) -> 'FieldProxy':
        """
        Proxy to all attributes (not relationships)
        """
        return FieldProxy(self._attributes)

    @cached_property
    def relationships(self) -> 'FieldProxy':
        """
        Proxy to relationship objects
        """
        class Proxy(FieldProxy):
            def __setitem__(proxy, key, value):
                rel = self._relationships[key]
                rel.set(value)

        return Proxy(self._relationships)

    @cached_property
    def relationship_resource(self) -> 'FieldProxy':
        """
        If async enabled, proxy to relationship objects.
        If async disabled, proxy to resources behind relationships.
        """
        class Proxy(FieldProxy):
            def __getitem__(proxy, item):
                rel = self.relationships[item]
                if self.session.enable_async:
                    # With async it's more convenient to access Relationship object
                    return self.relationships[item]

                if rel.is_single:
                    return rel.resource
                else:
                    return rel.resources

        return Proxy()

    def _handle_data(self, data: dict) -> None:
        from .objects import Links, Meta
        self.id = data['id']
        self.type = data['type']
        self.links = Links(self.session, data.get('links', {}))
        self.meta = Meta(self.session, data.get('meta', {}))

        self._attributes = (
            # TODO: handle if no attributes
            AttributeDict(data=data.get('attributes', {}), resource=self)
        )
        self._relationships = (
            RelationshipDict(data=data.get('relationships', {}), resource=self)
        )

        if self.id:
            self.validate()

    def create_map(self, name: str) -> None:
        """
        Create a map of values (AttributeDict) with name in attribute container.
        """
        return self._attributes.create_map(name)

    def __dir__(self):
        return chain(super().__dir__(), self._attributes.keys_python(),
                     self._relationships.keys_python())

    def __str__(self) -> str:
        return f'{self.type}: {self.id} ({id(self)})'

    @property
    def json(self) -> dict:
        """
        Return full JSON API resource object as json-serializable dictionary.
        """
        return self._commit_data(full=True)['data']

    @property
    def is_dirty(self) -> bool:
        return (self.id is None
                or self._delete
                or self._attributes.is_dirty
                or self._relationships.is_dirty)

    def __getitem__(self, item: str) -> Any:
        return self.fields[item]

    def __setitem__(self, item: str, value: Any) -> None:
        self.fields[item] = value

    def __getattr__(self, attr_name: str) -> Any:
        return getattr(self.fields, attr_name)

    def __setattr__(self, attr_name: str, value: Any) -> None:
        if attr_name.startswith('_') or attr_name in self.__attributes:
            return super().__setattr__(attr_name, value)

        return setattr(self.fields, attr_name, value)

    @property
    def dirty_fields(self) -> Set[str]:
        return (self._attributes._dirty_attributes |
                {name for name, rel in self._relationships.items() if rel.is_dirty})

    @property
    def url(self) -> str:
        url = str(self.links.self)
        return url or self.id and f'{self.session.url_prefix}/{self.type}/{self.id}'

    @property
    def post_url(self) -> str:
        return f'{self.session.url_prefix}/{self.type}'

    def validate(self) -> None:
        """
        Validate our attributes against schema.
        """
        # TODO: what about relationships? Shouldn't we somehow validate those too?
        self.session.schema.validate(self.type, self._attributes)

    def _commit_data(self, meta: dict = None, full: bool=False) -> dict:
        """
        Give JSON data for PATCH/POST request, requested by commit
        """
        meta = meta or self._commit_metadata

        res_json = {'type': self.type}
        if self.id:
            res_json['id'] = self.id

        if self._http_method == HttpMethod.POST or full:
            # When creating new resources, we need to define all relationships
            # as either to-one or to-many.
            relationships = {key: {'data': value.as_json_resource_identifiers}
                             for key, value in self._relationships.items() if bool(value)}
            res_json.update({
                    'attributes': self._attributes.post_data,
                    'relationships': relationships,
            })
        else:
            changed_relationships = {key: {'data': value.as_json_resource_identifiers}
                                     for key, value in self._relationships.items()
                                     if value.is_dirty}
            res_json.update({
                  'attributes': self._attributes.diff,
                  'relationships': changed_relationships,
            })
        if meta:
            res_json['meta'] = meta
        return {'data': res_json}

    @property
    def _http_method(self) -> str:
        return HttpMethod.PATCH if self.id else HttpMethod.POST

    def _pre_commit(self, url):
        url = url or self.post_url if self._http_method == HttpMethod.POST else self.url
        logger.info('Committing %s to %s', self, url)
        self.validate()
        return url

    def _post_commit(self, status, result, location):
        if HttpStatus.has_resource(status):
            self._update_resource(result, location)

        # If no resources are returned (which is the case when HTTP 202 Accepted
        # is received for PATCH, for example).
        self.mark_clean()

        if status == HttpStatus.HTTP_202_ACCEPTED:
            return self.session.read(result, location, no_cache=True).resource

    async def _commit_async(self, url: str= '', meta=None) -> None:
        self.session.assert_async()
        if self._delete:
            return await self._perform_delete_async(url)

        url = self._pre_commit(url)
        status, result, location = await self.session.http_request_async(
                                                self._http_method, url,
                                                self._commit_data(meta))
        return self._post_commit(status, result, location)

    def _commit_sync(self, url: str= '', meta: dict=None) -> 'None':
        self.session.assert_sync()
        if self._delete:
            return self._perform_delete(url)

        url = self._pre_commit(url)
        status, result, location = self.session.http_request(self._http_method, url,
                                                             self._commit_data(meta))
        return self._post_commit(status, result, location)

    def commit(self, custom_url: str = '', meta: dict = None) \
            -> 'Union[None, ResourceObject, Awaitable[Optional[ResourceObject]]':
        """
        Commit (PATCH/POST) this resource to server.

        :param custom_url: Use this url instead of automatically determined one.
        :param meta: Optional metadata that is passed to server in POST/PATCH request

        If in async mode, this needs to be awaited.
        """
        if self.session.enable_async:
            return self._commit_async(custom_url, meta)
        else:
            return self._commit_sync(custom_url, meta)

    def _update_resource(self,
                         resource_dict: 'Union[dict, ResourceObject]',
                         location: str=None) -> None:
        if isinstance(resource_dict, dict):
            new_res = self.session.read(resource_dict, location, no_cache=True).resource
        else:
            new_res = resource_dict
        self.id = new_res.id
        self._attributes.mark_invalid()
        self._relationships.mark_invalid()

        self._attributes: AttributeDict = new_res._attributes
        self._attributes.change_resource(self)
        self._relationships: RelationshipDict = new_res._relationships
        self._relationships.change_resource(self)
        self.meta = new_res.meta
        self.links = new_res.links
        self.session.add_resources(self)

    def _refresh_sync(self) -> None:
        self.session.assert_sync()
        new_res = self.session.fetch_resource_by_resource_identifier(self, force=True)
        self._update_resource(new_res)

    async def _refresh_async(self) -> None:
        self.session.assert_async()
        new_res = await self.session.fetch_resource_by_resource_identifier_async(
                                                                            self,
                                                                            force=True)
        self._update_resource(new_res)

    def refresh(self) -> Optional[Awaitable]:
        """
        Manual way to refresh the data contained in this ResourceObject from server.

        If in async mode, this needs to be awaited.
        """
        if self.session.enable_async:
            return self._refresh_async()
        else:
            return self._refresh_sync()

    def delete(self) -> None:
        """
        Mark resource to be deleted. Resource will be deleted upon commit.
        """
        self._delete = True

    def _perform_delete(self, url='') -> None:
        url = url or self.url
        self.session.http_request(HttpMethod.DELETE, url, {})
        self.session.remove_resource(self)

    async def _perform_delete_async(self, url=''):
        url = url or self.url
        await self.session.http_request_async(HttpMethod.DELETE, url, {})
        self.session.remove_resource(self)

    def mark_clean(self) -> None:
        """
        Mark this resource and attributes / relationships as clean (not dirty).
        """
        self._attributes.mark_clean()
        self._relationships.mark_clean()

    def mark_invalid(self) -> None:
        """
        Mark this resource and it's related objects as invalid.
        """
        super().mark_invalid()
        self._attributes.mark_invalid()
        self._relationships.mark_invalid()
        self.meta.mark_invalid()
        self.links.mark_invalid()

    def as_resource_identifier_dict(self) -> Dict[str, str]:
        return {'id': self.id, 'type': self.type}


RESOURCE_TYPES = (ResourceObject, ResourceIdentifier, ResourceTuple)
