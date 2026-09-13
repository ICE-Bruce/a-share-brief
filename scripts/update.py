"""Import an already-researched public JSON bundle, never invent market data.

This is NOT a news crawler, market-data feed, or AI analyst. Until an approved
report producer exists, leave REPORT_BUNDLE_URL / ENABLE_DATA_UPDATES unset.
"""
from __future__ import annotations
import json, math, os, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'site/data/latest.json'
STATUS=ROOT/'site/data/status.json'
LIMIT=3_000_000

def timestamp(value):
    if not isinstance(value,str): raise ValueError('Timestamp required')
    d=datetime.fromisoformat(value.replace('Z','+00:00'))
    if d.tzinfo is None: raise ValueError('Timezone-aware timestamp required')
    if d.timestamp()>datetime.now(timezone.utc).timestamp()+300: raise ValueError('Future timestamp')
    return d

def public_url(value):
    p=urlsplit(value)
    if p.scheme!='https' or not p.hostname or p.username or p.password: raise ValueError('Public HTTPS URL required')
    if p.hostname in ('localhost','127.0.0.1','::1') or '.' not in p.hostname: raise ValueError('Public host required')
    return value

def validate(d):
    if not isinstance(d,dict) or d.get('schema_version')!=2 or d.get('timezone')!='Asia/Shanghai': raise ValueError('Schema v2 / Asia/Shanghai required')
    if set(d)-{'schema_version','timezone','updated_at','sources','reports'}: raise ValueError('Unknown top-level fields')
    if not isinstance(d.get('sources'),list) or not isinstance(d.get('reports'),list): raise ValueError('Arrays required')
    if len(d['sources'])>5000 or len(d['reports'])>2000: raise ValueError('Bundle too large; archive first')
    ids=set()
    for s in d['sources']:
        if not isinstance(s,dict) or not isinstance(s.get('id'),str) or s['id'] in ids or not s.get('name'): raise ValueError('Invalid source')
        if set(s)-{'id','name','url','published_at','note','kind'}: raise ValueError('Unknown source fields')
        public_url(s.get('url','')); ids.add(s['id'])
        if s.get('published_at'): timestamp(s['published_at'])
    rids=set()
    for r in d['reports']:
        if not isinstance(r,dict) or not isinstance(r.get('id'),str) or r['id'] in rids: raise ValueError('Invalid/duplicate report id')
        rids.add(r['id'])
        if set(r)-{'id','date','slot','generated_at','information_cutoff','headline','summary','quotes','stories','opportunities','scenarios','alerts'}: raise ValueError('Unknown report fields; do not publish private data')
        if r.get('slot') not in ('09:00','14:00','breaking') or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',r.get('date','')): raise ValueError('Invalid report date/slot')
        generated=timestamp(r.get('generated_at')); cutoff=timestamp(r.get('information_cutoff'))
        if cutoff>generated: raise ValueError('Cutoff after generation')
        for key in ('summary','quotes','stories','opportunities','scenarios','alerts'):
            if not isinstance(r.get(key),list): raise ValueError('Missing list: '+key)
        for q in r['quotes']:
            if not q.get('name') or not q.get('code') or q.get('source_id') not in ids: raise ValueError('Quote source required')
            if timestamp(q.get('observed_at'))>cutoff: raise ValueError('Quote after information cutoff')
            for key in ('value','change_pct'):
                x=q.get(key)
                if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x): raise ValueError('Finite numeric quote required')
            if q['value']<0: raise ValueError('Negative quote')
        for s in r['stories']:
            if not s.get('title') or not s.get('fact') or not s.get('source_ids'): raise ValueError('News fact/source required')
            if timestamp(s.get('published_at'))>cutoff: raise ValueError('News after cutoff')
        for a in r['alerts']:
            if not a.get('id') or not a.get('title') or not a.get('fact') or not a.get('source_ids'): raise ValueError('Alert evidence required')
            timestamp(a.get('discovered_at'))
    def references(obj):
        if isinstance(obj,list):
            for x in obj: references(x)
        elif isinstance(obj,dict):
            for k,v in obj.items():
                if k=='source_ids' and (not isinstance(v,list) or any(i not in ids for i in v)): raise ValueError('Unknown citation')
                references(v)
    references(d['reports'])
    if d['reports']:
        if timestamp(d.get('updated_at')) < max(timestamp(r['generated_at']) for r in d['reports']): raise ValueError('Bundle date precedes report')
    return d

def merge(old,new):
    validate(old);validate(new)
    def immutable_union(a,b):
        out={v['id']:v for v in a}
        for v in b:
            if v['id'] in out and out[v['id']]!=v: raise ValueError('History cannot be overwritten; use a new revision id')
            out[v['id']]=v
        return list(out.values())
    result={'schema_version':2,'timezone':'Asia/Shanghai','updated_at':None,
      'sources':immutable_union(old['sources'],new['sources']), 'reports':immutable_union(old['reports'],new['reports'])}
    result['reports'].sort(key=lambda r:timestamp(r['generated_at']))
    times=[d['updated_at'] for d in (old,new) if d.get('updated_at')]
    result['updated_at']=max(times,key=timestamp) if times else None
    return validate(result)

def write_json(path,obj):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temp.replace(path)

def main():
    old=validate(json.loads(DATA.read_text(encoding='utf-8')))
    endpoint=os.environ.get('REPORT_BUNDLE_URL','').strip()
    if not endpoint:
        # No fake heartbeat or changing generation time when nothing is connected.
        write_json(STATUS,{'checked_at':None,'state':'unconfigured','message':'报告生产服务未配置。未进行市场检查；自动分析、行情和推送尚未接通。'})
        print('No report provider configured. No market check performed.');return 0
    now=datetime.now(timezone.utc).isoformat()
    try:
        public_url(endpoint)
        with urlopen(Request(endpoint,headers={'User-Agent':'a-share-brief/1.0','Accept':'application/json'}),timeout=25) as response:
            public_url(response.url)
            if 'json' not in response.headers.get('Content-Type','').lower(): raise ValueError('JSON content type required')
            body=response.read(LIMIT+1)
        if len(body)>LIMIT: raise ValueError('Response exceeds size limit')
        current=merge(old,json.loads(body))
        write_json(DATA,current)
        write_json(STATUS,{'checked_at':now,'state':'report_feed_read','message':'已读取报告生产服务；来源格式已校验，事实真实性仍需生产端核验。检查成功不代表行情或报告是当前时刻的，站外推送未配置。'})
        print('Report feed read and validated.');return 0
    except Exception as e:
        # No URLs, credentials or endpoint error bodies in public status / logs.
        write_json(STATUS,{'checked_at':now,'state':'error','message':'报告获取或校验失败。保留此前内容；数据覆盖中断，不代表没有风险。'})
        print('Import failed: '+type(e).__name__,file=sys.stderr)
        out=os.environ.get('GITHUB_OUTPUT')
        if out:
            with open(out,'a',encoding='utf-8') as f:f.write('fetch_failed=true\n')
            return 0 # Deploy warning first; workflow's last step marks failure.
        return 1
if __name__=='__main__': sys.exit(main())
