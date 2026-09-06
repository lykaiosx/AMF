"""Persistent history, torrent identity, private credentials and diagnostics."""
import base64
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qs


def torrent_identity(value):
    if isinstance(value, dict) and re.fullmatch('[0-9a-fA-F]{40}', str(value.get('info_hash') or '')):
        return 'btih:' + value['info_hash'].lower()
    link = value.get('link', '') if isinstance(value, dict) else str(value or '')
    if link.lower().startswith('magnet:'):
        for xt in parse_qs(urlsplit(link).query).get('xt', []):
            if xt.lower().startswith('urn:btih:'):
                code = xt[9:]
                if re.fullmatch('[0-9a-fA-F]{40}', code): return 'btih:' + code.lower()
                if re.fullmatch('[A-Za-z2-7]{32}', code):
                    return 'btih:' + base64.b32decode(code.upper()).hex()
            if re.fullmatch(r'urn:btmh:1220[0-9a-fA-F]{64}', xt, re.I): return xt.lower()
    return 'link:' + link.strip() if link else ''


def merge_duplicates(rows):
    merged, seen = [], {}
    for original in rows:
        item = dict(original)
        key = torrent_identity(item)
        if key and key in seen:
            match = seen[key]
            name = item.get('source', '')
            if name not in match['available_sources']: match['available_sources'].append(name)
            match['alternatives'].append(item)
        else:
            item['available_sources'] = [item.get('source', '')]
            item['alternatives'] = []
            merged.append(item)
            if key: seen[key] = item
    return merged


def error_guidance(message):
    text = str(message).lower()
    if any(x in text for x in ('captcha', 'cloudflare', 'just a moment', 'challenge', '403')):
        return 'Browser verification required', 'Open the source in a browser, complete its verification, then use Read Page or retry.'
    if any(x in text for x in ('401', 'unauthor', 'password', 'login', 'authentication')):
        return 'Sign-in failed', 'Check the client username/password in Settings, then test the connection.'
    if any(x in text for x in ('connection', 'timed out', 'timeout', 'resolve', 'unreachable', '502', '503')):
        return 'Connection unavailable', 'Check your connection and the site or client address, then retry.'
    if any(x in text for x in ('no result', '0 result', 'empty')):
        return 'No matching results', 'Try a shorter title or clear search filters.'
    return 'Request failed', 'Retry the operation. If it continues, export diagnostics from Settings.'


def history_connection(root):
    connection = sqlite3.connect(str(Path(root) / 'history.sqlite3'), timeout=10)
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, time TEXT, title TEXT, identity TEXT, client TEXT, destination TEXT, status TEXT, error TEXT)')
    connection.execute('CREATE INDEX IF NOT EXISTS history_identity ON events(identity, status)')
    return connection


def record_history(root, item, client, status, error=''):
    key = item.get('_queue_id') or hashlib.sha256((item.get('link','') + item.get('title','')).encode()).hexdigest()
    with history_connection(root) as db:
        db.execute('INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?)',
            (key + ':' + status, datetime.now(timezone.utc).isoformat(timespec='seconds'), item.get('title',''),
             torrent_identity(item), client, item.get('save_path',''), status, str(error)))
    db.close()


def history_rows(root, query='', offset=0, limit=200):
    with history_connection(root) as db:
        rows = db.execute('SELECT time,title,client,destination,status,error FROM events WHERE title LIKE ? OR client LIKE ? ORDER BY time DESC LIMIT ? OFFSET ?',
                          ('%'+query+'%', '%'+query+'%', limit, offset)).fetchall()
    db.close()
    return rows


def previously_sent(root):
    with history_connection(root) as db:
        rows = db.execute("SELECT identity FROM events WHERE status='Sent'").fetchall()
    db.close()
    return {row[0] for row in rows if row[0]}


class Credential(ctypes.Structure):
    _fields_ = [('Flags', w.DWORD), ('Type', w.DWORD), ('TargetName', w.LPWSTR),
                ('Comment', w.LPWSTR), ('LastWritten', w.FILETIME), ('CredentialBlobSize', w.DWORD),
                ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', w.DWORD),
                ('AttributeCount', w.DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', w.LPWSTR), ('UserName', w.LPWSTR)]


class CredentialStore:
    def __init__(self):
        self.api = ctypes.WinDLL('advapi32', use_last_error=True)
        self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), w.DWORD]
        self.api.CredWriteW.restype = w.BOOL
        self.api.CredReadW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
        self.api.CredReadW.restype = w.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]
        self.api.CredDeleteW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD]
    def write(self, target, value):
        raw = value.encode('utf-8')
        if len(raw) > 2560: raise ValueError('Credential exceeds the Windows storage limit')
        blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        credential = Credential(Type=1, TargetName=target, CredentialBlobSize=len(raw), CredentialBlob=blob, Persist=2, UserName='AMF')
        if not self.api.CredWriteW(ctypes.byref(credential), 0): raise ctypes.WinError(ctypes.get_last_error())
    def read(self, target):
        result = ctypes.POINTER(Credential)()
        if not self.api.CredReadW(target, 1, 0, ctypes.byref(result)): raise ctypes.WinError(ctypes.get_last_error())
        try: return ctypes.string_at(result.contents.CredentialBlob, result.contents.CredentialBlobSize).decode('utf-8')
        finally: self.api.CredFree(result)
    def delete(self, target): self.api.CredDeleteW(target, 1, 0)


SECRET_KEYS = {'password', 'token', 'api_key', 'apikey', 'authorization', 'cookie', 'cookies'}


def protect_config(value, config_path, store=None):
    store = store or CredentialStore()
    namespace = hashlib.sha256(str(Path(config_path).resolve()).lower().encode()).hexdigest()[:20]
    def walk(node, route=()):
        if isinstance(node, dict):
            out = {}
            for key, item in node.items():
                if key.lower() in SECRET_KEYS and isinstance(item, str) and item:
                    target = 'AMF/' + namespace + '/' + hashlib.sha256('/'.join(route+(key,)).encode()).hexdigest()
                    store.write(target, item)
                    out[key] = {'__amf_credential__': target}
                else: out[key] = walk(item, route+(key,))
            return out
        if isinstance(node, list): return [walk(item, route+(str(i),)) for i,item in enumerate(node)]
        return node
    return walk(value)


def hydrate_config(value, store=None, warnings=None):
    store = store or CredentialStore()
    if isinstance(value, dict):
        if '__amf_credential__' in value:
            try: return store.read(value['__amf_credential__'])
            except OSError:
                if warnings is not None: warnings.append('A saved credential is unavailable on this Windows account. Re-enter it in Settings.')
                return ''
        return {k: hydrate_config(v, store, warnings) for k,v in value.items()}
    if isinstance(value, list): return [hydrate_config(v, store, warnings) for v in value]
    return value


def diagnostic_report(root, version, statuses):
    # Allowlist only. Never copy config, history, cart, URLs, paths or raw logs.
    import platform
    report = {'app_version': version, 'python': platform.python_version(), 'windows': platform.win32_ver()[0],
              'source_health': {}, 'logs': {}}
    for name,(state,message) in statuses.items():
        report['source_health'][hashlib.sha256(name.encode()).hexdigest()[:8]] = {'state': state, 'category': error_guidance(message)[0] if state != 'OK' else 'Connected'}
    for name in ('startup-error.log', 'install-check.log', 'setup-error.log'):
        path = Path(root)/name
        if path.exists():
            text = path.read_text(encoding='utf-8', errors='replace')
            allowed = {'RuntimeError','ValueError','TypeError','ImportError','ModuleNotFoundError',
                       'PermissionError','FileNotFoundError','ConnectionError','TimeoutError','OSError'}
            report['logs'][name] = {'bytes': path.stat().st_size,
                'exception_types': sorted(allowed.intersection(re.findall(r'\b([A-Za-z]+(?:Error|Exception))\b', text)))}
    return report
