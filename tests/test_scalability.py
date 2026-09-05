import sys, tempfile, time, json
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'payload'))
import app
from PySide6.QtWidgets import QApplication, QComboBox
from PySide6.QtCore import Qt, QTimer
from cart_sender import CartSender, replay_receipts

qt = QApplication([])
with tempfile.TemporaryDirectory(prefix='amf-410-') as directory:
    state = Path(directory)
    app.APP_DIR, app.CONFIG_FILE, app.CART_FILE, app.PID_FILE = state, state/'config.json', state/'cart.json', state/'amf.pid'
    app.migrate_previous_state = lambda: None
    window = app.AnimeDownloader()
    window.show()
    baseline_widgets = len(window.findChildren(QComboBox))
    window.cart = [dict(title=f'Series S01E{i:05} 1080p', link=f'magnet:?xt=urn:btih:{i:040x}',
                        source='Test', size_bytes=1024, type='Series', destination_custom=True) for i in range(20000)]
    started = time.perf_counter()
    window.refresh_cart()
    qt.processEvents()
    duration = time.perf_counter()-started
    assert window.cart_model.rowCount() == 20000
    assert len(window.findChildren(QComboBox)) == baseline_widgets
    assert duration < 15, duration
    window.cart_model.setData(window.cart_model.index(10000, 3), 'Books')
    assert window.cart[10000]['save_path'] == r'D:\Books'
    window.cart_table.selectRow(19999)
    window.remove_selected_cart()
    assert len(window.cart) == 19999
    assert window.cart[-1]['title'].endswith('19998 1080p')
    for width, height in [(800,600), (1024,700), (1380,860)]:
        window.resize(width,height)
        for tab in range(4):
            window.tabs.setCurrentIndex(tab)
            window.adapt_layout()
            qt.processEvents()
            assert window.width() <= width, (width, window.width())
            window.grab().save(str(state / f'ui-{width}-{tab}.png'))
    print(f'PASS: 20,000 cart rows refreshed in {duration:.2f}s; no per-row widgets; edit/remove; 3 window sizes x 4 tabs.')
    class UIClient:
        def auth_log_in(self): pass
        def torrents_add(self, urls, save_path):
            if urls.endswith('3'): raise RuntimeError('test rejection')
            return 'Ok.'
    window.config['torrent_client'] = 'qBittorrent'
    app.qbittorrentapi.Client = lambda **kw: UIClient()
    window.cart = [dict(title='Test', type='Series', destination_custom=True,
                        link='magnet:test'+str(i)) for i in range(10)]
    window.refresh_cart()
    window.send_cart_to_qbittorrent()
    assert not window.send_cart_button.isEnabled()
    window.cart.append(dict(title='Added during send', link='magnet:new', type='Books', destination_custom=True))
    deadline = time.monotonic() + 30
    while window.cart_sender is not None and time.monotonic() < deadline:
        qt.processEvents()
        time.sleep(.001)
    assert window.cart_sender is None
    assert len(window.cart) == 2, window.cart
    assert window.send_cart_button.isEnabled()
    assert len(json.loads(app.CART_FILE.read_text())) == 2
    assert not (state/'sent-receipts.jsonl').exists()
    print('PASS: application send integration; failed/new items retained; controls restored; cart persisted.')
    window.close()

    class Client:
        def auth_log_in(self): pass
        def torrents_add(self, urls, save_path):
            if urls.endswith('3'): raise RuntimeError('test client rejection')
            return 'Ok.'
    batch = [(dict(_queue_id=str(i), link='magnet:test'+str(i), save_path=r'D:\Series'), {}) for i in range(1000)]
    worker = CartSender(Client, batch, state/'receipts.jsonl', app)
    results = []
    worker.progress.connect(lambda *args: results.append(args))
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(1)
    worker.start()
    while worker.isRunning():
        qt.processEvents()
        time.sleep(.001)
    qt.processEvents()
    worker.wait()
    timer.stop()
    sent = [r for r in results if r[1]=='Sent']
    assert len(sent) == 900, len(sent)
    remaining = replay_receipts([i for i,s in batch], state/'receipts.jsonl')
    assert len(remaining) == 100
    assert ticks, 'UI timer was blocked'
    cancelled = CartSender(Client, batch, state/'cancel.jsonl', app)
    def cancel_first(key,status,error):
        if status=='Sending': cancelled.requestInterruption()
    cancelled.progress.connect(cancel_first, Qt.DirectConnection)
    cancelled.start()
    cancelled.wait()
    assert len((state/'cancel.jsonl').read_text().splitlines()) == 1
    print('PASS: 1,000 mock transfers; 900 durable successes, 100 failures retained; responsive event loop; cancellation stops new sends.')

