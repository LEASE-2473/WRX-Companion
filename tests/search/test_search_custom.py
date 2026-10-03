import asyncio
import json
import httpx
import pytest
from app.search import service as search
from app.models import SearchSettings

@pytest.mark.parametrize('provider,method', [('volcengine','POST'),('custom','POST'),('custom','GET')])
def test_configurable_search_protocol(monkeypatch, provider, method):
    original = httpx.AsyncClient
    captured = []
    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={'Result': {'WebResults': [{'Title':'标题', 'Url':'https://example.com', 'Summary':'相关摘要', 'Content':'全文'}]}})
    monkeypatch.setattr(search.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    config = SearchSettings(enabled=True, provider=provider, request_method=method, endpoint='https://example.org/search', api_key='fake',
        request_template={'Query':'{{query}}', 'Count':'{{max_results}}'}, results_path='Result.WebResults', title_path='Title', url_path='Url', content_path='Summary',
        auth_header='X-Key', auth_prefix='', extra_body={'TimeRange':'OneWeek','Query':'ignored','Count':99})
    result=asyncio.run(search.search_web('中文"\\查询', config))
    assert result == [{'title':'标题','url':'https://example.com','content':'相关摘要'}]
    request=captured[0]
    assert request.method==method
    body=json.loads(request.content) if method=='POST' else dict(request.url.params)
    assert body['Query']=='中文"\\查询'
    assert str(body['Count'])=='5'
    if provider=='volcengine':
        assert request.headers['Authorization']=='Bearer fake'
        assert body['SearchType']=='web' and body['TimeRange']=='OneWeek'
    else:
        assert request.headers['X-Key']=='fake'


def test_volcengine_business_error_and_empty(monkeypatch):
    original=httpx.AsyncClient
    payload={'ResponseMetadata':{'Error':{'Code':'10403','Message':'fake-secret'}},'Result':None}
    monkeypatch.setattr(search.httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(lambda r: httpx.Response(200,json=payload)),**kw))
    config=SearchSettings(enabled=True,provider='volcengine',api_key='fake-secret')
    with pytest.raises(ValueError,match='10403') as error:
        asyncio.run(search.search_web('查询',config))
    assert 'fake-secret' not in str(error.value)
    payload={'Result':{'ResultCount':0,'WebResults':None}}
    assert asyncio.run(search.search_web('查询',config))==[]


def test_custom_settings_roundtrip_and_private_key():
    config=SearchSettings(provider='custom',api_key='fake',request_template={'q':'{{query}}'},results_path='data.items')
    public=search.save_search_settings(config)
    assert 'api_key' not in public and public['api_key_set']
    search.save_search_settings(SearchSettings(provider='custom',results_path='data.items'))
    assert search.load_search_settings().api_key=='fake'
    assert public['request_template']=={'q':'{{query}}'}
