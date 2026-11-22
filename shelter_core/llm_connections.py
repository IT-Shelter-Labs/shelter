"""Named local/cloud connections shared by desktop, routing and future clients."""
from shelter_core.paths import ROOT_PATH

import copy
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

PRESETS = {
    "ollama": {"name":"Ollama", "provider":"ollama", "url":"http://127.0.0.1:11434", "local":True},
    "lmstudio": {"name":"LM Studio", "provider":"openai", "url":"http://127.0.0.1:1234/v1", "local":True},
    "openai": {"name":"OpenAI", "provider":"openai", "url":"https://api.openai.com/v1", "local":False},
    "anthropic": {"name":"Anthropic · Claude", "provider":"anthropic", "url":"https://api.anthropic.com/v1", "local":False},
    "openrouter": {"name":"OpenRouter", "provider":"openai", "url":"https://openrouter.ai/api/v1", "local":False},
    "deepseek": {"name":"DeepSeek", "provider":"openai", "url":"https://api.deepseek.com/v1", "local":False},
    "alibaba": {"name":"Alibaba Model Studio", "provider":"openai",
                "url":"https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "local":False},
    "dahl": {"name":"Dahl Inference", "provider":"openai", "url":"https://inference.dahl.global/v1", "local":False},
    "custom": {"name":"Свой совместимый сервер", "provider":"openai", "url":"", "local":False},
}
ID=re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")
BUILTINS = json.loads((ROOT_PATH / "app/src/lib/builtinModels.json").read_text(encoding="utf-8"))


def endpoint(cfg, operation="chat"):
    provider=cfg.get('provider','ollama')
    default='https://api.anthropic.com/v1' if provider=='anthropic' else 'https://api.openai.com/v1' if provider=='openai' else 'http://127.0.0.1:11434'
    url=str(cfg.get("url") or default).strip()
    parts=urlsplit(url)
    if parts.scheme not in ("http","https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Нужен адрес HTTP/HTTPS без ключа, пароля и параметров в URL")
    path=parts.path.rstrip("/")
    for suffix in ("/chat/completions","/messages","/models","/api/chat","/api/tags"):
        if path.endswith(suffix):path=path[:-len(suffix)];break
    if provider=='ollama' or provider=='local' and '/v1' not in parts.path:
        path=path.removesuffix('/v1')
        path=path.removesuffix("/api")+("/api/chat" if operation=="chat" else "/api/tags")
    else:
        if not path:path="/v1"
        path+=("/messages" if provider=="anthropic" else "/chat/completions") if operation=="chat" else "/models"
    return urlunsplit((parts.scheme,parts.netloc,path,"",""))


def api_key(cfg):
    host=urlsplit(endpoint(cfg)).hostname
    default='ANTHROPIC_API_KEY' if host=='api.anthropic.com' else 'OPENAI_API_KEY' if host=='api.openai.com' else ''
    return str(cfg.get("api_key") or os.environ.get(str(cfg.get("api_key_env",default) or ''),""))


def open_request(request,timeout):
    from shelter_core import netfix
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,hdrs,newurl):
            return None  # Never forward credentials to a redirect target.
    return urllib.request.build_opener(netfix._LocalBypass(),NoRedirect()).open(request,timeout=timeout)


def headers(cfg):
    key=api_key(cfg)
    if cfg.get("provider")=="anthropic":
        return {"anthropic-version":"2023-06-01",**({"x-api-key":key} if key else {}),
                **({'anthropic-workspace-id':str(cfg['workspace_id'])} if cfg.get('workspace_id') else {})}
    return {"Authorization":"Bearer "+key} if key else {}


def resolve(cfg, role="conversation"):
    """No automatic cloud fallback: only the explicitly configured route is used."""
    result={k:copy.deepcopy(v) for k,v in cfg.items() if k not in ("connections","routes")}
    ident=(cfg.get("routes") or {}).get(role) or (cfg.get("routes") or {}).get("conversation")
    if ident:
        connection=BUILTINS.get(ident) or (cfg.get("connections") or {}).get(ident)
        if not isinstance(connection,dict):raise ValueError("Подключение модели не найдено: "+str(ident))
        # Credentials and endpoint belong to one connection, never to a route's
        # previous provider or the legacy fallback settings.
        for key in ('api_key','api_key_env','url','provider','model','share_context'):
            result.pop(key,None)
        result.update(copy.deepcopy(connection));result["connection_id"]=ident
        result.setdefault('api_key_env','')
        result['share_context']=connection.get('share_context',urlsplit(endpoint(connection)).hostname in ('localhost','127.0.0.1','::1'))
    elif role=="task" and (cfg.get("agent") or {}).get("model"):
        result["model"]=cfg["agent"]["model"]
    endpoint(result)
    if result.get('guest'):result['share_context']=False
    return result


def validate(cfg):
    connections=cfg.get("connections") or {}
    routes=cfg.get("routes") or {}
    if not isinstance(connections,dict) or len(connections)>24 or not isinstance(routes,dict):
        raise ValueError("Подключения моделей должны быть объектами, не более 24")
    for ident,connection in connections.items():
        if not isinstance(ident,str) or not ID.fullmatch(ident) or not isinstance(connection,dict):raise ValueError("Некорректное подключение модели")
        endpoint(connection)
        if connection.get("provider","ollama") not in ("ollama","local","openai","lmstudio","anthropic"):
            raise ValueError("Неизвестный протокол модели")
        context=connection.get("context",8192)
        if type(context) is not int or not 2048<=context<=262144:raise ValueError("Контекст подключения: от 2048 до 262144")
        if 'share_context' in connection and type(connection['share_context']) is not bool:raise ValueError('Доступ к материалам: включён или выключен')
        if any(not isinstance(connection.get(k,''),str) for k in ('model','name','api_key','api_key_env','workspace_id')):raise ValueError('Имя модели и ключ должны быть строками')
        if not 1<=int(connection.get('max_tokens',300))<=16384:raise ValueError('Лимит ответа: от 1 до 16384')
        if int(connection.get('max_tokens',300))>context-512:raise ValueError('Уменьшите лимит ответа: оставьте не меньше 512 токенов на вход')
        if not 0<=float(connection.get('temperature',.4))<=2:raise ValueError('Температура: от 0 до 2')
    available = {**connections, **BUILTINS}
    for role,ident in routes.items():
        if role not in ("conversation","task","vision") or not isinstance(ident, str) or (ident and ident not in available):
            raise ValueError("Маршрут ссылается на неизвестное подключение")
        if ident and not str(available[ident].get('model','')).strip():raise ValueError('У выбранного подключения должна быть модель')


def probe(connection):
    """List models, without sending chat/history or consuming a completion."""
    endpoint(connection)
    request=urllib.request.Request(endpoint(connection,"models"),headers=headers(connection))
    try:
        with open_request(request,timeout=8) as response:
            raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError("Слишком большой список моделей")
            data=json.loads(raw)
        items=data.get("models",data.get("data",[]))
        models=sorted({str(m.get("name") or m.get("id")) for m in items if isinstance(m,dict) and (m.get("name") or m.get("id"))})
        return {"ok":True,"models":models[:1000]}
    except urllib.error.HTTPError as error:
        # Provider error bodies may echo API keys. Never return/log their contents.
        return {"ok":False,"models":[],"error":f"Сервер ответил HTTP {error.code}. Проверьте адрес и ключ."}
    except (OSError,ValueError):
        return {"ok":False,"models":[],"error":"Не удалось получить модели. Проверьте адрес, доступность сервера и протокол."}


def completion_payload(messages,cfg,stream):
    payload={"model":cfg.get("model",""),"messages":multimodal(messages,'openai'),"stream":stream}
    reasoning=bool(re.match(r"^(?:gpt-[56]|o[134])",str(cfg.get("model",""))))
    payload["max_completion_tokens" if reasoning else "max_tokens"]=int(cfg.get("max_tokens",300))
    if not reasoning:payload["temperature"]=float(cfg.get("temperature",.6))
    return payload


def multimodal(messages,provider):
    """Translate the internal image representation only at the HTTP boundary."""
    result=[]
    for original in messages:
        message={k:v for k,v in original.items() if k!='images' and not k.startswith('_')}
        images=original.get('images') or []
        if images:
            content=[{'type':'text','text':str(message.get('content') or '')}]
            for value in images:
                # screen.py provides PNG/JPEG base64, never a remote URL.
                mime='image/png' if str(value).startswith('iVBOR') else 'image/jpeg'
                if provider=='anthropic':content.append({'type':'image','source':{'type':'base64','media_type':mime,'data':value}})
                else:content.append({'type':'image_url','image_url':{'url':f'data:{mime};base64,{value}'}})
            message['content']=content
        result.append(message)
    return result
