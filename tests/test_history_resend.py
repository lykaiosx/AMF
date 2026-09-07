import sys, tempfile, sqlite3, time
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'payload'))
import app
from reliability import history_entries, history_download, record_history
from PySide6.QtWidgets import QApplication, QPushButton
from selection_ui import ToggleRowTable
qt=QApplication([])
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    db=sqlite3.connect(root/'history.sqlite3')
    db.execute('CREATE TABLE events (event_id TEXT PRIMARY KEY,time TEXT,title TEXT,identity TEXT,client TEXT,destination TEXT,status TEXT,error TEXT)')
    db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?)',('old','2026-09-07','Old example','btih:'+'ab'*20,'qBittorrent',directory,'Sent',''))
    db.commit();db.close()
    entry=history_entries(root)[0]
    restored=history_download(entry)
    assert restored['link']=='magnet:?xt=urn:btih:'+'ab'*20
    assert restored['save_path']==directory
    app.APP_DIR,app.CONFIG_FILE,app.CART_FILE,app.PID_FILE=root,root/'config.json',root/'cart.json',root/'amf.pid'
    app.migrate_previous_state=lambda:None
    window=app.AnimeDownloader()
    window.cart=[{'title':'Unrelated cart item','link':'magnet:?xt=urn:btih:'+'cd'*20}]
    history=window.tabs.widget(3)
    table=history.findChild(ToggleRowTable)
    table.selectRow(0)
    client=Mock()
    client.name='qBittorrent'
    client.torrents_add.return_value='Ok.'
    with patch.object(app.qbittorrentapi,'Client',return_value=client):
        next(b for b in history.findChildren(QPushButton) if b.text()=='Add to qBittorrent').click()
        deadline=time.monotonic()+5
        while window.history_sender.isRunning():
            qt.processEvents();time.sleep(.01)
            assert time.monotonic()<deadline
        qt.processEvents()
    client.torrents_add.assert_called_once_with(urls=restored['link'],save_path=directory)
    assert len(window.cart)==1 and window.cart[0]['title']=='Unrelated cart item'
    new=history_entries(root)[0]
    assert len(history_entries(root))==2
    assert history_download(new)['link']==restored['link']
    saved=dict(title='Safe fields',link='magnet:?xt=urn:btih:'+'ef'*20,save_path=directory,password='DO_NOT_STORE',headers={'Secret':'DO_NOT_STORE'})
    record_history(root,saved,'qBittorrent','Sent')
    assert 'DO_NOT_STORE' not in history_entries(root)[0]['payload']
    window.close()
print('PASS: legacy history migrates; selected entry re-sends without searching or sending unrelated cart items; future entries retain reusable torrent data only.')
