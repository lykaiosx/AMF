"""Serial, cancellable client transfers outside the UI thread; durable receipts."""
import json
import os
from pathlib import Path
from PySide6.QtCore import QThread, Signal


def replay_receipts(cart, receipt_path):
    sent = set()
    if Path(receipt_path).exists():
        for line in Path(receipt_path).read_text(encoding='utf-8').splitlines():
            try: sent.add(json.loads(line)['sent'])
            except (ValueError, KeyError): pass  # tolerate an interrupted final write
    return [item for item in cart if item.get('_queue_id') not in sent]


class CartSender(QThread):
    progress = Signal(str, str, str)
    failed = Signal(str)

    def __init__(self, client_factory, batch, receipt_path, api, parent=None):
        super().__init__(parent)
        self.client_factory, self.batch = client_factory, batch
        self.receipt_path, self.api = Path(receipt_path), api

    def run(self):
        client = None
        try:
            client = self.client_factory()
            client.auth_log_in()
            # Open the receipt file before any external operation, so a read-only
            # state folder cannot silently lose acknowledgement of sent torrents.
            with self.receipt_path.open('a', encoding='utf-8') as receipts:
                for item, source in self.batch:
                    if self.isInterruptionRequested(): break
                    key = item['_queue_id']
                    try:
                        link = str(item.get('link') or '').strip()
                        local = item.get('local_torrent_path')
                        path = item.get('save_path')
                        if not path: raise RuntimeError('No save location')
                        if not (link or local): raise RuntimeError('No torrent link or file')
                        self.progress.emit(key, 'Sending', '')
                        if local:
                            result = client.torrents_add(torrent_files=self.api.local_torrent_payload(local), save_path=path)
                        elif link.lower().startswith('magnet:'):
                            result = client.torrents_add(urls=link, save_path=path)
                        elif link.lower().startswith(('http://', 'https://')):
                            try:
                                data = self.api.fetch_torrent_payload(link, source=source, item=item, timeout=20, attempts=3)
                            except Exception:
                                magnet = self.api.magnet_fallback_from_detail(source, item, timeout=15)
                                if not magnet: raise
                                result = client.torrents_add(urls=magnet, save_path=path)
                            else:
                                result = client.torrents_add(torrent_files=data, save_path=path)
                        else:
                            raise RuntimeError('Unsupported torrent link')
                        if self.api.qb_add_result_failed(result): raise RuntimeError(str(result))
                        receipts.write(json.dumps({'sent': key}) + '\n')
                        receipts.flush()
                        os.fsync(receipts.fileno())
                        self.progress.emit(key, 'Sent', '')
                    except Exception as exc:
                        self.progress.emit(key, 'Failed', str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            close = getattr(client, 'close', None)
            if callable(close):
                try: close()
                except Exception: pass
