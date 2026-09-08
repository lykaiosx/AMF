"""Media routing, source parsing and client integrations for AMF."""
import base64
import hashlib
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote, urlsplit

import requests
from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QPushButton, QLabel, QLineEdit, QHBoxLayout
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy


class BatchSourceTest(QThread):
    result_ready = Signal(str, str, str)

    def __init__(self, sources, query, fetch, parent=None):
        super().__init__(parent)
        self.sources = copy.deepcopy(sources)
        self.query, self.fetch = query, fetch

    def test_one(self, source):
        if self.isInterruptionRequested():
            return source.get('name', ''), 'CANCELLED', 'Cancelled'
        try:
            results, status = self.fetch(source, self.query, timeout=12, match_mode='Smart', local_query=self.query)
            usable = sum(bool(r.get('link_usable')) for r in results)
            return source.get('name', ''), 'OK', f'{len(results)} results, {usable} download links — {status}'
        except Exception as exc:
            return source.get('name', ''), 'ERROR', str(exc)

    def run(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(self.test_one, source) for source in self.sources]
            for future in as_completed(futures):
                self.result_ready.emit(*future.result())


def add_batch_test_controls(window, layout, fetch):
    row = QHBoxLayout()
    query = QLineEdit('test')
    query.setPlaceholderText('One search term for all sources')
    start = QPushButton('Test All Sources')
    cancel = QPushButton('Cancel Tests')
    cancel.setEnabled(False)
    progress = QLabel('Tests all sources, including disabled sources.')
    progress.setWordWrap(True)
    row.addWidget(query, 1)
    row.addWidget(start)
    row.addWidget(cancel)
    layout.addLayout(row)
    layout.addWidget(progress)
    window.batch_test_button = start
    window.batch_test_progress = progress
    window.batch_test_query = query
    counts = {}

    def result(name, code, text):
        window.source_status[name] = (code, text)
        counts[code] = counts.get(code, 0) + 1
        window.refresh_sources()
        progress.setText(f"{sum(counts.values())}/{len(window.batch_test_worker.sources)} tested • {counts.get('OK', 0)} connected • {counts.get('ERROR', 0)} failed • {counts.get('CANCELLED', 0)} cancelled")

    def finished():
        start.setEnabled(True)
        cancel.setEnabled(False)
        query.setEnabled(True)
        progress.setText('Finished: ' + progress.text())

    def begin():
        if getattr(window, 'test_worker', None) and window.test_worker.isRunning():
            window.toast.show_message('Wait for the individual source test to finish', 3500)
            return
        sources = window.config.get('sources', [])
        if not sources:
            progress.setText('No sources to test.')
            return
        counts.clear()
        start.setEnabled(False)
        cancel.setEnabled(True)
        query.setEnabled(False)
        for source in sources:
            window.source_status[source.get('name', '')] = ('WAIT', 'Queued for testing')
        window.refresh_sources()
        progress.setText(f'0/{len(sources)} tested')
        worker = BatchSourceTest(sources, query.text().strip() or 'test', fetch, window)
        window.batch_test_worker = worker
        worker.result_ready.connect(result)
        worker.finished.connect(finished)
        worker.start()

    def stop():
        window.batch_test_worker.requestInterruption()
        cancel.setEnabled(False)
        progress.setText('Cancelling; waiting for current requests to finish…')

    start.clicked.connect(begin)
    cancel.clicked.connect(stop)

DESTINATIONS = {
    "Books": ("books_path", r"D:\Books"),
    "Games": ("games_path", r"D:\Games"),
    "Movie": ("movies_path", r"D:\Movies"),
    "Series": ("series_path", r"D:\Series"),
    "Anime Movie": ("anime_movies_path", r"D:\Anime\Movies"),
    "Anime Series": ("anime_series_path", r"D:\Anime\Series"),
    "Music": ("music_path", r"D:\Music"),
}


def infer_destination(item, source=None):
    source = source or {}
    title = str(item.get("title", ""))
    category = str(item.get("category", "")).lower()
    host = urlsplit(source.get("url") or item.get("detail_url") or item.get("link") or "").hostname or ""
    provider = source.get("builtin_id", "")
    name = str(item.get("source", "")).lower()
    if provider == "annas_archive" or host.endswith("annas-archive.gl") or any(word in category for word in ("book", "ebook", "literature")) or re.search(r"\b(epub|mobi|audiobook)\b", title, re.I):
        return "Books"
    if "game" in category or re.search(r"\b(PC game|GOG|CODEX|FLT|DODI|FitGirl|repack)\b", title, re.I):
        return "Games"
    anime = "anime" in category or bool(re.search(r"\banime\b", title, re.I))
    anime |= provider in ("nyaa", "animetosho") or host == "nyaa.si" or host.endswith("animetosho.org") or "nyaa" in name
    if any(word in category for word in ("music", "audio")) or re.search(r"\b(FLAC|MP3|discography|soundtrack|OST)\b", title, re.I):
        return "Music"
    movie = item.get("kind") == "Movie" or "movie" in category or "film" in category
    movie |= bool(re.search(r"\b(movie|film|gekijouban|gekijōban)\b|劇場版", title, re.I))
    movie |= provider == "yts" or host in ("yts.gg", "yts.mx") or bool(re.search(r"\b(yts|yify)\b", name))
    if anime:
        return "Anime Movie" if movie else "Anime Series"
    if movie:
        return "Movie"
    return item.get("type") if item.get("type") in DESTINATIONS else "Series"


def parse_piratebay(payload, source):
    if not isinstance(payload, list):
        raise ValueError("The Pirate Bay returned an unexpected response")
    results = []
    categories = {"201": "Movies", "202": "Movies", "205": "TV Series", "207": "Movies", "208": "TV Series", "209": "Movies", "211": "Movies"}
    for row in payload:
        if not isinstance(row, dict):
            continue
        info_hash = str(row.get("info_hash", ""))
        if not re.fullmatch(r"[0-9a-fA-F]{40}", info_hash) or info_hash == "0" * 40:
            continue
        title = str(row.get("name", "")).strip()
        if not title:
            continue
        cat = str(row.get("category", ""))
        category = "Games" if cat.startswith("4") else ("Music" if cat.startswith("1") else categories.get(cat, "Other"))
        def number(key):
            try:
                return max(0, int(row.get(key) or 0))
            except (ValueError, TypeError):
                return 0
        item = {"title": title, "source": source.get("name", "The Pirate Bay"),
                "category": category, "size_bytes": number("size"),
                "size": f"{number('size') / 1024**3:.2f} GB", "seeders": number("seeders"),
                "leechers": number("leechers"), "link_usable": True, "link_kind": "Magnet",
                "link": "magnet:?xt=urn:btih:" + info_hash + "&dn=" + quote(title),
                "detail_url": "https://thepiratebay.org/description.php?id=" + quote(str(row.get("id", ""))),
                "kind": "Movie" if category == "Movies" else "Unknown"}
        item["type"] = infer_destination(item, source)
        item["scope"] = "Movie" if "Movie" in item["type"] else "Unknown"
        resolution = re.search(r"\b(2160p|1080p|720p|480p)\b", title, re.I)
        item["resolution"] = resolution.group(1).lower() if resolution else ""
        results.append(item)
    return results


def fetch_piratebay(source, query, timeout):
    response = requests.get("https://apibay.org/q.php", params={"q": query, "cat": "0"}, timeout=timeout)
    response.raise_for_status()
    results = parse_piratebay(response.json(), source)
    return results, f"The Pirate Bay • {len(results)} results • API search"


class RemoteClient:
    """Expose the add/login contract used by the cart, with confirmed RPC results."""
    def __init__(self, name, profile):
        self.name, self.profile = name, profile
        self.session = requests.Session()
        host = profile.get("host") or "127.0.0.1"
        if not host.startswith(("http://", "https://")):
            host = "http://" + host
        parsed = urlsplit(host)
        port = profile.get("port", 8112 if name == "Deluge" else 9091)
        self.url = f"{parsed.scheme}://{parsed.hostname}:{port}" + ("/json" if name == "Deluge" else "/transmission/rpc")
        if name == "Transmission":
            self.session.auth = (profile.get("username", ""), profile.get("password", ""))

    def rpc(self, method, args):
        body = {"method": method, "params": args, "id": 1} if self.name == "Deluge" else {"method": method, "arguments": args}
        response = self.session.post(self.url, json=body, timeout=20)
        if self.name == "Transmission" and response.status_code == 409:
            token = response.headers.get("X-Transmission-Session-Id")
            if not token:
                raise RuntimeError("Transmission did not supply a session token")
            self.session.headers["X-Transmission-Session-Id"] = token
            response = self.session.post(self.url, json=body, timeout=20)
        response.raise_for_status()
        data = response.json()
        if self.name == "Deluge":
            if data.get("error"):
                raise RuntimeError(str(data["error"]))
            return data.get("result")
        if data.get("result") != "success":
            raise RuntimeError(str(data.get("result", "Invalid RPC response")))
        return data.get("arguments", {})

    def auth_log_in(self):
        if self.name == "Deluge":
            if not self.rpc("auth.login", [self.profile.get("password", "")]):
                raise RuntimeError("Deluge Web password was rejected")
            if not self.rpc("web.connected", []):
                raise RuntimeError("Connect Deluge Web to a daemon first")
        else:
            self.rpc("session-get", {})

    def torrents_add(self, urls=None, torrent_files=None, save_path=None):
        encoded = base64.b64encode(torrent_files).decode("ascii") if torrent_files else None
        if self.name == "Deluge":
            options = {"download_location": save_path}
            result = self.rpc("core.add_torrent_file", ["amf.torrent", encoded, options]) if encoded else self.rpc("core.add_torrent_magnet", [urls, options])
            if not result:
                raise RuntimeError("Deluge did not confirm the torrent was added; check for a duplicate")
        else:
            args = {"download-dir": save_path, "metainfo" if encoded else "filename": encoded or urls}
            result = self.rpc("torrent-add", args)
            if not (result.get("torrent-added") or result.get("torrent-duplicate")):
                raise RuntimeError("Transmission did not confirm the torrent")
        return "Ok."


def install_features(cls):
    def result_selection_key(self, result):
        return (result.get("source", ""), result.get("detail_url") or result.get("link") or result.get("title", ""))

    def remember_selection(self, key, checked):
        if checked:
            self.selected_result_keys.add(key)
        else:
            self.selected_result_keys.discard(key)

    def change_result_selection(self, mode):
        if mode == "clear":
            self.selected_result_keys.clear()
        for row in range(self.results_table.rowCount()):
            box = self.results_table.cellWidget(row, 0)
            if box and not self.results_table.isRowHidden(row):
                box.setChecked(not box.isChecked() if mode == "invert" else False)

    def choose_extra_path(self, edit):
        selected = QFileDialog.getExistingDirectory(self, "Choose Default Folder", edit.text())
        if selected:
            edit.setText(selected)

    def store_client_profile(self):
        name = self._editing_client
        profile = {"host": self.qb_host.text().strip(), "port": self.qb_port.value(),
                   "username": self.qb_user.text(), "password": self.qb_password.text(),
                   "executable": self.client_executable.text().strip()}
        if name == "qBittorrent":
            self.config["qbittorrent"] = profile
        else:
            self.config.setdefault("client_profiles", {})[name] = profile

    def load_client_profile(self):
        name = self._editing_client
        profile = self.config.get("qbittorrent", {}) if name == "qBittorrent" else self.config.get("client_profiles", {}).get(name, {})
        self.qb_host.setText(profile.get("host", "127.0.0.1"))
        self.qb_port.setValue(profile.get("port", {"Deluge": 8112, "Transmission": 9091}.get(name, 8080)))
        self.qb_user.setText(profile.get("username", ""))
        self.qb_password.setText(profile.get("password", ""))
        self.client_executable.setText(profile.get("executable", ""))
        desktop = name in ("uTorrent", "Other desktop client")
        self.client_executable.setEnabled(desktop)
        for widget in (self.qb_host, self.qb_port, self.qb_user, self.qb_password):
            widget.setEnabled(not desktop)
        self.client_note.setText("Opens magnets/files in this client. Choose the displayed destination in its add dialog. Items remain in Cart until you remove them." if desktop else "Enable the client's Web UI / RPC service. Deluge requires its Web password and an already connected daemon. Download paths refer to the client computer.")

    def switch_client_profile(self, name):
        self.store_client_profile()
        self._editing_client = name
        self.load_client_profile()

    original_test = cls.test_qbittorrent
    def test_qbittorrent(self):
        if self.client_combo.currentText() not in ("uTorrent", "Other desktop client"):
            return original_test(self)
        self.save_settings(False)
        path = Path(self.client_executable.text())
        valid = path.is_file() and path.suffix.lower() == ".exe"
        QMessageBox.information(self, "Client", "Executable found. Opening a torrent will hand it to this client." if valid else "Enter the full path to an existing client .exe.")

    def open_cart_in_desktop_client(self):
        name = self.config["torrent_client"]
        executable = self.config.get("client_profiles", {}).get(name, {}).get("executable", "")
        if not Path(executable).is_file() or Path(executable).suffix.lower() != ".exe":
            QMessageBox.warning(self, "Client", "Choose the client executable in Settings and save it first.")
            return
        from book_downloads import is_book_page
        for item in self.cart:
            if is_book_page(item): continue
            link = item.get("local_torrent_path") or item.get("link", "")
            if not link:
                continue
            try:
                subprocess.Popen([executable, link], shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                item["cart_status"] = "Opened — confirm in client"
                item["last_error"] = "Choose destination: " + self.effective_item_save_path(item)
            except OSError as exc:
                item["cart_status"] = "Failed"
                item["last_error"] = str(exc)
        self.save_cart()
        self.refresh_cart()
        self.toast.show_message("Opened in client. Confirm its save folders; cart items were retained.", 6000)
        from reliability import record_history
        import sys
        root = sys.modules[cls.__module__].APP_DIR
        for item in self.cart:
            record_history(root, item, name, item.get('cart_status', 'Opened'), item.get('last_error', ''))

    for name, method in list(locals().items()):
        if callable(method) and name not in ("cls", "original_test"):
            setattr(cls, name, method)
