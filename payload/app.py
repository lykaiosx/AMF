
import sys
import uuid
import os
import json
import re
import html
import urllib.parse
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QIcon
import ctypes
from scalable_ui import FlowLayout, CartModel, DestinationDelegate
from usability_core import PALETTES, theme_css, validate_theme, check_destinations, routed_destination
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QLineEdit, QPushButton, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QComboBox, QSpinBox, QGroupBox, QFormLayout, QCheckBox,
    QAbstractItemView, QFrame, QDialog, QDialogButtonBox, QPlainTextEdit, QInputDialog,
    QProgressDialog, QScrollArea, QTableView, QLayout
)

try:
    import qbittorrentapi
except ImportError:
    qbittorrentapi = None


# In a PyInstaller EXE, keep config/cart beside the executable while loading
# bundled resources (icon, etc.) from the temporary _MEIPASS directory.
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = Path(__file__).resolve().parent
    RESOURCE_DIR = APP_DIR

CONFIG_FILE = APP_DIR / "config.json"
CART_FILE = APP_DIR / "cart.json"

BACKGROUND_SERVICES = False
APP_NAME = "AMF"
APP_VERSION = "4.13"
APP_USER_MODEL_ID = "AMF.Desktop"
PID_FILE = APP_DIR / "amf.pid"

DEFAULT_CONFIG = {
    # Legacy root is kept only so old config files still load.
    "anime_root": "",
    "books_path": r"D:\Books",
    "games_path": r"D:\Games",
    "movies_path": r"D:\Movies",
    "series_path": r"D:\Series",
    "qbittorrent": {
        "host": "127.0.0.1",
        "port": 8080,
        "username": "",
        "password": ""
    },
    "anime_movies_path": r"D:\Anime\Movies",
    "anime_series_path": r"D:\Anime\Series",
    "music_path": r"D:\Music",
    "torrent_client": "qBittorrent",
    "client_profiles": {},
    "sources": [],
    "source_presets": [],
    "appearance": {"theme": "Dark", "text_size": 13, "density": 1.0},
    "show_first_run_tour": True,
    "routing_rules": [],
    "retention_days": 90,
    "backup_limit": 20
}


def migrate_previous_state():
    """Reuse V2/V2.1 state automatically when this folder is beside them."""
    candidates = [
        APP_DIR.parent / "AnimeDownloader_V2_8_11",
        APP_DIR.parent / "AnimeDownloader_V2_8_10",
        APP_DIR.parent / "AnimeDownloader_V2_8_9",
        APP_DIR.parent / "AnimeDownloader_V2_8_8",
        APP_DIR.parent / "AnimeDownloader_V2_8_7",
        APP_DIR.parent / "AnimeDownloader_V2_8_6",
        APP_DIR.parent / "AnimeDownloader_V2_8_5",
        APP_DIR.parent / "AnimeDownloader_V2_8_4",
        APP_DIR.parent / "AnimeDownloader_V2_8_3",
        APP_DIR.parent / "AnimeDownloader_V2_8_2",
        APP_DIR.parent / "AnimeDownloader_V2_8_1",
        APP_DIR.parent / "AnimeDownloader_V2_8",
        APP_DIR.parent / "AnimeDownloader_V2_7",
        APP_DIR.parent / "AnimeDownloader_V2_6",
        APP_DIR.parent / "AnimeDownloader_V2_5",
        APP_DIR.parent / "AnimeDownloader_V2_4",
        APP_DIR.parent / "AnimeDownloader_V2_3",
        APP_DIR.parent / "AnimeDownloader_V2_2",
        APP_DIR.parent / "AnimeDownloader_V2_1",
        APP_DIR.parent / "AnimeDownloader_V2",
    ]

    for filename in ("config.json", "cart.json"):
        dest = APP_DIR / filename
        if dest.exists():
            continue
        for old_dir in candidates:
            src = old_dir / filename
            if src.exists():
                try:
                    shutil.copy2(src, dest)
                    break
                except Exception:
                    pass




BUILTIN_DEFAULT_SOURCES = [
    {
        "builtin_id": "nyaa",
        "name": "Browse :: Nyaa",
        "type": "HTML Search",
        "search_mode": "Search Endpoint",
        "url": "https://nyaa.si/?q={query}",
        "query_param": "",
        "dynamic_feed_url": "https://nyaa.si/?page=rss&q={query}&c=0_0&f=0",
        "dynamic_feed_query_param": "",
        "results_path": "",
        "mappings": {},
        "headers": {},
        "enabled": True,
    },
    {
        "builtin_id": "1377x",
        "name": "1377x | Download torrents | 1337x.to | 1377x.to",
        "type": "HTML Search",
        "search_mode": "Search Endpoint",
        "url": "https://www.1377x.to/srch?search={query}",
        "query_param": "",
        "dynamic_feed_url": "",
        "dynamic_feed_query_param": "",
        "results_path": "",
        "mappings": {},
        "headers": {},
        "enabled": True,
    },
    {
        "builtin_id": "yts",
        "name": "YIFY movies: download HD quality official YIFY torrents",
        "type": "HTML Search",
        "search_mode": "Search Endpoint",
        "url": "https://yts.gg/search-movies?query={query}",
        "query_param": "",
        "dynamic_feed_url": "",
        "dynamic_feed_query_param": "",
        "results_path": "",
        "mappings": {},
        "headers": {},
        "enabled": True,
    },
]


def source_provider_identity(source):
    """
    Identify the four permanent built-in providers.

    Existing user configuration wins: if a source for that provider already
    exists, AMF leaves its settings/name/enabled state untouched.
    """
    source = source or {}

    builtin_id = str(
        source.get("builtin_id") or ""
    ).strip().lower()

    if builtin_id in {"nyaa", "1377x", "yts", "piratebay", "animetosho", "annas_archive", "eztv"}:
        return builtin_id

    url = str(
        source.get("url") or ""
    ).strip().lower()

    try:
        hostname = (
            urllib.parse.urlsplit(url).hostname
            or ""
        ).lower()
    except Exception:
        hostname = ""

    for domain, identity in [("animetosho.org", "animetosho"), ("annas-archive.gl", "annas_archive"), ("eztvx.to", "eztv")]:
        if hostname == domain or hostname.endswith("." + domain):
            return identity
    if hostname in ("thepiratebay.org", "www.thepiratebay.org", "apibay.org"):
        return "piratebay"

    if hostname == "nyaa.si" or hostname.endswith(".nyaa.si"):
        return "nyaa"

    if (
        hostname == "1377x.to"
        or hostname.endswith(".1377x.to")
        or hostname == "1337x.to"
        or hostname.endswith(".1337x.to")
    ):
        return "1377x"

    if (
        hostname == "yts.gg"
        or hostname.endswith(".yts.gg")
        or hostname == "yts.mx"
        or hostname.endswith(".yts.mx")
    ):
        return "yts"

    return ""


def ensure_builtin_default_sources(config):
    """
    Ensure Nyaa, 1377x and YTS always exist without deleting or overwriting
    user-added providers.

    Returns True when the config was modified.
    """
    if not isinstance(config, dict):
        return False

    sources = config.get("sources")

    if not isinstance(sources, list):
        sources = []
        config["sources"] = sources

    existing_ids = {
        source_provider_identity(source)
        for source in sources
        if isinstance(source, dict)
    }

    changed = False

    for builtin in BUILTIN_DEFAULT_SOURCES:
        provider_id = builtin["builtin_id"]

        if provider_id in existing_ids:
            continue

        sources.append(
            deep_copy(builtin)
        )
        existing_ids.add(provider_id)
        changed = True

    return changed


BUILTIN_DEFAULT_SOURCES.append({"builtin_id": "piratebay", "name": "The Pirate Bay",
    "type": "HTML Search", "search_mode": "Search Endpoint",
    "url": "https://thepiratebay.org/search.php?q={query}&cat=0",
    "enabled": True, "query_param": "", "mappings": {}, "headers": {}})

for identity, name, url, kind in [
    ("animetosho", "Anime Tosho", "https://feed.animetosho.org/rss2?only_tor=1&q={query}", "RSS / Atom"),
    ("annas_archive", "Anna's Archive", "https://annas-archive.gl/search?q={query}", "HTML Search"),
    ("eztv", "EZTV", "https://eztvx.to/search/{query}", "HTML Search"),
]:
    BUILTIN_DEFAULT_SOURCES.append({"builtin_id": identity, "name": name,
        "url": url, "type": kind, "search_mode": "Search Endpoint",
        "enabled": True, "query_param": "", "mappings": {}, "headers": {}})

BUILTIN_SOURCE_PRESETS = [
    {
        "preset_name": "FOSS Torrents",
        "source": {
            "name": "FOSS Torrents",
            "type": "RSS / Atom",
            "search_mode": "Static Feed",
            "url": "https://fosstorrents.com/feed/torrents.xml",
            "query_param": "",
            "dynamic_feed_url": "",
            "dynamic_feed_query_param": "",
            "results_path": "",
            "mappings": {},
            "headers": {},
            "enabled": True
        }
    },
    {
        "preset_name": "DistroWatch Torrents",
        "source": {
            "name": "DistroWatch",
            "type": "RSS / Atom",
            "search_mode": "Static Feed",
            "url": "https://distrowatch.com/news/torrents.xml",
            "query_param": "",
            "dynamic_feed_url": "",
            "dynamic_feed_query_param": "",
            "results_path": "",
            "mappings": {},
            "headers": {},
            "enabled": True
        }
    }
]

def deep_copy(obj):
    return json.loads(json.dumps(obj))


def load_json(path, default):
    """
    Load JSON while accepting both normal UTF-8 and UTF-8-with-BOM files.

    Older AMF installers used Windows PowerShell 5.1 to restore config.json
    and cart.json. Its UTF8 mode writes a BOM, which made json.loads() fail
    when the file was read as plain UTF-8.
    """
    if not path.exists():
        return deep_copy(default)

    try:
        return json.loads(
            path.read_text(encoding="utf-8-sig")
        )
    except Exception:
        return deep_copy(default)


def save_json(path, value):
    """Atomically save JSON so cart/config files are not left half-written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.resolve() == CONFIG_FILE.resolve():
        from reliability import protect_config
        value = protect_config(value, CONFIG_FILE)
    payload = json.dumps(
        value,
        indent=2,
        ensure_ascii=False
    )

    temp_path = path.with_name(
        path.name + ".tmp"
    )

    with temp_path.open(
        "w",
        encoding="utf-8",
        newline="\n"
    ) as handle:
        handle.write(payload)
        handle.flush()

        try:
            os.fsync(handle.fileno())
        except Exception:
            pass

    temp_path.replace(path)


def local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def text_of(el):
    if el is None:
        return ""
    return (el.text or "").strip()


def human_bytes(value):
    try:
        n = float(value)
    except Exception:
        return str(value or "")

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{n:.2f} {units[i]}"


def parse_size_to_bytes(value):
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)

    s = str(value).strip().replace(",", "")
    if not s:
        return 0

    try:
        return int(float(s))
    except Exception:
        pass

    m = re.search(r"([\d.]+)\s*(B|KB|KIB|MB|MIB|GB|GIB|TB|TIB|PB|PIB)", s, re.I)
    if not m:
        return 0

    num = float(m.group(1))
    unit = m.group(2).upper()

    powers = {
        "B": 0,
        "KB": 1, "KIB": 1,
        "MB": 2, "MIB": 2,
        "GB": 3, "GIB": 3,
        "TB": 4, "TIB": 4,
        "PB": 5, "PIB": 5,
    }
    return int(num * (1024 ** powers[unit]))


def detect_resolution(title):
    title = title or ""
    for res in ("2160p", "1080p", "720p", "480p"):
        if re.search(rf"\b{re.escape(res)}\b", title, re.I):
            return res
    if re.search(r"\b4k\b", title, re.I):
        return "2160p"
    return ""


def detect_release_scope(title, category=""):
    """
    Best-effort release scope classification.

    This is intentionally based on release-title metadata only; it does not
    inspect the actual archive/torrent contents.
    """
    raw = str(title or "")
    t = raw.lower()
    c = str(category or "").lower()

    movie_words = (
        " movie", "movie ", "(movie)", "[movie]", "film",
        "gekijouban", "gekijōban", "劇場版"
    )
    if "movie" in c or any(word in f" {t} " for word in movie_words):
        return "Movie"

    if re.search(r"\b(ova|oad|ona|specials?|special|sp)\b", raw, re.I):
        return "OVA / Special"

    # Complete-series / all-season language.
    complete_series_patterns = [
        r"\bcomplete\s+series\b",
        r"\bcomplete\s+collection\b",
        r"\ball\s+seasons?\b",
        r"\bseries\s+complete\b",
        r"\bfull\s+series\b",
        r"\b全集\b",
        r"\bS\d{1,2}\s*[-–—]\s*S?\d{1,2}\b",
    ]
    if any(re.search(p, raw, re.I) for p in complete_series_patterns):
        return "Complete Series"

    # Multi-episode range such as E01-E12, S01E01-E12, Episodes 1-12.
    multi_episode_patterns = [
        r"\bS\d{1,3}E\d{1,4}\s*[-–—~]\s*E?\d{1,4}\b",
        r"\bE\d{1,4}\s*[-–—~]\s*E?\d{1,4}\b",
        r"\bepisodes?\s*\d{1,4}\s*[-–—~]\s*\d{1,4}\b",
        r"\bep(?:isodes?)?\s*\d{1,4}\s*[-–—~]\s*\d{1,4}\b",
    ]
    if any(re.search(p, raw, re.I) for p in multi_episode_patterns):
        return "Multi-Episode Pack"

    # Season / cour batches.
    season_pack_words = (
        "batch", "season pack", "season batch", "complete season",
        "cour batch", "volumes", "bdmv", "bdrip batch"
    )
    if any(word in t for word in season_pack_words):
        return "Season Pack"

    if re.search(r"\bseason\s*\d+\b", raw, re.I):
        return "Season Pack"

    # Bare S01/S02 without an episode marker is usually a season-level release.
    if re.search(r"\bS\d{1,3}\b(?!\s*E\d)", raw, re.I):
        return "Season Pack"

    # Single-episode markers.
    single_episode_patterns = [
        r"\bS\d{1,3}E\d{1,4}\b",
        r"\b(?:EP|E)\s*0*\d{1,4}\b",
        r"\bepisode\s*0*\d{1,4}\b",
        r"\s[-–—]\s*0*\d{1,3}(?:\s|$|\[|\()",
    ]
    if any(re.search(p, raw, re.I) for p in single_episode_patterns):
        return "Single Episode"

    # "Complete" / "collection" without explicit all-season wording is more
    # likely a season/batch than a single episode.
    if any(word in t for word in ("complete", "collection", "pack")):
        return "Season Pack"

    return "Unknown"


def detect_kind(title, category=""):
    scope = detect_release_scope(title, category)
    mapping = {
        "Single Episode": "Episode",
        "Multi-Episode Pack": "Season / Batch",
        "Season Pack": "Season / Batch",
        "Complete Series": "Season / Batch",
        "Movie": "Movie",
        "OVA / Special": "OVA / Special",
        "Unknown": "Unknown",
    }
    return mapping.get(scope, "Unknown")


def destination_from_kind(kind):
    """
    Map parsed release kind to the app's qBittorrent destination folders.
    Movies go to Movies; everything else defaults to Series.
    """
    return "Movie" if str(kind or "").strip() == "Movie" else "Series"

def detect_type(title, category=""):
    return "Movie" if detect_kind(title, category) == "Movie" else "Series"


def normalize_yes_no(value):
    if value in (None, ""):
        return None
    s = str(value).strip().lower()
    if s in ("yes", "true", "1", "trusted", "verified"):
        return "Yes"
    if s in ("no", "false", "0"):
        return "No"
    return str(value).strip()


def normalize_date(value):
    raw = str(value or "").strip()
    if not raw:
        return "", None

    dt = None
    try:
        dt = parsedate_to_datetime(raw)
    except Exception:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            dt = None

    if dt is None:
        return raw, None

    try:
        ts = dt.timestamp()
    except Exception:
        ts = None

    suffix = " UTC" if getattr(dt, "tzinfo", None) is not None else ""
    return dt.strftime("%Y-%m-%d %H:%M") + suffix, ts


def display_unknown(value):
    return "N/A" if value in (None, "") else str(value)


def classify_link(link, explicit_download=False):
    link = str(link or "").strip()
    if not link:
        return "Missing", False
    low = link.lower()
    if low.startswith("magnet:"):
        return "Magnet", True
    if low.startswith(("http://", "https://")):
        try:
            path = urllib.parse.urlsplit(link).path.lower()
        except Exception:
            path = low
        if path.endswith(".torrent"):
            return "Torrent", True
        if explicit_download:
            return "Download URL", True
        return "Page URL", False
    return "Unknown", False


def is_static_source(source):
    mode = (source.get("search_mode") or "Auto").strip()
    if mode == "Static Feed":
        return True
    if mode == "Search Endpoint":
        return False
    return "{query}" not in (source.get("url") or "") and not (source.get("query_param") or "").strip()


def first_nonempty(d, keys):
    for key in keys:
        val = d.get(key)
        if val not in (None, "", []):
            return val
    return ""


def get_by_path(obj, path):
    """Read dotted JSON paths such as data.results or attributes.title."""
    if not path:
        return None
    cur = obj
    for part in str(path).split("."):
        part = part.strip()
        if not part:
            continue
        if isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            if idx < 0 or idx >= len(cur):
                return None
            cur = cur[idx]
        else:
            return None
    return cur


def mapped_or_default(item, source, mapping_key, default_keys):
    mappings = source.get("mappings") or {}
    path = (mappings.get(mapping_key) or "").strip()
    if path:
        value = get_by_path(item, path)
        if value not in (None, "", []):
            return value
    return first_nonempty(item, default_keys)


def source_headers(source):
    headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION} (+desktop client)"}
    custom = source.get("headers") or {}
    if isinstance(custom, dict):
        headers.update({str(k): str(v) for k, v in custom.items()})
    return headers





def torrent_download_headers(source=None, item=None):
    """
    Headers used when AMF itself downloads a .torrent file.

    qBittorrent's URL downloader and a normal web browser do not always get
    treated the same way by torrent index sites. AMF therefore fetches the
    small .torrent payload itself and uploads the bytes to qBittorrent.
    """
    headers = source_headers(source or {})

    # The normal AMF UA is useful for APIs, but a browser-like UA is more
    # compatible with ordinary website download endpoints.
    current_ua = str(headers.get("User-Agent") or "")
    if not current_ua or current_ua.startswith("AMF/"):
        headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) "
            "Gecko/20100101 Firefox/155.0"
        )

    headers["Accept"] = (
        "application/x-bittorrent, application/octet-stream;q=0.9, "
        "*/*;q=0.7"
    )

    detail_url = str((item or {}).get("detail_url") or "").strip()
    if detail_url.startswith(("http://", "https://")):
        headers.setdefault("Referer", detail_url)

    # Avoid keeping a problematic HTTP connection alive across a burst of
    # many small torrent-file requests.
    headers.setdefault("Connection", "close")

    return headers


def looks_like_torrent_payload(data):
    """
    Basic bencoded .torrent validation.

    Torrent metainfo is a bencoded dictionary and contains an 'info' key.
    This rejects HTML error pages that some sites return with HTTP 200.
    """
    if not isinstance(data, (bytes, bytearray)):
        return False

    if len(data) < 32:
        return False

    payload = bytes(data)

    return (
        payload.startswith(b"d")
        and b"4:info" in payload
    )


def fetch_torrent_payload(url, source=None, item=None, timeout=20, attempts=3):
    """
    Download a .torrent file in AMF rather than asking qBittorrent to fetch
    the remote URL itself.
    """
    last_error = None

    for attempt in range(max(1, int(attempts))):
        try:
            response = requests.get(
                url,
                headers=torrent_download_headers(source, item),
                timeout=timeout,
                allow_redirects=True,
            )
            response.raise_for_status()

            payload = response.content

            if not looks_like_torrent_payload(payload):
                content_type = str(
                    response.headers.get("Content-Type") or ""
                ).lower()

                if "html" in content_type:
                    raise RuntimeError(
                        "the torrent site returned an HTML page instead of "
                        "a .torrent file"
                    )

                raise RuntimeError(
                    "the downloaded response is not a valid .torrent file"
                )

            return payload

        except Exception as exc:
            last_error = exc

            if attempt + 1 < max(1, int(attempts)):
                time.sleep(0.35 * (attempt + 1))

    raise RuntimeError(
        str(last_error or "could not download the .torrent file")
    )


def magnet_fallback_from_detail(source, item, timeout=15):
    """
    If a direct .torrent endpoint fails, try the result's detail page and
    prefer an exposed magnet link.
    """
    detail_url = str(
        (item or {}).get("detail_url")
        or (item or {}).get("guid")
        or ""
    ).strip()

    if not detail_url.startswith(("http://", "https://")):
        return ""

    try:
        response = requests.get(
            detail_url,
            headers=torrent_download_headers(source, item),
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()

        link, kind, usable = extract_usable_download_link_from_html(
            response.text,
            response.url,
        )

        if (
            usable
            and str(link or "").lower().startswith("magnet:")
        ):
            return str(link)

    except Exception:
        pass

    return ""


def qb_add_result_failed(result):
    """
    qbittorrent-api can return 'Ok.' or 'Fails.' depending on qBittorrent
    version. Treat the explicit failure response as a failure instead of
    accidentally removing the item from the cart.
    """
    if result is False:
        return True

    if isinstance(result, str):
        value = result.strip().lower()
        return value.startswith("fail")

    return False




def bdecode_torrent_value(data, index=0):
    """
    Minimal bencode decoder used only for torrent metadata inspection.

    Returns (value, next_index). Dictionary keys and byte strings remain bytes
    so torrent metadata can be decoded explicitly and safely.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("bencoded data must be bytes")

    data = bytes(data)

    if index >= len(data):
        raise ValueError("unexpected end of bencoded data")

    token = data[index:index + 1]

    if token == b"i":
        end = data.index(b"e", index + 1)
        raw = data[index + 1:end]

        if not raw:
            raise ValueError("invalid bencoded integer")

        return int(raw), end + 1

    if token == b"l":
        values = []
        cursor = index + 1

        while data[cursor:cursor + 1] != b"e":
            value, cursor = bdecode_torrent_value(
                data,
                cursor,
            )
            values.append(value)

        return values, cursor + 1

    if token == b"d":
        values = {}
        cursor = index + 1

        while data[cursor:cursor + 1] != b"e":
            key, cursor = bdecode_torrent_value(
                data,
                cursor,
            )

            if not isinstance(key, bytes):
                raise ValueError(
                    "bencoded dictionary key is not bytes"
                )

            value, cursor = bdecode_torrent_value(
                data,
                cursor,
            )
            values[key] = value

        return values, cursor + 1

    if token.isdigit():
        colon = data.index(b":", index)
        size = int(data[index:colon])
        start = colon + 1
        end = start + size

        if end > len(data):
            raise ValueError(
                "bencoded string exceeds input"
            )

        return data[start:end], end

    raise ValueError(
        f"unknown bencode token at position {index}"
    )


def decode_torrent_text(value):
    if isinstance(value, str):
        return value.strip()

    if not isinstance(value, (bytes, bytearray)):
        return ""

    raw = bytes(value)

    for encoding in (
        "utf-8",
        "utf-8-sig",
        "cp1252",
        "latin-1",
    ):
        try:
            return raw.decode(
                encoding
            ).strip()
        except Exception:
            pass

    return raw.decode(
        "utf-8",
        errors="replace",
    ).strip()


def torrent_name_from_payload(payload):
    """
    Read the real torrent name from the torrent's info dictionary.

    This is preferable to guessing from a URL such as:
        /download/1960266.torrent
    """
    if not looks_like_torrent_payload(payload):
        return ""

    try:
        root, _ = bdecode_torrent_value(
            payload,
            0,
        )
    except Exception:
        return ""

    if not isinstance(root, dict):
        return ""

    info = root.get(b"info")

    if not isinstance(info, dict):
        return ""

    for key in (
        b"name.utf-8",
        b"name",
    ):
        title = decode_torrent_text(
            info.get(key)
        )

        if title:
            return title

    return ""


def imported_title_is_placeholder(title):
    """
    Detect the temporary names AMF used before 4.4.
    """
    value = str(
        title or ""
    ).strip()

    if not value:
        return True

    if value.lower() in {
        "imported torrent",
        "imported magnet",
        "manual item",
        "recovered torrent",
    }:
        return True

    if re.fullmatch(
        r"\d+",
        value,
    ):
        return True

    if re.fullmatch(
        r"recovered\s+nyaa\s+#?\d+",
        value,
        re.I,
    ):
        return True

    return False


def provider_detail_url_for_import(link):
    """
    Derive a detail page when a provider's direct torrent URL encodes it.

    Nyaa:
        /download/1960266.torrent
        -> /view/1960266
    """
    link = str(
        link or ""
    ).strip()

    if not link.startswith(
        ("http://", "https://")
    ):
        return ""

    try:
        parsed = urllib.parse.urlsplit(
            link
        )
    except Exception:
        return ""

    hostname = (
        parsed.hostname or ""
    ).lower()

    if (
        hostname == "nyaa.si"
        or hostname.endswith(".nyaa.si")
    ):
        match = re.search(
            r"/download/(\d+)\.torrent(?:$|[/?#])",
            parsed.path,
            re.I,
        )

        if match:
            return urllib.parse.urlunsplit((
                parsed.scheme or "https",
                parsed.netloc,
                f"/view/{match.group(1)}",
                "",
                "",
            ))

    return ""


def clean_provider_page_title(value):
    value = html.unescape(
        str(value or "")
    )
    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    # Remove common provider/site suffixes without touching the release title.
    suffix_patterns = (
        r"\s*[-|]\s*Nyaa\s*$",
        r"\s*[-|]\s*Nyaa\.si\s*$",
        r"\s*[-|]\s*1337x.*$",
        r"\s*[-|]\s*1377x.*$",
        r"\s*[-|]\s*YTS.*$",
        r"\s*[-|]\s*YIFY.*$",
    )

    for pattern in suffix_patterns:
        value = re.sub(
            pattern,
            "",
            value,
            flags=re.I,
        ).strip()

    return value


def title_from_detail_page(
    detail_url,
    timeout=10,
):
    if not detail_url:
        return ""

    try:
        response = requests.get(
            detail_url,
            headers=torrent_download_headers(
                {},
                {
                    "detail_url": detail_url,
                },
            ),
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
    except Exception:
        return ""

    content = response.text

    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(
                content,
                "html.parser",
            )

            for selector, attribute in (
                ('meta[property="og:title"]', "content"),
                ('meta[name="twitter:title"]', "content"),
            ):
                node = soup.select_one(
                    selector
                )

                if node:
                    title = clean_provider_page_title(
                        node.get(attribute)
                    )

                    if title:
                        return title

            for node in (
                soup.find("h1"),
                soup.find("title"),
            ):
                if node:
                    title = clean_provider_page_title(
                        node.get_text(
                            " ",
                            strip=True,
                        )
                    )

                    if title:
                        return title
        except Exception:
            pass

    # Lightweight fallback when BeautifulSoup is unavailable.
    match = re.search(
        r"(?is)<title[^>]*>(.*?)</title>",
        content,
    )

    if match:
        title = re.sub(
            r"(?is)<[^>]+>",
            " ",
            match.group(1),
        )

        return clean_provider_page_title(
            title
        )

    return ""


def resolve_imported_torrent_title(
    link="",
    local_torrent_path="",
    timeout=10,
):
    """
    Resolve the actual torrent/release name.

    Resolution order:
      1. Magnet dn= value.
      2. Local .torrent info.name.
      3. Remote .torrent info.name.
      4. Provider detail-page title (currently includes Nyaa URL mapping).
      5. Previous URL-derived fallback.
    """
    link = str(
        link or ""
    ).strip()

    local_torrent_path = str(
        local_torrent_path or ""
    ).strip()

    if link.lower().startswith(
        "magnet:"
    ):
        title = imported_link_title(
            link
        )

        if not imported_title_is_placeholder(
            title
        ):
            return title

    if local_torrent_path:
        try:
            title = torrent_name_from_payload(
                Path(
                    local_torrent_path
                ).read_bytes()
            )

            if title:
                return title
        except Exception:
            pass

    if link.startswith(
        ("http://", "https://")
    ):
        try:
            payload = fetch_torrent_payload(
                link,
                source={},
                item={},
                timeout=timeout,
                attempts=1,
            )

            title = torrent_name_from_payload(
                payload
            )

            if title:
                return title
        except Exception:
            pass

        detail_url = provider_detail_url_for_import(
            link
        )

        if detail_url:
            title = title_from_detail_page(
                detail_url,
                timeout=timeout,
            )

            if title:
                return title

    return imported_link_title(
        link
    )


def clean_imported_url(value):
    value = html.unescape(
        str(value or "").strip()
    )

    while value and value[-1] in ".,;]}>":
        value = value[:-1]

    return value.strip()


def imported_link_title(link):
    link = str(link or "").strip()

    if link.lower().startswith("magnet:"):
        try:
            parsed = urllib.parse.urlsplit(link)
            params = urllib.parse.parse_qs(
                parsed.query
            )
            names = params.get("dn") or []
            if names:
                return urllib.parse.unquote_plus(
                    names[0]
                ).strip() or "Imported magnet"
        except Exception:
            pass

        return "Imported magnet"

    try:
        parsed = urllib.parse.urlsplit(link)
        name = Path(
            urllib.parse.unquote(parsed.path)
        ).name

        if name:
            if name.lower().endswith(".torrent"):
                name = name[:-8]
            return name or "Imported torrent"
    except Exception:
        pass

    return "Imported torrent"


def extract_torrent_links_from_text(content):
    """
    Extract torrent/magnet links from TXT, CSV, JSON, Markdown, M3U, URL files,
    and other text-like files.
    """
    value = str(content or "")
    found = []

    patterns = [
        r"magnet:\?[^\s<>\"']+",
        r"https?://[^\s<>\"']+",
    ]

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            value,
            re.I
        ):
            link = clean_imported_url(
                match.group(0)
            )

            if not link:
                continue

            if link.lower().startswith("magnet:"):
                found.append(link)
                continue

            low = link.lower()
            if (
                low.endswith(".torrent")
                or ".torrent?" in low
                or "/download/" in low
                or "/torrent/" in low
                or "torrent" in low
            ):
                found.append(link)

    result = []
    seen = set()

    for link in found:
        key = link.strip()

        if key in seen:
            continue

        seen.add(key)
        result.append(link)

    return result


def local_torrent_payload(path):
    data = Path(path).read_bytes()

    if not looks_like_torrent_payload(data):
        raise RuntimeError(
            f"{Path(path).name} is not a valid .torrent file"
        )

    return data


def normalize_search_text(value):
    value = str(value or "").lower()
    value = re.sub(r"[_\-.]+", " ", value)
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def fuzzy_score(query, title):
    """
    Token-aware fuzzy score from 0-100.
    Designed for long release names where the anime title is only part of
    the full torrent title.
    """
    q = normalize_search_text(query)
    t = normalize_search_text(title)

    if not q:
        return 100.0
    if not t:
        return 0.0
    if q in t:
        return 100.0

    q_tokens = q.split()
    t_tokens = t.split()

    if not q_tokens or not t_tokens:
        return 0.0

    # Each query token gets its best title-token match.
    token_scores = []
    for qtok in q_tokens:
        best = 0.0
        for ttok in t_tokens:
            if qtok == ttok:
                best = 1.0
                break
            score = SequenceMatcher(None, qtok, ttok).ratio()
            if score > best:
                best = score
        token_scores.append(best)

    token_score = (sum(token_scores) / len(token_scores)) * 100.0

    # Also compare normalized phrases, but don't let long release metadata
    # punish a good token match too heavily.
    phrase_score = SequenceMatcher(None, q, t).ratio() * 100.0

    # Reward exact token coverage.
    exact_hits = sum(1 for tok in q_tokens if tok in t_tokens)
    coverage = (exact_hits / len(q_tokens)) * 100.0

    return max(token_score, phrase_score, coverage)


def title_matches(query, title, match_mode="Normal", fuzzy_threshold=70):
    query = str(query or "").strip()
    title = str(title or "")

    if not query:
        return True

    if match_mode == "Regex":
        return re.search(query, title, re.IGNORECASE) is not None

    if match_mode == "Fuzzy":
        return fuzzy_score(query, title) >= float(fuzzy_threshold)

    q = normalize_search_text(query)
    t = normalize_search_text(title)
    words = [w for w in q.split() if w]

    if match_mode == "Phrase":
        return bool(q and q in t)

    return all(word in t for word in words)


def smart_regex_matches(query, title):
    words = [w for w in normalize_search_text(query).split() if w]
    if not words:
        return False

    pattern = r".*?".join(re.escape(word) for word in words)
    try:
        return re.search(
            pattern,
            normalize_search_text(title),
            re.IGNORECASE
        ) is not None
    except re.error:
        return False


def smart_filter_results(results, query, fuzzy_threshold=70):
    """
    Local Smart Search for sources that DO NOT provide their own query-aware
    search engine.

    Unlike the old cascade, this ranks/merges all match strategies instead of
    stopping after the first non-empty stage. This prevents a couple of exact
    matches from hiding other relevant fuzzy matches.
    """
    if not query:
        return list(results), "All"

    ranked = []

    for index, item in enumerate(results):
        title = item.get("title", "")

        phrase = title_matches(
            query, title, "Phrase", fuzzy_threshold
        )
        normal = title_matches(
            query, title, "Normal", fuzzy_threshold
        )
        fuzzy = fuzzy_score(query, title)
        regex_fallback = smart_regex_matches(query, title)

        # Relevance score. Exact/normal matches rank first, then fuzzy.
        score = 0.0
        stage = None

        if phrase:
            score = 1000.0 + fuzzy
            stage = "Phrase"
        elif normal:
            score = 900.0 + fuzzy
            stage = "Normal"
        elif fuzzy >= float(fuzzy_threshold):
            score = 500.0 + fuzzy
            stage = "Fuzzy"
        elif regex_fallback:
            score = 400.0 + fuzzy
            stage = "Regex fallback"

        if stage is not None:
            copy = dict(item)
            copy["_smart_score"] = score
            copy["_smart_stage"] = stage
            copy["_source_order"] = index
            ranked.append(copy)

    ranked.sort(
        key=lambda item: (
            -float(item.get("_smart_score", 0)),
            int(item.get("_source_order", 0)),
        )
    )

    stages = []
    for item in ranked:
        stage = item.get("_smart_stage")
        if stage and stage not in stages:
            stages.append(stage)

    label = "+".join(stages) if stages else "No match"
    return ranked, label


def provider_query_for_search(query, match_mode="Smart"):
    # Remote sources receive the user's plain text. Smart matching is applied
    # locally to whatever the provider returns.
    return str(query or "").strip()

def friendly_source_error(exc):
    if isinstance(exc, requests.exceptions.Timeout):
        return "Timed out while connecting to the source"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "Could not connect to the source"
    if isinstance(exc, requests.exceptions.HTTPError):
        response = getattr(exc, "response", None)
        if response is not None:
            return f"HTTP {response.status_code} {response.reason}".strip()
    if isinstance(exc, ET.ParseError):
        return f"Invalid RSS/XML: {exc}"
    if isinstance(exc, json.JSONDecodeError):
        return f"Invalid JSON: {exc.msg}"
    return str(exc)


def find_descendant_value(node, wanted_names):
    wanted = {x.lower() for x in wanted_names}
    for child in node.iter():
        if local_name(child.tag) in wanted:
            val = text_of(child)
            if val:
                return val
    return ""


def find_link_in_xml(node):
    """Return (link, link_kind, usable) while preferring actual torrent downloads."""
    # Prefer magnets and bittorrent enclosures.
    for child in node.iter():
        lname = local_name(child.tag)

        if lname == "enclosure":
            url = (child.attrib.get("url") or "").strip()
            typ = (child.attrib.get("type") or "").lower()
            if url:
                kind, usable = classify_link(url, explicit_download="bittorrent" in typ)
                if usable:
                    return url, kind, usable

        if lname == "link":
            href = (child.attrib.get("href") or "").strip()
            rel = (child.attrib.get("rel") or "").lower()
            typ = (child.attrib.get("type") or "").lower()

            if href and href.startswith("magnet:"):
                return href, "Magnet", True

            if href and ("bittorrent" in typ or rel == "enclosure"):
                kind, usable = classify_link(href, explicit_download=True)
                return href, kind, usable

            txt = text_of(child)
            if txt.startswith("magnet:"):
                return txt, "Magnet", True

    # Explicit torrent/download tags are treated as download endpoints.
    val = find_descendant_value(
        node,
        ["magnet", "magneturi", "magnet_uri", "torrent", "torrenturl",
         "torrent_url", "download", "downloadurl", "download_url"]
    )
    if val:
        kind, usable = classify_link(val, explicit_download=True)
        return val, kind, usable

    # A normal RSS <link> is only auto-usable when it is clearly a .torrent URL.
    fallback = ""
    for child in node.iter():
        if local_name(child.tag) == "link":
            href = (child.attrib.get("href") or "").strip()
            txt = text_of(child)
            candidate = href or txt
            if not candidate:
                continue
            kind, usable = classify_link(candidate, explicit_download=False)
            if usable:
                return candidate, kind, usable
            if not fallback:
                fallback = candidate

    if fallback:
        kind, usable = classify_link(fallback, explicit_download=False)
        return fallback, kind, usable

    return "", "Missing", False



def absolute_url(base, value):
    value = str(value or "").strip()
    if not value:
        return ""
    return urllib.parse.urljoin(base, value)


def html_text(node):
    if node is None:
        return ""
    try:
        return " ".join(node.stripped_strings)
    except Exception:
        return str(node or "").strip()


def clean_opensearch_template(template):
    template = str(template or "").strip()
    if not template:
        return ""

    template = template.replace("{searchTerms}", "{query}")

    # Remove optional OpenSearch placeholders such as {language?}.
    template = re.sub(r"\{[^{}]+\?\}", "", template)

    # A few common required placeholders have safe generic defaults.
    template = template.replace("{startPage}", "1")
    template = template.replace("{startIndex}", "0")
    template = template.replace("{count}", "50")
    return template



def normalized_hostname(url):
    try:
        host = (urllib.parse.urlsplit(str(url or "")).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def approximate_site_key(url):
    """
    Lightweight same-site check without an extra public-suffix dependency.
    Subdomains of the same last-two-label host are treated as related.
    """
    host = normalized_hostname(url)
    if not host:
        return ""

    parts = host.split(".")
    if len(parts) <= 2:
        return host

    return ".".join(parts[-2:])


def same_site_family(url_a, url_b):
    a = approximate_site_key(url_a)
    b = approximate_site_key(url_b)
    return bool(a and b and a == b)


def candidate_target_is_same_site(candidate_url, final_page_url):
    return same_site_family(candidate_url, final_page_url)


def annotate_candidate_origin(candidate, final_page_url):
    candidate = deep_copy(candidate)

    target = candidate.get("url", "")
    final_host = normalized_hostname(final_page_url)
    target_host = normalized_hostname(target)

    candidate["_final_host"] = final_host
    candidate["_target_host"] = target_host

    if (
        target_host
        and final_host
        and not candidate_target_is_same_site(target, final_page_url)
    ):
        candidate["_cross_site"] = True
        candidate["_description"] = (
            f"{candidate.get('_description', '')} • "
            f"cross-site target: {target_host}"
        )
    else:
        candidate["_cross_site"] = False

    return candidate



def rebase_url_to_final_host(template_url, final_page_url):
    """
    Keep the detected path/query/template but move it onto the site's current
    final redirected scheme+host.

    Example:
        stale.example/search?q={query}
        -> current.example/search?q={query}
    """
    try:
        old = urllib.parse.urlsplit(str(template_url or ""))
        current = urllib.parse.urlsplit(str(final_page_url or ""))

        if not current.scheme or not current.netloc:
            return ""

        return urllib.parse.urlunsplit((
            current.scheme,
            current.netloc,
            old.path or "/",
            old.query,
            old.fragment,
        ))
    except Exception:
        return ""


def probe_search_template(template_url, final_page_url, headers, timeout=10):
    """
    Validate a rebased search template with a harmless placeholder query.
    The probe succeeds only if the request responds and remains on the same
    final site family.
    """
    if not template_url:
        return False, ""

    probe_url = template_url.replace(
        "{query}",
        urllib.parse.quote_plus("test")
    )

    try:
        response = requests.get(
            probe_url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()

        if not same_site_family(
            response.url,
            final_page_url
        ):
            return False, response.url

        return True, response.url

    except Exception:
        return False, ""


def try_rebase_cross_site_candidate(
    candidate,
    final_page_url,
    headers,
    timeout=10
):
    """
    A page may advertise an absolute search action on an obsolete domain even
    though the same path still works on the site's current redirected host.

    Try that same path/query template on the current host. This remains
    generic and does not know any provider-specific domain aliases.
    """
    original_url = str(candidate.get("url") or "").strip()
    rebased_url = rebase_url_to_final_host(
        original_url,
        final_page_url
    )

    if not rebased_url:
        return None

    ok, resolved_probe = probe_search_template(
        rebased_url,
        final_page_url,
        headers,
        timeout=timeout,
    )

    if not ok:
        return None

    repaired = deep_copy(candidate)
    repaired["url"] = rebased_url
    repaired["_cross_site"] = False
    repaired["_rejected"] = False
    repaired["_detected_by"] = (
        f"{candidate.get('_detected_by', 'Detected')} • Rebased"
    )
    repaired["_description"] = (
        f"Rebased stale/external target onto current host "
        f"{normalized_hostname(final_page_url)}"
    )
    repaired["_original_stale_url"] = original_url
    repaired["_probe_final_url"] = resolved_probe

    return repaired



def walk_json_objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json_objects(child)

    elif isinstance(value, list):
        for child in value:
            yield from walk_json_objects(child)


def normalize_schema_search_template(template):
    """
    Convert common Schema.org/OpenSearch-style placeholders into {query}.
    """
    template = str(template or "").strip()

    replacements = (
        "{search_term_string}",
        "{searchTerms}",
        "{searchterms}",
        "{query}",
    )

    for token in replacements:
        if token in template:
            template = template.replace(token, "{query}")

    return template


def jsonld_search_action_candidates(soup, base_url, page_title):
    """
    Discover Schema.org WebSite/SearchAction metadata, for example:

      {
        "@type": "WebSite",
        "potentialAction": {
          "@type": "SearchAction",
          "target": "https://example.com/search/{search_term_string}",
          "query-input": "required name=search_term_string"
        }
      }
    """
    candidates = []

    for script in soup.find_all(
        "script",
        attrs={"type": re.compile(r"application/ld\+json", re.I)}
    ):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()

        if not raw:
            continue

        try:
            payload = json.loads(raw)
        except Exception:
            # Some real sites include multiple adjacent JSON objects or minor
            # formatting issues. Do not let that break all discovery.
            continue

        for obj in walk_json_objects(payload):
            obj_type = obj.get("@type")

            if isinstance(obj_type, list):
                types = {str(x).lower() for x in obj_type}
            else:
                types = {str(obj_type or "").lower()}

            if "searchaction" not in types:
                continue

            target = obj.get("target")

            if isinstance(target, dict):
                target = (
                    target.get("urlTemplate")
                    or target.get("url")
                    or target.get("@id")
                    or ""
                )

            target = normalize_schema_search_template(target)

            if not target or "{query}" not in target:
                continue

            target = absolute_url(base_url, target)

            query_input = str(
                obj.get("query-input")
                or obj.get("queryInput")
                or ""
            )

            candidates.append({
                "name": page_title,
                "type": "HTML Search",
                "search_mode": "Search Endpoint",
                "url": target,
                "query_param": "",
                "results_path": "",
                "dynamic_feed_url": "",
                "dynamic_feed_query_param": "",
                "mappings": {},
                "headers": {},
                "html": {
                    "auto": True,
                    "catalog_cards": True,
                },
                "enabled": True,
                "_detected_by": "JSON-LD SearchAction",
                "_description": (
                    "Schema.org SearchAction"
                    + (
                        f" • {query_input}"
                        if query_input
                        else ""
                    )
                ),
            })

    return candidates


def detect_site_sources(website_url, timeout=15):
    """
    Discover conventional search/feed interfaces advertised by a website:
      - OpenSearch descriptions
      - RSS/Atom alternate links
      - GET search forms
    Returns normalized source candidates.
    """
    if BeautifulSoup is None:
        raise RuntimeError(
            "Website Auto-Detect needs BeautifulSoup. "
            "Run: python -m pip install beautifulsoup4"
        )

    website_url = str(website_url or "").strip()
    if not website_url:
        raise RuntimeError("Enter a website URL.")

    parsed = urllib.parse.urlsplit(website_url)
    if parsed.scheme not in ("http", "https"):
        website_url = "https://" + website_url.lstrip("/")

    headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION} (+desktop client)"}

    try:
        response = requests.get(website_url, headers=headers, timeout=timeout)
        response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(friendly_source_error(exc)) from exc

    final_url = response.url
    soup = BeautifulSoup(response.text, "html.parser")
    page_title = html_text(soup.title) or urllib.parse.urlsplit(final_url).netloc

    candidates = []
    rejected_candidates = []
    seen = set()

    def add_candidate(candidate):
        candidate = annotate_candidate_origin(
            candidate,
            final_url
        )

        url = candidate.get("url", "")
        key = (
            candidate.get("type", ""),
            candidate.get("search_mode", ""),
            url,
            candidate.get("query_param", ""),
        )

        if not url or key in seen:
            return

        seen.add(key)

        # If the page points to an unrelated absolute domain, first try
        # the SAME path/query template on the site's current redirected host.
        # This repairs a common stale-domain metadata pattern generically.
        if candidate.get("_cross_site"):
            rebased = try_rebase_cross_site_candidate(
                candidate,
                final_url,
                headers,
                timeout=min(timeout, 10),
            )

            if rebased:
                rebased_key = (
                    rebased.get("type", ""),
                    rebased.get("search_mode", ""),
                    rebased.get("url", ""),
                    rebased.get("query_param", ""),
                )

                if rebased_key not in seen:
                    seen.add(rebased_key)

                candidates.append(rebased)
                rejected_candidates.append(candidate)
                return

            rejected_candidates.append(candidate)
            return

        candidates.append(candidate)

    # 0) Schema.org JSON-LD SearchAction metadata.
    for candidate in jsonld_search_action_candidates(
        soup,
        final_url,
        page_title
    ):
        add_candidate(candidate)

    # 1) OpenSearch metadata.
    search_links = []
    for link in soup.find_all("link"):
        rel = [str(x).lower() for x in (link.get("rel") or [])]
        typ = str(link.get("type") or "").lower()
        href = link.get("href")
        if href and "search" in rel and "opensearchdescription" in typ:
            search_links.append(absolute_url(final_url, href))

    for opensearch_url in search_links[:5]:
        try:
            r = requests.get(opensearch_url, headers=headers, timeout=timeout)
            r.raise_for_status()
            root = ET.fromstring(r.content)

            short_name = ""
            for el in root.iter():
                if local_name(el.tag) == "shortname":
                    short_name = text_of(el)
                    break
            source_name = short_name or page_title

            for el in root.iter():
                if local_name(el.tag) != "url":
                    continue

                template = clean_opensearch_template(el.attrib.get("template", ""))
                if not template or "{query}" not in template:
                    continue

                typ = str(el.attrib.get("type") or "").lower()
                if "rss" in typ or "atom" in typ:
                    stype = "RSS / Atom"
                elif "json" in typ:
                    stype = "JSON API"
                elif "html" in typ or not typ:
                    stype = "HTML Search"
                else:
                    continue

                add_candidate({
                    "name": source_name,
                    "type": stype,
                    "search_mode": "Search Endpoint",
                    "url": absolute_url(final_url, template),
                    "query_param": "",
                    "results_path": "",
                    "dynamic_feed_url": "",
                    "dynamic_feed_query_param": "",
                    "mappings": {},
                    "headers": {},
                    "html": {"auto": True},
                    "enabled": True,
                    "_detected_by": "OpenSearch",
                    "_description": f"OpenSearch • {typ or 'text/html'}",
                })
        except Exception:
            pass

    # 2) RSS / Atom links advertised by the page.
    for link in soup.find_all("link"):
        rel = [str(x).lower() for x in (link.get("rel") or [])]
        typ = str(link.get("type") or "").lower()
        href = link.get("href")
        if not href or "alternate" not in rel:
            continue
        if "rss" not in typ and "atom" not in typ:
            continue

        feed_url = absolute_url(final_url, href)
        add_candidate({
            "name": page_title,
            "type": "RSS / Atom",
            "search_mode": "Static Feed",
            "url": feed_url,
            "query_param": "",
            "results_path": "",
            "dynamic_feed_url": "",
            "dynamic_feed_query_param": "",
            "mappings": {},
            "headers": {},
            "enabled": True,
            "_detected_by": "Feed Link",
            "_description": f"Advertised {typ or 'RSS/Atom'} feed",
        })

    # 3) Conventional GET search forms.
    preferred_names = {
        "q", "query", "search", "search_query", "keyword",
        "keywords", "term", "text", "s"
    }

    for form in soup.find_all("form"):
        method = str(form.get("method") or "get").lower()
        if method != "get":
            continue

        action = absolute_url(final_url, form.get("action") or final_url)

        query_input = None
        all_inputs = form.find_all(["input", "textarea"])
        for inp in all_inputs:
            name = str(inp.get("name") or "").strip()
            typ = str(inp.get("type") or "").lower()
            if not name:
                continue
            if typ == "search" or name.lower() in preferred_names:
                query_input = inp
                break

        if query_input is None:
            continue

        query_name = str(query_input.get("name") or "").strip()
        fixed_params = []

        # Preserve hidden inputs that affect search/category/filter behavior.
        for inp in form.find_all("input"):
            name = str(inp.get("name") or "").strip()
            typ = str(inp.get("type") or "").lower()
            value = str(inp.get("value") or "").strip()
            if not name or name == query_name:
                continue
            if typ == "hidden" and value:
                fixed_params.append((name, value))

        parts = urllib.parse.urlsplit(action)
        params = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        params.extend(fixed_params)
        params = [(k, v) for k, v in params if k != query_name]
        params.append((query_name, "{query}"))

        # urlencode normally, then restore the placeholder.
        query_string = urllib.parse.urlencode(params)
        query_string = query_string.replace("%7Bquery%7D", "{query}")
        search_url = urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, query_string, parts.fragment)
        )

        add_candidate({
            "name": page_title,
            "type": "HTML Search",
            "search_mode": "Search Endpoint",
            "url": search_url,
            "query_param": "",
            "results_path": "",
            "dynamic_feed_url": "",
            "dynamic_feed_query_param": "",
            "mappings": {},
            "headers": {},
            "html": {"auto": True},
            "enabled": True,
            "_detected_by": "Search Form",
            "_description": f"GET search form • parameter {query_name}",
        })

    # Prefer full-site search methods over static feeds.
    rank = {
        # A real GET form mirrors what the browser submits and is therefore
        # preferred over descriptive metadata when both are present.
        ("Search Form", "HTML Search"): 0,
        ("JSON-LD SearchAction", "HTML Search"): 1,
        ("OpenSearch", "HTML Search"): 2,
        ("OpenSearch", "RSS / Atom"): 3,
        ("OpenSearch", "JSON API"): 3,
        ("Feed Link", "RSS / Atom"): 4,
    }
    candidates.sort(
        key=lambda c: rank.get(
            (c.get("_detected_by"), c.get("type")),
            9
        )
    )

    for rejected in rejected_candidates:
        rejected["_rejected"] = True
        rejected["_description"] = (
            f"REJECTED: stale/external search target • "
            f"{rejected.get('_description', '')}"
        )
        candidates.append(rejected)

    return page_title, final_url, candidates


def direct_download_href(href):
    href = str(href or "").strip()
    low = href.lower()
    return (
        low.startswith("magnet:")
        or low.endswith(".torrent")
        or ".torrent?" in low
        or "/download/" in low
        or "download=" in low
    )


def first_direct_link(container, base_url):
    if container is None:
        return "", ""
    for a in container.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if direct_download_href(href):
            return absolute_url(base_url, href), html_text(a)
    return "", ""


def parse_int_from_text(value):
    m = re.search(r"-?\d[\d,]*", str(value or ""))
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except Exception:
        return None



COMMON_LANGUAGES = (
    "English", "Japanese", "Spanish", "French", "German", "Italian",
    "Portuguese", "Russian", "Korean", "Chinese", "Cantonese",
    "Mandarin", "Hindi", "Tamil", "Telugu", "Malayalam", "Bengali",
    "Arabic", "Turkish", "Polish", "Dutch", "Swedish", "Norwegian",
    "Danish", "Finnish", "Greek", "Hebrew", "Persian", "Thai",
    "Vietnamese", "Indonesian", "Malay", "Ukrainian", "Romanian",
    "Hungarian", "Czech", "Slovak", "Croatian", "Serbian", "Bulgarian",
    "Filipino", "Tagalog", "Punjabi", "Urdu", "Amharic", "Tigrinya"
)

LANG_CODE_MAP = {
    "eng": "English", "en": "English",
    "jpn": "Japanese", "jp": "Japanese", "ja": "Japanese",
    "spa": "Spanish", "es": "Spanish",
    "fra": "French", "fre": "French", "fr": "French",
    "deu": "German", "ger": "German", "de": "German",
    "ita": "Italian", "it": "Italian",
    "por": "Portuguese", "pt": "Portuguese",
    "rus": "Russian", "ru": "Russian",
    "kor": "Korean", "ko": "Korean",
    "zho": "Chinese", "chi": "Chinese", "zh": "Chinese",
    "hin": "Hindi", "hi": "Hindi",
    "ara": "Arabic", "ar": "Arabic",
}


def clean_result_title(value):
    value = html.unescape(str(value or "")).strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(
        r"\s*[-–—]?\s*(?:torrent\s+)?downloads?\s*$",
        "",
        value,
        flags=re.I
    )
    value = re.sub(
        r"\s*[-–—]?\s*download\s+(?:movie|torrent)s?\s*$",
        "",
        value,
        flags=re.I
    )
    return value.strip(" |·•-\t\r\n")


def is_bad_result_title(value):
    value = clean_result_title(value)
    norm = normalize_search_text(value)

    if not value or len(value) < 2:
        return True

    # Ratings / scores.
    if re.fullmatch(r"\d+(?:\.\d+)?\s*/\s*10", value, re.I):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?\s*%", value):
        return True

    # Bare metadata.
    if re.fullmatch(r"(?:19|20)\d{2}", value):
        return True
    if re.fullmatch(
        r"(?:360p|480p|720p|1080p|1080p\.x265|1440p|2160p|4k|3d|web|bluray|bdrip|webrip)",
        value,
        re.I
    ):
        return True
    if re.fullmatch(
        r"\d+(?:\.\d+)?\s*(?:kb|mb|gb|tb|kib|mib|gib|tib)",
        value,
        re.I
    ):
        return True

    generic = {
        "yts", "yify", "yts yify movies", "yify movies", "movies", "movie",
        "browse movies", "popular downloads", "latest movies", "trending movies",
        "similar movies", "available in", "advanced search", "search results",
        "download", "torrent", "torrents", "rating", "imdb rating"
    }
    return norm in generic


def title_tokens(value):
    return {
        token
        for token in normalize_search_text(value).split()
        if len(token) >= 3 and not token.isdigit()
    }


def title_from_detail_slug(detail_url):
    try:
        path = urllib.parse.urlsplit(detail_url).path.rstrip("/")
        slug = urllib.parse.unquote(path.split("/")[-1])
    except Exception:
        return ""

    slug = re.sub(r"[-_.]+", " ", slug).strip()
    year_match = re.search(r"\b((?:19|20)\d{2})\b", slug)
    year = year_match.group(1) if year_match else ""
    slug = re.sub(r"\b(?:19|20)\d{2}\b", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()

    if not slug:
        return ""

    title = " ".join(
        word.upper() if len(word) <= 2 else word.capitalize()
        for word in slug.split()
    )

    return f"{title} ({year})" if year else title


def title_matches_detail_slug(title, detail_url):
    if not detail_url:
        return True

    slug_title = title_from_detail_slug(detail_url)
    slug_tokens = title_tokens(slug_title)
    candidate_tokens = title_tokens(title)

    if not slug_tokens:
        return True

    return bool(slug_tokens.intersection(candidate_tokens))


def best_catalog_title(container, selected_anchor, detail_url, query=""):
    """
    Bind a title to the selected item/detail URL. Nearby ratings, years,
    scores and generic section headings are never allowed to replace it.
    """
    candidates = []

    # Explicit title/name elements get first priority.
    for node in container.find_all(
        ["a", "h1", "h2", "h3", "h4", "h5", "span", "div", "p"]
    ):
        classes = " ".join(node.get("class") or []).lower()
        node_id = str(node.get("id") or "").lower()
        semantic = f"{classes} {node_id}"

        if not any(x in semantic for x in ("title", "name")):
            continue
        if any(x in semantic for x in ("rating", "score", "year", "quality", "size")):
            continue

        candidate = clean_result_title(html_text(node))
        if is_bad_result_title(candidate):
            continue

        score = 50
        if title_matches_detail_slug(candidate, detail_url):
            score += 30
        else:
            score -= 35

        if node.name == "a" and node.get("href"):
            node_url = absolute_url(detail_url, node.get("href"))
            if canonical_url_key(node_url) == canonical_url_key(detail_url):
                score += 25

        candidates.append((score, candidate))

    # Selected anchor: text / title / image alt.
    if selected_anchor is not None:
        raw_values = [
            html_text(selected_anchor),
            str(selected_anchor.get("title") or ""),
        ]
        image = selected_anchor.find("img")
        if image is not None:
            raw_values.append(str(image.get("alt") or ""))

        for raw in raw_values:
            candidate = clean_result_title(raw)
            if is_bad_result_title(candidate):
                continue

            score = 45
            if title_matches_detail_slug(candidate, detail_url):
                score += 35
            else:
                score -= 30
            candidates.append((score, candidate))

    # Other image-alt text inside the same result card.
    for image in container.find_all("img"):
        candidate = clean_result_title(image.get("alt") or "")
        if is_bad_result_title(candidate):
            continue

        score = 30
        if title_matches_detail_slug(candidate, detail_url):
            score += 30
        else:
            score -= 30
        candidates.append((score, candidate))

    candidates.sort(key=lambda row: (row[0], len(row[1])), reverse=True)

    for score, candidate in candidates:
        if score >= 30 and not is_bad_result_title(candidate):
            return candidate

    # URL slug is safer than returning unrelated metadata.
    return clean_result_title(title_from_detail_slug(detail_url))


def detect_language(text="", node=None):
    pieces = [str(text or "")]

    if node is not None:
        for tag in node.find_all(True):
            semantics = normalize_search_text(
                " ".join([
                    " ".join(tag.get("class") or []),
                    str(tag.get("id") or ""),
                    str(tag.get("title") or ""),
                    str(tag.get("aria-label") or ""),
                    str(tag.get("data-label") or ""),
                ])
            )
            if "language" in semantics or re.search(r"\blang\b", semantics):
                value = html_text(tag).strip()
                if value:
                    pieces.insert(0, f"Language: {value}")

    combined = " | ".join(pieces)
    low = combined.lower()

    labelled = re.search(
        r"\b(?:language|audio\s*language|lang)\s*:?\s*([A-Za-z][A-Za-z -]{1,30})",
        combined,
        re.I
    )
    if labelled:
        candidate = labelled.group(1)
        candidate = re.split(r"\s{2,}|[|,;/\[\]\(\)]", candidate)[0].strip()
        candidate = re.sub(r"\s+\d(?:\.\d)?\s*$", "", candidate).strip()
        for language in COMMON_LANGUAGES:
            if language.lower() in candidate.lower():
                return language

    if re.search(r"\bmulti(?:ple)?[\s-]*(?:audio|language|lang)\b", low):
        return "Multi"

    if re.search(r"\bdual[\s-]*audio\b", low):
        found = [
            language for language in COMMON_LANGUAGES
            if re.search(rf"\b{re.escape(language.lower())}\b", low)
        ]
        return " / ".join(dict.fromkeys(found)) if found else "Dual Audio"

    found = [
        language for language in COMMON_LANGUAGES
        if re.search(rf"\b{re.escape(language.lower())}\b", low)
    ]
    if found:
        return " / ".join(dict.fromkeys(found[:3]))

    # Only accept short codes when bracketed.
    for code, language in LANG_CODE_MAP.items():
        if re.search(rf"[\[\(\{{]\s*{re.escape(code)}\s*[\]\)\}}]", low, re.I):
            return language

    return ""


def extract_detail_language(content):
    if BeautifulSoup is None:
        return ""
    soup = BeautifulSoup(content, "html.parser")
    return detect_language(html_text(soup), soup)


def parse_html_result_table(source, query, soup, base_url):
    results = []

    # Common table-header names and exact abbreviations used by many
    # conventional server-rendered download/catalog tables.
    seed_aliases = {
        "se", "sd", "seed", "seeds", "seeder", "seeders"
    }
    peer_aliases = {
        "le", "lee", "lc", "leech", "leeches", "leecher",
        "leechers", "peer", "peers"
    }
    download_aliases = {
        "dl", "dls", "download", "downloads", "completed",
        "complete", "snatch", "snatches"
    }
    size_aliases = {
        "sz", "size", "filesize", "file size"
    }
    date_aliases = {
        "dt", "date", "age", "uploaded", "published", "time"
    }
    category_aliases = {
        "cat", "category", "type"
    }
    language_aliases = {
        "lang", "language", "audio language", "audio lang"
    }

    def canonical_header(value):
        value = normalize_search_text(value)
        return value.strip()

    def find_col(headers, aliases, contains_words=()):
        # First prefer exact normalized aliases. This safely supports short
        # headers such as "se" and "le" without matching them inside unrelated
        # words like "size" or "release".
        for i, header in enumerate(headers):
            h = canonical_header(header)
            if h in aliases:
                return i

        # Then allow conservative full-word/phrase matching.
        for i, header in enumerate(headers):
            h = canonical_header(header)
            for word in contains_words:
                if re.search(rf"\b{re.escape(word)}\b", h):
                    return i

        return None


    def cell_semantic_text(cell):
        """
        Collect semantic hints from a cell itself. This provides a generic
        fallback for tables whose visible headers are icons/abbreviations but
        whose cells expose classes or data-label attributes.
        """
        if cell is None:
            return ""

        bits = []

        for attr in (
            "class", "id", "data-label", "data-title", "aria-label",
            "headers", "title"
        ):
            value = cell.get(attr)

            if isinstance(value, (list, tuple)):
                bits.extend(str(x) for x in value)
            elif value:
                bits.append(str(value))

        return normalize_search_text(" ".join(bits))


    def infer_col_from_cells(rows, aliases, contains_words=()):
        """
        If the header row is insufficient, inspect semantic attributes on the
        first several data rows. Return a column only when the same semantic
        signal appears consistently.
        """
        votes = {}

        for tr in rows[1:8]:
            cells = tr.find_all("td")
            for i, cell in enumerate(cells):
                semantic = cell_semantic_text(cell)
                if not semantic:
                    continue

                tokens = set(semantic.split())
                exact = bool(tokens.intersection(aliases))
                contains = any(
                    re.search(rf"\b{re.escape(word)}\b", semantic)
                    for word in contains_words
                )

                if exact or contains:
                    votes[i] = votes.get(i, 0) + 1

        if not votes:
            return None

        best_col, best_votes = max(votes.items(), key=lambda pair: pair[1])
        return best_col if best_votes >= 1 else None

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        header_cells = rows[0].find_all(["th", "td"])
        headers = [html_text(x) for x in header_cells]

        size_i = find_col(
            headers,
            size_aliases,
            ("size", "filesize")
        )
        seed_i = find_col(
            headers,
            seed_aliases,
            ("seed", "seeds", "seeder", "seeders")
        )
        peer_i = find_col(
            headers,
            peer_aliases,
            ("leech", "leecher", "leechers", "peer", "peers")
        )
        downloads_i = find_col(
            headers,
            download_aliases,
            ("download", "downloads", "completed", "snatch", "snatches")
        )
        date_i = find_col(
            headers,
            date_aliases,
            ("date", "age", "uploaded", "published", "time")
        )
        cat_i = find_col(
            headers,
            category_aliases,
            ("category", "type")
        )
        language_i = find_col(
            headers,
            language_aliases,
            ("language",)
        )

        # Semantic-cell fallback for unusual headers/icons.
        if size_i is None:
            size_i = infer_col_from_cells(
                rows, size_aliases, ("size", "filesize")
            )
        if seed_i is None:
            seed_i = infer_col_from_cells(
                rows, seed_aliases, ("seed", "seeds", "seeders")
            )
        if peer_i is None:
            peer_i = infer_col_from_cells(
                rows, peer_aliases, ("leech", "leechers", "peer", "peers")
            )
        if downloads_i is None:
            downloads_i = infer_col_from_cells(
                rows,
                download_aliases,
                ("download", "downloads", "completed", "snatch")
            )
        if date_i is None:
            date_i = infer_col_from_cells(
                rows, date_aliases, ("date", "uploaded", "time")
            )
        if cat_i is None:
            cat_i = infer_col_from_cells(
                rows, category_aliases, ("category",)
            )
        if language_i is None:
            language_i = infer_col_from_cells(
                rows, language_aliases, ("language",)
            )

        for tr in rows[1:]:
            cells = tr.find_all("td")
            if not cells:
                continue

            link, _ = first_direct_link(tr, base_url)

            anchors = [
                a for a in tr.find_all("a", href=True)
                if html_text(a) and not direct_download_href(a.get("href"))
            ]
            title_anchor = max(anchors, key=lambda a: len(html_text(a)), default=None)
            title = html_text(title_anchor)

            if not title:
                # Fallback to the longest non-empty cell.
                cell_texts = [html_text(c) for c in cells]
                title = max(cell_texts, key=len, default="")

            if not title:
                continue

            page_link = absolute_url(base_url, title_anchor.get("href")) if title_anchor else ""

            row_text = html_text(tr)
            size_text = (
                html_text(cells[size_i])
                if size_i is not None and size_i < len(cells)
                else ""
            )
            if not size_text:
                size_match = re.search(
                    r"\b\d+(?:\.\d+)?\s*(?:KiB|MiB|GiB|TiB|KB|MB|GB|TB)\b",
                    row_text,
                    re.I
                )
                size_text = size_match.group(0) if size_match else ""

            seeders = (
                parse_int_from_text(html_text(cells[seed_i]))
                if seed_i is not None and seed_i < len(cells)
                else None
            )
            leechers = (
                parse_int_from_text(html_text(cells[peer_i]))
                if peer_i is not None and peer_i < len(cells)
                else None
            )
            downloads = (
                parse_int_from_text(html_text(cells[downloads_i]))
                if downloads_i is not None and downloads_i < len(cells)
                else None
            )
            date = (
                html_text(cells[date_i])
                if date_i is not None and date_i < len(cells)
                else ""
            )
            category = (
                html_text(cells[cat_i])
                if cat_i is not None and cat_i < len(cells)
                else ""
            )
            language = (
                html_text(cells[language_i])
                if language_i is not None and language_i < len(cells)
                else detect_language(row_text)
            )

            if not title_matches(query, title, "Normal", 70):
                # Final fuzzy/regex filtering happens elsewhere; this avoids
                # obviously unrelated navigation tables in HTML pages.
                pass

            size_bytes = parse_size_to_bytes(size_text)
            kind = detect_kind(title, category)
            destination = destination_from_kind(kind)
            resolution = detect_resolution(title)

            chosen_link = link or page_link
            link_kind, link_usable = classify_link(chosen_link)

            results.append({
                "title": title,
                "source": source.get("name", ""),
                "kind": kind,
                "type": destination,

                "resolution": resolution,
                "language": language,
                "size_bytes": size_bytes,
                "size": human_bytes(size_bytes) if size_bytes else size_text,
                "seeders": seeders,
                "leechers": leechers,
                "downloads": downloads,
                "date": date,
                "category": category,
                "trusted": None,
                "remake": None,
                "info_hash": "",
                "guid": page_link,
                "detail_url": page_link,
                "link": chosen_link,
                "link_kind": link_kind,
                "link_usable": link_usable,
                "_table_result": True,
            })

    return results



def parse_html_catalog_cards(source, query, soup, base_url):
    """
    Generic repeated-card parser for catalog/search pages whose result cards
    link to a detail page. Titles are tied to that detail link so ratings and
    nearby UI metadata cannot become titles.
    """
    results = []
    seen_detail_urls = set()

    result_class_words = (
        "result", "movie", "torrent", "item", "card",
        "browse", "poster", "entry", "media",
    )

    nav_words = {
        "home", "login", "register", "contact", "blog", "api",
        "rss", "requests", "suggestions", "browse", "trending",
        "advanced search", "search"
    }

    class_frequency = {}

    for node in soup.find_all(["div", "article", "li"]):
        classes = tuple(sorted(str(x).lower() for x in (node.get("class") or [])))
        if classes:
            class_frequency[classes] = class_frequency.get(classes, 0) + 1

    for container in soup.find_all(["div", "article", "li"]):
        classes = [str(x).lower() for x in (container.get("class") or [])]
        class_text = " ".join(classes)

        if not any(word in class_text for word in result_class_words):
            continue

        signature = tuple(sorted(classes))
        repeated = class_frequency.get(signature, 0) >= 2

        scored = []

        for anchor in container.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not href:
                continue

            absolute = absolute_url(base_url, href)
            if not absolute.startswith(("http://", "https://")):
                continue

            path = urllib.parse.urlsplit(absolute).path.lower()
            anchor_text = clean_result_title(html_text(anchor))
            title_attr = clean_result_title(anchor.get("title") or "")
            image = anchor.find("img")
            image_alt = clean_result_title(image.get("alt") or "") if image else ""

            raw_title = next(
                (
                    x for x in (anchor_text, title_attr, image_alt)
                    if x and not is_bad_result_title(x)
                ),
                ""
            )

            norm = normalize_search_text(raw_title)
            if norm in nav_words:
                continue

            score = 0

            if image is not None:
                score += 5
            if title_attr:
                score += 4
            if raw_title:
                score += 3

            if any(token in path for token in (
                "/movie", "/movies", "/title", "/detail", "/view", "/torrent"
            )):
                score += 6

            if query and title_tokens(query).intersection(title_tokens(raw_title)):
                score += 3

            scored.append((score, anchor, absolute))

        if not scored:
            continue

        scored.sort(key=lambda row: row[0], reverse=True)
        score, title_anchor, detail_url = scored[0]

        if not repeated and score < 9:
            continue

        if detail_url in seen_detail_urls:
            continue

        title = best_catalog_title(
            container,
            title_anchor,
            detail_url,
            query
        )

        if is_bad_result_title(title):
            continue

        if not title_matches_detail_slug(title, detail_url):
            fallback = title_from_detail_slug(detail_url)
            if fallback:
                title = fallback

        if not title:
            continue

        seen_detail_urls.add(detail_url)

        full_text = html_text(container)

        year_match = re.search(r"\b(19|20)\d{2}\b", full_text)
        year = year_match.group(0) if year_match else ""

        if year and year not in title and len(title) < 180:
            title = f"{title} ({year})"

        resolution = detect_resolution(full_text or title)
        language = detect_language(full_text or title, container)

        size_match = re.search(
            r"\b\d+(?:\.\d+)?\s*(?:KiB|MiB|GiB|TiB|KB|MB|GB|TB)\b",
            full_text,
            re.I
        )
        size_text = size_match.group(0) if size_match else ""
        size_bytes = parse_size_to_bytes(size_text)

        seeders = None
        leechers = None

        seed_match = re.search(
            r"\b(?:seeders?|seeds?)\s*:?\s*(\d[\d,]*)",
            full_text,
            re.I
        )
        if seed_match:
            seeders = parse_int_from_text(seed_match.group(1))

        peer_match = re.search(
            r"\b(?:leechers?|peers?)\s*:?\s*(\d[\d,]*)",
            full_text,
            re.I
        )
        if peer_match:
            leechers = parse_int_from_text(peer_match.group(1))

        kind = detect_kind(title, "")
        scope = detect_release_scope(title, "")

        results.append({
            "title": title[:350],
            "source": source.get("name", ""),
            "kind": kind,
            "scope": scope,
            "type": destination_from_kind(kind),
            "resolution": resolution,
            "language": language,
            "size_bytes": size_bytes,
            "size": human_bytes(size_bytes) if size_bytes else size_text,
            "seeders": seeders,
            "leechers": leechers,
            "downloads": None,
            "date": "",
            "category": "",
            "trusted": None,
            "remake": None,
            "info_hash": "",
            "guid": detail_url,
            "detail_url": detail_url,
            "link": detail_url,
            "link_kind": "Detail Page",
            "link_usable": False,
        })

    return results

def parse_html_result_cards(source, query, soup, base_url):
    """
    Generic non-table fallback:
    find direct torrent/magnet links, then use the nearest row/card/list item
    as one search result.
    """
    results = []
    seen_containers = set()

    for link_node in soup.find_all("a", href=True):
        href = str(link_node.get("href") or "").strip()
        if not direct_download_href(href):
            continue

        container = None
        for parent_name in ("tr", "article", "li"):
            container = link_node.find_parent(parent_name)
            if container is not None:
                break

        if container is None:
            # Look for a nearby div whose class name suggests a result/card.
            current = link_node.parent
            for _ in range(5):
                if current is None:
                    break
                classes = " ".join(current.get("class") or []).lower()
                if any(x in classes for x in ("result", "torrent", "item", "card", "row")):
                    container = current
                    break
                current = current.parent

        container = container or link_node.parent
        if container is None:
            continue

        cid = id(container)
        if cid in seen_containers:
            continue
        seen_containers.add(cid)

        anchors = [
            a for a in container.find_all("a", href=True)
            if html_text(a) and not direct_download_href(a.get("href"))
        ]
        title_anchor = max(anchors, key=lambda a: len(html_text(a)), default=None)

        title = html_text(title_anchor)
        if not title:
            text = html_text(container)
            # Avoid using an entire giant page as a title.
            title = text[:350]

        if not title:
            continue

        chosen_link = absolute_url(base_url, href)
        page_link = absolute_url(base_url, title_anchor.get("href")) if title_anchor else ""

        full_text = html_text(container)
        language = detect_language(full_text, container)
        size_match = re.search(
            r"\b\d+(?:\.\d+)?\s*(?:KiB|MiB|GiB|TiB|KB|MB|GB|TB)\b",
            full_text,
            re.I
        )
        size_text = size_match.group(0) if size_match else ""
        size_bytes = parse_size_to_bytes(size_text)

        def labelled_number(labels):
            for label in labels:
                m = re.search(
                    rf"\b{label}\s*:?\s*(\d[\d,]*)",
                    full_text,
                    re.I
                )
                if m:
                    return parse_int_from_text(m.group(1))
            return None

        seeders = labelled_number(("seeders?", "seeds?"))
        leechers = labelled_number(("leechers?", "leeches?", "peers?"))
        downloads = labelled_number(("downloads?", "completed", "snatches?"))

        link_kind, link_usable = classify_link(chosen_link)
        kind = detect_kind(title, "")
        scope = detect_release_scope(title, "")
        results.append({
            "title": title,
            "source": source.get("name", ""),
            "kind": kind,
            "scope": scope,
            "type": destination_from_kind(kind),
            "resolution": detect_resolution(title),
            "size_bytes": size_bytes,
            "size": human_bytes(size_bytes) if size_bytes else size_text,
            "seeders": seeders,
            "leechers": leechers,
            "downloads": downloads,
            "date": "",
            "category": "",
            "trusted": None,
            "remake": None,
            "info_hash": "",
            "guid": page_link,
            "detail_url": page_link,
            "link": chosen_link,
            "link_kind": link_kind,
            "link_usable": link_usable,
        })

    return results



def advertised_feed_urls_from_html(content, base_url):
    """
    Return RSS/Atom feeds advertised by the CURRENT HTML page.

    This is intentionally page-specific. If a site's search-results page
    advertises a feed for the current query/filter state, the app can use
    that structured feed without knowing anything site-specific.
    """
    if BeautifulSoup is None:
        return []

    soup = BeautifulSoup(content, "html.parser")
    urls = []
    seen = set()

    for link in soup.find_all("link"):
        rel = [str(x).lower() for x in (link.get("rel") or [])]
        typ = str(link.get("type") or "").lower()
        href = str(link.get("href") or "").strip()

        if not href or "alternate" not in rel:
            continue

        if "rss" not in typ and "atom" not in typ:
            continue

        absolute = absolute_url(base_url, href)
        if absolute and absolute not in seen:
            seen.add(absolute)
            urls.append(absolute)

    return urls


def decoded_url_text(url):
    try:
        return urllib.parse.unquote_plus(str(url or "")).lower()
    except Exception:
        return str(url or "").lower()


def rank_advertised_feed(url, query, search_result_url):
    """
    Prefer feeds that appear tied to the current search result page.
    No site-specific parameter names are assumed.
    """
    score = 0
    decoded = decoded_url_text(url)
    query_norm = normalize_search_text(query)

    # Strong signal: query words actually appear in the advertised feed URL.
    query_words = [w for w in query_norm.split() if len(w) > 1]
    if query_words:
        hits = sum(1 for word in query_words if word in decoded)
        score += hits * 5

    try:
        feed_parts = urllib.parse.urlsplit(url)
        page_parts = urllib.parse.urlsplit(search_result_url)

        if feed_parts.netloc == page_parts.netloc:
            score += 3

        # Shared non-empty query values are a useful generic signal that the
        # feed describes the same filtered/search state.
        feed_qs = dict(
            urllib.parse.parse_qsl(
                feed_parts.query,
                keep_blank_values=True
            )
        )
        page_qs = dict(
            urllib.parse.parse_qsl(
                page_parts.query,
                keep_blank_values=True
            )
        )

        for key, value in page_qs.items():
            if value and feed_qs.get(key) == value:
                score += 2

    except Exception:
        pass

    return score


def try_advertised_search_feed(
    source,
    query,
    html_content,
    search_result_url,
    headers,
    timeout=15,
    fuzzy_threshold=70,
):
    """
    Search-result HTML may advertise an RSS/Atom feed for the current query.
    Try those feeds first and return the first one that actually contains
    Smart Search matches.
    """
    feed_urls = advertised_feed_urls_from_html(
        html_content,
        search_result_url,
    )

    if not feed_urls:
        return None, None, None

    feed_urls.sort(
        key=lambda url: rank_advertised_feed(
            url,
            query,
            search_result_url,
        ),
        reverse=True,
    )

    for feed_url in feed_urls[:5]:
        try:
            response = requests.get(
                feed_url,
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()

            results = parse_rss(
                source,
                query,
                response.content,
            )

            if results:
                # The advertised feed belongs to the current search-results
                # page, so it is already query-aware. Keep every returned row.
                return results, "Provider results", feed_url

        except Exception:
            # A bad advertised feed should never prevent the normal HTML
            # search-result parser from running.
            continue

    return None, None, None



def canonical_url_key(value):
    value = html.unescape(str(value or "").strip())
    if value.lower().startswith("magnet:"):
        from reliability import torrent_identity
        return torrent_identity(value)

    try:
        parts = urllib.parse.urlsplit(value)
        # Fragments don't matter for downloads.
        return urllib.parse.urlunsplit((
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            parts.query,
            ""
        ))
    except Exception:
        return value


def magnet_from_info_hash(info_hash):
    info_hash = str(info_hash or "").strip()

    # Standard BTIH representations:
    # 40 hexadecimal chars or 32 base32 chars.
    if re.fullmatch(r"[A-Fa-f0-9]{40}", info_hash):
        return f"magnet:?xt=urn:btih:{info_hash}"

    if re.fullmatch(r"[A-Za-z2-7]{32}", info_hash):
        return f"magnet:?xt=urn:btih:{info_hash}"

    return ""


def extract_info_hash_from_html(content):
    """
    Look specifically for an info-hash-labelled value rather than accepting
    arbitrary SHA1-looking strings from scripts/assets.
    """
    source = html.unescape(str(content or ""))

    patterns = [
        r"info\s*hash\s*[:\-]?\s*([A-Fa-f0-9]{40})",
        r"info\s*hash\s*[:\-]?\s*([A-Za-z2-7]{32})",
        r"infohash\s*[:=\-]?\s*[\"']?([A-Fa-f0-9]{40})",
        r"infohash\s*[:=\-]?\s*[\"']?([A-Za-z2-7]{32})",
    ]

    for pattern in patterns:
        match = re.search(pattern, source, re.I)
        if match:
            return match.group(1)

    return ""


def extract_usable_download_link_from_html(content, base_url):
    """
    Resolve a detail page using STRONG torrent signals only.

    Priority:
      1. magnet URI
      2. actual .torrent URL
      3. info-hash-derived magnet
      4. clearly torrent-shaped download URL

    Arbitrary HTTP links whose anchor merely says "download" are no longer
    accepted. That old behavior could resolve multiple unrelated rows to the
    same global navigation/download URL.
    """
    if BeautifulSoup is None:
        return "", "", False

    soup = BeautifulSoup(content, "html.parser")
    candidates = []
    seen = set()

    base_key = canonical_url_key(base_url)

    def add_candidate(url, score, kind_hint=""):
        url = html.unescape(str(url or "").strip())
        if not url:
            return

        absolute = url
        if not url.lower().startswith("magnet:"):
            absolute = absolute_url(base_url, url)

        key = canonical_url_key(absolute)
        if not key or key == base_key or key in seen:
            return

        seen.add(key)
        candidates.append((score, absolute, kind_hint))

    # 1) Anchors.
    for a in soup.find_all("a", href=True):
        href = html.unescape(str(a.get("href") or "").strip())
        if not href:
            continue

        low = href.lower()

        if low.startswith("magnet:"):
            add_candidate(href, 100, "Magnet")
            continue

        absolute = absolute_url(base_url, href)

        try:
            parts = urllib.parse.urlsplit(absolute)
            path_low = parts.path.lower()
            query_low = parts.query.lower()
        except Exception:
            path_low = low
            query_low = ""

        if path_low.endswith(".torrent"):
            add_candidate(absolute, 98, "Torrent")
            continue

        # Some providers expose a torrent endpoint such as:
        #   /torrent/download/<40-char-info-hash>
        # It is a real torrent target even without a .torrent suffix.
        if torrent_specific_http_url(absolute):
            info_hash = torrent_hash_from_url(
                absolute
            )
            magnet = magnet_from_info_hash(
                info_hash
            )

            if magnet:
                add_candidate(
                    magnet,
                    99,
                    "Magnet"
                )
            else:
                add_candidate(
                    absolute,
                    97,
                    "Torrent"
                )
            continue

        # Strong but non-extension torrent/download patterns.
        semantics = normalize_search_text(
            " ".join([
                html_text(a),
                " ".join(a.get("class") or []),
                str(a.get("id") or ""),
                str(a.get("title") or ""),
                str(a.get("aria-label") or ""),
            ])
        )

        url_signal = (
            "torrent" in path_low
            or "torrent" in query_low
            or "magnet" in path_low
            or "magnet" in query_low
        )
        semantic_signal = (
            "torrent" in semantics
            or "magnet" in semantics
        )

        # Require torrent-specific evidence from BOTH the URL or semantics.
        # A generic "Download" button alone is deliberately insufficient.
        if url_signal and semantic_signal:
            add_candidate(absolute, 80, "Download URL")

    # 2) data-* attributes.
    for tag in soup.find_all(True):
        for attr, value in tag.attrs.items():
            if not str(attr).lower().startswith("data-"):
                continue

            values = value if isinstance(value, (list, tuple)) else [value]

            for raw in values:
                raw = html.unescape(str(raw or "").strip())
                if not raw:
                    continue

                if raw.lower().startswith("magnet:"):
                    add_candidate(raw, 100, "Magnet")
                    continue

                absolute = absolute_url(base_url, raw)

                try:
                    path_low = urllib.parse.urlsplit(absolute).path.lower()
                except Exception:
                    path_low = absolute.lower()

                if path_low.endswith(".torrent"):
                    add_candidate(absolute, 98, "Torrent")

    # 3) Inline magnet in page source.
    source_text = html.unescape(str(content or ""))
    for match in re.finditer(
        r'magnet:\?xt=urn:btih:[A-Za-z0-9]+[^"\'<>\s]*',
        source_text,
        re.I
    ):
        add_candidate(match.group(0), 100, "Magnet")

    # 4) Info hash -> magnet.
    info_hash = extract_info_hash_from_html(content)
    if info_hash:
        magnet = magnet_from_info_hash(info_hash)
        if magnet:
            add_candidate(magnet, 95, "Magnet")

    if not candidates:
        return "", "", False

    candidates.sort(key=lambda item: item[0], reverse=True)
    _, best_url, kind_hint = candidates[0]

    kind, usable = classify_link(best_url)

    # A torrent-shaped HTTP URL may not end in ".torrent", but it was only
    # admitted above after strong torrent-specific checks.
    if not usable and kind_hint == "Download URL":
        kind, usable = classify_link(
            best_url,
            explicit_download=True
        )

    return best_url, kind_hint or kind, bool(usable)


def resolve_result_download_link(source, result, timeout=15):
    """
    Resolve a search-result/detail page into a usable download link.
    """
    resolved = dict(result or {})

    current_link = str(resolved.get("link") or "").strip()
    current_kind, current_usable = classify_link(current_link)

    if current_usable:
        resolved["link_kind"] = current_kind
        resolved["link_usable"] = True
        return resolved, None

    detail_url = (
        str(resolved.get("detail_url") or "").strip()
        or str(resolved.get("guid") or "").strip()
        or current_link
    )

    if not detail_url:
        return resolved, "No detail/download URL is available."

    parsed = urllib.parse.urlsplit(detail_url)
    if parsed.scheme not in ("http", "https"):
        return resolved, "The result has no usable HTTP detail page."

    try:
        response = requests.get(
            detail_url,
            headers=source_headers(source or {}),
            timeout=timeout,
        )
        response.raise_for_status()

        link, kind, usable = extract_usable_download_link_from_html(
            response.text,
            response.url,
        )

        detail_language = extract_detail_language(response.text)
        if detail_language:
            resolved["language"] = detail_language

        if not usable:
            return resolved, "No usable magnet/torrent link was found."

        resolved["link"] = link
        resolved["link_kind"] = kind
        resolved["link_usable"] = True
        resolved["detail_url"] = detail_url

        return resolved, None

    except Exception as exc:
        return resolved, friendly_source_error(exc)



def torrent_hash_from_url(url):
    """
    Recognize common torrent-download URLs that carry a BTIH hash in the path
    or query. This is stronger evidence than a generic 'Download' button.
    """
    value = html.unescape(str(url or "").strip())

    if not value:
        return ""

    match = re.search(
        r"(?:^|/)([A-Fa-f0-9]{40})(?:$|[/?#])",
        value
    )
    if match:
        return match.group(1)

    match = re.search(
        r"(?:hash|infohash|btih)=([A-Fa-f0-9]{40})",
        value,
        re.I
    )
    if match:
        return match.group(1)

    return ""


def torrent_specific_http_url(url):
    """
    Strong HTTP torrent URL detection. Paths such as /torrent/download/<hash>
    are accepted even when they do not end in .torrent.
    """
    value = str(url or "").strip()

    if not value:
        return False

    try:
        parts = urllib.parse.urlsplit(value)
        path = parts.path.lower()
        query = parts.query.lower()
    except Exception:
        path = value.lower()
        query = ""

    if path.endswith(".torrent"):
        return True

    info_hash = torrent_hash_from_url(value)

    if info_hash and any(
        token in path
        for token in (
            "/torrent/",
            "/torrents/",
            "/download/",
            "/torrent-download/",
        )
    ):
        return True

    if (
        "torrent" in path
        and (
            "download" in path
            or "hash=" in query
            or "infohash=" in query
        )
    ):
        return True

    return False


def page_movie_identity(soup, fallback_title=""):
    """
    Extract a detail-page title/year without confusing ratings or genres.
    """
    title = ""

    for selector in (
        "h1",
        ".movie-info h1",
        ".movie-title",
        "[itemprop='name']",
    ):
        node = soup.select_one(selector)
        if node:
            candidate = clean_result_title(
                html_text(node)
            )
            if (
                candidate
                and not is_bad_result_title(candidate)
            ):
                title = candidate
                break

    if not title:
        title = clean_result_title(
            fallback_title
        )

    page_text = html_text(soup)

    year = ""
    year_match = re.search(
        r"\b((?:19|20)\d{2})\b",
        page_text
    )
    if year_match:
        year = year_match.group(1)

    if (
        title
        and year
        and year not in title
    ):
        title = f"{title} ({year})"

    return title, year


def variant_context_for_anchor(anchor):
    """
    Find the smallest nearby container that describes one downloadable
    quality/variant. Stop before swallowing the entire page.
    """
    best = anchor
    current = anchor

    for _ in range(7):
        current = getattr(current, "parent", None)

        if current is None:
            break

        if getattr(current, "name", None) not in (
            "div", "li", "article", "section",
            "tr", "td", "figure"
        ):
            continue

        value = html_text(current)

        has_resolution = bool(
            re.search(
                r"\b(?:360p|480p|720p|1080p|1440p|2160p|4k)\b",
                value,
                re.I
            )
        )
        has_size = bool(
            re.search(
                r"\b\d+(?:\.\d+)?\s*"
                r"(?:KB|MB|GB|TB|KiB|MiB|GiB|TiB)\b",
                value,
                re.I
            )
        )

        if has_resolution or has_size:
            best = current

        # A compact block containing both is almost certainly the variant.
        if has_resolution and has_size and len(value) < 1200:
            return current

        # Never use a giant page container.
        if len(value) > 3500:
            break

    return best


def variant_resolution_and_quality(text_value):
    resolution = detect_resolution(
        text_value
    )

    quality = ""

    quality_match = re.search(
        r"\b(WEB(?:-DL|Rip)?|BluRay|BDRip|BRRip|HDTV|DVDRip)\b",
        str(text_value or ""),
        re.I
    )
    if quality_match:
        quality = quality_match.group(1)

    return resolution, quality


def variant_size(text_value):
    match = re.search(
        r"\b\d+(?:\.\d+)?\s*"
        r"(?:KB|MB|GB|TB|KiB|MiB|GiB|TiB)\b",
        str(text_value or ""),
        re.I
    )

    if not match:
        return "", 0

    size_text = match.group(0)
    return size_text, parse_size_to_bytes(
        size_text
    )


def variant_seeders(text_value):
    match = re.search(
        r"\bSeeds?\s*:?\s*(\d[\d,]*)",
        str(text_value or ""),
        re.I
    )

    if match:
        return parse_int_from_text(
            match.group(1)
        )

    return None


def direct_torrent_candidates_from_detail(soup, base_url):
    """
    Collect torrent/magnet targets from a detail page and preserve the nearby
    DOM context so each quality can become a separate result row.
    """
    candidates = []
    seen = set()

    for anchor in soup.find_all(
        "a",
        href=True
    ):
        href = html.unescape(
            str(anchor.get("href") or "").strip()
        )

        if not href:
            continue

        absolute = (
            href
            if href.lower().startswith("magnet:")
            else absolute_url(base_url, href)
        )

        info_hash = ""

        if href.lower().startswith("magnet:"):
            match = re.search(
                r"urn:btih:([A-Za-z0-9]+)",
                href,
                re.I
            )
            if match:
                info_hash = match.group(1)

        if not info_hash:
            info_hash = torrent_hash_from_url(
                absolute
            )

        strong = (
            href.lower().startswith("magnet:")
            or torrent_specific_http_url(absolute)
        )

        if not strong:
            continue

        key = (
            info_hash.lower()
            if info_hash
            else canonical_url_key(absolute)
        )

        if key in seen:
            continue

        seen.add(key)

        context = variant_context_for_anchor(
            anchor
        )
        context_text = html_text(context)

        # A magnet derived from the BTIH is more portable than an HTTP
        # download endpoint and avoids cookies/session dependence.
        link = absolute
        link_kind = "Torrent"

        magnet = magnet_from_info_hash(
            info_hash
        )
        if magnet:
            link = magnet
            link_kind = "Magnet"
        elif href.lower().startswith("magnet:"):
            link_kind = "Magnet"

        candidates.append({
            "link": link,
            "link_kind": link_kind,
            "info_hash": info_hash,
            "context": context,
            "context_text": context_text,
        })

    return candidates


def variant_seed_sequence_from_page(soup):
    """
    Detail pages sometimes display seeds in a second technical-spec section
    rather than beside the download button. Keep the sequence as a fallback
    for otherwise seed-less variant rows.
    """
    values = []

    for node in soup.find_all(
        string=re.compile(r"\bSeeds?\s*:?\s*\d", re.I)
    ):
        match = re.search(
            r"\bSeeds?\s*:?\s*(\d[\d,]*)",
            str(node),
            re.I
        )
        if match:
            value = parse_int_from_text(
                match.group(1)
            )
            if value is not None:
                values.append(value)

    if values:
        return values

    # Text extraction can merge labels/numbers across sibling tags.
    for match in re.finditer(
        r"\bSeeds?\s*:?\s*(\d[\d,]*)",
        html_text(soup),
        re.I
    ):
        value = parse_int_from_text(
            match.group(1)
        )
        if value is not None:
            values.append(value)

    return values


def parse_html_detail_variants(
    source,
    query,
    content,
    base_url,
    fallback_title=""
):
    """
    Turn a movie/detail page into one row per downloadable quality.

    Example shape:
        Movie title [720p WEB]
        Movie title [1080p WEB]

    Each row gets its own size, language, seeds when available, and its own
    magnet/torrent target.
    """
    if BeautifulSoup is None:
        return []

    soup = BeautifulSoup(
        content,
        "html.parser"
    )

    direct = direct_torrent_candidates_from_detail(
        soup,
        base_url
    )

    if not direct:
        return []

    movie_title, year = page_movie_identity(
        soup,
        fallback_title=fallback_title or query
    )

    if not movie_title:
        movie_title = clean_result_title(
            fallback_title or query
        )

    global_language = extract_detail_language(
        content
    )

    page_seeders = variant_seed_sequence_from_page(
        soup
    )

    variants = []

    for index, candidate in enumerate(direct):
        context = candidate.get("context")
        context_text = candidate.get(
            "context_text",
            ""
        )

        resolution, quality = (
            variant_resolution_and_quality(
                context_text
            )
        )

        size_text, size_bytes = variant_size(
            context_text
        )

        language = detect_language(
            context_text,
            context
        ) or global_language

        seeders = variant_seeders(
            context_text
        )

        if (
            seeders is None
            and index < len(page_seeders)
        ):
            seeders = page_seeders[index]

        suffix_parts = []

        if resolution:
            suffix_parts.append(
                resolution
            )

        if quality:
            suffix_parts.append(
                quality
            )

        variant_title = movie_title

        if suffix_parts:
            variant_title = (
                f"{movie_title} "
                f"[{' '.join(suffix_parts)}]"
            )

        variants.append({
            "title": variant_title[:350],
            "source": source.get("name", ""),
            "kind": "Movie",
            "scope": "Movie",
            "type": "Movie",
            "resolution": resolution,
            "language": language,
            "size_bytes": size_bytes,
            "size": (
                human_bytes(size_bytes)
                if size_bytes
                else size_text
            ),
            "seeders": seeders,
            "leechers": None,
            "downloads": None,
            "date": "",
            "category": "Movie",
            "trusted": None,
            "remake": None,
            "info_hash": candidate.get(
                "info_hash",
                ""
            ),
            "guid": base_url,
            "detail_url": base_url,
            "link": candidate.get(
                "link",
                ""
            ),
            "link_kind": candidate.get(
                "link_kind",
                "Torrent"
            ),
            "link_usable": bool(
                candidate.get("link")
            ),
            "_detail_variant": True,
        })

    # De-dupe identical resolution/hash rows.
    deduped = []
    seen = set()

    for item in variants:
        key = (
            item.get("info_hash", "").lower(),
            item.get("resolution", "").lower(),
            canonical_url_key(
                item.get("link", "")
            ),
        )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(item)

    return deduped


def strong_detail_match(result, query):
    score = provider_result_relevance(
        result.get("title", ""),
        query
    )

    # Exact/phrase/all-word matches only. This avoids opening many detail
    # pages for broad/fuzzy catalog results.
    return score >= 8000


def expand_strong_detail_results(
    source,
    results,
    query,
    headers,
    timeout=15,
    max_details=4,
):
    """
    For the strongest catalog matches, fetch the detail page during search and
    replace one generic movie row with its separate downloadable qualities.
    """
    expanded = []
    fetched = 0

    for result in results:
        detail_url = str(
            result.get("detail_url") or ""
        ).strip()

        should_expand = (
            # Search-table rows are already complete provider releases.
            # Never rewrite their titles through movie-detail expansion.
            not result.get("link_usable")
            and not result.get("_table_result")
            and detail_url.startswith(
                ("http://", "https://")
            )
            and strong_detail_match(
                result,
                query
            )
            and fetched < max_details
        )

        if not should_expand:
            expanded.append(result)
            continue

        fetched += 1

        try:
            response = requests.get(
                detail_url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )
            response.raise_for_status()

            variants = parse_html_detail_variants(
                source,
                query,
                response.text,
                response.url,
                fallback_title=result.get(
                    "title",
                    ""
                ),
            )

            if variants:
                expanded.extend(
                    variants
                )
                continue

        except Exception:
            pass

        # If detail expansion fails, keep the original card row.
        expanded.append(result)

    return expanded



def table_header_tokens(table):
    rows = table.find_all("tr")
    if not rows:
        return []

    header_cells = rows[0].find_all(["th", "td"])

    return [
        normalize_search_text(
            html_text(cell)
        ).strip()
        for cell in header_cells
    ]


def table_looks_like_result_list(table):
    """
    Detect conventional torrent/search result tables.

    A result-list page contains many separate releases. It must never be
    interpreted as one movie detail page with multiple quality variants.
    """
    rows = table.find_all("tr")
    if len(rows) < 2:
        return False

    headers = table_header_tokens(table)
    header_text = " ".join(headers)

    has_title_header = any(
        re.search(
            r"\b(?:name|title|torrent|release)\b",
            header
        )
        for header in headers
    )

    metadata_words = (
        "size", "date", "time", "seed", "seeds", "seeders",
        "leech", "leechers", "peer", "peers", "completed",
        "downloads", "category", "uploader", "link"
    )

    has_metadata_header = any(
        re.search(
            rf"\b{re.escape(word)}\b",
            header_text
        )
        for word in metadata_words
    )

    if has_title_header and has_metadata_header:
        return True

    # Fallback for tables with icon-heavy/minimal headers.
    data_rows = rows[1:]

    if len(data_rows) >= 3:
        useful_rows = 0

        for row in data_rows[:8]:
            anchors = row.find_all("a", href=True)
            row_text = html_text(row)

            has_size = bool(
                re.search(
                    r"\b\d+(?:\.\d+)?\s*"
                    r"(?:KB|MB|GB|TB|KiB|MiB|GiB|TiB)\b",
                    row_text,
                    re.I
                )
            )

            if anchors and (has_size or len(anchors) >= 2):
                useful_rows += 1

        if useful_rows >= 3:
            return True

    return False


def page_has_result_table(soup):
    return any(
        table_looks_like_result_list(table)
        for table in soup.find_all("table")
    )


def dedupe_html_results(results):
    """
    Dedupe results without changing the displayed provider title.

    The normalized title is only an internal comparison key. The original
    title string remains untouched.
    """
    results = list(results)

    results.sort(
        key=lambda item: (
            0 if item.get("link_usable") else 1,
            0 if item.get("size_bytes") else 1,
            0 if item.get("seeders") is not None else 1,
        )
    )

    deduped = []
    seen = set()

    for item in results:
        detail = (
            item.get("detail_url")
            or item.get("guid")
            or item.get("link")
            or ""
        )

        key = (
            canonical_url_key(detail),
            normalize_search_text(
                item.get("title", "")
            ),
            item.get("size_bytes") or 0,
        )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(item)

    return deduped


def parse_html_results(source, query, content, base_url):
    if BeautifulSoup is None:
        raise RuntimeError(
            "HTML Search needs BeautifulSoup. "
            "Run: python -m pip install beautifulsoup4"
        )

    soup = BeautifulSoup(content, "html.parser")

    # ------------------------------------------------------------
    # 1) CONVENTIONAL TORRENT / SEARCH TABLES
    #
    # Each row is a separate release and its title belongs to that row.
    # Preserve that provider title EXACTLY.
    #
    # Do this BEFORE detail-page detection. Previous builds scanned all
    # torrent links first, mistook a search page for one movie detail page,
    # and then reused one movie-style title across many separate releases.
    # ------------------------------------------------------------
    table_results = parse_html_result_table(
        source,
        query,
        soup,
        base_url
    )

    if page_has_result_table(soup) and table_results:
        return dedupe_html_results(
            table_results
        )

    # ------------------------------------------------------------
    # 2) TRUE SINGLE MOVIE / DETAIL PAGES
    #
    # These can legitimately expand into one row per quality, e.g.
    # 720p / 1080p.
    # ------------------------------------------------------------
    detail_variants = parse_html_detail_variants(
        source,
        query,
        content,
        base_url,
        fallback_title=query
    )

    if detail_variants:
        return dedupe_html_results(
            detail_variants
        )

    # ------------------------------------------------------------
    # 3) CARD / CATALOG SEARCH PAGES
    # ------------------------------------------------------------
    results = list(table_results)

    results.extend(
        parse_html_result_cards(
            source,
            query,
            soup,
            base_url
        )
    )

    results.extend(
        parse_html_catalog_cards(
            source,
            query,
            soup,
            base_url
        )
    )

    return dedupe_html_results(
        results
    )




def build_url_from_template(
    template,
    query,
    query_param="",
    static=False
):
    template = str(template or "").strip()
    query_param = str(query_param or "").strip()

    if static:
        return template

    if "{query}" in template:
        try:
            parts = urllib.parse.urlsplit(template)

            if "{query}" in parts.path:
                encoded = urllib.parse.quote(
                    str(query or ""),
                    safe=""
                )
            else:
                encoded = urllib.parse.quote_plus(
                    str(query or "")
                )

            return template.replace(
                "{query}",
                encoded
            )

        except Exception:
            return template.replace(
                "{query}",
                urllib.parse.quote_plus(
                    str(query or "")
                )
            )

    if query_param:
        parsed = urllib.parse.urlsplit(template)

        qs = urllib.parse.parse_qsl(
            parsed.query,
            keep_blank_values=True
        )

        qs = [
            (key, value)
            for key, value in qs
            if key != query_param
        ]

        qs.append(
            (query_param, str(query or ""))
        )

        new_query = urllib.parse.urlencode(qs)

        return urllib.parse.urlunsplit((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            new_query,
            parsed.fragment,
        ))

    return template


def build_search_url(source, query):
    template = str(
        source.get("url") or ""
    ).strip()

    query_param = str(
        source.get("query_param") or ""
    ).strip()

    static = is_static_source(source)

    url = build_url_from_template(
        template,
        query,
        query_param,
        static=static,
    )

    if (
        not static
        and "{query}" not in template
        and not query_param
        and (source.get("search_mode") or "Auto") == "Search Endpoint"
    ):
        raise ValueError(
            "Search Endpoint mode needs {query} in the URL "
            "or a Query Parameter"
        )

    return url


def build_dynamic_feed_url(source, query):
    template = str(
        source.get("dynamic_feed_url") or ""
    ).strip()

    query_param = str(
        source.get("dynamic_feed_query_param") or ""
    ).strip()

    if not template:
        return ""

    if "{query}" not in template and not query_param:
        raise ValueError(
            "Dynamic feed needs {query} in the URL or "
            "a Dynamic Feed Query Param"
        )

    return build_url_from_template(
        template,
        query,
        query_param,
        static=False,
    )


def parse_rss(source, query, content):
    root = ET.fromstring(content)
    items = [
        el for el in root.iter()
        if local_name(el.tag) in ("item", "entry")
    ]

    results = []

    for item in items:
        title = html.unescape(
            find_descendant_value(item, ["title", "name"])
        ).strip()

        if not title:
            continue

        link, link_kind, link_usable = find_link_in_xml(item)

        size_text = find_descendant_value(
            item, ["size", "length", "filesize", "file_size", "bytes"]
        )
        seeders_text = find_descendant_value(
            item, ["seeders", "seeds", "seed", "seedcount", "seed_count"]
        )
        leechers_text = find_descendant_value(
            item, ["leechers", "leeches", "peers", "peercount", "peer_count"]
        )
        downloads_text = find_descendant_value(
            item, ["downloads", "downloadcount", "download_count", "completed", "snatches"]
        )

        category = find_descendant_value(item, ["category", "type", "kind"])
        category_id = find_descendant_value(item, ["categoryid", "category_id"])
        language = find_descendant_value(
            item, ["language", "lang", "audio_language", "audio_lang"]
        )
        if not language:
            language = detect_language(title + " " + category)
        res = find_descendant_value(item, ["resolution", "quality"]) or detect_resolution(title)

        date_raw = find_descendant_value(
            item, ["pubdate", "published", "updated", "date", "created"]
        )
        date_display, date_ts = normalize_date(date_raw)

        trusted = normalize_yes_no(
            find_descendant_value(item, ["trusted", "verified"])
        )
        remake = normalize_yes_no(
            find_descendant_value(item, ["remake", "repack"])
        )
        info_hash = find_descendant_value(
            item, ["infohash", "info_hash", "hash"]
        )
        guid = find_descendant_value(item, ["guid", "id"])

        def parse_count(raw):
            if raw in (None, ""):
                return None
            digits = re.sub(r"[^\d]", "", str(raw))
            return int(digits) if digits else None

        seeders = parse_count(seeders_text)
        leechers = parse_count(leechers_text)
        downloads = parse_count(downloads_text)
        size_bytes = parse_size_to_bytes(size_text)
        kind = detect_kind(title, category)

        results.append({
            "title": title,
            "source": source.get("name", ""),
            "kind": kind,
            "type": "Movie" if kind == "Movie" else "Series",
            "category": category,
            "category_id": category_id,
            "resolution": res,
            "language": language,
            "size_bytes": size_bytes,
            "size": human_bytes(size_bytes) if size_bytes else (size_text or None),
            "seeders": seeders,
            "leechers": leechers,
            "downloads": downloads,
            "trusted": trusted,
            "remake": remake,
            "date": date_display or None,
            "date_ts": date_ts,
            "info_hash": info_hash or None,
            "guid": guid or None,
            "link": link,
            "link_kind": link_kind,
            "link_usable": bool(link_usable),
        })

    return results


def parse_json_results(source, query, content):
    obj = json.loads(content)

    results_path = (source.get("results_path") or "").strip()
    if results_path:
        items = get_by_path(obj, results_path)
        if not isinstance(items, list):
            raise ValueError(
                f"Results path '{results_path}' did not point to a JSON list"
            )
    elif isinstance(obj, list):
        items = obj
    elif isinstance(obj, dict):
        items = None
        for key in ("results", "items", "data", "torrents", "releases", "entries"):
            if isinstance(obj.get(key), list):
                items = obj[key]
                break

        if items is None:
            for value in obj.values():
                if isinstance(value, dict):
                    for key in ("results", "items", "data", "torrents", "releases"):
                        if isinstance(value.get(key), list):
                            items = value[key]
                            break
                if items is not None:
                    break

        if items is None:
            items = []
    else:
        items = []

    results = []

    for item in items:
        if not isinstance(item, dict):
            continue

        title = str(mapped_or_default(
            item, source, "title",
            ["title", "name", "release_name", "torrent_name"]
        ) or "").strip()

        if not title:
            continue

        mappings = source.get("mappings") or {}
        link_mapping = (mappings.get("link") or "").strip()
        link = str(mapped_or_default(
            item, source, "link",
            [
                "magnet", "magnet_uri", "magnetUrl", "magnet_url",
                "torrent", "torrent_url", "download", "download_url", "url"
            ]
        ) or "").strip()

        # If a field was explicitly mapped as the link, trust it as a download endpoint.
        explicit_download = bool(link_mapping)
        if not explicit_download:
            # Recognize common explicit download keys if present.
            explicit_download = any(
                key in item and item.get(key) == link
                for key in ("magnet", "magnet_uri", "magnetUrl", "magnet_url",
                            "torrent", "torrent_url", "download", "download_url")
            )
        link_kind, link_usable = classify_link(link, explicit_download=explicit_download)

        size_val = mapped_or_default(
            item, source, "size",
            ["size_bytes", "bytes", "size", "filesize", "file_size"]
        )
        size_bytes = parse_size_to_bytes(size_val)

        def parse_count(value):
            if value in (None, ""):
                return None
            try:
                return int(value)
            except Exception:
                digits = re.sub(r"[^\d]", "", str(value))
                return int(digits) if digits else None

        seeders = parse_count(mapped_or_default(
            item, source, "seeders",
            ["seeders", "seeds", "seed_count", "seed"]
        ))
        leechers = parse_count(mapped_or_default(
            item, source, "leechers",
            ["leechers", "leeches", "peers", "peer_count"]
        ))
        downloads = parse_count(mapped_or_default(
            item, source, "downloads",
            ["downloads", "download_count", "completed", "snatches"]
        ))

        category_raw = mapped_or_default(
            item, source, "type", ["type", "category", "kind"]
        )
        category = str(category_raw or "").strip()

        resolution = str(mapped_or_default(
            item, source, "resolution",
            ["resolution", "quality", "video_quality"]
        ) or "").strip()
        if not resolution:
            resolution = detect_resolution(title)

        language = str(mapped_or_default(
            item, source, "language",
            ["language", "lang", "audio_language", "audio_lang"]
        ) or "").strip()
        if not language:
            language = detect_language(title + " " + category)

        date_raw = mapped_or_default(
            item, source, "date",
            ["date", "published", "pubDate", "created_at", "uploaded_at", "updated_at"]
        )
        date_display, date_ts = normalize_date(date_raw)

        trusted = normalize_yes_no(mapped_or_default(
            item, source, "trusted", ["trusted", "verified"]
        ))
        remake = normalize_yes_no(mapped_or_default(
            item, source, "remake", ["remake", "repack"]
        ))
        info_hash = mapped_or_default(
            item, source, "info_hash", ["info_hash", "infoHash", "hash"]
        )

        kind = detect_kind(title, category)

        results.append({
            "title": title,
            "source": source.get("name", ""),
            "kind": kind,
            "type": "Movie" if kind == "Movie" else "Series",
            "category": category,
            "category_id": None,
            "resolution": resolution,
            "language": language,
            "size_bytes": size_bytes,
            "size": human_bytes(size_bytes) if size_bytes else (str(size_val) if size_val not in (None, "") else None),
            "seeders": seeders,
            "leechers": leechers,
            "downloads": downloads,
            "trusted": trusted,
            "remake": remake,
            "date": date_display or None,
            "date_ts": date_ts,
            "info_hash": str(info_hash).strip() if info_hash not in (None, "") else None,
            "guid": None,
            "link": link,
            "link_kind": link_kind,
            "link_usable": bool(link_usable),
        })

    return results



QUERY_STOP_WORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "on",
    "at", "for", "with", "from", "by"
}


def significant_query_tokens(query):
    tokens = [
        token
        for token in normalize_search_text(query).split()
        if len(token) >= 3 and token not in QUERY_STOP_WORDS
    ]

    if tokens:
        return tokens

    return [
        token
        for token in normalize_search_text(query).split()
        if len(token) >= 2
    ]


def signal_confirms_query(signal, query):
    signal = normalize_search_text(
        urllib.parse.unquote_plus(str(signal or ""))
    )
    query_norm = normalize_search_text(query)

    if not signal or not query_norm:
        return False

    if query_norm in signal:
        return True

    tokens = significant_query_tokens(query)
    if not tokens:
        return False

    hits = sum(1 for token in tokens if token in signal)

    # Single-word searches need that word. Multi-word searches need all
    # meaningful words or at least 2/3 of them.
    if len(tokens) == 1:
        return hits == 1

    required = max(2, (len(tokens) * 2 + 2) // 3)
    return hits >= required


def html_query_confirmation_signals(content, final_url):
    """
    Extract ONLY places that normally identify the active query. We do not
    scan the entire result list, because a random catalog title could contain
    one of the query words and create a false positive.
    """
    signals = [final_url]

    if BeautifulSoup is None:
        return signals

    soup = BeautifulSoup(content, "html.parser")

    # Canonical / OpenGraph URL often contains the active search slug.
    for tag in soup.find_all(["meta", "link"]):
        prop = str(
            tag.get("property")
            or tag.get("name")
            or tag.get("rel")
            or ""
        ).lower()

        if any(key in prop for key in ("og:url", "canonical")):
            value = tag.get("content") or tag.get("href")
            if value:
                signals.append(str(value))

    # Search controls echoing the submitted value.
    for inp in soup.find_all(["input", "textarea"]):
        typ = str(inp.get("type") or "").lower()
        name = str(inp.get("name") or "").lower()
        value = str(inp.get("value") or "").strip()

        if not value:
            continue

        if (
            typ == "search"
            or name in {
                "q", "query", "search", "search_query",
                "keyword", "keywords", "term", "text", "s"
            }
        ):
            # Ignore generic control text.
            if normalize_search_text(value) not in {
                "quick search", "search", "search..."
            }:
                signals.append(value)

    # Result/search headings.
    for node in soup.find_all(["h1", "h2", "h3"]):
        value = html_text(node).strip()
        semantic = normalize_search_text(
            " ".join([
                value,
                " ".join(node.get("class") or []),
                str(node.get("id") or ""),
            ])
        )

        if any(
            word in semantic
            for word in (
                "search", "result", "results", "movies with",
                "showing", "found", "matching"
            )
        ):
            signals.append(value)

    return signals


def html_query_was_applied(content, final_url, query):
    if not query:
        return True

    return any(
        signal_confirms_query(signal, query)
        for signal in html_query_confirmation_signals(
            content,
            final_url
        )
    )


def source_origin_for_redetect(source):
    origin = str(
        source.get("origin_website")
        or source.get("detected_final_url")
        or ""
    ).strip()

    if origin:
        return origin

    try:
        parts = urllib.parse.urlsplit(
            str(source.get("url") or "")
        )
        if parts.scheme and parts.netloc:
            return urllib.parse.urlunsplit(
                (parts.scheme, parts.netloc, "/", "", "")
            )
    except Exception:
        pass

    return ""


def fresh_html_search_candidates(source, headers, timeout=15):
    """
    Re-detect the site's current search interfaces when the configured HTML
    endpoint appears to have ignored the query.

    This makes old saved SearchAction/OpenSearch sources self-healing when the
    current page exposes a better browser search form.
    """
    origin = source_origin_for_redetect(source)
    if not origin:
        return []

    try:
        page_title, final_url, candidates = detect_site_sources(
            origin,
            timeout=min(timeout, 12)
        )
    except Exception:
        return []

    ready = [
        candidate
        for candidate in candidates
        if (
            not candidate.get("_rejected")
            and "html" in str(candidate.get("type") or "").lower()
        )
    ]

    priority = {
        "Search Form": 0,
        "JSON-LD SearchAction": 1,
        "OpenSearch": 2,
    }

    ready.sort(
        key=lambda candidate: priority.get(
            candidate.get("_detected_by"),
            9
        )
    )

    return ready


def try_html_search_candidate(candidate, query, headers, timeout=15):
    url = build_search_url(candidate, query)

    response = requests.get(
        url,
        headers=headers,
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()

    return response


def provider_result_relevance(title, query):
    """
    Re-rank provider results locally without deleting them. Exact/complete
    title matches rise to the top while the provider's broader matches remain
    available underneath.
    """
    title_norm = normalize_search_text(title)
    query_norm = normalize_search_text(query)

    if not query_norm:
        return 0.0

    if title_norm == query_norm:
        return 10000.0

    if query_norm in title_norm:
        return 9000.0 + fuzzy_score(query, title)

    q_tokens = significant_query_tokens(query)
    if q_tokens:
        hits = sum(
            1 for token in q_tokens
            if token in title_norm
        )

        if hits == len(q_tokens):
            return 8000.0 + fuzzy_score(query, title)

        if hits:
            return 5000.0 + (
                hits / max(1, len(q_tokens))
            ) * 1000.0 + fuzzy_score(query, title)

    return fuzzy_score(query, title)


def rank_provider_results(results, query):
    indexed = list(enumerate(results))

    indexed.sort(
        key=lambda pair: (
            -provider_result_relevance(
                pair[1].get("title", ""),
                query
            ),
            pair[0],
        )
    )

    return [item for _, item in indexed]


def html_candidate_result_score(
    results,
    query,
    query_verified=False,
):
    if not results:
        return -1.0

    relevances = [
        provider_result_relevance(
            item.get("title", ""),
            query
        )
        for item in results
    ]

    best = max(
        relevances,
        default=0.0
    )

    strong = sum(
        1
        for score in relevances
        if score >= 8000
    )

    relevant = sum(
        1
        for score in relevances
        if score >= 5000
    )

    usable = sum(
        1
        for item in results
        if item.get("link_usable")
    )

    detail_variants = sum(
        1
        for item in results
        if item.get("_detail_variant")
    )

    # Content relevance is more important than merely seeing the query echoed
    # in a search box. That prevents a default/latest catalog with an echoed
    # query from beating a candidate that actually returned the requested film.
    score = (
        best * 10.0
        + strong * 2500.0
        + relevant * 500.0
        + usable * 100.0
        + detail_variants * 250.0
        + min(len(results), 100) * 5.0
    )

    if query_verified:
        score += 5000.0

    return score


def candidate_key_for_search(candidate, query):
    try:
        return canonical_url_key(
            build_search_url(
                candidate,
                query
            )
        )
    except Exception:
        return ""


def resolve_html_search_response(
    source,
    provider_query,
    user_query,
    headers,
    timeout=15,
):
    """
    Evaluate every plausible current HTML search interface instead of stopping
    on the first endpoint that merely echoes the query.

    Returns:
        response, parse_source, status, preparsed_results
    """
    candidate_sources = []

    configured = deep_copy(
        source
    )
    configured["_candidate_label"] = (
        "Configured search"
    )
    candidate_sources.append(
        configured
    )

    for candidate in fresh_html_search_candidates(
        source,
        headers,
        timeout=timeout
    ):
        merged = deep_copy(
            candidate
        )

        # Preserve the user's source identity/settings.
        merged["name"] = source.get(
            "name",
            merged.get("name", "")
        )
        merged["enabled"] = source.get(
            "enabled",
            True
        )
        merged["origin_website"] = source.get(
            "origin_website",
            ""
        )
        merged["detected_final_url"] = source.get(
            "detected_final_url",
            ""
        )

        merged["_candidate_label"] = candidate.get(
            "_detected_by",
            "Detected search"
        )

        candidate_sources.append(
            merged
        )

    # De-dupe search URLs before making requests.
    unique_candidates = []
    seen_candidate_urls = set()

    for candidate in candidate_sources:
        key = candidate_key_for_search(
            candidate,
            provider_query
        )

        if not key or key in seen_candidate_urls:
            continue

        seen_candidate_urls.add(
            key
        )
        unique_candidates.append(
            candidate
        )

    best = None

    for candidate in unique_candidates:
        try:
            request_url = build_search_url(
                candidate,
                provider_query
            )

            response = requests.get(
                request_url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )
            response.raise_for_status()

            parsed_results = parse_html_results(
                candidate,
                user_query,
                response.text,
                response.url,
            )

            verified = html_query_was_applied(
                response.text,
                response.url,
                user_query
            )

            score = html_candidate_result_score(
                parsed_results,
                user_query,
                query_verified=verified,
            )

            entry = {
                "score": score,
                "response": response,
                "source": candidate,
                "results": parsed_results,
                "verified": verified,
                "label": candidate.get(
                    "_candidate_label",
                    "HTML search"
                ),
            }

            if (
                best is None
                or entry["score"] > best["score"]
            ):
                best = entry

        except Exception:
            continue

    if best is None:
        # Preserve previous error behavior by trying the configured source one
        # final time and letting requests raise a meaningful error.
        request_url = build_search_url(
            source,
            provider_query
        )
        response = requests.get(
            request_url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()

        return (
            response,
            source,
            "Configured search",
            [],
        )

    results = best["results"]

    # If even the best provider page has no meaningful title matches, never
    # present an unrelated default/latest catalog as a successful search.
    strong_or_relevant = any(
        provider_result_relevance(
            item.get("title", ""),
            user_query
        ) >= 5000
        for item in results
    )

    if (
        user_query
        and results
        and not strong_or_relevant
    ):
        results, local_stage = smart_filter_results(
            results,
            user_query,
            fuzzy_threshold=70,
        )

        status = (
            f"{best['label']} • "
            f"provider results weak • "
            f"local {local_stage}"
        )
    else:
        verify_text = (
            "query verified"
            if best["verified"]
            else "best matching interface"
        )

        status = (
            f"{best['label']} • "
            f"{verify_text}"
        )

    return (
        best["response"],
        best["source"],
        status,
        results,
    )



def fetch_source(
    source,
    query,
    timeout=15,
    match_mode="Smart",
    fuzzy_threshold=70,
    local_query=None
):
    if source_provider_identity(source) == "yts":
        from yts_provider import fetch_yts
        return fetch_yts(source, query if local_query is None else local_query, timeout)
    if source_provider_identity(source) in ("eztv", "annas_archive"):
        from provider_pages import provider_url, parse_provider_page
        url = provider_url(source, query if local_query is None else local_query)
        response = requests.get(url, timeout=timeout, headers=source_headers(source))
        if response.status_code in (403, 429, 503):
            raise RuntimeError("Site requires browser verification. Use the Read Provider Page button below Search results.")
        response.raise_for_status()
        return parse_provider_page(source, response.text, response.url)
    if source_provider_identity(source) == "piratebay":
        from amf_features import fetch_piratebay
        return fetch_piratebay(source, query, timeout)
    user_query = query if local_query is None else local_query
    provider_query = provider_query_for_search(query, "Smart")
    headers = source_headers(source)

    try:
        dynamic_feed = str(
            source.get("dynamic_feed_url") or ""
        ).strip()

        # ----------------------------------------------------
        # 1) Explicit query-aware structured feed
        # ----------------------------------------------------
        if dynamic_feed:
            url = build_dynamic_feed_url(
                source,
                provider_query,
            )
            r = requests.get(
                url,
                headers=headers,
                timeout=timeout,
            )
            r.raise_for_status()

            results = parse_rss(
                source,
                user_query,
                r.content,
            )
            results = rank_provider_results(
                results,
                user_query
            )

            stage = "Provider results"
            transport = "Configured dynamic RSS/Atom"

        else:
            stype = (
                source.get("type") or ""
            ).lower()

            # ------------------------------------------------
            # 2) HTML website search endpoint
            # ------------------------------------------------
            if "html" in stype or "website" in stype:
                (
                    r,
                    parse_source,
                    query_status,
                    preparsed_results,
                ) = resolve_html_search_response(
                    source,
                    provider_query,
                    user_query,
                    headers,
                    timeout=timeout,
                )

                feed_results, feed_stage, feed_url = (
                    try_advertised_search_feed(
                        parse_source,
                        user_query,
                        r.text,
                        r.url,
                        headers,
                        timeout=timeout,
                        fuzzy_threshold=fuzzy_threshold,
                    )
                )

                if (
                    feed_results is not None
                    and feed_results
                    and not any(
                        item.get("_detail_variant")
                        for item in preparsed_results
                    )
                ):
                    results = rank_provider_results(
                        feed_results,
                        user_query
                    )
                    stage = "Provider results"
                    transport = (
                        f"Advertised search RSS/Atom • "
                        f"{query_status}"
                    )

                else:
                    results = (
                        preparsed_results
                        if preparsed_results is not None
                        else parse_html_results(
                            parse_source,
                            user_query,
                            r.text,
                            r.url,
                        )
                    )

                    # For strong movie/catalog matches, fetch only the matching
                    # detail pages and expose the actual downloadable
                    # resolutions as separate rows.
                    results = expand_strong_detail_results(
                        parse_source,
                        results,
                        user_query,
                        headers,
                        timeout=timeout,
                        max_details=4,
                    )

                    results = rank_provider_results(
                        results,
                        user_query
                    )

                    stage = "Provider results"
                    transport = (
                        f"HTML search • {query_status}"
                    )

            else:
                # Normal URL-based non-HTML transports.
                url = build_search_url(
                    source,
                    provider_query,
                )
                r = requests.get(
                    url,
                    headers=headers,
                    timeout=timeout,
                )
                r.raise_for_status()

                # --------------------------------------------
                # 3) JSON search API
                # --------------------------------------------
                if "json" in stype or "api" in stype:
                    results = parse_json_results(
                        source,
                        user_query,
                        r.text,
                    )

                    if not is_static_source(source):
                        results = rank_provider_results(
                            results,
                            user_query
                        )
                        stage = "Provider results"
                        transport = "JSON search"
                    else:
                        results, stage = smart_filter_results(
                            results,
                            user_query,
                            fuzzy_threshold=fuzzy_threshold,
                        )
                        transport = "Static JSON feed"

                # --------------------------------------------
                # 4) RSS / Atom
                # --------------------------------------------
                else:
                    results = parse_rss(
                        source,
                        user_query,
                        r.content,
                    )

                    if is_static_source(source):
                        results, stage = smart_filter_results(
                            results,
                            user_query,
                            fuzzy_threshold=fuzzy_threshold,
                        )
                        transport = "Static feed • local Smart Search"
                    else:
                        results = rank_provider_results(
                            results,
                            user_query
                        )
                        stage = "Provider results"
                        transport = "RSS/Atom search"

        usable = sum(
            1 for item in results
            if item.get("link_usable")
        )

        return (
            results,
            f"{transport} • {stage} • "
            f"{len(results)} result(s) • "
            f"{usable} usable link(s)",
        )

    except Exception as exc:
        raise RuntimeError(
            friendly_source_error(exc)
        ) from exc


class SearchWorker(QThread):
    finished_search = Signal(list, dict)
    failed = Signal(str)

    def __init__(self, sources, query, match_mode="Smart", fuzzy_threshold=70):
        super().__init__()
        self.sources = sources
        self.query = query
        self.match_mode = match_mode
        self.fuzzy_threshold = fuzzy_threshold

    def run(self):
        all_results = []
        statuses = {}

        try:
            max_workers = min(8, max(1, len(self.sources)))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(
                        fetch_source,
                        source,
                        self.query,
                        15,
                        self.match_mode,
                        self.fuzzy_threshold,
                        self.query
                    ): source
                    for source in self.sources
                }

                for future in as_completed(futures):
                    source = futures[future]
                    name = source.get("name", "Source")

                    try:
                        results, status = future.result()
                        all_results.extend(results)
                        statuses[name] = ("OK", status)
                    except Exception as exc:
                        statuses[name] = ("ERROR", str(exc))

            self.finished_search.emit(all_results, statuses)
        except Exception as exc:
            self.failed.emit(str(exc))


class TestSourceWorker(QThread):
    finished_test = Signal(bool, str, list)

    def __init__(self, source, query="test"):
        super().__init__()
        self.source = source
        self.query = query

    def run(self):
        try:
            results, status = fetch_source(self.source, self.query, timeout=12, match_mode="Smart", fuzzy_threshold=70, local_query=self.query)
            self.finished_test.emit(True, status, results[:20])
        except Exception as exc:
            self.finished_test.emit(False, friendly_source_error(exc), [])



class DetectSiteWorker(QThread):
    finished_detect = Signal(bool, str, list, str)

    def __init__(self, website_url):
        super().__init__()
        self.website_url = website_url

    def run(self):
        try:
            page_title, final_url, candidates = detect_site_sources(
                self.website_url,
                timeout=15
            )
            self.finished_detect.emit(True, page_title, candidates, final_url)
        except Exception as exc:
            self.finished_detect.emit(False, str(exc), [], self.website_url)


class SiteDetectionDialog(QDialog):
    def __init__(self, parent, page_title, final_url, candidates):
        super().__init__(parent)
        self.setWindowTitle("Detected Site Interfaces")
        self.resize(980, 520)
        self.candidates = candidates
        self.selected_source = None

        layout = QVBoxLayout(self)

        info = QLabel(
            f"<b>{html.escape(page_title)}</b><br>"
            f"{html.escape(final_url)}<br><br>"
            "Choose the interface you want the app to use. "
            "Full-site search methods are listed before static feeds."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Status", "Method", "Type", "Mode", "Description", "URL"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.Stretch
        )
        self.table.setRowCount(len(candidates))

        for row, source in enumerate(candidates):
            values = [
                "Rejected" if source.get("_rejected") else "Ready",
                source.get("_detected_by", ""),
                source.get("type", ""),
                source.get("search_mode", ""),
                source.get("_description", ""),
                source.get("url", ""),
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))

        if candidates:
            first_ready = next(
                (
                    i for i, candidate in enumerate(candidates)
                    if not candidate.get("_rejected")
                ),
                0
            )
            self.table.selectRow(first_ready)

        layout.addWidget(self.table, 1)

        note = QLabel(
            "Ready entries stay on the site's current redirected domain. "
            "Rejected entries point to a different unrelated domain and are "
            "shown only so stale/external metadata is visible. "
            "OpenSearch/Search Form entries search the site; Static Feed only "
            "contains current feed entries."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox()
        use_btn = buttons.addButton("Use Selected", QDialogButtonBox.AcceptRole)
        cancel_btn = buttons.addButton(QDialogButtonBox.Cancel)
        use_btn.clicked.connect(self.use_selected)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def use_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "Detect Site", "Select an interface first.")
            return

        idx = rows[0].row()
        if not (0 <= idx < len(self.candidates)):
            return

        source = deep_copy(self.candidates[idx])

        if source.get("_rejected"):
            QMessageBox.warning(
                self,
                "Rejected Search Target",
                "This auto-detected interface points to a different unrelated "
                "domain than the site's final redirected address.\n\n"
                "It may be stale or external metadata, so the app will not "
                "save it automatically."
            )
            return

        for key in (
            "_detected_by",
            "_description",
            "_rejected",
            "_cross_site",
            "_final_host",
            "_target_host",
        ):
            source.pop(key, None)

        self.selected_source = source
        self.accept()

    def result_source(self):
        return deep_copy(self.selected_source) if self.selected_source else None


class SourceEditorDialog(QDialog):
    def __init__(self, parent=None, source=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Source" if source else "Add Source")
        self.resize(760, 860)
        self.source = deep_copy(source or {})

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name = QLineEdit(self.source.get("name", ""))
        self.type = QComboBox()
        self.type.addItems(["RSS / Atom", "JSON API", "HTML Search"])
        self.type.setCurrentText(self.source.get("type", "RSS / Atom"))

        self.search_mode = QComboBox()
        self.search_mode.addItems(["Auto", "Static Feed", "Search Endpoint"])
        self.search_mode.setCurrentText(self.source.get("search_mode", "Auto"))

        self.url = QLineEdit(self.source.get("url", ""))
        self.url.setPlaceholderText("https://example.com/search?q={query}")

        self.query_param = QLineEdit(self.source.get("query_param", ""))
        self.query_param.setPlaceholderText("Optional, e.g. q")

        self.dynamic_feed_url = QLineEdit(
            self.source.get("dynamic_feed_url", "")
        )
        self.dynamic_feed_url.setPlaceholderText(
            "Optional query-aware RSS/Atom template using {query}"
        )

        self.dynamic_feed_query_param = QLineEdit(
            self.source.get("dynamic_feed_query_param", "")
        )
        self.dynamic_feed_query_param.setPlaceholderText(
            "Optional if dynamic feed uses a separate query parameter"
        )

        self.results_path = QLineEdit(self.source.get("results_path", ""))
        self.results_path.setPlaceholderText("JSON only, e.g. data.results")

        form.addRow("Name", self.name)
        form.addRow("Type", self.type)
        form.addRow("Search Mode", self.search_mode)
        form.addRow("Search URL / Feed", self.url)
        form.addRow("Query Parameter", self.query_param)
        form.addRow("Dynamic RSS / Atom URL", self.dynamic_feed_url)
        form.addRow("Dynamic Feed Query Param", self.dynamic_feed_query_param)
        form.addRow("JSON Results Path", self.results_path)
        layout.addLayout(form)

        mapping_box = QGroupBox("JSON Field Mapping (optional)")
        mapping_form = QFormLayout(mapping_box)
        mappings = self.source.get("mappings") or {}

        self.map_title = QLineEdit(mappings.get("title", ""))
        self.map_link = QLineEdit(mappings.get("link", ""))
        self.map_size = QLineEdit(mappings.get("size", ""))
        self.map_seeders = QLineEdit(mappings.get("seeders", ""))
        self.map_leechers = QLineEdit(mappings.get("leechers", ""))
        self.map_resolution = QLineEdit(mappings.get("resolution", ""))
        self.map_type = QLineEdit(mappings.get("type", ""))
        self.map_downloads = QLineEdit(mappings.get("downloads", ""))
        self.map_date = QLineEdit(mappings.get("date", ""))
        self.map_trusted = QLineEdit(mappings.get("trusted", ""))
        self.map_remake = QLineEdit(mappings.get("remake", ""))
        self.map_info_hash = QLineEdit(mappings.get("info_hash", ""))

        for widget in (
            self.map_title, self.map_link, self.map_size,
            self.map_seeders, self.map_leechers,
            self.map_resolution, self.map_type, self.map_downloads,
            self.map_date, self.map_trusted, self.map_remake, self.map_info_hash
        ):
            widget.setPlaceholderText("e.g. attributes.title")

        mapping_form.addRow("Title", self.map_title)
        mapping_form.addRow("Torrent / Magnet Link", self.map_link)
        mapping_form.addRow("Size", self.map_size)
        mapping_form.addRow("Seeders", self.map_seeders)
        mapping_form.addRow("Leechers / Peers", self.map_leechers)
        mapping_form.addRow("Downloads", self.map_downloads)
        mapping_form.addRow("Resolution", self.map_resolution)
        mapping_form.addRow("Type / Category", self.map_type)
        mapping_form.addRow("Upload Date", self.map_date)
        mapping_form.addRow("Trusted / Verified", self.map_trusted)
        mapping_form.addRow("Remake / Repack", self.map_remake)
        mapping_form.addRow("Info Hash", self.map_info_hash)
        layout.addWidget(mapping_box)

        headers_box = QGroupBox("Custom HTTP Headers (optional JSON)")
        headers_layout = QVBoxLayout(headers_box)
        self.headers = QPlainTextEdit()
        self.headers.setPlaceholderText(
            '{\n  "Authorization": "Bearer ...",\n  "X-API-Key": "..."\n}'
        )
        current_headers = self.source.get("headers") or {}
        if current_headers:
            self.headers.setPlainText(json.dumps(current_headers, indent=2))
        headers_layout.addWidget(self.headers)
        layout.addWidget(headers_box)

        self.enabled = QCheckBox("Enabled")
        self.enabled.setChecked(self.source.get("enabled", True))
        layout.addWidget(self.enabled)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate_and_accept(self):
        name = self.name.text().strip()
        url = self.url.text().strip()
        if not name or not url:
            QMessageBox.warning(self, "Source", "Enter both a name and an address.")
            return

        parsed = urllib.parse.urlsplit(url.replace("{query}", "test"))
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            QMessageBox.warning(self, "Source", "Enter a valid HTTP/HTTPS address.")
            return

        if self.search_mode.currentText() == "Search Endpoint":
            if "{query}" not in url and not self.query_param.text().strip():
                QMessageBox.warning(
                    self, "Source",
                    "Search Endpoint mode needs {query} in the URL or a Query Parameter."
                )
                return

        dynamic_feed_url = self.dynamic_feed_url.text().strip()
        if dynamic_feed_url:
            parsed_feed = urllib.parse.urlsplit(
                dynamic_feed_url.replace("{query}", "test")
            )
            if (
                parsed_feed.scheme not in ("http", "https")
                or not parsed_feed.netloc
            ):
                QMessageBox.warning(
                    self,
                    "Source",
                    "Dynamic RSS / Atom URL must be a valid HTTP/HTTPS address."
                )
                return

            if (
                "{query}" not in dynamic_feed_url
                and not self.dynamic_feed_query_param.text().strip()
            ):
                QMessageBox.warning(
                    self,
                    "Source",
                    "Dynamic feed needs {query} in its URL or "
                    "a Dynamic Feed Query Param."
                )
                return

        raw_headers = self.headers.toPlainText().strip()
        headers = {}
        if raw_headers:
            try:
                headers = json.loads(raw_headers)
                if not isinstance(headers, dict):
                    raise ValueError("Headers JSON must be an object")
            except Exception as exc:
                QMessageBox.warning(self, "Headers", f"Invalid headers JSON:\n{exc}")
                return

        self.source = {
            "name": name,
            "type": self.type.currentText(),
            "search_mode": self.search_mode.currentText(),
            "url": url,
            "query_param": self.query_param.text().strip(),
            "dynamic_feed_url": self.dynamic_feed_url.text().strip(),
            "dynamic_feed_query_param": self.dynamic_feed_query_param.text().strip(),
            "results_path": self.results_path.text().strip(),
            "mappings": {
                "title": self.map_title.text().strip(),
                "link": self.map_link.text().strip(),
                "size": self.map_size.text().strip(),
                "seeders": self.map_seeders.text().strip(),
                "leechers": self.map_leechers.text().strip(),
                "downloads": self.map_downloads.text().strip(),
                "resolution": self.map_resolution.text().strip(),
                "type": self.map_type.text().strip(),
                "date": self.map_date.text().strip(),
                "trusted": self.map_trusted.text().strip(),
                "remake": self.map_remake.text().strip(),
                "info_hash": self.map_info_hash.text().strip(),
            },
            "headers": headers,
            "enabled": self.enabled.isChecked(),
        }
        self.accept()

    def result_source(self):
        return deep_copy(self.source)


class SortableItem(QTableWidgetItem):
    def __init__(self, text="", sort_value=None):
        super().__init__(str(text))
        self.sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, SortableItem):
            a = self.sort_value
            b = other.sort_value
            if a is None and b is None:
                return super().__lt__(other)
            if a is None:
                return False
            if b is None:
                return True
            try:
                return a < b
            except Exception:
                return str(a) < str(b)
        return super().__lt__(other)


class PreviewDialog(QDialog):
    def __init__(self, parent, source_name, results):
        super().__init__(parent)
        self.setWindowTitle(f"Preview — {source_name}")
        self.resize(1250, 600)
        layout = QVBoxLayout(self)

        total = len(results)
        usable = sum(1 for r in results if r.get("link_usable"))
        with_size = sum(1 for r in results if r.get("size"))
        with_seeds = sum(1 for r in results if r.get("seeders") is not None)
        with_date = sum(1 for r in results if r.get("date"))
        with_trust = sum(1 for r in results if r.get("trusted") is not None)

        label = QLabel(
            f"Previewing {total} parsed result(s) • "
            f"usable links {usable}/{total} • size {with_size}/{total} • "
            f"seeds {with_seeds}/{total} • date {with_date}/{total} • "
            f"trusted {with_trust}/{total}"
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        table = QTableWidget(0, 10)
        table.setHorizontalHeaderLabels([
            "Title", "Kind", "Resolution", "Size", "Seeds", "Peers",
            "Downloads", "Trusted", "Date", "Link"
        ])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setRowCount(total)

        for row, result in enumerate(results):
            values = [
                result.get("title", ""),
                display_unknown(result.get("kind")),
                display_unknown(result.get("resolution")),
                display_unknown(result.get("size")),
                display_unknown(result.get("seeders")),
                display_unknown(result.get("leechers")),
                display_unknown(result.get("downloads")),
                display_unknown(result.get("trusted")),
                display_unknown(result.get("date")),
                display_unknown(result.get("link_kind")),
            ]
            for col, val in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(str(val)))

        layout.addWidget(table)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)


class Toast(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setWindowFlags(Qt.ToolTip)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)

        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(460)
        layout.addWidget(self.label)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

        self.hide()

    def show_message(self, text, duration_ms=5000):
        self.label.setText(text)
        self.adjustSize()

        parent = self.parentWidget()
        if parent:
            margin = 20
            x = parent.x() + parent.width() - self.width() - margin
            y = parent.y() + parent.height() - self.height() - margin - 35
            self.move(x, y)

        self.show()
        self.raise_()
        self.timer.start(duration_ms)


class AnimeDownloader(QMainWindow):
    def __init__(self):
        super().__init__()

        # Gives the installer an exact way to close the currently-running AMF
        # process before replacing files during an in-place update.
        try:
            PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass
        migrate_previous_state()
        from reliability import hydrate_config
        self.credential_warnings = []
        self.config = hydrate_config(load_json(CONFIG_FILE, DEFAULT_CONFIG), warnings=self.credential_warnings)
        if self.config.get('torrent_client') not in ('qBittorrent','Deluge','Transmission','uTorrent','Other desktop client'):
            self.config['torrent_client'] = 'qBittorrent'
        # Re-save immediately through credential protection to migrate old plaintext.
        save_json(CONFIG_FILE, self.config)
        from cart_sender import replay_receipts
        self.cart = replay_receipts(load_json(CART_FILE, []), APP_DIR / 'sent-receipts.jsonl')
        self.search_results = []
        self.selected_result_keys = set()
        self.source_status = {}
        self.search_worker = None
        self.test_worker = None
        self.toast = Toast(self)

        # Ensure new config keys exist.
        for key, value in DEFAULT_CONFIG.items():
            self.config.setdefault(key, deep_copy(value))

        # Permanent baseline providers. Existing versions/configuration of
        # these providers are preserved; only missing providers are restored.
        if ensure_builtin_default_sources(self.config):
            save_json(CONFIG_FILE, self.config)

        self.setWindowTitle(APP_NAME)
        self.resize(1380, 860)
        self.setMinimumSize(560, 400)

        icon_path = RESOURCE_DIR / "AMF.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # Give Windows a stable app identity so taskbar/search grouping uses AMF.
        if sys.platform == "win32":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    APP_USER_MODEL_ID
                )
            except Exception:
                pass

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        brand_bar = QFrame()
        brand_bar.setObjectName("brandBar")
        brand_layout = QHBoxLayout(brand_bar)
        brand_layout.setContentsMargins(18, 12, 18, 12)
        brand_layout.setSpacing(12)

        brand_icon = QLabel()
        brand_icon.setObjectName("brandIcon")
        if not self.windowIcon().isNull():
            brand_icon.setPixmap(self.windowIcon().pixmap(42, 42))
        brand_icon.setFixedSize(46, 46)
        brand_icon.setAlignment(Qt.AlignCenter)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)

        brand_title = QLabel("AMF")
        brand_title.setObjectName("brandTitle")
        brand_subtitle = QLabel("Search, queue, and route downloads")
        brand_subtitle.setObjectName("brandSubtitle")

        brand_text.addWidget(brand_title)
        brand_text.addWidget(brand_subtitle)

        version_badge = QLabel(APP_VERSION)
        version_badge.setObjectName("versionBadge")
        version_badge.setAlignment(Qt.AlignCenter)

        brand_layout.addWidget(brand_icon)
        brand_layout.addLayout(brand_text)
        brand_layout.addStretch()
        brand_layout.addWidget(version_badge)

        root_layout.addWidget(brand_bar)

        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs, 1)

        self.anime_tab = QWidget()
        self.cart_tab = QWidget()
        self.sources_tab = QWidget()
        self.settings_tab = QWidget()

        self.tabs.addTab(self.anime_tab, "Search")
        self.tabs.addTab(self.cart_tab, "Cart")
        self.tabs.addTab(self.sources_tab, "Sources")
        self.tabs.addTab(self.settings_tab, "Settings")

        self.build_anime_tab()
        self.build_cart_tab()
        self.build_sources_tab()
        self.build_settings_tab()

        self.apply_dark_style()
        self.refresh_sources()
        self.refresh_paths()
        self.refresh_cart()
        self._responsive_timer = QTimer(self)
        self._responsive_timer.setSingleShot(True)
        self._responsive_timer.timeout.connect(self.adapt_layout)
        for index, page in enumerate([self.anime_tab, self.cart_tab, self.sources_tab, self.settings_tab]):
            title = self.tabs.tabText(index)
            self.tabs.removeTab(index)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            page.layout().setSizeConstraint(QLayout.SetMinAndMaxSize)
            scroll.setWidget(page)
            self.tabs.insertTab(index, scroll, title)
        self.tabs.setCurrentIndex(0)
        area = self.screen().availableGeometry()
        self.resize(min(1380, int(area.width() * .94)), min(860, int(area.height() * .90)))
        self.adapt_layout()
        from productivity_ui import install_productivity
        install_productivity(self, sys.modules[__name__])
        if self.credential_warnings:
            self.toast.show_message(self.credential_warnings[0], 12000)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_responsive_timer'):
            self._responsive_timer.start(80)

    def adapt_layout(self):
        scale = max(.80, min(1.0, self.width() / 1380, self.height() / 860))
        if getattr(self, '_ui_scale', None) == round(scale, 2):
            return
        self._ui_scale = round(scale, 2)
        self.apply_theme()
        for table in self.findChildren(QTableView):
            table.verticalHeader().setDefaultSectionSize(max(24, round(34 * scale)))

    # ---------------- ANIME ----------------

    def build_anime_tab(self):
        layout = QVBoxLayout(self.anime_tab)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("Search")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search titles across all enabled sources...")
        self.search_input.returnPressed.connect(self.search_sources)

        self.search_btn = QPushButton("Search")
        self.search_btn.setObjectName("primaryButton")
        self.search_btn.setToolTip("Search all enabled sources")
        self.search_btn.clicked.connect(self.search_sources)

        row.addWidget(self.search_input, 1)
        row.addWidget(self.search_btn)
        layout.addLayout(row)

        filters = FlowLayout()

        self.scope_filter = QComboBox()
        self.scope_filter.addItems([
            "All Releases",
            "Single Episode",
            "Multi-Episode Pack",
            "Season Pack",
            "Complete Series",
            "Movie",
            "OVA / Special",
            "Unknown"
        ])
        self.scope_filter.currentTextChanged.connect(self.apply_result_filters)

        self.source_filter = QComboBox()
        self.source_filter.addItem("All Sources", "")
        self.source_filter.setMinimumWidth(240)
        self.total_results_label = QLabel("0 total results")
        self.total_results_label.setMinimumWidth(150)
        self.source_filter.setToolTip(
            "Post-search filter. Search asks every enabled provider "
            "for its own search results. Changing this dropdown only filters "
            "the merged cached rows locally and never performs another request."
        )
        self.source_filter.currentIndexChanged.connect(self.apply_result_filters)

        self.resolution_filter = QComboBox()
        self.resolution_filter.addItems(["Any", "480p", "720p", "1080p", "2160p"])
        self.resolution_filter.currentTextChanged.connect(self.apply_result_filters)

        from provider_pages import NumberField
        self.min_seeders = NumberField()
        self.min_seeders.setRange(0, 999999)
        self.min_seeders.valueChanged.connect(self.apply_result_filters)

        self.max_size_gb = NumberField(decimal=True)
        self.max_size_gb.setRange(0, 100000)
        self.max_size_gb.setValue(0)
        self.max_size_gb.setSpecialValueText("Any")
        self.max_size_gb.valueChanged.connect(self.apply_result_filters)

        filters.addWidget(QLabel("Release"))
        filters.addWidget(self.scope_filter)
        filters.addSpacing(8)
        filters.addWidget(QLabel("Filter source"))
        filters.addWidget(self.source_filter)
        filters.addWidget(self.total_results_label)
        filters.addStretch()
        layout.addLayout(filters)
        filters = FlowLayout()
        filters.addWidget(QLabel("Resolution"))
        filters.addWidget(self.resolution_filter)
        filters.addSpacing(8)
        filters.addWidget(QLabel("Min seeds"))
        filters.addWidget(self.min_seeders)
        filters.addSpacing(8)
        filters.addWidget(QLabel("Max GB"))
        filters.addWidget(self.max_size_gb)
        filters.addStretch()

        layout.addLayout(filters)

        self.search_status = QLabel("Ready.")
        self.search_status.setObjectName("mutedText")
        layout.addWidget(self.search_status)

        self.results_table = QTableWidget(0, 15)
        self.results_table.setHorizontalHeaderLabels([
            "Select", "Title", "Source", "Release Scope", "Resolution / Format", "Language",
            "Size", "Seeds", "Peers", "Downloads", "Trusted", "Remake", "Date",
            "Category", "Link"
        ])
        result_header = self.results_table.horizontalHeader()
        for section in range(self.results_table.columnCount()):
            result_header.setSectionResizeMode(section, QHeaderView.Interactive)
        result_header.setSectionsMovable(True)
        result_header.setStretchLastSection(False)

        # Sensible starting widths; every column can be dragged afterwards.
        default_widths = {
            0: 55,   1: 520,  2: 130,  3: 155,  4: 95,
            5: 120,  6: 100,  7: 75,   8: 75,   9: 100,
            10: 85, 11: 85,  12: 145, 13: 190, 14: 110,
        }
        for section, width in default_widths.items():
            self.results_table.setColumnWidth(section, width)

        row_header = self.results_table.verticalHeader()
        row_header.setSectionResizeMode(QHeaderView.Interactive)
        row_header.setDefaultSectionSize(30)

        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setShowGrid(False)
        self.results_table.setSortingEnabled(True)
        layout.addWidget(self.results_table, 1)
        provider_row = QHBoxLayout()
        for identity, label in [("eztv", "Read EZTV Page"), ("annas_archive", "Read Anna’s Archive Page")]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, i=identity: self.read_provider_page(i))
            provider_row.addWidget(button)
        provider_row.addStretch()
        layout.addLayout(provider_row)

        action_row = QHBoxLayout()
        self.select_all_btn = QPushButton("Select Visible")
        self.select_all_btn.clicked.connect(self.select_visible_results)

        self.add_cart_btn = QPushButton("Add Selected to Cart")
        self.add_cart_btn.setObjectName("primaryButton")
        self.add_cart_btn.clicked.connect(self.add_selected_to_cart)

        self.advanced_columns_toggle = QCheckBox("Advanced columns")
        self.advanced_columns_toggle.setToolTip(
            "Show Downloads, Trusted, Remake, Category and Link columns."
        )
        self.advanced_columns_toggle.toggled.connect(
            self.set_advanced_columns_visible
        )

        action_row.addWidget(self.select_all_btn)
        for label, mode in [("Unselect Visible", "none"), ("Invert Visible", "invert"), ("Clear All Selections", "clear")]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, m=mode: self.change_result_selection(m))
            action_row.addWidget(button)
        action_row.addWidget(self.add_cart_btn)
        action_row.addStretch()
        action_row.addWidget(self.advanced_columns_toggle)
        layout.addLayout(action_row)

        self.set_advanced_columns_visible(False)

        location_box = QGroupBox("Routing")
        loc_layout = QVBoxLayout(location_box)

        location_header = QHBoxLayout()
        location_note = QLabel(
            "Movies and series are routed automatically. Double-click Save Location "
            "in Cart to override a single item."
        )
        location_note.setObjectName("mutedText")
        location_note.setWordWrap(True)

        edit_locations = QPushButton("Edit Locations")
        edit_locations.clicked.connect(
            lambda: self.tabs.setCurrentIndex(self.tabs.count() - 1)
        )

        location_header.addWidget(location_note, 1)
        location_header.addWidget(edit_locations)
        loc_layout.addLayout(location_header)

        self.movies_path_label = QLabel()
        self.series_path_label = QLabel()
        self.movies_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.series_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        loc_layout.addWidget(self.movies_path_label)
        loc_layout.addWidget(self.series_path_label)

        layout.addWidget(location_box)
        self.refresh_source_filter_options()




    def set_advanced_columns_visible(self, visible):
        if not hasattr(self, "results_table"):
            return

        for column in (9, 10, 11, 13, 14):
            self.results_table.setColumnHidden(column, not bool(visible))


    def refresh_source_filter_options(self):
        if not hasattr(self, "source_filter"):
            return

        # Keep the raw source name in userData. The visible text can therefore
        # include a result count without breaking filtering.
        current_raw = self.source_filter.currentData()
        if current_raw is None:
            current_raw = ""

        counts = {}
        for result in self.search_results:
            for name in result.get('available_sources', [result.get('source','')]):
                if name: counts[name] = counts.get(name,0)+1

        # Test statuses may outlive a source being disabled or removed.
        # Only the current configuration determines filter membership.
        status_names = sorted(
            name for name in getattr(self, "source_status", {}).keys()
            if name
        )

        names = sorted({s['name'] for s in self.config.get('sources', [])
                        if s.get('name') and s.get('enabled')})

        total = sum(bool(set(result.get('available_sources', [result.get('source', '')])) & set(names))
                    for result in self.search_results)
        self.total_results_label.setText(f"{total:,} total results")

        self.source_filter.blockSignals(True)
        self.source_filter.clear()
        self.source_filter.addItem(
            f"All Sources ({total})" if self.search_results or status_names
            else "All Sources",
            ""
        )

        for name in names:
            if self.search_results or status_names:
                label = f"{name} ({counts.get(name, 0)})"
            else:
                label = name
            self.source_filter.addItem(label, name)

        # Restore by raw source name rather than display label.
        selected = 0
        for i in range(self.source_filter.count()):
            if self.source_filter.itemData(i) == current_raw:
                selected = i
                break

        self.source_filter.setCurrentIndex(selected)
        self.source_filter.blockSignals(False)

    def read_provider_page(self, identity):
        query = self.search_input.text().strip()
        if not query:
            self.toast.show_message("Enter a search term first", 3500)
            return
        if self.search_worker and self.search_worker.isRunning():
            self.toast.show_message("Wait for the current search to finish", 3500)
            return
        source = next((x for x in self.config.get("sources", []) if source_provider_identity(x) == identity), None)
        if source is None:
            return
        try:
            from provider_pages import ProviderPageDialog
            dialog = ProviderPageDialog(self, source, query)
            if dialog.exec() != QDialog.Accepted:
                return
            name = source.get("name", "")
            remaining = [r for r in self.search_results if r.get("source") != name]
            statuses = dict(self.source_status)
            statuses[name] = ("OK", dialog.summary)
            self.results_table.setSortingEnabled(False)
            self.scope_filter.setCurrentIndex(0)
            self.resolution_filter.setCurrentIndex(0)
            self.min_seeders.setValue(0)
            self.max_size_gb.setValue(0)
            self.search_finished(remaining + dialog.rows, statuses)
            self.source_filter.setCurrentIndex(self.source_filter.findData(name))
            self.search_status.setText(dialog.summary)
        except Exception as exc:
            QMessageBox.warning(self, "Provider page", str(exc))

    def search_sources(self):
        query = self.search_input.text().strip()
        if not query:
            QMessageBox.information(self, "Search", "Enter a title first.")
            return

        match_mode = "Smart"
        fuzzy_threshold = 70

        enabled = [
            s for s in self.config.get("sources", [])
            if s.get("enabled")
        ]

        if not enabled:
            QMessageBox.information(
                self,
                "No Sources",
                "No sources are enabled.\n\n"
                "Open Sources and add/enable an RSS or API source."
            )
            return

        self.search_btn.setEnabled(False)
        self.search_status.setText(
            f"Searching {len(enabled)} source(s) for “{query}” • Smart Search…"
        )
        self.search_results = []
        self.selected_result_keys = set()
        self.results_table.setRowCount(0)

        self.search_worker = SearchWorker(
            enabled,
            query,
            match_mode=match_mode,
            fuzzy_threshold=fuzzy_threshold
        )
        self.search_worker.finished_search.connect(self.search_finished)
        self.search_worker.failed.connect(self.search_failed)
        self.search_worker.start()

    def search_finished(self, results, statuses):
        if any(r.get("provider_page") for r in results):
            self.results_table.setSortingEnabled(False)
        self.search_btn.setEnabled(True)
        self.source_status = statuses

        # Dedupe conservatively: same link, or same normalized title+size.
        deduped = []
        seen = set()

        for result in results:
            key_link = (result.get("link") or "").strip().lower()
            normalized_title = re.sub(
                r"\s+", " ", (result.get("title") or "").lower()
            ).strip()
            key = (
                "link", key_link
            ) if key_link else (
                "title", normalized_title, result.get("size_bytes", 0)
            )

            key = (result.get("source", ""), key)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(result)

        for result in deduped:
            if not result.get("scope"):
                result["scope"] = detect_release_scope(
                    result.get("title", ""),
                    result.get("category", "")
                )

            if not result.get("language"):
                result["language"] = detect_language(
                    " ".join([
                        str(result.get("title") or ""),
                        str(result.get("category") or "")
                    ])
                )

        from reliability import merge_duplicates
        deduped = merge_duplicates(deduped)
        self.search_results = deduped
        self.refresh_source_filter_options()
        self.apply_result_filters()

        ok = sum(1 for status, _ in statuses.values() if status == "OK")
        bad = len(statuses) - ok
        usable = sum(1 for r in deduped if r.get("link_usable"))
        self.search_status.setText(
            f"{len(deduped)} provider result(s) merged & cached • "
            f"{usable} usable torrent link(s) • "
            f"{ok} source(s) OK, {bad} failed. "
            f"Filters below are local only."
        )
        self.refresh_sources()

    def search_failed(self, message):
        self.search_btn.setEnabled(True)
        self.search_status.setText("Search failed.")
        QMessageBox.critical(self, "Search Error", message)

    def apply_result_filters(self):
        if not hasattr(self, "results_table"):
            return

        scope = self.scope_filter.currentText()
        source_name = self.source_filter.currentData() or ""
        res = self.resolution_filter.currentText()
        min_seeds = self.min_seeders.value()
        max_gb = self.max_size_gb.value()
        max_bytes = max_gb * 1024**3 if max_gb else 0

        visible = []
        enabled_names = {s.get('name') for s in self.config.get('sources', []) if s.get('enabled')}

        for idx, result in enumerate(self.search_results):
            if not enabled_names.intersection(result.get('available_sources', [result.get('source')])):
                continue
            if scope != "All Releases" and result.get("scope", "Unknown") != scope:
                continue

            if source_name and source_name not in result.get("available_sources", [result.get("source")]):
                continue

            rres = result.get("resolution") or ""
            if res != "Any" and rres != res:
                continue

            seeders = result.get("seeders")
            if min_seeds > 0:
                if seeders is None or int(seeders) < min_seeds:
                    continue

            size_bytes = int(result.get("size_bytes", 0) or 0)
            if max_bytes and size_bytes and size_bytes > max_bytes:
                continue

            visible.append((idx, result))

        sorting = self.results_table.isSortingEnabled()
        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(len(visible))

        for row, (result_index, result) in enumerate(visible):
            check = QCheckBox()
            check.setProperty("result_index", result_index)
            key = self.result_selection_key(result)
            check.setChecked(key in self.selected_result_keys)
            check.toggled.connect(lambda checked, k=key: self.remember_selection(k, checked))
            check.setToolTip(
                "Usable torrent link" if result.get("link_usable")
                else "This entry does not expose a direct torrent/magnet link"
            )
            self.results_table.setCellWidget(row, 0, check)

            values = [
                (result.get("title", ""), result.get("title", "")),
                (" / ".join(result.get("available_sources", [result.get("source", "")])) or "Unknown", result.get("source") or ""),
                (display_unknown(result.get("scope")), result.get("scope") or ""),
                (display_unknown(result.get("resolution") or result.get("format")), result.get("resolution") or result.get("format") or ""),
                (display_unknown(result.get("language")), result.get("language") or ""),
                (display_unknown(result.get("size")), result.get("size_bytes") or None),
                (display_unknown(result.get("seeders")), result.get("seeders")),
                (display_unknown(result.get("leechers")), result.get("leechers")),
                (display_unknown(result.get("downloads")), result.get("downloads")),
                (display_unknown(result.get("trusted")), result.get("trusted") or ""),
                (display_unknown(result.get("remake")), result.get("remake") or ""),
                (display_unknown(result.get("date")), result.get("date_ts")),
                (display_unknown(result.get("category")), result.get("category") or ""),
                (display_unknown(result.get("link_kind")), 1 if result.get("link_usable") else 0),
            ]

            for col, (text, sort_value) in enumerate(values, start=1):
                item = SortableItem(text, sort_value)
                if col == 1:
                    item.setToolTip(result.get("description") or result.get("title", ""))
                if col == 14 and not result.get("link_usable"):
                    item.setText("Resolve on Add")
                    item.setToolTip(
                        result.get("detail_url")
                        or result.get("link")
                        or "No detail page"
                    )
                self.results_table.setItem(row, col, item)

        self.results_table.setSortingEnabled(sorting)

        if self.search_results:
            usable = sum(1 for _, r in visible if r.get("link_usable"))
            enabled_total = sum(bool(enabled_names.intersection(r.get('available_sources', [r.get('source')])))
                                for r in self.search_results)
            self.search_status.setText(
                f"Showing {len(visible)} of {enabled_total} result(s) • "
                f"{usable} usable torrent link(s)"
            )


    def source_config_for_result(self, result):
        name = str(result.get("source") or "").strip()

        for source in self.config.get("sources", []):
            if str(source.get("name") or "").strip() == name:
                return source

        return {}


    def select_visible_results(self):
        for row in range(self.results_table.rowCount()):
            box = self.results_table.cellWidget(row, 0)
            if box:
                box.setChecked(True)

    def add_selected_to_cart(self):
        selected = []

        # Snapshot selection FIRST. Rebuilding the table later must not change
        # which rows the user originally selected.
        for row in range(self.results_table.rowCount()):
            box = self.results_table.cellWidget(row, 0)

            if not box or not box.isChecked():
                continue

            idx = box.property("result_index")
            if idx is None:
                continue

            idx = int(idx)

            if 0 <= idx < len(self.search_results):
                selected.append(idx)

        if not selected:
            self.toast.show_message(
                "Nothing added — select one or more results first",
                5000
            )
            return

        added = 0
        already_in_cart = 0
        failed_to_resolve = []
        collisions = []
        resolved_any = False

        # Track links resolved during THIS batch. If two different detail pages
        # unexpectedly resolve to the same link, surface it as a resolver
        # collision instead of silently dropping the second title.
        batch_links = {}

        existing_links = {
            canonical_url_key(item.get("link"))
            for item in self.cart
            if item.get("link")
        }

        total = len(selected)

        for position, idx in enumerate(selected, start=1):
            result = deep_copy(self.search_results[idx])

            self.search_status.setText(
                f"Preparing {position}/{total}: "
                f"{result.get('title', 'selected result')}…"
            )
            QApplication.processEvents()

            if not result.get("link_usable"):
                source = self.source_config_for_result(result)

                resolved, error = resolve_result_download_link(
                    source,
                    result,
                    timeout=15,
                )

                if error or not resolved.get("link_usable"):
                    failed_to_resolve.append(
                        result.get("title", "Unknown")
                    )
                    continue

                result = resolved
                self.search_results[idx].update(resolved)
                resolved_any = True

            link = str(result.get("link") or "").strip()
            link_key = canonical_url_key(link)

            if not link_key:
                failed_to_resolve.append(
                    result.get("title", "Unknown")
                )
                continue

            detail_key = canonical_url_key(
                result.get("detail_url")
                or result.get("guid")
                or ""
            )

            previous = batch_links.get(link_key)

            if previous:
                # Same final link but different search/detail result: this is
                # suspicious resolver behavior, not a normal duplicate.
                if (
                    previous.get("title") != result.get("title")
                    or previous.get("detail_key") != detail_key
                ):
                    collisions.append(
                        result.get("title", "Unknown")
                    )
                    continue

            batch_links[link_key] = {
                "title": result.get("title", ""),
                "detail_key": detail_key,
            }

            if link_key in existing_links:
                already_in_cart += 1
                continue

            result.setdefault("save_path_custom", False)
            result.setdefault("cart_status", "Ready")
            result.setdefault("last_error", "")
            self.apply_default_save_path(result)

            self.cart.append(result)
            self.selected_result_keys.discard(self.result_selection_key(self.search_results[idx]))
            existing_links.add(link_key)
            added += 1

        if resolved_any or added:
            self.apply_result_filters()

        if added:
            self.save_cart()
            self.refresh_cart()

        # Never hide partial failures again.
        parts = []

        if added:
            parts.append(f"{added} added")

        if already_in_cart:
            parts.append(f"{already_in_cart} already in cart")

        if failed_to_resolve:
            parts.append(
                f"{len(failed_to_resolve)} couldn't resolve"
            )

        if collisions:
            parts.append(
                f"{len(collisions)} resolver collision(s)"
            )

        summary = " • ".join(parts) if parts else "Nothing added"

        self.toast.show_message(summary, 6500)

        # If something suspicious happened, also show a useful diagnostic.
        if collisions:
            QMessageBox.warning(
                self,
                "Link Resolver Collision",
                "Different selected results resolved to the same download "
                "link, so they were NOT silently discarded.\n\n"
                "This usually means the page parser found a shared/global "
                "download link instead of the item's actual torrent/magnet.\n\n"
                f"Collisions: {len(collisions)}"
            )

        visible = self.results_table.rowCount()
        usable = sum(
            1 for item in self.search_results
            if item.get("link_usable")
        )

        self.search_status.setText(
            f"Showing {visible} result(s) • "
            f"{usable} resolved usable torrent link(s)"
        )


    # ---------------- CART ----------------

    def build_cart_tab(self):
        layout = QVBoxLayout(self.cart_tab)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("Cart")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.cart_summary = QLabel("0 items")
        self.cart_summary.setObjectName("mutedText")
        layout.addWidget(self.cart_summary)

        cart_hint = QLabel(
            "Destination is detected automatically. Double-click Save Location "
            "to choose a different folder for an individual item."
        )
        cart_hint.setWordWrap(True)
        cart_hint.setObjectName("mutedText")
        layout.addWidget(cart_hint)

        self.cart_table = QTableView()
        self.cart_model = CartModel(self)
        self.cart_table.setModel(self.cart_model)
        self.cart_table.setItemDelegateForColumn(3, DestinationDelegate(self.cart_table))

        cart_header = self.cart_table.horizontalHeader()
        for section in range(self.cart_model.columnCount()):
            cart_header.setSectionResizeMode(section, QHeaderView.Interactive)

        cart_header.setSectionsMovable(True)
        self.cart_table.setColumnWidth(0, 360)
        self.cart_table.setColumnWidth(1, 140)
        self.cart_table.setColumnWidth(2, 130)
        self.cart_table.setColumnWidth(3, 110)
        self.cart_table.setColumnWidth(4, 90)
        self.cart_table.setColumnWidth(5, 105)
        self.cart_table.setColumnWidth(6, 90)
        self.cart_table.setColumnWidth(7, 70)
        self.cart_table.setColumnWidth(8, 105)
        self.cart_table.setColumnWidth(9, 290)
        self.cart_table.setColumnWidth(10, 250)

        self.cart_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cart_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.cart_table.setAlternatingRowColors(True)
        self.cart_table.setShowGrid(False)
        self.cart_table.doubleClicked.connect(lambda index: self.cart_cell_double_clicked(index.row(), index.column()))
        layout.addWidget(self.cart_table, 1)

        manual_box = QGroupBox("Add / Import Torrents")
        manual_layout = QHBoxLayout(manual_box)

        self.manual_magnet = QLineEdit()
        self.manual_magnet.setPlaceholderText(
            "Paste one magnet link or torrent URL..."
        )

        self.manual_type = QComboBox()
        self.manual_type.addItems(["Auto", "Games", "Movie", "Series", "Anime Movie", "Anime Series", "Music", "Books"])
        self.manual_type.setToolTip(
            "Destination used for manually added and imported items."
        )

        add_manual = QPushButton("Add")
        add_manual.clicked.connect(self.add_manual_link)

        paste_list = QPushButton("Paste List")
        paste_list.clicked.connect(self.paste_cart_list)

        import_files = QPushButton("Import Files")
        import_files.clicked.connect(self.import_cart_files)

        manual_layout.addWidget(self.manual_magnet, 1)
        manual_layout.addWidget(self.manual_type)
        manual_layout.addWidget(add_manual)
        manual_layout.addWidget(paste_list)
        manual_layout.addWidget(import_files)

        layout.addWidget(manual_box)

        row = FlowLayout()
        remove = QPushButton("Remove Selected")
        remove.clicked.connect(self.remove_selected_cart)

        clear = QPushButton("Clear Cart")
        clear.clicked.connect(self.clear_cart)

        reset_location = QPushButton("Reset Selected Location")
        reset_location.setToolTip(
            "Return selected items to the automatic Movies/Series folder."
        )
        reset_location.clicked.connect(
            self.reset_selected_cart_locations
        )

        resolve_titles = QPushButton("Resolve Titles")
        resolve_titles.setToolTip(
            "Read torrent metadata/provider pages and replace numeric or "
            "placeholder imported titles with the real torrent names."
        )
        resolve_titles.clicked.connect(
            self.resolve_cart_titles
        )

        send = QPushButton("Send Cart to Client")
        self.send_cart_button = send
        cancel_send = QPushButton('Cancel Sending')
        self.cancel_send_button = cancel_send
        cancel_send.setEnabled(False)
        cancel_send.clicked.connect(lambda: self.cart_sender.requestInterruption() if getattr(self, 'cart_sender', None) else None)
        row.addWidget(cancel_send)
        send.setObjectName("primaryButton")
        send.clicked.connect(self.send_cart_to_qbittorrent)

        selection_row = FlowLayout()
        layout.addLayout(selection_row)
        for label, action in [("Select All", self.cart_table.selectAll), ("Unselect All", self.cart_table.clearSelection)]:
            button = QPushButton(label)
            button.clicked.connect(action)
            row.addWidget(button)
        row.addWidget(remove)
        row.addWidget(clear)
        row.addWidget(reset_location)
        row.addWidget(resolve_titles)
        row.addStretch()
        row.addWidget(send)
        layout.addLayout(row)

    def add_manual_link(self):
        link = self.manual_magnet.text().strip()

        if not (
            link.startswith("magnet:")
            or link.startswith("http://")
            or link.startswith("https://")
        ):
            QMessageBox.warning(
                self,
                "Invalid Link",
                "Paste a magnet link or HTTP/HTTPS torrent URL."
            )
            return

        resolved_title = resolve_imported_torrent_title(
            link=link,
            timeout=9,
        )

        item = {
            "title": resolved_title or "Manual item",
            "source": "Manual",
            "kind": "Movie" if self.manual_type.currentText() == "Movie" else "Unknown",
            "scope": "Movie" if self.manual_type.currentText() == "Movie" else "Unknown",
            "type": self.manual_type.currentText(),
            "destination_custom": self.manual_type.currentText() != "Auto",
            "resolution": "",
            "language": "",
            "size_bytes": 0,
            "size": None,
            "seeders": None,
            "leechers": None,
            "downloads": None,
            "trusted": None,
            "remake": None,
            "date": None,
            "link": link,
            "link_kind": classify_link(link, explicit_download=True)[0],
            "link_usable": True,
            "save_path": "",
            "save_path_custom": False,
            "cart_status": "Ready",
            "last_error": "",
        }

        self.apply_default_save_path(item)

        if not any(canonical_url_key(x.get("link")) == canonical_url_key(link) for x in self.cart):
            self.cart.append(item)

        self.manual_magnet.clear()
        self.save_cart()
        self.refresh_cart()

    def make_import_cart_item(
        self,
        link="",
        local_torrent_path="",
        title="",
        destination=None,
    ):
        destination = (
            destination
            or self.manual_type.currentText()
            or "Series"
        )

        link = str(link or "").strip()
        local_torrent_path = str(
            local_torrent_path or ""
        ).strip()

        if not title:
            title = (
                Path(local_torrent_path).stem
                if local_torrent_path
                else imported_link_title(link)
            )

        item = {
            "title": title or "Imported torrent",
            "source": "Imported",
            "kind": "Movie" if destination == "Movie" else "Unknown",
            "scope": "Movie" if destination == "Movie" else "Unknown",
            "type": destination,
            "destination_custom": destination != "Auto",
            "resolution": "",
            "language": "",
            "size_bytes": 0,
            "size": None,
            "seeders": None,
            "leechers": None,
            "downloads": None,
            "trusted": None,
            "remake": None,
            "date": None,
            "category": "",
            "link": link,
            "link_kind": (
                "Torrent File"
                if local_torrent_path
                else classify_link(link, explicit_download=True)[0]
            ),
            "link_usable": bool(link or local_torrent_path),
            "local_torrent_path": local_torrent_path,
            "save_path": "",
            "save_path_custom": False,
            "cart_status": "Ready",
            "last_error": "",
        }

        self.apply_default_save_path(item)
        return item


    def enrich_imported_items(
        self,
        items,
        window_title="Resolving Torrent Titles",
    ):
        """
        Resolve multiple imported titles concurrently so a large pasted list
        does not take one network timeout per item serially.
        """
        candidates = [
            item
            for item in items
            if imported_title_is_placeholder(
                item.get("title")
            )
        ]

        if not candidates:
            return 0, 0

        progress = QProgressDialog(
            "Reading torrent metadata...",
            "Cancel",
            0,
            len(candidates),
            self,
        )
        progress.setWindowTitle(
            window_title
        )
        progress.setWindowModality(
            Qt.WindowModal
        )
        progress.setMinimumDuration(
            0
        )
        progress.setValue(
            0
        )

        resolved = 0
        failed = 0

        max_workers = min(
            8,
            max(
                1,
                len(candidates),
            ),
        )

        def worker(item):
            title = resolve_imported_torrent_title(
                link=item.get("link", ""),
                local_torrent_path=item.get(
                    "local_torrent_path",
                    "",
                ),
                timeout=9,
            )
            return item, title

        pool = ThreadPoolExecutor(max_workers=max_workers)
        try:
            from scalable_ui import bounded_results
            completed = 0
            for future in bounded_results(pool, worker, candidates, progress, max_workers):
                completed += 1

                try:
                    item, title = future.result()
                except Exception:
                    failed += 1
                    progress.setValue(
                        completed
                    )
                    QApplication.processEvents()
                    continue

                title = str(
                    title or ""
                ).strip()

                if (
                    title
                    and not imported_title_is_placeholder(
                        title
                    )
                ):
                    item["title"] = title

                    category = item.get(
                        "category",
                        "",
                    )
                    item["kind"] = detect_kind(
                        title,
                        category,
                    )
                    item["scope"] = detect_release_scope(
                        title,
                        category,
                    )

                    resolution = detect_resolution(
                        title
                    )
                    if resolution:
                        item["resolution"] = resolution

                    language = detect_language(
                        title
                    )
                    if language:
                        item["language"] = language

                    resolved += 1
                else:
                    failed += 1

                progress.setLabelText(
                    f"Resolved {resolved} title(s) • "
                    f"{completed}/{len(candidates)} checked"
                )
                progress.setValue(
                    completed
                )
                QApplication.processEvents()

        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        progress.close()
        return resolved, failed


    def resolve_cart_titles(self):
        """
        Resolve selected imported rows; if nothing is selected, resolve every
        placeholder/numeric imported title in the Cart.
        """
        rows = sorted({
            index.row()
            for index in self.cart_table.selectionModel().selectedRows()
        })

        if rows:
            items = [
                self.cart[row]
                for row in rows
                if 0 <= row < len(self.cart)
            ]
        else:
            items = [
                item
                for item in self.cart
                if imported_title_is_placeholder(
                    item.get("title")
                )
            ]

        if not items:
            QMessageBox.information(
                self,
                "Resolve Titles",
                "There are no numeric/placeholder torrent titles to resolve."
            )
            return

        resolved, failed = self.enrich_imported_items(
            items,
            "Resolve Cart Titles",
        )

        self.save_cart()
        self.refresh_cart()

        if failed:
            QMessageBox.information(
                self,
                "Resolve Titles",
                f"Resolved {resolved} title(s).\\n"
                f"{failed} item(s) could not be resolved and were left "
                "unchanged."
            )
        else:
            self.toast.show_message(
                f"Resolved {resolved} torrent title(s)",
                5000,
            )


    def cart_item_identity(self, item):
        local_path = str(
            item.get("local_torrent_path") or ""
        ).strip()

        if local_path:
            try:
                return "file:" + str(
                    Path(local_path).resolve()
                ).lower()
            except Exception:
                return "file:" + local_path.lower()

        from reliability import torrent_identity
        return torrent_identity(item)


    def add_import_items(self, items):
        existing = {
            self.cart_item_identity(item)
            for item in self.cart
        }

        added = 0
        skipped = 0

        for item in items:
            key = self.cart_item_identity(item)

            if not key or key in existing:
                skipped += 1
                continue

            existing.add(key)
            self.cart.append(item)
            added += 1

        if added:
            self.save_cart()
            self.refresh_cart()

        return added, skipped


    def paste_cart_list(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Paste Torrent List")
        dialog.resize(760, 470)

        layout = QVBoxLayout(dialog)

        hint = QLabel(
            "Paste magnet links or HTTP/HTTPS torrent links. "
            "AMF can extract them from raw TXT/CSV/JSON/Markdown-style text."
        )
        hint.setWordWrap(True)
        hint.setObjectName("mutedText")
        layout.addWidget(hint)

        editor = QPlainTextEdit()
        editor.setPlaceholderText(
            "magnet:?xt=urn:btih:...\\n"
            "https://example.com/download/file.torrent"
        )
        layout.addWidget(editor, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Ok).setText("Import to Cart")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        links = extract_torrent_links_from_text(
            editor.toPlainText()
        )

        if not links:
            QMessageBox.warning(
                self,
                "Import Torrents",
                "No magnet links or torrent URLs were found."
            )
            return

        destination = self.manual_type.currentText()
        items = [
            self.make_import_cart_item(
                link=link,
                destination=destination,
            )
            for link in links
        ]

        self.enrich_imported_items(
            items,
            "Resolving Pasted Torrent Titles",
        )

        added, skipped = self.add_import_items(items)

        self.toast.show_message(
            f"Imported {added} item(s) to Cart"
            + (f" • {skipped} duplicate(s) skipped" if skipped else ""),
            5000
        )


    def import_cart_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Torrent Links / Files",
            "",
            (
                "Torrent and link files "
                "(*.torrent *.txt *.list *.csv *.tsv *.json *.md "
                "*.m3u *.m3u8 *.url *.urls);;"
                "Torrent files (*.torrent);;"
                "Text / link lists "
                "(*.txt *.list *.csv *.tsv *.json *.md *.m3u *.m3u8 "
                "*.url *.urls);;"
                "All files (*.*)"
            )
        )

        if not paths:
            return

        destination = self.manual_type.currentText()
        items = []
        errors = []

        for raw_path in paths:
            path = Path(raw_path)

            if path.suffix.lower() == ".torrent":
                try:
                    local_torrent_payload(path)
                    metadata_title = torrent_name_from_payload(
                        local_torrent_payload(
                            path
                        )
                    )

                    items.append(
                        self.make_import_cart_item(
                            local_torrent_path=str(path),
                            title=metadata_title or path.stem,
                            destination=destination,
                        )
                    )
                except Exception as exc:
                    errors.append(f"{path.name}: {exc}")
                continue

            try:
                try:
                    content = path.read_text(encoding="utf-8-sig")
                except UnicodeDecodeError:
                    content = path.read_text(encoding="cp1252")

                links = extract_torrent_links_from_text(content)

                if not links:
                    errors.append(
                        f"{path.name}: no torrent/magnet links found"
                    )
                    continue

                for link in links:
                    items.append(
                        self.make_import_cart_item(
                            link=link,
                            destination=destination,
                        )
                    )
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")

        self.enrich_imported_items(
            items,
            "Resolving Imported Torrent Titles",
        )

        added, skipped = self.add_import_items(items)

        if errors:
            preview = "\\n".join(
                f"• {line}" for line in errors[:8]
            )
            if len(errors) > 8:
                preview += f"\\n• ...and {len(errors) - 8} more"

            QMessageBox.warning(
                self,
                "Import Completed with Warnings",
                f"Added {added} item(s).\\n"
                f"Skipped {skipped} duplicate(s).\\n\\n"
                f"{preview}"
            )
        else:
            self.toast.show_message(
                f"Imported {added} item(s) to Cart"
                + (f" • {skipped} duplicate(s) skipped" if skipped else ""),
                5000
            )


    def backup_cart_snapshot(self, label="backup"):
        if not self.cart:
            return None

        backup_dir = APP_DIR / "cart_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_label = re.sub(
            r"[^A-Za-z0-9_-]+",
            "-",
            str(label or "backup")
        ).strip("-") or "backup"

        target = backup_dir / f"cart-{safe_label}-{stamp}.json"
        save_json(target, self.cart)

        backups = sorted(
            backup_dir.glob("cart-*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

        for old in backups[20:]:
            try:
                old.unlink()
            except Exception:
                pass

        return target


    def default_download_path(self, destination):
        from amf_features import DESTINATIONS
        key, default = DESTINATIONS.get(destination, DESTINATIONS["Series"])
        return str(self.config.get(key) or default)


    def apply_default_save_path(self, item, force=False):
        """
        Keep an item on the automatic destination path until the user manually
        overrides Save Location in the Cart.
        """
        if not item.get("destination_custom"):
            from amf_features import infer_destination
            item["type"] = infer_destination(item, self.source_config_for_result(item))
        if force or not item.get("save_path_custom"):
            item["save_path"] = self.default_download_path(
                item.get("type", "Series")
            )
            item["save_path_custom"] = False

        return item


    def effective_item_save_path(self, item):
        value = str(
            item.get("save_path") or ""
        ).strip()

        if value:
            return value

        return self.default_download_path(
            item.get("type", "Series")
        )


    def cart_cell_double_clicked(self, row, column):
        if getattr(self, 'cart_sender', None) and self.cart_sender.isRunning(): return
        # Save Location column.
        if column != 9:
            return

        if not (0 <= row < len(self.cart)):
            return

        item = self.cart[row]
        current = self.effective_item_save_path(item)

        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose Save Location for This Item",
            current
        )

        if not selected:
            return

        item["save_path"] = selected
        item["save_path_custom"] = True
        self.save_cart()
        self.refresh_cart()

        self.toast.show_message(
            f"Save location changed for {item.get('title', 'item')}",
            4500
        )


    def reset_selected_cart_locations(self):
        rows = sorted({
            index.row()
            for index in self.cart_table.selectionModel().selectedRows()
        })

        if not rows:
            self.toast.show_message(
                "Select one or more cart items first",
                3500
            )
            return

        changed = 0

        for row in rows:
            if 0 <= row < len(self.cart):
                self.apply_default_save_path(
                    self.cart[row],
                    force=True
                )
                changed += 1

        self.save_cart()
        self.refresh_cart()

        self.toast.show_message(
            f"{changed} item(s) reset to automatic location",
            4000
        )


    def cart_destination_changed(self, row, value):
        if 0 <= row < len(self.cart):
            item = self.cart[row]
            item["type"] = value
            item["destination_custom"] = True

            # Destination changes also change the folder while the item is in
            # automatic mode. A manually overridden Save Location is preserved.
            if not item.get("save_path_custom"):
                self.apply_default_save_path(item, force=True)

            self.save_cart()

    def remove_selected_cart(self):
        rows = sorted(
            {index.row() for index in self.cart_table.selectionModel().selectedRows()},
            reverse=True
        )

        for row in rows:
            if 0 <= row < len(self.cart):
                del self.cart[row]

        self.save_cart()
        self.refresh_cart()

    def clear_cart(self):
        if not self.cart:
            return

        answer = QMessageBox.question(
            self,
            "Clear Cart",
            "Remove every item from the cart?"
        )
        if answer == QMessageBox.Yes:
            self.cart = []
            self.save_cart()
            self.refresh_cart()

    def save_cart(self):
        if CART_FILE.exists():
            try:
                previous = json.loads(CART_FILE.read_text(encoding='utf-8-sig'))
                if isinstance(previous, list) and previous:
                    backup = APP_DIR / 'cart_backups'
                    backup.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(CART_FILE, backup / 'cart-last-good.json')
            except (ValueError, OSError):
                pass
        save_json(CART_FILE, self.cart)

    def refresh_cart_summary_only(self):
        total_bytes = sum(
            int(x.get("size_bytes", 0) or 0)
            for x in self.cart
        )
        total_text = human_bytes(total_bytes) if total_bytes else "unknown size"
        self.cart_summary.setText(
            f"{len(self.cart)} item(s) • {total_text}"
        )
        self.tabs.setTabText(
            1, "Cart" if not self.cart else f"Cart ({len(self.cart)})"
        )

    def refresh_cart(self):
        normalized = False
        for item in self.cart:
            previous = (item.get('type'), item.get('save_path'))
            self.apply_default_save_path(item)
            normalized |= previous != (item.get('type'), item.get('save_path'))
        self.cart_model.reset_rows(self.cart)
        if normalized:
            self.save_cart()
        self.refresh_cart_summary_only()

    # ---------------- SOURCES ----------------

    def build_sources_tab(self):
        layout = QVBoxLayout(self.sources_tab)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("Sources")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        desc = QLabel(
            "Paste a website below and let the app detect Schema.org SearchAction, OpenSearch, "
            "RSS/Atom, and normal search forms, or add a source manually."
        )
        desc.setWordWrap(True)
        desc.setObjectName("mutedText")
        layout.addWidget(desc)


        detect_box = QGroupBox("Add Website Automatically")
        detect_layout = QHBoxLayout(detect_box)

        self.website_detect_input = QLineEdit()
        self.website_detect_input.setPlaceholderText(
            "https://example.com"
        )
        self.website_detect_input.returnPressed.connect(
            self.detect_website_source
        )

        self.detect_site_btn = QPushButton("Detect Search")
        self.detect_site_btn.setObjectName("primaryButton")
        self.detect_site_btn.clicked.connect(self.detect_website_source)

        detect_layout.addWidget(QLabel("Website"))
        detect_layout.addWidget(self.website_detect_input, 1)
        detect_layout.addWidget(self.detect_site_btn)

        layout.addWidget(detect_box)


        preset_box = QGroupBox("Provider Presets")
        preset_layout = QHBoxLayout(preset_box)

        self.preset_combo = QComboBox()
        self.refresh_preset_combo()

        self.add_preset_btn = QPushButton("Add Preset")
        self.add_preset_btn.clicked.connect(self.add_selected_preset)

        self.save_preset_btn = QPushButton("Save Selected as Preset")
        self.save_preset_btn.clicked.connect(self.save_selected_source_as_preset)

        self.delete_preset_btn = QPushButton("Delete Custom Preset")
        self.delete_preset_btn.clicked.connect(self.delete_selected_custom_preset)

        preset_layout.addWidget(QLabel("Preset"))
        preset_layout.addWidget(self.preset_combo, 1)
        preset_layout.addWidget(self.add_preset_btn)
        preset_layout.addWidget(self.save_preset_btn)
        preset_layout.addWidget(self.delete_preset_btn)

        layout.addWidget(preset_box)

        self.sources_table = QTableWidget(0, 7)
        self.sources_table.setHorizontalHeaderLabels([
            "Enabled", "Name", "Type", "Mode", "Status", "Query Param", "Address"
        ])
        self.sources_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.sources_table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.Stretch
        )
        self.sources_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sources_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sources_table.doubleClicked.connect(self.edit_selected_source)
        layout.addWidget(self.sources_table, 1)

        controls = QHBoxLayout()

        add = QPushButton("+ Add Source")
        add.setObjectName("primaryButton")
        add.clicked.connect(self.add_source)

        edit = QPushButton("Edit Selected")
        edit.clicked.connect(self.edit_selected_source)

        preview = QPushButton("Test & Preview")
        preview.clicked.connect(self.test_selected_source)

        repair = QPushButton("Repair Selected")
        repair.clicked.connect(self.repair_selected_source)

        delete = QPushButton("Delete Selected")
        delete.clicked.connect(self.delete_selected_source)

        import_btn = QPushButton("Import Sources")
        import_btn.clicked.connect(self.import_sources)

        export_btn = QPushButton("Export Sources")
        export_btn.clicked.connect(self.export_sources)

        controls.addWidget(add)
        controls.addWidget(edit)
        controls.addWidget(preview)
        from amf_features import add_batch_test_controls
        add_batch_test_controls(self, layout, fetch_source)
        controls.addWidget(repair)
        controls.addWidget(delete)
        controls.addStretch()
        controls.addWidget(import_btn)
        controls.addWidget(export_btn)
        layout.addLayout(controls)

        help_box = QGroupBox("Quick Setup")
        help_layout = QVBoxLayout(help_box)
        help_text = QLabel(
            "Quick path: paste a homepage into Add Website Automatically. "
            "HTML searches are now verified after every request. If the configured metadata URL ignores the query, the app re-detects the homepage and tries the real GET search form automatically. "
            "Unverified default/latest pages are locally filtered instead of being shown as valid search results."
        )
        help_text.setWordWrap(True)
        help_layout.addWidget(help_text)
        layout.addWidget(help_box)



    def all_source_presets(self):
        presets = []
        for item in BUILTIN_SOURCE_PRESETS:
            presets.append({
                "preset_name": item.get("preset_name", "Preset"),
                "source": deep_copy(item.get("source") or {}),
                "builtin": True,
            })

        for item in self.config.get("source_presets", []):
            presets.append({
                "preset_name": item.get("preset_name", "Custom Preset"),
                "source": deep_copy(item.get("source") or {}),
                "builtin": False,
            })
        return presets

    def refresh_preset_combo(self):
        if not hasattr(self, "preset_combo"):
            return

        current = self.preset_combo.currentText()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()

        for item in self.all_source_presets():
            prefix = "Built-in" if item.get("builtin") else "Custom"
            self.preset_combo.addItem(
                f"{prefix} • {item.get('preset_name', 'Preset')}",
                item
            )

        if current:
            idx = self.preset_combo.findText(current)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)

        self.preset_combo.blockSignals(False)

    def add_selected_preset(self):
        item = self.preset_combo.currentData()
        if not isinstance(item, dict):
            self.toast.show_message("Choose a preset first", 3500)
            return

        source = deep_copy(item.get("source") or {})
        if not source:
            return

        sources = self.config.setdefault("sources", [])
        duplicate = any(
            s.get("url") == source.get("url")
            and s.get("type") == source.get("type")
            for s in sources
        )
        if duplicate:
            self.toast.show_message("That preset source is already added", 4000)
            return

        sources.append(source)
        save_json(CONFIG_FILE, self.config)
        self.refresh_sources()
        self.refresh_source_filter_options()
        self.toast.show_message(
            f"{item.get('preset_name', 'Preset')} added",
            4000
        )

    def save_selected_source_as_preset(self):
        row = self.selected_source_row()
        if row is None:
            self.toast.show_message("Select a source first", 3500)
            return

        sources = self.config.get("sources", [])
        if not (0 <= row < len(sources)):
            return

        source = deep_copy(sources[row])
        preset_name, ok = QInputDialog.getText(
            self,
            "Save Provider Preset",
            "Preset name:",
            text=source.get("name", "Source")
        )
        if not ok:
            return

        preset_name = preset_name.strip()
        if not preset_name:
            return

        custom = self.config.setdefault("source_presets", [])
        custom.append({
            "preset_name": preset_name,
            "source": source,
        })
        save_json(CONFIG_FILE, self.config)
        self.refresh_preset_combo()
        self.toast.show_message(f"Preset saved: {preset_name}", 4000)

    def delete_selected_custom_preset(self):
        item = self.preset_combo.currentData()
        if not isinstance(item, dict):
            return

        if item.get("builtin"):
            self.toast.show_message("Built-in presets can't be deleted", 4000)
            return

        preset_name = item.get("preset_name", "")
        custom = self.config.get("source_presets", [])

        for i, preset in enumerate(list(custom)):
            if preset.get("preset_name") == preset_name:
                del custom[i]
                save_json(CONFIG_FILE, self.config)
                self.refresh_preset_combo()
                self.toast.show_message(f"Preset deleted: {preset_name}", 4000)
                return

    def detect_website_source(self):
        website = self.website_detect_input.text().strip()
        if not website:
            self.toast.show_message("Paste a website URL first", 3500)
            return

        # Keep the exact homepage the user entered so this source can be
        # repaired later if its detected search endpoint changes domains.
        self.detect_origin_website = website

        self.detect_site_btn.setEnabled(False)
        self.detect_site_btn.setText("Detecting…")

        self.detect_worker = DetectSiteWorker(website)
        self.detect_worker.finished_detect.connect(
            self.website_detection_finished
        )
        self.detect_worker.start()

    def website_detection_finished(self, ok, page_title, candidates, final_url):
        self.detect_site_btn.setEnabled(True)
        self.detect_site_btn.setText("Detect Search")

        if not ok:
            QMessageBox.warning(
                self,
                "Website Detection Failed",
                page_title
            )
            return

        if not candidates:
            QMessageBox.information(
                self,
                "No Standard Search Found",
                "The site loaded, but it did not advertise OpenSearch/RSS/Atom "
                "and no conventional GET search form was detected.\n\n"
                "You can still use + Add Source to configure a known endpoint manually."
            )
            return

        dialog = SiteDetectionDialog(
            self,
            page_title,
            final_url,
            candidates
        )
        if dialog.exec() != QDialog.Accepted:
            return

        source = dialog.result_source()
        if not source:
            return

        source["origin_website"] = getattr(
            self,
            "detect_origin_website",
            final_url
        )
        source["detected_final_url"] = final_url

        # Avoid an accidental duplicate.
        current = self.config.setdefault("sources", [])
        duplicate = any(
            s.get("url") == source.get("url")
            and s.get("type") == source.get("type")
            for s in current
        )
        if duplicate:
            self.toast.show_message("That detected source is already in Sources", 4500)
            return

        current.append(source)
        save_json(CONFIG_FILE, self.config)
        self.refresh_sources()
        self.website_detect_input.clear()
        self.toast.show_message(
            f"{source.get('name', 'Website')} added • {source.get('type', '')}",
            5000
        )

    def add_source(self):
        dialog = SourceEditorDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        source = dialog.result_source()
        self.config.setdefault("sources", []).append(source)
        save_json(CONFIG_FILE, self.config)
        self.refresh_sources()
        self.toast.show_message(f"{source.get('name', 'Source')} added", 4000)

    def edit_selected_source(self):
        row = self.selected_source_row()
        if row is None:
            self.toast.show_message("Select a source first", 3500)
            return

        sources = self.config.get("sources", [])
        if not (0 <= row < len(sources)):
            return

        old_name = sources[row].get("name", "")
        dialog = SourceEditorDialog(self, sources[row])
        if dialog.exec() != QDialog.Accepted:
            return

        updated = dialog.result_source()
        sources[row] = updated
        if old_name != updated.get("name", ""):
            self.source_status.pop(old_name, None)
        save_json(CONFIG_FILE, self.config)
        self.refresh_sources()
        self.toast.show_message(f"{updated.get('name', 'Source')} updated", 4000)

    def selected_source_row(self):
        indexes = self.sources_table.selectedIndexes()
        if not indexes:
            return None
        return indexes[0].row()


    def repair_selected_source(self):
        row = self.selected_source_row()

        if row is None:
            self.toast.show_message(
                "Select the broken source first",
                3500
            )
            return

        sources = self.config.get("sources", [])

        if not (0 <= row < len(sources)):
            return

        source = sources[row]

        stored_origin = str(
            source.get("origin_website") or ""
        ).strip()

        if not stored_origin:
            # Older V2.8.x sources did not store their original homepage.
            # Fall back to the current endpoint's root as a starting suggestion.
            try:
                parts = urllib.parse.urlsplit(
                    source.get("url", "")
                )
                stored_origin = urllib.parse.urlunsplit((
                    parts.scheme or "https",
                    parts.netloc,
                    "/",
                    "",
                    "",
                ))
            except Exception:
                stored_origin = ""

        website, ok = QInputDialog.getText(
            self,
            "Repair Source",
            "Current homepage for this provider:",
            text=stored_origin
        )

        if not ok:
            return

        website = website.strip()

        if not website:
            return

        self.repair_source_row = row
        self.repair_origin_website = website

        self.source_status[
            source.get("name", "")
        ] = ("WAIT", "Repairing…")

        self.refresh_sources()

        self.repair_worker = DetectSiteWorker(website)
        self.repair_worker.finished_detect.connect(
            self.repair_detection_finished
        )
        self.repair_worker.start()


    def repair_detection_finished(
        self,
        ok,
        page_title,
        candidates,
        final_url
    ):
        row = getattr(
            self,
            "repair_source_row",
            None
        )

        if row is None:
            return

        sources = self.config.get("sources", [])

        if not (0 <= row < len(sources)):
            return

        old_source = sources[row]
        old_name = old_source.get("name", "Source")

        if not ok:
            self.source_status[old_name] = (
                "ERROR",
                page_title
            )
            self.refresh_sources()

            QMessageBox.warning(
                self,
                "Repair Failed",
                page_title
            )
            return

        ready = [
            candidate
            for candidate in candidates
            if not candidate.get("_rejected")
        ]

        if not ready:
            self.source_status[old_name] = (
                "ERROR",
                "No usable current search interface detected"
            )
            self.refresh_sources()

            QMessageBox.warning(
                self,
                "Repair Failed",
                "The homepage loaded, but no usable current search/feed "
                "interface could be detected."
            )
            return

        dialog = SiteDetectionDialog(
            self,
            page_title,
            final_url,
            candidates
        )

        if dialog.exec() != QDialog.Accepted:
            self.source_status[old_name] = (
                "WAIT",
                "Repair cancelled"
            )
            self.refresh_sources()
            return

        repaired = dialog.result_source()

        if not repaired:
            return

        # Preserve whether the user had this source enabled.
        repaired["enabled"] = old_source.get(
            "enabled",
            True
        )

        # Remember the homepage for future self-repair.
        repaired["origin_website"] = getattr(
            self,
            "repair_origin_website",
            final_url
        )
        repaired["detected_final_url"] = final_url

        sources[row] = repaired

        self.source_status.pop(
            old_name,
            None
        )

        self.source_status[
            repaired.get("name", "Source")
        ] = (
            "WAIT",
            "Repaired • run Test & Preview"
        )

        save_json(
            CONFIG_FILE,
            self.config
        )
        self.refresh_sources()

        self.toast.show_message(
            f"Source repaired: "
            f"{repaired.get('name', 'Source')}",
            5000
        )


    def test_selected_source(self):
        if getattr(self, "batch_test_worker", None) and self.batch_test_worker.isRunning():
            self.toast.show_message("Wait for the batch test to finish first", 3500)
            return
        if self.test_worker and self.test_worker.isRunning():
            return
        row = self.selected_source_row()
        if row is None:
            self.toast.show_message("Select a source first", 3500)
            return

        sources = self.config.get("sources", [])
        if not (0 <= row < len(sources)):
            return

        source = deep_copy(sources[row])
        query, ok = QInputDialog.getText(
            self,
            "Test & Preview",
            "Search term to use for this test:",
            text="test"
        )
        if not ok:
            return
        query = query.strip() or "test"

        self.source_status[source.get("name", "")] = ("WAIT", "Testing…")
        self.refresh_sources()

        self.test_worker = TestSourceWorker(source, query=query)
        self.test_worker.finished_test.connect(
            lambda ok, msg, results, name=source.get("name", ""):
                self.test_source_finished(name, ok, msg, results)
        )
        self.test_worker.start()

    def test_source_finished(self, name, ok, msg, results):
        self.source_status[name] = (
            "OK" if ok else "ERROR",
            msg
        )
        self.refresh_sources()

        if ok:
            if results:
                PreviewDialog(self, name, results).exec()
            else:
                self.toast.show_message(
                    f"{name} connected, but the test returned 0 results",
                    5000
                )
        else:
            # If this source was auto-detected in V2.8.7+, the app remembers
            # the homepage and can repair it without the user reconstructing
            # the endpoint manually.
            source = next(
                (
                    s for s in self.config.get("sources", [])
                    if s.get("name") == name
                ),
                None
            )

            extra = (
                "\n\nSelect this row and click Repair Selected."
            )

            if source and source.get("origin_website"):
                extra += (
                    "\nThe original homepage is already stored, "
                    "so Repair Selected will be pre-filled."
                )

            QMessageBox.warning(
                self,
                "Source Test Failed",
                f"{name}\n\n{msg}{extra}"
            )

    def delete_selected_source(self):
        row = self.selected_source_row()
        if row is None:
            self.toast.show_message("Select a source first", 3500)
            return

        sources = self.config.get("sources", [])
        if not (0 <= row < len(sources)):
            return

        name = sources[row].get("name", "this source")
        answer = QMessageBox.question(
            self,
            "Delete Source",
            f"Delete “{name}”?"
        )
        if answer != QMessageBox.Yes:
            return

        del sources[row]
        self.source_status.pop(name, None)
        save_json(CONFIG_FILE, self.config)
        self.refresh_sources()
        self.toast.show_message(f"{name} deleted", 4000)

    def import_sources(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Source Config",
            "",
            "JSON files (*.json);;All files (*.*)"
        )
        if not path:
            return

        try:
            obj = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(obj, dict) and isinstance(obj.get("sources"), list):
                incoming = obj["sources"]
            elif isinstance(obj, list):
                incoming = obj
            else:
                raise ValueError("Expected a JSON list or an object containing a 'sources' list")

            valid = [x for x in incoming if isinstance(x, dict) and x.get("name") and x.get("url")]
            if not valid:
                raise ValueError("No valid source definitions were found")

            existing_names = {s.get("name") for s in self.config.get("sources", [])}
            added = 0
            for source in valid:
                candidate = deep_copy(source)
                base = candidate.get("name", "Imported Source")
                name = base
                n = 2
                while name in existing_names:
                    name = f"{base} ({n})"
                    n += 1
                candidate["name"] = name
                candidate.setdefault("enabled", True)
                candidate.setdefault("search_mode", "Auto")
                candidate.setdefault("mappings", {})
                candidate.setdefault("headers", {})
                self.config.setdefault("sources", []).append(candidate)
                existing_names.add(name)
                added += 1

            save_json(CONFIG_FILE, self.config)
            self.refresh_sources()
            self.toast.show_message(f"Imported {added} source(s)", 5000)
        except Exception as exc:
            QMessageBox.warning(self, "Import Failed", str(exc))

    def export_sources(self):
        sources = self.config.get("sources", [])
        if not sources:
            self.toast.show_message("There are no sources to export", 3500)
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Source Config",
            "amf_sources.json",
            "JSON files (*.json)"
        )
        if not path:
            return

        if not path.lower().endswith(".json"):
            path += ".json"

        try:
            payload = {
                "format": "AMFSources",
                "version": 1,
                "sources": deep_copy(sources)
            }
            Path(path).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            self.toast.show_message("Source config exported", 4000)
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", str(exc))

    def toggle_source(self, row, state):
        sources = self.config.get("sources", [])
        if 0 <= row < len(sources):
            sources[row]["enabled"] = bool(state)
            save_json(CONFIG_FILE, self.config)
            self.refresh_source_filter_options()
            self.apply_result_filters()

    def refresh_sources(self):
        if not hasattr(self, "sources_table"):
            return

        sources = self.config.get("sources", [])
        self.sources_table.setRowCount(len(sources))

        for row, source in enumerate(sources):
            enabled = QCheckBox()
            enabled.setChecked(bool(source.get("enabled")))
            enabled.stateChanged.connect(
                lambda state, r=row: self.toggle_source(r, state)
            )
            self.sources_table.setCellWidget(row, 0, enabled)

            status_code, status_text = self.source_status.get(
                source.get("name", ""),
                ("", "Not tested")
            )

            if status_code == "OK":
                status_display = f"Connected • {status_text}"
            elif status_code == "ERROR":
                status_display = status_text or "Error"
            elif status_code == "CANCELLED":
                status_display = "Cancelled"
            elif status_code == "WAIT":
                status_display = "Testing…"
            else:
                status_display = "Not tested"

            mode = source.get("search_mode", "Auto")
            if mode == "Auto":
                mode = "Static Feed" if is_static_source(source) else "Search Endpoint"

            vals = [
                source.get("name", ""),
                source.get("type", ""),
                mode,
                status_display,
                source.get("query_param", ""),
                source.get("url", ""),
            ]

            for col, val in enumerate(vals, start=1):
                self.sources_table.setItem(
                    row, col, QTableWidgetItem(str(val))
                )

        self.refresh_source_filter_options()

    # ---------------- SETTINGS / QBIT ----------------

    def build_settings_tab(self):
        layout = QVBoxLayout(self.settings_tab)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        paths_box = QGroupBox("Default Download Locations")
        paths_layout = QVBoxLayout(paths_box)

        paths_note = QLabel(
            "Games, Movies, Series, Anime, Music and Books are routed separately. Cart items inherit these "
            "paths automatically, but an individual item can override its folder."
        )
        paths_note.setObjectName("mutedText")
        paths_note.setWordWrap(True)
        paths_layout.addWidget(paths_note)

        games_row = QHBoxLayout()
        games_label = QLabel("Games")
        games_label.setMinimumWidth(70)
        self.games_path_edit = QLineEdit(self.config.get("games_path", r"D:\Games"))
        games_browse = QPushButton("Browse")
        games_browse.clicked.connect(lambda checked=False: self.choose_extra_path(self.games_path_edit))
        games_row.addWidget(games_label)
        games_row.addWidget(self.games_path_edit, 1)
        games_row.addWidget(games_browse)
        paths_layout.addLayout(games_row)

        movies_row = QHBoxLayout()
        movies_label = QLabel("Movies")
        movies_label.setMinimumWidth(70)
        self.movies_path_edit = QLineEdit(
            self.config.get("movies_path", r"D:\Movies")
        )
        movies_browse = QPushButton("Browse")
        movies_browse.clicked.connect(self.choose_movies_path)
        movies_row.addWidget(movies_label)
        movies_row.addWidget(self.movies_path_edit, 1)
        movies_row.addWidget(movies_browse)
        paths_layout.addLayout(movies_row)

        series_row = QHBoxLayout()
        series_label = QLabel("Series")
        series_label.setMinimumWidth(70)
        self.series_path_edit = QLineEdit(
            self.config.get("series_path", r"D:\Series")
        )
        series_browse = QPushButton("Browse")
        series_browse.clicked.connect(self.choose_series_path)
        series_row.addWidget(series_label)
        series_row.addWidget(self.series_path_edit, 1)
        series_row.addWidget(series_browse)
        paths_layout.addLayout(series_row)

        from amf_features import DESTINATIONS
        self.extra_path_edits = {"games_path": self.games_path_edit}
        anime_heading = QLabel("Anime")
        anime_heading.setStyleSheet('font-weight: bold; background: transparent;')
        paths_layout.addWidget(anime_heading)
        for destination in ("Anime Movie", "Anime Series", "Music", "Books"):
            key, default = DESTINATIONS[destination]
            edit = QLineEdit(self.config.get(key, default))
            self.extra_path_edits[key] = edit
            row = QHBoxLayout()
            label = QLabel({"Anime Movie": "  Movies", "Anime Series": "  Series"}.get(destination, destination))
            label.setFixedWidth(70)
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            row.addWidget(label)
            row.addWidget(edit, 1)
            browse = QPushButton("Browse")
            browse.clicked.connect(lambda checked=False, e=edit: self.choose_extra_path(e))
            row.addWidget(browse)
            paths_layout.addLayout(row)
        layout.addWidget(paths_box)

        box = QGroupBox("Torrent Client")
        form = QFormLayout(box)

        qb = self.config.get("qbittorrent", {})

        self.qb_host = QLineEdit(qb.get("host", "127.0.0.1"))

        self.qb_port = QSpinBox()
        self.qb_port.setRange(1, 65535)
        self.qb_port.setValue(int(qb.get("port", 8080)))

        self.qb_user = QLineEdit(qb.get("username", ""))

        self.qb_password = QLineEdit(qb.get("password", ""))
        self.qb_password.setEchoMode(QLineEdit.Password)

        self.client_combo = QComboBox()
        self.client_combo.addItems(["qBittorrent", "Deluge", "Transmission", "uTorrent", "Other desktop client"])
        self.client_combo.setCurrentText(self.config.get("torrent_client", "qBittorrent"))
        self.client_executable = QLineEdit()
        self.client_executable.setPlaceholderText("Full path to the desktop client .exe")
        self.client_note = QLabel()
        self.client_note.setWordWrap(True)
        form.addRow("Client", self.client_combo)
        form.addRow("Executable", self.client_executable)
        form.addRow(self.client_note)
        self._editing_client = self.client_combo.currentText()
        self.load_client_profile()
        self.client_combo.currentTextChanged.connect(self.switch_client_profile)
        form.addRow("Host", self.qb_host)
        form.addRow("Port", self.qb_port)
        form.addRow("Username", self.qb_user)
        form.addRow("Password", self.qb_password)

        buttons = QHBoxLayout()

        save = QPushButton("Save Settings")
        save.clicked.connect(self.save_settings)

        test = QPushButton("Test Client")
        test.clicked.connect(self.test_qbittorrent)

        buttons.addWidget(save)
        buttons.addWidget(test)
        buttons.addStretch()
        form.addRow(buttons)

        layout.addWidget(box)
        layout.addStretch()

    def save_settings(self, show_message=True):
        movies_path = self.movies_path_edit.text().strip() or r"D:\Movies"
        series_path = self.series_path_edit.text().strip() or r"D:\Series"

        self.config["movies_path"] = movies_path
        self.config["series_path"] = series_path

        self.store_client_profile()
        self.config["torrent_client"] = self.client_combo.currentText()
        for key, edit in self.extra_path_edits.items():
            self.config[key] = edit.text().strip() or DEFAULT_CONFIG[key]

        # Move only automatic cart items to the new defaults. Manual overrides
        # remain untouched.
        for item in self.cart:
            if not item.get("save_path_custom"):
                self.apply_default_save_path(item, force=True)

        save_json(CONFIG_FILE, self.config)
        self.save_cart()
        self.refresh_paths()
        self.refresh_cart()

        if show_message:
            QMessageBox.information(
                self, "Settings", "Settings saved."
            )

    def qb_client(self):
        if self.config.get("torrent_client", "qBittorrent") != "qBittorrent":
            from amf_features import RemoteClient
            name = self.config["torrent_client"]
            return RemoteClient(name, self.config.get("client_profiles", {}).get(name, {}))
        if qbittorrentapi is None:
            raise RuntimeError(
                "qbittorrent-api is not installed."
            )

        qb = self.config.get("qbittorrent", {})

        return qbittorrentapi.Client(
            host=qb.get("host", "127.0.0.1"),
            port=int(qb.get("port", 8080)),
            username=qb.get("username", ""),
            password=qb.get("password", "")
        )

    def test_qbittorrent(self):
        self.save_settings(show_message=False)

        try:
            client = self.qb_client()
            client.auth_log_in()
            QMessageBox.information(
                self,
                "Torrent Client",
                "Connected successfully.\n\n"
                f"Client: {self.config.get('torrent_client', 'qBittorrent')}"
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Torrent Client",
                "Connection failed.\n\n"
                f"{exc}"
            )

    def send_cart_to_qbittorrent(self):
        if getattr(self, 'cart_sender', None) and self.cart_sender.isRunning():
            return
        if self.config.get('torrent_client') in ('uTorrent', 'Other desktop client'):
            return self.open_cart_in_desktop_client()
        if not self.cart:
            return
        from cart_sender import CartSender
        from reliability import previously_sent, torrent_identity
        sent_before = previously_sent(APP_DIR)
        duplicates = sum(torrent_identity(item) in sent_before for item in self.cart)
        if duplicates and QMessageBox.question(self, 'Previously Sent', f'{duplicates} item(s) already appear in successful history. Send this cart again?', QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.backup_cart_snapshot('before-send')
        batch = []
        for item in self.cart:
            item.setdefault('_queue_id', uuid.uuid4().hex)
            self.apply_default_save_path(item)
            batch.append((deep_copy(item), deep_copy(self.source_config_for_result(item))))
        self.save_cart()
        # The worker owns a snapshot of connection settings, never UI objects.
        config = deep_copy(self.config)
        def client_factory():
            if config.get('torrent_client', 'qBittorrent') != 'qBittorrent':
                from amf_features import RemoteClient
                name = config['torrent_client']
                return RemoteClient(name, config.get('client_profiles', {}).get(name, {}))
            qb = config.get('qbittorrent', {})
            return qbittorrentapi.Client(host=qb.get('host', '127.0.0.1'), port=int(qb.get('port', 8080)),
                username=qb.get('username', ''), password=qb.get('password', ''),
                REQUESTS_ARGS={'timeout': (10, 30)})
        self._sending_items = {item['_queue_id']: item for item in self.cart}
        self._sent_ids = set()
        self._send_failure = ''
        self.cart_sender = CartSender(client_factory, batch, APP_DIR / 'sent-receipts.jsonl', sys.modules[__name__], self)
        self.cart_sender.progress.connect(self.cart_send_progress)
        self.cart_sender.failed.connect(self.cart_send_failed)
        self.cart_sender.finished.connect(self.cart_send_finished)
        self._send_disabled_buttons = [button for button in self.cart_tab.findChildren(QPushButton)
                                       if button is not self.cancel_send_button and button.isEnabled()]
        for button in self._send_disabled_buttons: button.setEnabled(False)
        self.cart_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.send_cart_button.setEnabled(False)
        self.cancel_send_button.setEnabled(True)
        self.cart_sender.start()

    def cart_send_failed(self, message):
        self._send_failure = message

    def cart_send_progress(self, key, status, error):
        item = self._sending_items.get(key)
        if item:
            item['cart_status'], item['last_error'] = status, error
        if status == 'Sent':
            self._sent_ids.add(key)
        self.cart_summary.setText(f"Sending cart: {len(self._sent_ids)} confirmed / {len(self._sending_items)}")
        # Only repaint the viewport; no table rebuild or whole-cart save per item.
        self.cart_table.viewport().update()

    def cart_send_finished(self):
        self.cart = [item for item in self.cart if item.get('_queue_id') not in self._sent_ids]
        for item in self.cart:
            if item.get('cart_status') == 'Sending': item['cart_status'] = 'Ready'
        try:
            self.save_cart()
            # Clear receipts only after the new cart has been durably replaced.
            (APP_DIR / 'sent-receipts.jsonl').unlink(missing_ok=True)
        except Exception as exc:
            self._send_failure += '\nCould not save the cart: ' + str(exc)
        self.refresh_cart()
        for button in self._send_disabled_buttons: button.setEnabled(True)
        self.cart_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.send_cart_button.setEnabled(True)
        self.cancel_send_button.setEnabled(False)
        self.toast.show_message(f'{len(self._sent_ids)} sent; {len(self.cart)} retained in cart.', 6000)
        if self._send_failure:
            QMessageBox.warning(self, 'Client operation', self._send_failure)
        self._sending_items.clear()
        self.cart_sender.deleteLater()
        self.cart_sender = None

    def closeEvent(self, event):
        for worker in (getattr(self, 'cart_sender', None), self.search_worker, self.test_worker,
                       getattr(self, 'detect_worker', None), getattr(self, 'repair_worker', None), getattr(self, '_update_worker', None)):
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                self.toast.show_message('Waiting for the current request to finish before closing.', 5000)
                event.ignore()
                return
        batch = getattr(self, "batch_test_worker", None)
        if batch is not None and batch.isRunning():
            batch.requestInterruption()
            self.toast.show_message("Stopping source tests; close again when the current requests finish.", 5000)
            event.ignore()
            return
        try:
            if PID_FILE.exists():
                recorded = PID_FILE.read_text(encoding="utf-8").strip()
                if recorded == str(os.getpid()):
                    PID_FILE.unlink()
        except Exception:
            pass

        if hasattr(self, '_session_marker'):
            self._session_marker.unlink(missing_ok=True)
        super().closeEvent(event)


    # ---------------- PATHS ----------------

    def choose_movies_path(self):
        current = (
            self.movies_path_edit.text().strip()
            if hasattr(self, "movies_path_edit")
            else str(self.config.get("movies_path") or r"D:\Movies")
        )

        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose Default Movies Folder",
            current
        )

        if selected:
            self.movies_path_edit.setText(selected)


    def choose_series_path(self):
        current = (
            self.series_path_edit.text().strip()
            if hasattr(self, "series_path_edit")
            else str(self.config.get("series_path") or r"D:\Series")
        )

        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose Default Series Folder",
            current
        )

        if selected:
            self.series_path_edit.setText(selected)


    def refresh_paths(self):
        movies_path = str(
            self.config.get("movies_path") or r"D:\Movies"
        )
        series_path = str(
            self.config.get("series_path") or r"D:\Series"
        )

        if hasattr(self, "movies_path_edit"):
            self.movies_path_edit.setText(movies_path)

        if hasattr(self, "series_path_edit"):
            self.series_path_edit.setText(series_path)

        if hasattr(self, "movies_path_label"):
            self.movies_path_label.setText(
                f"Movies → {movies_path}"
            )

        if hasattr(self, "series_path_label"):
            self.series_path_label.setText(
                f"Series → {series_path}"
            )


    # ---------------- STYLE ----------------

    def apply_dark_style(self):
        self._base_style = """
            QWidget {
                background: #0A0A0C;
                color: #F5F5F5;
                font-family: Segoe UI;
                font-size: 13px;
            }

            QMainWindow {
                background: #09090B;
            }

            QFrame#brandBar {
                background: #0F0F12;
                border-bottom: 1px solid #26262C;
            }

            QLabel#brandIcon {
                background: transparent;
            }

            QLabel#brandTitle {
                background: transparent;
                color: #FFFFFF;
                font-size: 21px;
                font-weight: 800;
                letter-spacing: 1px;
            }

            QLabel#brandSubtitle {
                background: transparent;
                color: #85858E;
                font-size: 11px;
            }

            QLabel#versionBadge {
                color: #FFB3B3;
                background: #2A1113;
                border: 1px solid #612126;
                border-radius: 10px;
                padding: 4px 10px;
                min-width: 38px;
                font-weight: 700;
            }

            QTabWidget::pane {
                border: 1px solid #2B2B30;
                background: #0B0B0D;
            }

            QTabBar::tab {
                background: #101014;
                color: #AFAFB7;
                min-width: 105px;
                padding: 12px 20px;
                border: none;
                border-right: 1px solid #222227;
                border-bottom: 2px solid transparent;
                font-weight: 600;
            }

            QTabBar::tab:hover {
                background: #19191E;
                color: #FFFFFF;
            }

            QTabBar::tab:selected {
                background: #151519;
                color: #FFFFFF;
                border-bottom: 2px solid #F04444;
            }

            QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {
                background: #121216;
                color: #FFFFFF;
                border: 1px solid #303036;
                border-radius: 8px;
                padding: 9px 11px;
                selection-background-color: #B71C1C;
                selection-color: #FFFFFF;
            }

            QLineEdit:focus, QComboBox:focus,
            QSpinBox:focus, QPlainTextEdit:focus {
                border: 1px solid #E53935;
            }

            QComboBox::drop-down {
                border: none;
                width: 28px;
            }

            QComboBox QAbstractItemView {
                background: #151519;
                color: #FFFFFF;
                border: 1px solid #3A3A40;
                selection-background-color: #B71C1C;
                selection-color: #FFFFFF;
            }

            QPushButton {
                background: #17171C;
                color: #F5F5F5;
                border: 1px solid #35353C;
                border-radius: 8px;
                padding: 9px 14px;
                font-weight: 500;
            }

            QPushButton:hover {
                background: #242429;
                border-color: #E53935;
            }

            QPushButton:pressed {
                background: #111114;
            }

            QPushButton#primaryButton {
                background: #E23636;
                color: #FFFFFF;
                border: 1px solid #F04A4A;
                font-weight: 700;
            }

            QPushButton#primaryButton:hover {
                background: #E53935;
                border-color: #FF5C57;
            }

            QPushButton#primaryButton:pressed {
                background: #A91F1F;
            }

            QPushButton:disabled {
                color: #73737A;
                background: #141418;
                border-color: #28282D;
            }

            QTableView {
                background: #101013;
                alternate-background-color: #141418;
                color: #F4F4F5;
                gridline-color: #25252A;
                border: 1px solid #2B2B30;
                border-radius: 6px;
                selection-background-color: #4A1717;
                selection-color: #FFFFFF;
            }

            QTableView::item {
                padding: 6px;
            }

            QTableView::item:selected {
                background: #4A1717;
                color: #FFFFFF;
            }

            QHeaderView::section {
                background: #1A1A1F;
                color: #FFFFFF;
                padding: 9px;
                border: none;
                border-right: 1px solid #303036;
                border-bottom: 1px solid #303036;
                font-weight: 600;
            }

            QHeaderView::section:hover {
                background: #222227;
            }

            QGroupBox {
                background: #0E0E12;
                border: 1px solid #2B2B31;
                border-radius: 10px;
                margin-top: 14px;
                padding-top: 12px;
                font-weight: 650;
                color: #FFFFFF;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #F5F5F5;
            }

            QLabel#pageTitle {
                font-size: 26px;
                font-weight: 750;
                color: #FFFFFF;
                padding: 4px 0 8px 0;
            }

            QLabel#mutedText {
                color: #9A9AA3;
                background: transparent;
                font-size: 12px;
            }

            QCheckBox {
                spacing: 7px;
                color: #F5F5F5;
            }

            QCheckBox::indicator {
                width: 17px;
                height: 17px;
                border-radius: 4px;
                border: 1px solid #55555C;
                background: #151519;
            }

            QCheckBox::indicator:hover {
                border-color: #E53935;
            }

            QCheckBox::indicator:checked {
                background: #D32F2F;
                border: 1px solid #E53935;
            }

            QScrollBar:vertical {
                background: #101013;
                width: 12px;
                margin: 0;
            }

            QScrollBar::handle:vertical {
                background: #34343A;
                min-height: 28px;
                border-radius: 6px;
            }

            QScrollBar::handle:vertical:hover {
                background: #D32F2F;
            }

            QScrollBar:horizontal {
                background: #101013;
                height: 12px;
                margin: 0;
            }

            QScrollBar::handle:horizontal {
                background: #34343A;
                min-width: 28px;
                border-radius: 6px;
            }

            QScrollBar::handle:horizontal:hover {
                background: #D32F2F;
            }

            QFrame#toast {
                background: #17171B;
                border: 1px solid #E53935;
                border-radius: 10px;
            }

            QFrame#toast QLabel {
                background: transparent;
                color: #FFFFFF;
                font-size: 14px;
            }
        """
        self.apply_theme()

    def apply_theme(self):
        appearance = self.config.get("appearance", {})
        name = appearance.get("theme", "Dark")
        palette = PALETTES.get(name, PALETTES["Dark"])
        scale = getattr(self, '_ui_scale', 1.0)
        self.setStyleSheet(theme_css(self._base_style, palette,
                                     max(10, round(int(appearance.get("text_size", 13)) * scale)),
                                     float(appearance.get("density", 1.0)) * scale))
        for choice in self.findChildren(QComboBox, 'appearanceChoice'):
            choice.ensurePolished()
            from PySide6.QtWidgets import QStyle, QStyleOptionComboBox
            from PySide6.QtCore import QSize
            option = QStyleOptionComboBox()
            choice.initStyleOption(option)
            contents = QSize(choice.fontMetrics().horizontalAdvance(choice.currentText()) + 12,
                             choice.fontMetrics().height())
            choice.setFixedWidth(choice.style().sizeFromContents(QStyle.CT_ComboBox, option, contents, choice).width())
        from PySide6.QtGui import QImage, QPixmap
        logo = self.findChild(QLabel, 'brandIcon')
        if logo is not None:
            filename = 'logo-light.png' if name == 'Light' else 'logo-dark.png'
            if not hasattr(self, '_brand_pixmaps'):
                self._brand_pixmaps = {}
            image = QImage(str(Path(__file__).parent / filename)) if filename not in self._brand_pixmaps else QImage()
            if not image.isNull():
                # The supplied artwork has a tall transparent canvas. Trim it
                # for display without changing the original image file.
                mask = image.createAlphaMask()
                from PySide6.QtGui import QBitmap, QRegion
                bounds = QRegion(QBitmap.fromImage(mask)).boundingRect()
                pixmap = QPixmap.fromImage(image.copy(bounds))
                self._brand_pixmaps[filename] = pixmap
            pixmap = self._brand_pixmaps.get(filename)
            if pixmap is not None:
                logo.setPixmap(pixmap.scaled(42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.setWindowIcon(QIcon(pixmap))



from amf_features import install_features
install_features(AnimeDownloader)

def main():
    global BACKGROUND_SERVICES
    BACKGROUND_SERVICES = True
    if sys.platform == 'win32':
        ctypes.windll.kernel32.CreateMutexW.restype = ctypes.c_void_p
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, 'AMF.Desktop.Running')
        if ctypes.windll.kernel32.GetLastError() == 183:
            ctypes.windll.user32.MessageBoxW(None, 'AMF is already running. Open its existing window from the taskbar.', 'AMF', 64)
            return
    app = QApplication(sys.argv)
    app.setApplicationName("AMF")
    app.setApplicationDisplayName("AMF")
    app.setOrganizationName("AMF")
    window = AnimeDownloader()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

