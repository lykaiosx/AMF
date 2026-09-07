import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'payload'))
import app
from fitgirl_provider import parse_search
from PySide6.QtCore import QCoreApplication
qt=QCoreApplication([])
source=dict(builtin_id='fitgirl',name='FitGirl Repacks',url='https://fitgirl-repacks.site/all-my-repacks-a-z/',enabled=False)
config={'sources':[source]};app.ensure_builtin_default_sources(config)
assert source['enabled'] is False and source['search_mode']=='Search Endpoint'
fixture='<article><h2 class="entry-title"><a href="/game/">Game</a></h2><span class="cat-links"><a>Lossless Repacks</a></span></article><a class="next page-numbers" href="/?s=game&amp;paged=2">Next</a>'
rows,nxt=parse_search(fixture,'https://fitgirl-repacks.site/?s=game')
assert len(rows)==1 and 'paged=2' in nxt
assert parse_search('<section class="no-results"></section>','https://fitgirl-repacks.site/')[0]==[]
try: parse_search('<html>Verification required</html>','https://fitgirl-repacks.site/')
except ValueError: pass
else: raise AssertionError('Challenge must not be treated as no matches')
if '--live' in sys.argv:
 for query in ['Cyberpunk 2077','BLUD']:
  worker=app.SearchWorker([source],query);captured=[]
  worker.finished_search.connect(lambda rows,status:captured.append((rows,status)))
  worker.run()
  assert captured and captured[0][0],captured
  print(query,len(captured[0][0]),captured[0][1])
print('PASS FitGirl search and migration')
# Pagination must request subsequent pages and deduplicate repeated posts.
from unittest.mock import patch
from types import SimpleNamespace
from fitgirl_provider import fetch_fitgirl
from usability_core import theme_css, PALETTES
responses=[SimpleNamespace(content=fixture.encode(),raise_for_status=lambda:None),SimpleNamespace(content=fixture.split('<a class="next')[0].replace('/game/','/second/').encode(),raise_for_status=lambda:None)]
with patch('fitgirl_provider.requests.get',side_effect=responses) as get:
 rows,status=fetch_fitgirl(source,'game')
 assert len(rows)==2 and get.call_count==2
 assert 'paged=2' in get.call_args.args[0]
for name,palette in PALETTES.items():
 css=theme_css('',palette)
 assert f"background: {palette['accent']}" in css and '#22c55e' not in css
 assert ('checkmark-black.svg' in css)==(name=='High Contrast')
print('PASS pagination and theme accent contrast')
