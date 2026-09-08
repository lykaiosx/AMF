import sys
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'payload'))
import app
from animetosho_provider import parse_page
fixture='''<div class="home_list_entry"><div class="date" title="Date/time submitted: 08/05/2026 23:56"></div><div class="size" title="Total file size: 1,234 bytes">1.2 KB</div><div class="link"><a href="https://animetosho.org/view/example.n123">Example S01 1080p Dual Audio</a></div><a href="https://animetosho.org/storage/test.torrent">Torrent</a><span title="Seeders: 0 / Leechers: 12">[0/12]</span></div>'''
rows=parse_page({'name':'Anime Tosho'},fixture,app)
assert len(rows)==1
r=rows[0];assert r['size_bytes']==1234 and r['seeders']==0 and r['leechers']==12 and r['date_ts']
assert r['resolution']=='1080p' and r['language'] and r['link_usable'] and r['metadata_archived']
missing=parse_page({},fixture.replace('Seeders: 0 / Leechers: 12','unknown'),app)[0]
assert missing['seeders'] is None and missing['leechers'] is None
with patch('animetosho_provider.requests.get',return_value=Mock(content=fixture.encode())) as get:
 result,status=app.fetch_source({'builtin_id':'animetosho','name':'Anime Tosho'},'Example',local_query='Example')
 assert result[0]['seeders']==0 and 'Archived' in status
 assert get.call_args.kwargs['params']=={'q':'Example'}
config={'sources':[{'builtin_id':'annas_archive','enabled':True},{'builtin_id':'animetosho','url':'https://feed.animetosho.org/rss2?only_tor=1&q={query}','enabled':False}]}
app.ensure_builtin_default_sources(config)
assert not any(s.get('builtin_id')=='annas_archive' for s in config['sources'])
assert config['sources'][0]['enabled'] is False and config['sources'][0]['type']=='HTML Search'
print('PASS AnimeTosho exact fields, unknown counts, query dispatch and source migration')
