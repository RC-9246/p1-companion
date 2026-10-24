"""Shared strict host/URL policy, with DNS pinning enforced by the egress proxy."""
import ipaddress
import json
import re
import socket
from pathlib import Path
from urllib.parse import urlsplit,parse_qsl,unquote

DEFAULT_DOMAINS=['gimaiseikatsu-anime.com','promo.kadokawa.co.jp','www.kadokawa.co.jp','docs.astrbot.app','docs.python.org','cn.bing.com','www.bing.com','bing.com','baike.baidu.com','baike.sogou.com','baike.so.com','zh.wikipedia.org','en.wikipedia.org','zh.m.wikipedia.org','en.m.wikipedia.org','zh.wikibooks.org','zh.wikisource.org','zh.wiktionary.org','www.britannica.com','www.bbc.com','www3.nhk.or.jp','www.nhk.or.jp','developer.mozilla.org','en.cppreference.com','zh.cppreference.com','docs.docker.com','modelcontextprotocol.io','docs.n8n.io','playwright.dev','pypi.org','github.com','raw.githubusercontent.com','arxiv.org','www.nature.com','www.science.org','www.nasa.gov','science.nasa.gov','www.cas.cn','www.bilibili.com']
DENY_SEGMENTS={'login','logout','signin','signout','delete','remove','confirm','authorize','oauth','checkout','purchase','unsubscribe','action','admin','api','edit','submit','upload','comment','danmaku','follow','favorite','like','watchlater','write','settings','account','logout.php'}

def hostname(value):
    if not isinstance(value,str) or len(value)>253 or value!=value.strip() or value.endswith('.'):
        raise ValueError('invalid_host')
    host=value.lower().encode('idna').decode('ascii')
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',host) or '..' in host or '.' not in host:
        raise ValueError('invalid_host')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('ip_literal_forbidden')
    if host.endswith(('.local','.localhost','.internal','.ts.net')):
        raise ValueError('private_name_forbidden')
    return host

def domains(path):
    v=json.loads(Path(path).read_text())
    if not isinstance(v,list) or not 1<=len(v)<=120:
        raise ValueError('invalid_policy')
    return {hostname(h) for h in v}

def validate_url(url,allowed):
    if not isinstance(url,str) or len(url)>2048 or any(ord(c)<33 for c in url) or '\\' in url:
        raise ValueError('invalid_url')
    p=urlsplit(url)
    if p.scheme!='https' or p.username is not None or p.password is not None or p.port not in (None,443) or p.fragment:
        raise ValueError('https_public_read_only_required')
    host=hostname(p.hostname or '')
    if host not in allowed:
        raise ValueError('domain_not_approved')
    if p.query:
        pairs=parse_qsl(p.query,keep_blank_values=True)
        keys={k.lower() for k,v in pairs}
        query_rules={
            'cn.bing.com':{'q','first','count','ensearch','setlang','format'},'www.bing.com':{'q','first','count','ensearch','setlang','format'},'bing.com':{'q','first','count','ensearch','setlang','format'},
            'zh.wikipedia.org':{'search','title','variant','uselang','oldid','limit','offset'},'en.wikipedia.org':{'search','title','oldid','limit','offset'},
            'baike.baidu.com':{'word','lemmaid','frommodule'},'baike.sogou.com':{'word','id'},'baike.so.com':{'q','word'},
            'github.com':{'q','type','page','tab'},'pypi.org':{'q','page'},'arxiv.org':{'query','searchtype','abstracts','order','size','start'},
            'www.bilibili.com':{'p','t'},
        }
        if not pairs or len(pairs)>8 or keys-query_rules.get(host,set()):raise ValueError('query_not_read_only')
        from search_policy import query as checked_query
        for k,v in pairs:
            if len(v)>160 or re.search(r'(?i)(password|token|secret|cookie|session|csrf|credential|api.key|密码|口令|密钥)',v):raise ValueError('private_query_rejected')
            if k.lower() in ('q','word','search','query'):checked_query(v)
    segs=set(re.split(r'[/;=.?&]',unquote(p.path).lower()))
    if segs & DENY_SEGMENTS:
        raise ValueError('side_effect_path_forbidden')
    return host

def public_addresses(host):
    rows=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    addresses=[]
    for family,kind,proto,_,address in rows:
        ip=ipaddress.ip_address(address[0])
        if not ip.is_global or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise ValueError('nonpublic_dns_forbidden')
        addresses.append((family,kind,proto,address))
    if not addresses:
        raise ValueError('no_public_dns')
    return addresses
