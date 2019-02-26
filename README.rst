.. image:: https://travis-ci.org/qvantel/jsonapi-client.svg?branch=master
   :target: https://travis-ci.org/qvantel/jsonapi-client

.. image:: https://coveralls.io/repos/github/qvantel/jsonapi-client/badge.svg
   :target: https://coveralls.io/github/qvantel/jsonapi-client

.. image:: https://img.shields.io/pypi/v/jsonapi-client.svg
   :target: https://pypi.python.org/pypi/jsonapi-client

.. image:: https://img.shields.io/pypi/pyversions/jsonapi-client.svg
   :target: https://pypi.python.org/pypi/jsonapi-client

.. image:: https://img.shields.io/badge/licence-BSD%203--clause-blue.svg
   :target: https://github.com/qvantel/jsonapi-client/blob/master/LICENSE.rst

==========================
JSON API client for Python
==========================

Introduction
============

Project home: https://github.com/qvantel/jsonapi-client

This Python (3.6+) library provides easy-to-use, pythonic, ORM-like access to
backend services implementing a `JSON API <https://jsonapi.org/format/1.0/>`_ interface.

- Optional asyncio implementation
- Optional model schema definition and validation (=> easy reads even without schema)
- Resource caching within session

Installation
============

From Pypi::

    pip install jsonapi-client

Or from sources::

    python setup.py install

Usage
=====

Client session
--------------

.. code-block:: python

    from jsonapi_client import Session

    # Start a synchronous session
    s = Session('http://localhost:8080/')

    # Start a session in async mode
    s = Session('http://localhost:8080/', is_async=True)

    # Start a session and provide arguments for the requests or aiohttp methods
    # via request_kwargs, e.g. authentication object
    s = Session('http://localhost:8080/',
                request_kwargs={'auth': HttpBasicAuth('user', 'password')})

    # Use Session as context manager
    # Changes are committed at the end of the block and session is closed.
    with Session(...) as s:
        # your code

    # Or in async mode as follows
    async with Session(..., is_async=True) as s:
        # your code

    # Fetch multiple resources
    documents = s.get('resource_type')
    # Or just a single one
    documents = s.get('resource_type', 'id_of_document')

    # In async mode remember to use `await`
    documents = await s.get('resource_type')


    # Then remember to close the session, unless using it as context manager
    s.close()

Filtering and includes
----------------------

.. code-block:: python

    from jsonapi_client import Filter, Include, Modifier

    # First to specify a modifier instance.
    # - filtering with two criteria joined with &
    filter = Filter(attribute1='something', attribute2='something_else')
    # - filtering with some-dict.some-attr == 'something'
    filter = Filter(some_dict__some_attr='something')
    # - filtering with raw query string
    filter = Filter(query_str='filter[attribute1]=something&filter[attribute2]=something_else')
    # - mix raw and named parameter based filtering
    filter = Filter('filter[attribute1]=something&filter[attribute2]=something_else',
                    **{'attribute1': 'else', 'attribute2': 'something_more'})

    # Same for related resource inclusion.
    # - including resources under two relationship fields
    include = Include('related_field', 'other_related_field')

    # Custom syntax for request parameters.
    # If you have different URL schema for filtering or other GET parameters,
    # you can use Modifier class to pass a raw query string.
    # Alternatively, you can implement your own modifier class by inheriting
    # from BaseModifier and implementing appended_query.
    modifier = Modifier('filter[post]=1&filter[author]=2&sort=attribute1,attribute2&include=relation1,relation3')

    # All above classes subclass BaseModifier and can be concatenated into a
    # single modifier
    modifier_sum = filter + include + modifier

    # Now fetch your document
    filtered = s.get('resource_type', modifier_sum) # NOTE: use await when async

    # To access resources included in document:
    r1 = document.resources[0]  # first ResourceObject of document.
    r2 = document.resource      # if there is only 1 resource you can use this

Pagination
----------

.. code-block:: python

    # Pagination links can be accessed via Document object.
    next_doc = document.links.next.fetch()
    # AsyncIO
    next_doc = await document.links.next.fetch()

    # Iteration through results (uses pagination):
    for r in s.iterate('resource_type'):
        print(r)

    # AsyncIO:
    async for r in s.iterate('resource_type'):
        print(r)

Resource attribute and relationship access
------------------------------------------

.. code-block:: python

    # - attribute access
    attr1 = r1.some_attr
    nested_attr = r1.some_dict.some_attr
    #   Attributes can always also be accessed via __getitem__:
    nested_attr = r1['some-dict']['some-attr']

    # If there is namespace collision, you can also access attributes via .fields proxy
    # (both attributes and relationships)
    attr2 = r1.fields.some_attr

    # - relationship access.
    #   * Sync, this gives directly ResourceObject
    rel = r1.some_relation
    attr3 = r1.some_relation.some_attr  # Relationship attribute can be accessed directly

    #   * AsyncIO, this gives Relationship object instead because we anyway need to
    #     call asynchronous fetch function.
    rel = r1.some_relation
    #     To access ResourceObject you need to first fetch content
    await r1.some_relation.fetch()
    #     and then you can access associated resourceobject
    res = r1.some_relation.resource
    attr3 = res.some_attr  # Attribute access through ResourceObject

    # If you need to access relatinoship object itself (with sync API), you can do it via
    # .relationships proxy. For example, if you are interested in links or metadata
    # provided within relationship, or intend to manipulate relationship.
    rel_obj = r1.relationships.relation_name

Resource updating
-----------------

.. code-block:: python

    from jsonapi_client import ResourceTuple

    # Updating / patching existing resources
    r1.some_attr = 'something else'
    # Patching element in nested json
    r1.some_dict.some_dict.some_attr = 'something else'

    # change relationships, to-many. Accepts also iterable of ResourceObjects/
    # ResourceIdentifiers/ResourceTuples
    r1.comments = ['1', '2']
    # or if resource type is not known or can have multiple types of resources
    r1.comments_or_people = [ResourceTuple('1', 'comments'), ResourceTuple('2', 'people')]
    # or if you want to add some resources you can
    r1.comments_or_people += [ResourceTuple('1', 'people')]
    r1.commit()

    # change to-one relationships
    r1.author = '3'  # accepts also ResourceObjects/ResourceIdentifiers/ResourceTuple
    # or resource type is not known (via schema etc.)
    r1.author = ResourceTuple('3', 'people')

    # Committing changes (PATCH request)
    r1.commit(meta={'some_meta': 'data'})  # Resource committing supports optional meta data
    # AsyncIO
    await r1.commit(meta={'some_meta': 'data'})

Creating new resources
----------------------

.. code-block:: python

    # To create new resources a schema must be given.
    # Session expects a dictionary of schema models where
    # key is the name of the model and value is the schema as per JSON Schema.

    # Define schema inline
    models_as_jsonschema = {
        'articles': {
            'properties': {
                'title': {'type': 'string'},
                'author': {'relation': 'to-one', 'resource': ['people']},
                'comments': {'relation': 'to-many', 'resource': ['comments']},
            }
        },
        'people': {
            'properties': {
                'first-name': {'type': 'string'},
                'last-name': {'type': 'string'},
                'twitter': {'type': ['null', 'string']},
            }
        },
        'comments': {
            'properties': {
                'body': {'type': 'string'},
                'author': {'relation': 'to-one', 'resource': ['people']}
            }
        }
    }

    # Or maintain schema in e.g. a YAML file and load it from there
    # # my_schema.yaml
    #
    # articles:
    #   properties:
    #     title:
    #       type: string
    #     author:
    #       relation: to-one
    #       resource:
    #         - people
    #     comments:
    #       relation: to-many
    #       resource:
    #         - comments
    # people:
    #   properties:
    #     first-name:
    #       type: string
    #     last-name:
    #       type: string
    #     twitter:
    #       type:
    #         - null
    #         - string
    # comments:
    #   properties
    #     body:
    #       type: string
    #     author:
    #       relation: to-one
    #     resource:
    #       - people
    import yaml
    models_as_jsonschema = yaml.load(open('my_schema.yaml'))

    s = Session('http://localhost:8080/', schema=models_as_jsonschema)

    # Create empty ResourceObject of 'articles' type
    a = s.create('articles')
    # One by one assign values to fields
    a.title = 'Test title'

    # Then validate and perform update
    a.commit(meta={'some_meta': 'data'})
    # In async mode remember to await
    await a.commit(meta={'some_meta': 'data'})

    # To commit all changes in the session at once,
    # save the metadata of each resource object
    a.commit_metadata = {'some_meta': 'data'}
    # And call commit on the session instead of the resource objects
    s.commit()
    # or with AsyncIO
    await s.commit()

    # Alternatively, one could create ResourceObject with assigned values.
    a = s.create_and_commit(
            # model name
            'articles',

            # properties passed as named parameters
            title='One really interesting article',
            dict_object__attribute='2',
            to_one_relationship='author-id-here',
            to_many_relationship=['comment-id1', 'comment-id2'],

            # if a field name contains underscore, pass it in `fields` dict
            fields={'field_name_with_underscore': '1'}
    )

    # Async:
    a = await s.create_and_commit(
            'articles', # model

            title='One really interesting article',
            dict_object__attribute='2',
            to_one_relationship='author-id-here',
            to_many_relationship=['comment-id1', 'comment-id2'],

            fields={'some_field_with_underscore': '1'}
    )

Deleting resources
------------------

.. code-block:: python

    # Delete resource
    a.delete() # Mark to be deleted
    a.commit() # Carry out the deletion
