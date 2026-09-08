import sys,tempfile,hashlib
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'payload'))
import app
from metadata_cache import prepare,read_cached,validate,PreparationWorker
from yts_provider import is_yts_item,metadata_url
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
qt=QApplication([])
info=b'd6:lengthi0e4:name7:example12:piece lengthi16384e6:pieces0:e'
data=b'd4:info'+info+b'e';code=hashlib.sha1(info).hexdigest()
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory)
 app.APP_DIR,app.CONFIG_FILE,app.CART_FILE,app.PID_FILE=root,root/'config.json',root/'cart.json',root/'amf.pid'
 app.migrate_previous_state=lambda:None
 for name in ('nyaa.si','1377x.to','yts.gg','The Pirate Bay','Anime Tosho','EZTV','FitGirl Repacks'):
  item=dict(title='Example',source=name,link='magnet:?xt=urn:btih:'+code,detail_url='https://example.test/detail')
  source={'name':name,'url':'https://example.test/'}
  if name=='yts.gg':source.update(builtin_id='yts',url='https://yts.gg')
  with patch('metadata_cache.download',side_effect=lambda url,*args:data if '/file.torrent' in url or '/torrent/download/' in url else b'<a href="/file.torrent">Torrent</a>'):
   path=prepare(item,source,root,app)
  assert Path(path).read_bytes()==data
  assert read_cached(dict(item,metadata_path=path),app)==data
  Path(path).unlink()
 try:validate(data,{'info_hash':'a'*40},app)
 except ValueError:pass
 else:raise AssertionError('Wrong hash accepted')
 mirrored={'title':'Akira [YTS] [YIFY]','link':'magnet:?xt=urn:btih:'+code,'source':'1377x.to'}
 assert is_yts_item(mirrored,{'url':'https://www.1377x.to'})
 assert metadata_url(mirrored,{'url':'https://www.1377x.to'}).startswith('https://yts.gg/')
 window=app.AnimeDownloader()
 source=window.config['sources'][0]['name']
 rows=[dict(title=str(n),source=source,seeders=n,leechers=n,size_bytes=n,link='magnet:?xt=urn:btih:'+str(n).zfill(40),link_usable=True,provider_page=True) for n in (19,243,27)]
 window.search_finished(rows,{source:('OK','')})
 assert window.results_table.isSortingEnabled()
 for column in (6,7,8):
  window.results_table.sortItems(column,Qt.AscendingOrder)
  assert [window.results_table.item(r,1).text() for r in range(3)]==['19','27','243']
  window.results_table.sortItems(column,Qt.DescendingOrder)
  assert [window.results_table.item(r,1).text() for r in range(3)]==['243','27','19']
 window.close()
 client=Mock();client.app_web_api_version.return_value='2.11.9'
 client.torrents_fetch_metadata.return_value={'name':'example'}
 with patch.object(app.qbittorrentapi,'Client',return_value=client):
  worker=PreparationWorker([],root,app,profile={'host':'localhost'})
  assert worker.peer_metadata({'link':'magnet:?xt=urn:btih:'+code})
  client.torrents_add.assert_not_called()
  client.app_web_api_version.return_value='2.8.0'
  client.torrents_fetch_metadata.reset_mock()
  assert not worker.peer_metadata({'link':'magnet:?xt=urn:btih:'+code})
  client.torrents_fetch_metadata.assert_not_called()
print('PASS: all seven source metadata paths, cache validation, mirrored YTS, and numeric sorting after provider-page results')
