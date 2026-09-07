"""YTS sends complete verified metainfo, including old saved magnet entries."""
import sys, tempfile, hashlib
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'payload'))
import app
from cart_sender import CartSender
from yts_provider import fetch_metadata
from PySide6.QtCore import QCoreApplication
qt = QCoreApplication([])
info = b'd6:lengthi0e4:name7:example12:piece lengthi16384e6:pieces0:e'
data = b'd4:info' + info + b'e'
code = hashlib.sha1(info).hexdigest()
source = {'name':'yts.gg', 'builtin_id':'yts', 'url':'https://yts.gg'}
api = Mock()
api.fetch_torrent_payload.return_value = data
api.bdecode_torrent_value = app.bdecode_torrent_value
api.qb_add_result_failed = app.qb_add_result_failed
with tempfile.TemporaryDirectory() as directory:
    for old in (True, False):
        item = dict(_queue_id=str(old), source='yts.gg', title='Example', save_path=directory,
                    link='magnet:?xt=urn:btih:'+code if old else 'https://yts.gg/torrent/download/'+code)
        client = Mock()
        client.name = 'test client'
        client.torrents_add.return_value = 'Ok.'
        sender = CartSender(lambda:client, [(item,source)], Path(directory)/'receipts', api)
        sender.run()
        client.torrents_add.assert_called_once_with(torrent_files=data, save_path=directory)
        assert code.upper() in api.fetch_torrent_payload.call_args.args[0]
    client.reset_mock()
    api.fetch_torrent_payload.return_value = data.replace(b'example', b'changed')
    failed = []
    sender = CartSender(lambda:client, [(item,source)], Path(directory)/'bad-receipts', api)
    sender.progress.connect(lambda *args: failed.append(args))
    sender.run()
    client.torrents_add.assert_not_called()
    assert failed[-1][1] == 'Failed' and 'hash does not match' in failed[-1][2]
    assert (Path(directory)/'bad-receipts').read_text() == ''
    api.fetch_torrent_payload.side_effect = TimeoutError('offline')
    failed.clear()
    sender.run()
    client.torrents_add.assert_not_called()
    assert failed[-1][1] == 'Failed' and 'remains in the cart' in failed[-1][2]
print('PASS: new YTS links and saved magnets send complete torrent bytes; mismatched/unavailable metadata never sends a magnet or writes success receipts.')
