"""Exercise real Qt browser session reuse against a local synthetic provider."""
import sys, time, tempfile, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'payload'))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWebEngineCore import QWebEnginePage
from provider_pages import ProviderPageDialog

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        query = unquote(self.path.rsplit('/', 1)[-1])
        ready = 'verified=yes' in self.headers.get('Cookie', '')
        if not ready or query == 'expired':
            body = '<title>Just a moment</title><button id="verify" onclick="document.cookie=\'verified=yes; path=/; max-age=3600\';location.reload()">Synthetic verification</button>'
        else:
            body = f'<title>Results</title><table><tr><td><a class="epinfo" href="/ep/{query}">{query}</a></td><td>1 GB</td><td>4</td></tr></table>'
        encoded = body.encode()
        self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
qt = QApplication([])
def wait_for(condition, seconds=15):
    deadline = time.monotonic() + seconds
    while not condition():
        qt.processEvents()
        if time.monotonic() > deadline: raise AssertionError('Browser operation timed out')
        time.sleep(.01)

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
    source = {'builtin_id':'eztv', 'name':'Synthetic EZTV', 'url':f'http://127.0.0.1:{server.server_port}'}
    dialog = ProviderPageDialog(None, source, 'first', Path(directory)/'session')
    dialog.show()
    wait_for(lambda: dialog.browser.title() == 'Just a moment')
    # This button belongs to our local fixture, not a third-party challenge.
    dialog.browser.page().runJavaScript("document.getElementById('verify').click()")
    wait_for(lambda: dialog.browser.title() == 'Results')
    dialog.browser.page().toHtml(dialog.read_html)
    wait_for(lambda: dialog.rows is not None)
    assert dialog.rows[0]['title'] == 'first'
    assert not dialog.profile.isOffTheRecord()
    assert dialog.profile.httpCacheMaximumSize() == 16*1024*1024
    for query in ('second query', 'third'):
        completed = []
        dialog.request_background(query, lambda rows, summary: completed.append((rows, summary)))
        wait_for(lambda: bool(completed))
        assert completed[0][0][0]['title'] == query, completed
        assert not dialog.isVisible()
        dialog.discard_idle_page()
        qt.processEvents()
        assert dialog.browser.page().lifecycleState() == QWebEnginePage.Discarded
    completed = []
    dialog.request_background('expired', lambda rows, summary: completed.append((rows,summary)))
    wait_for(lambda: dialog.browser.title() == 'Just a moment')
    dialog.timeout.start(100)
    wait_for(lambda: bool(completed))
    assert completed[0][0] is None and 'attention' in completed[0][1]
    dialog.shutdown()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
server.shutdown()
print('PASS: one manual fixture verification; two hidden queries reuse cookies; idle discard/reload works; expired session reports attention without imported rows.')
