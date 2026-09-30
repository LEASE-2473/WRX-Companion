"""搜索 Provider 适配层；搜索结果是资料，不是系统指令。"""
from urllib.parse import urlparse
import httpx

from . import companion_store as store
from .models import SearchSettings


def load_search_settings():
    return SearchSettings.model_validate(store.get_setting("search", {}))


def public_search_settings():
    config = load_search_settings()
    return {**config.model_dump(exclude={"api_key"}), "api_key_set": bool(config.api_key)}


def save_search_settings(config: SearchSettings):
    parsed = urlparse(config.endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("搜索 Endpoint 必须是有效的 HTTP(S) URL，不能含登录凭据")
    if not config.api_key:
        config.api_key = load_search_settings().api_key
    store.save_setting("search", config.model_dump())
    return public_search_settings()


def field_at(value, path):
    for key in path.split(".") if path else []:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def render_template(value, query, count):
    if isinstance(value, dict):
        return {k: render_template(v, query, count) for k, v in value.items()}
    if isinstance(value, list):
        return [render_template(v, query, count) for v in value]
    if isinstance(value, str):
        if value == "{{max_results}}":
            return count
        return value.replace("{{query}}", query).replace("{{max_results}}", str(count))
    return value


async def search_web(query: str, config: SearchSettings | None = None):
    config = config or load_search_settings()
    if not config.enabled:
        raise ValueError("搜索尚未启用，请先配置搜索服务")
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            if config.provider == "tavily":
                if not config.api_key:
                    raise ValueError("Tavily API Key 未配置")
                response = await client.post(config.endpoint, headers={"Authorization": f"Bearer {config.api_key}"}, json={
                    "query": query[:2000], "max_results": config.max_results, "search_depth": config.search_depth,
                    "include_answer": False, "include_raw_content": False,
                })
            elif config.provider == "volcengine":
                if not config.api_key:
                    raise ValueError("豆包搜索 API Key 未配置")
                body = {"SearchType": "web", "Filter": {"NeedUrl": True}, **config.extra_body,
                        "Query": query[:100], "Count": config.max_results}
                if body["SearchType"] != "web":
                    raise ValueError("当前聊天搜索只支持 SearchType=web")
                response = await client.post(config.endpoint, headers={"Authorization": f"Bearer {config.api_key}"}, json=body)
            elif config.provider == "custom":
                headers = {config.auth_header: config.auth_prefix + config.api_key} if config.api_key else {}
                body = render_template(config.request_template, query[:2000], config.max_results)
                if config.request_method == "GET":
                    response = await client.get(config.endpoint, headers=headers, params=body)
                else:
                    response = await client.post(config.endpoint, headers=headers, json=body)
            else:
                headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
                response = await client.get(config.endpoint, headers=headers, params={"q": query[:2000], "format": "json"})
            response.raise_for_status()
            payload = response.json()
            if config.provider == "volcengine":
                error = field_at(payload, "ResponseMetadata.Error")
                if error:
                    code = error.get("Code", "unknown") if isinstance(error, dict) else "unknown"
                    raise ValueError(f"豆包搜索接口错误（代码 {code}），请检查参数、权限与额度")
                items = field_at(payload, "Result.WebResults")
                if items is None and field_at(payload, "Result.ResultCount") == 0:
                    items = []
            else:
                items = field_at(payload, config.results_path if config.provider == "custom" else "results")
            if not isinstance(items, list):
                raise ValueError("搜索响应中未找到结果数组，请检查响应字段映射")
            results = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                if config.provider == "volcengine":
                    title, url, content = item.get("Title"), item.get("Url"), item.get("Summary") or item.get("Content") or item.get("Snippet")
                elif config.provider == "custom":
                    title, url, content = (field_at(item, path) for path in (config.title_path, config.url_path, config.content_path))
                else:
                    title, url, content = item.get("title"), item.get("url"), item.get("content")
                url = str(url or "")
                if urlparse(url).scheme not in {"http", "https"}:
                    continue
                results.append({"title": str(title or url)[:300], "url": url,
                                "content": str(content or "")[:3000]})
                if len(results) >= config.max_results:
                    break
            return results
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"搜索服务返回 HTTP {exc.response.status_code}，请检查配置和额度") from None
    except httpx.HTTPError:
        raise ValueError("搜索连接失败或超时") from None
