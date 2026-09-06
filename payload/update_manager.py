"""GitHub-only, opt-out update checks and checksum-verified downloads."""
import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit
import requests
from PySide6.QtCore import QThread, Signal

API = 'https://api.github.com/repos/lykaiosx/AMF/releases/latest'


def version_tuple(text):
    if not re.fullmatch(r'v?\d+(?:\.\d+)*', text): raise ValueError('Unsupported version format')
    parts = tuple(int(x) for x in text.lstrip('v').split('.'))
    return parts + (0,) * max(0, 4-len(parts))


def release_asset(release, current):
    if release.get('draft') or release.get('prerelease') or version_tuple(release['tag_name']) <= version_tuple(current): return None
    for asset in release.get('assets', []):
        url = asset.get('browser_download_url', '')
        parsed = urlsplit(url)
        if (re.fullmatch(r'AMF-[0-9.]+-Setup\.exe', asset.get('name','')) and parsed.scheme == 'https'
                and parsed.netloc == 'github.com' and parsed.path.startswith('/lykaiosx/AMF/releases/download/')
                and re.fullmatch(r'sha256:[a-f0-9]{64}', asset.get('digest') or '')):
            return dict(asset)
    raise ValueError('The release does not contain a verified Windows installer.')


class UpdateWorker(QThread):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(int)
    def __init__(self, current, folder, asset=None, parent=None):
        super().__init__(parent)
        self.current, self.folder, self.asset = current, Path(folder), asset
    def run(self):
        try:
            if self.asset is None:
                response = requests.get(API, timeout=(10,30), headers={'Accept':'application/vnd.github+json'})
                response.raise_for_status()
                release = response.json()
                self.result.emit({'asset':release_asset(release,self.current), 'version':release['tag_name'],
                                  'notes':str(release.get('body') or '')[:8000]})
                return
            # Re-validate metadata supplied to the downloader independently.
            release_asset({'tag_name':'9999', 'assets':[self.asset]}, '0') or (_ for _ in ()).throw(ValueError('Invalid asset'))
            self.folder.mkdir(parents=True, exist_ok=True)
            destination = self.folder / self.asset['name']
            temporary = destination.with_suffix('.part')
            digest, total = hashlib.sha256(), 0
            try:
                with requests.get(self.asset['browser_download_url'], stream=True, timeout=(10,45)) as response:
                    response.raise_for_status()
                    parsed = urlsplit(response.url)
                    if parsed.scheme != 'https' or parsed.hostname not in ('github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'):
                        raise ValueError('Unexpected update download host')
                    with temporary.open('wb') as stream:
                        for block in response.iter_content(256*1024):
                            if self.isInterruptionRequested(): raise RuntimeError('Download cancelled')
                            stream.write(block)
                            digest.update(block)
                            total += len(block)
                            self.progress.emit(min(99, int(total * 100 / max(1,self.asset['size']))))
                if total != self.asset['size'] or 'sha256:'+digest.hexdigest() != self.asset['digest']:
                    raise ValueError('Installer verification failed; the download was discarded')
                temporary.replace(destination)
                self.result.emit({'path':str(destination)})
            finally:
                temporary.unlink(missing_ok=True)
        except Exception as exc:
            self.error.emit(str(exc))
