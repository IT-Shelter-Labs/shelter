"""Optional local CPU embeddings; bounded lookup with lexical fallback.

No facts are learned automatically. Only explicit memory rows are embedded.
Vectors are scoped at retrieval by the caller and invalidated on edits/deletes.
"""
import hashlib
import json
import math
import threading
import time
import urllib.request

_index_lock=threading.Lock()
_cache={}
_cache_lock=threading.Lock()


def settings(cfg):
    options=(cfg.get('memory') or {}).get('embedding') or {}
    return str(options.get('url','http://127.0.0.1:11434')).rstrip('/'),str(options.get('model','embeddinggemma'))


def identity(cfg):
    return '|'.join(settings(cfg))


def text_hash(text):
    return hashlib.sha256(text.encode('utf8')).hexdigest()


def embed(texts,cfg,timeout=1.):
    url,model=settings(cfg)
    # This endpoint is deliberately separate from chat/cloud credentials.
    payload={'model':model,'input':texts,'truncate':True,'keep_alive':'30m','options':{'num_gpu':0}}
    request=urllib.request.Request(url+'/api/embed',data=json.dumps(payload).encode('utf8'),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=timeout) as response:
        raw=response.read(8_000_001)
        if len(raw)>8_000_000:raise ValueError('Embedding response too large')
        result=json.loads(raw).get('embeddings',[])
    if len(result)!=len(texts):raise ValueError('Incomplete embedding batch')
    vectors=[]
    for vector in result:
        if not isinstance(vector,list) or not 16<=len(vector)<=4096 or not all(type(v) in (int,float) and math.isfinite(v) for v in vector):
            raise ValueError('Invalid embedding vector')
        norm=math.sqrt(sum(v*v for v in vector))
        if norm<1e-9:raise ValueError('Empty embedding vector')
        vectors.append([v/norm for v in vector])
    return vectors


def reindex(cfg):
    from shelter_core import assistant_store as store
    if not _index_lock.acquire(blocking=False):return {'ok':True,'status':'already_running'}
    try:
        model=identity(cfg)
        with store.db() as con:
            all_items=store.rows(con,'SELECT id,text FROM memories ORDER BY updated DESC LIMIT 500')
            old={r['memory_id']:dict(r) for r in con.execute('SELECT memory_id,model,text_hash FROM memory_vectors')}
        pending=[r for r in all_items if r['id'] not in old or old[r['id']]['model']!=model or old[r['id']]['text_hash']!=text_hash(r['text'])]
        total=0
        for start in range(0,len(pending),16):
            batch=pending[start:start+16]
            vectors=embed(['title: user preference | text: '+r['text'] for r in batch],cfg,timeout=30)
            with store.db() as con:
                for row,vector in zip(batch,vectors):
                    # A concurrent deletion or edit must never resurrect a stale fact.
                    live=con.execute('SELECT text FROM memories WHERE id=?',(row['id'],)).fetchone()
                    if not live or live['text']!=row['text']:continue
                    con.execute('INSERT OR REPLACE INTO memory_vectors VALUES(?,?,?,?,?)',
                                (row['id'],model,text_hash(row['text']),json.dumps(vector),time.time()))
                    total+=1
        return {'ok':True,'indexed':total,'total':len(all_items)}
    except (OSError,ValueError):
        return {'ok':False,'error':'Смысловой поиск пока недоступен. Проверьте Ollama и модель embeddinggemma; поиск по словам продолжает работать.'}
    finally:_index_lock.release()


def rank(items,query,cfg,lexical):
    from shelter_core import assistant_store as store
    if not items or not query.strip():return lexical
    model=identity(cfg);current={r['id']:r for r in items}
    with store.db() as con:
        vectors=store.rows(con,'SELECT * FROM memory_vectors WHERE model=?',(model,))
    valid=[r for r in vectors if r['memory_id'] in current and r['text_hash']==text_hash(current[r['memory_id']]['text'])]
    if len(valid)<len(items):threading.Thread(target=reindex,args=(cfg,),name='memory-index',daemon=True).start()
    if not valid:return lexical
    key=(model,query)
    try:
        with _cache_lock:vector=_cache.get(key)
        if vector is None:
            vector=embed(['task: search result | query: '+query],cfg,timeout=1.)[0]
            with _cache_lock:
                if len(_cache)>=64:_cache.pop(next(iter(_cache)))
                _cache[key]=vector
        scored=[]
        for row in valid:
            other=json.loads(row['vector'])
            if len(other)!=len(vector):continue
            score=sum(a*b for a,b in zip(vector,other))
            if score>=.30:scored.append((score,current[row['memory_id']]))
        semantic=[r for _,r in sorted(scored,key=lambda r:r[0],reverse=True)[:4]]
        # Semantic candidates first, explicit lexical evidence still retained.
        return list({r['id']:r for r in semantic+lexical}.values())[:6]
    except (OSError,ValueError):return lexical
