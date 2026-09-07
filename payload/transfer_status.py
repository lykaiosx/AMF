"""Read actual client state; accepting a torrent is not download completion."""
from PySide6.QtCore import QThread, Signal
import qbittorrentapi


def explain(item):
    state = item.get('state', '')
    if item.get('progress', 0) >= 1: return 'Download complete'
    if state in ('error', 'missingFiles'): return 'File or disk error — check the save folder in qBittorrent'
    if state in ('stoppedDL', 'pausedDL'): return 'Stopped — resume this download in qBittorrent'
    if state == 'queuedDL': return 'Waiting for a download slot in qBittorrent'
    if 'meta' in state.lower(): return 'Waiting for metadata — resend YTS from the updated AMF'
    if state == 'stalledDL' and not item.get('num_seeds', 0):
        return 'Waiting for seeds — the provider count does not guarantee reachable peers'
    if state == 'stalledDL': return 'Peers connected but not sending data yet'
    return state or 'Unknown state'


class TransferStatusWorker(QThread):
    report = Signal(str)
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = dict(profile)
    def run(self):
        client = None
        try:
            p = self.profile
            client = qbittorrentapi.Client(host=p.get('host','127.0.0.1'), port=int(p.get('port',8080)),
                username=p.get('username',''), password=p.get('password',''), REQUESTS_ARGS={'timeout':10})
            client.auth_log_in()
            connection = client.transfer_info()
            lines = ['Connection: '+str(connection.get('connection_status','unknown')),
                     'DHT nodes: '+str(connection.get('dht_nodes',0)),
                     'Sent in AMF means accepted by the client, not download complete.']
            if client.transfer_speed_limits_mode():
                limit = client.app_preferences().get('alt_dl_limit',0)
                lines.append(f'Alternate download limits are active ({limit} bytes/sec; 0 means unlimited).')
            pending = [item for item in client.torrents_info() if item.get('progress',0)<1]
            if not pending: lines.append('No incomplete downloads in this client.')
            for item in pending[:30]:
                if self.isInterruptionRequested(): break
                lines.append('\n'+item['name']+'\n'+explain(item))
                if item.get('state') == 'stalledDL':
                    trackers = client.torrents_trackers(torrent_hash=item['hash'])
                    failed = sum(t.get('status')==4 for t in trackers)
                    if failed: lines.append(f'{failed} tracker(s) report errors. Open Trackers in qBittorrent for details.')
            if len(pending)>30: lines.append(f'\nShowing 30 of {len(pending)} incomplete downloads.')
            self.report.emit('\n'.join(lines))
        except Exception as exc:
            self.report.emit('Could not read qBittorrent status: '+str(exc))
        finally:
            if client is not None:
                try: client.auth_log_out()
                except Exception: pass
