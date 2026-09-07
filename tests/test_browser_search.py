"""Mixed browser/ordinary source results finish together and obey enable toggles."""
import sys, tempfile, time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'payload'))
import app
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
qt = QApplication([])
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    app.APP_DIR, app.CONFIG_FILE, app.CART_FILE, app.PID_FILE = root, root/'config.json', root/'cart.json', root/'amf.pid'
    app.migrate_previous_state = lambda: None
    window = app.AnimeDownloader()
    window.config['sources'] = [dict(name='EZTV', builtin_id='eztv', enabled=True),
                                dict(name='Anna', builtin_id='annas_archive', enabled=True),
                                dict(name='Regular', enabled=True)]
    window.config['browser_session_sources'] = ['eztv', 'annas_archive']
    calls = []
    class Session:
        def __init__(self, source): self.source = source
        def request_background(self, query, done):
            calls.append((self.source['name'], query))
            QTimer.singleShot(50 if self.source['name']=='EZTV' else 100,
                lambda: done([{'title':query, 'source':self.source['name'], 'link':self.source['name']+query}], 'Browser OK'))
    window.provider_session = lambda source: Session(source)
    def ordinary(source, query, *args):
        assert source['name'] == 'Regular', 'Verified provider was sent to ordinary HTTP search'
        return [{'title':query, 'source':'Regular', 'link':'regular'+query}], 'OK'
    def search(query):
        window.search_input.setText(query)
        window.search_sources()
        # Enter cannot start a second search while browser results are pending.
        window.search_sources()
        deadline = time.monotonic()+5
        while not window.search_btn.isEnabled():
            qt.processEvents()
            if time.monotonic()>deadline: raise AssertionError('Combined search did not finish')
            time.sleep(.01)
    with patch.object(app, 'fetch_source', ordinary):
        search('first query')
        assert len(window.search_results)==3 and len(calls)==2
        window.config['sources'][1]['enabled']=False
        search('second query')
        assert len(window.search_results)==2 and calls[-1]==('EZTV','second query') and len(calls)==3
        assert all(r['title']=='second query' for r in window.search_results)
        window.config['sources'][2]['enabled']=False
        search('browser only')
        assert len(window.search_results)==1 and window.search_results[0]['source']=='EZTV'
    window.close()
print('PASS: mixed searches wait for browser results; disabled sources excluded; repeated Enter ignored; browser-only searches finish.')
