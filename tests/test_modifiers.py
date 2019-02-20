from jsonapi_client.modifiers import Modifier, Include, Filter, Sort, SparseFieldset


def test_modifier():
    url = 'http://localhost:8080'
    query = 'example_attr=1'
    m = Modifier(query)
    assert m.url_with_modifiers(url) == f'{url}?{query}'


def test_include():
    url = 'http://localhost:8080'
    f = Include('something', 'something_else')
    assert f.url_with_modifiers(url) == f'{url}?include=something,something_else'


def test_sorting():
    url = 'http://localhost:8080'
    f = Sort('something', 'something_else')
    assert f.url_with_modifiers(url) == f'{url}?sort=something,something_else'


def test_modifier_sum():
    url = 'http://localhost:8080'
    q1 = 'item1=1'
    q2 = 'item2=2'
    q3 = 'item3=3'
    m1 = Modifier(q1)
    m2 = Modifier(q2)
    m3 = Modifier(q3)

    assert ((m1 + m2) + m3).url_with_modifiers(url) == f'{url}?{q1}&{q2}&{q3}'
    assert (m1 + (m2 + m3)).url_with_modifiers(url) == f'{url}?{q1}&{q2}&{q3}'
    assert (m1 + m2 + m3).url_with_modifiers(url) == f'{url}?{q1}&{q2}&{q3}'


def test_filter():
    url = 'http://localhost:8080'
    f1 = Filter('filter[hello]=world')
    assert f1.url_with_modifiers(url) == f'{url}?filter[hello]=world'

    f2 = Filter(**{'arg1': '1'})
    assert f2.url_with_modifiers(url) == f'{url}?filter[arg1]=1'

    f3 = Filter('filter[hello]=world', **{'arg1': '1', 'arg2': [1, 2, 3], 'rel1__arg1': 2.57})
    assert f3.url_with_modifiers(url) == f'{url}?filter[hello]=world&filter[arg1]=1&filter[arg2]=1,2,3&filter[rel1.arg1]=2.57'

    f4 = Filter('filter[hello]=world', **{'hello': 'universe'})
    assert f4.url_with_modifiers(url) == f'{url}?filter[hello]=world,universe'

    f5 = Filter('filter[hello]=world&filter[hello]=universe')
    assert f5.url_with_modifiers(url) == f'{url}?filter[hello]=universe'

    f6 = Filter(**{'hello': 'world', 'hello': 'universe'})
    assert f6.url_with_modifiers(url) == f'{url}?filter[hello]=universe'


def test_fieldset():
    url = 'http://localhost:8080'
    f1 = SparseFieldset('fields[myclazz]=attr1')
    assert f1.url_with_modifiers(url) == f'{url}?fields[myclazz]=attr1'

    f2 = SparseFieldset(**{'myclazz': 'attr1'})
    assert f2.url_with_modifiers(url) == f'{url}?fields[myclazz]=attr1'

    f3 = SparseFieldset('fields[myclazz]=attr1', **{'yourclazz': 'attr1', 'herclazz': ['attr1', 'rel1', 'rel2']})
    assert f3.url_with_modifiers(url) == f'{url}?fields[myclazz]=attr1&fields[yourclazz]=attr1&fields[herclazz]=attr1,rel1,rel2'

    f4 = SparseFieldset('fields[myclazz]=attr1', **{'myclazz': 'attr2'})
    assert f4.url_with_modifiers(url) == f'{url}?fields[myclazz]=attr1,attr2'

    f5 = SparseFieldset('fields[myclazz]=attr1&fields[myclazz]=attr2')
    assert f5.url_with_modifiers(url) == f'{url}?fields[myclazz]=attr2'

    f6 = SparseFieldset(**{'myclazz': 'attr1', 'myclazz': 'attr2'})
    assert f6.url_with_modifiers(url) == f'{url}?fields[myclazz]=attr2'
