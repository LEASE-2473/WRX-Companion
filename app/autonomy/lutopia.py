"""Lutopia 受限 MCP 客户端：仅 discover/show，不执行任意 CLI 或私信。"""
import json
import re
import httpx


async def browse(cfg, post_id=''):
    from app.autonomy.service import validate_public_host, plain, require_available
    require_available()
    if post_id and not re.fullmatch(r'[A-Za-z0-9-]{1,100}', post_id):
        raise ValueError('帖子 ID 格式无效')
    endpoint = cfg.mcp_url.removesuffix('/sse')
    await validate_public_host(endpoint, cfg.allow_fake_ip)
    headers = {'Accept':'application/json, text/event-stream'}
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False, proxy=cfg.proxy_url or None) as client:
        async def rpc(method, params, request_id=None):
            body = {'jsonrpc':'2.0', 'method':method, 'params':params}
            if request_id is not None:
                body['id'] = request_id
            async with client.stream('POST', endpoint, headers=headers, json=body) as response:
                if response.status_code not in (200,202,204):
                    raise ValueError('Lutopia 连接失败，请检查个人 MCP 地址与账号状态')
                if response.headers.get('Mcp-Session-Id'):
                    headers['Mcp-Session-Id'] = response.headers['Mcp-Session-Id']
                if request_id is None:
                    return {}
                buffer = bytearray()
                sse = response.headers.get('content-type','').startswith('text/event-stream')
                processed = 0
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > 512000:
                        raise ValueError('Lutopia 返回数据超过限制')
                    if sse:
                        # 流可能保持打开；收到对应 JSON-RPC 返回便退出，不等待 EOF。
                        normalized = bytes(buffer).replace(b'\r\n', b'\n')
                        frames = normalized.split(b'\n\n')
                        for frame in frames[processed:-1]:
                            data = b'\n'.join(line[5:].lstrip() for line in frame.split(b'\n') if line.startswith(b'data:'))
                            if not data:
                                continue
                            payload = json.loads(data)
                            if payload.get('id') == request_id:
                                if 'error' in payload:
                                    raise ValueError('Lutopia MCP 拒绝请求')
                                return payload.get('result', {})
                        processed = len(frames)-1
                if sse:
                    raise ValueError('Lutopia MCP 未返回对应结果')
                payload = json.loads(buffer)
                if payload.get('id') != request_id or 'error' in payload:
                    raise ValueError('Lutopia MCP 返回格式不符')
                return payload.get('result', {})

        init = await rpc('initialize', {'protocolVersion':'2025-03-26', 'capabilities':{}, 'clientInfo':{'name':'wrx-public-explorer','version':'1.0'}}, 1)
        version = init.get('protocolVersion')
        if version not in ('2025-03-26','2025-06-18','2025-11-25'):
            raise ValueError('Lutopia MCP 协议版本暂不支持')
        headers['MCP-Protocol-Version'] = version
        await rpc('notifications/initialized', {})
        result = await rpc('tools/call', {'name':'lutopia_cli', 'arguments':{'command':f'show {post_id}' if post_id else 'discover --limit 5'}}, 2)
        if result.get('isError'):
            raise ValueError('Lutopia 需要完成账号／AI身份接入，或不支持此命令')
    blocks = [item.get('text','') for item in result.get('content',[]) if item.get('type') == 'text']
    # CLI 可能返回自然语言，保留实际文本；绝不臆造帖子 ID。
    text = '\n'.join(blocks).replace(cfg.mcp_url, '[个人接入地址已隐藏]').replace(endpoint, '[个人接入地址已隐藏]')[:12000]
    if not text.strip() and not result.get('structuredContent'):
        raise ValueError('Lutopia 没有返回可阅读的资料')
    structured = result.get('structuredContent')
    if structured is None:
        try:
            structured = json.loads(text)
        except ValueError:
            structured = None
    if isinstance(structured, dict):
        items = structured.get('posts', structured.get('data', []))
        if post_id:
            items = [structured.get('post', structured)]
    else:
        items = structured if isinstance(structured, list) else []
    if isinstance(items, list) and items:
        return [{'id':str(p.get('id', p.get('post_id','')))[:100], 'title':plain(p.get('title','')), 'content':plain(p.get('content',p.get('body','')))} for p in items[:5] if isinstance(p,dict)]
    # 明确标注的 ID 才能成为下一轮 show 的参数；无法识别仍可看文本、写笔记。
    ids = list(dict.fromkeys(re.findall(r'(?:post_id|帖子\s*ID|Post\s*ID)\s*[:：=]\s*["\']?([A-Za-z0-9-]{1,100})', text, re.I)))[:5]
    return [{'id':identifier, 'content':plain(text)} for identifier in ids] or [{'id':post_id, 'content':plain(text)}]
