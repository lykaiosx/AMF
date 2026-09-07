"""Read YTS's structured movie search instead of guessing its HTML layout."""
import re
import hashlib
from urllib.parse import quote, urlsplit
import requests


def parse_yts(payload, source):
    if not isinstance(payload, dict) or payload.get('status') != 'ok':
        raise ValueError('YTS returned an unsuccessful movie search response.')
    data = payload.get('data')
    if not isinstance(data, dict) or 'movie_count' not in data:
        raise ValueError('YTS returned an unexpected movie search response.')
    movies = data.get('movies', [])
    if not isinstance(movies, list):
        raise ValueError('YTS returned an invalid movie list.')
    results = []
    for movie in movies:
        if not isinstance(movie, dict):
            continue
        title = str(movie.get('title_long') or movie.get('title') or '').strip()
        if not title:
            continue
        for torrent in movie.get('torrents', []):
            info_hash = str(torrent.get('hash', ''))
            if not re.fullmatch(r'[0-9a-fA-F]{40}', info_hash) or info_hash == '0' * 40:
                continue
            quality = str(torrent.get('quality') or '')
            release = ' '.join(str(torrent.get(key) or '') for key in ('type', 'video_codec')).strip()
            display = ' '.join(part for part in (title, quality, release, '[YTS]') if part)
            def number(key):
                try:
                    return max(0, int(torrent.get(key) or 0))
                except (ValueError, TypeError):
                    return 0
            results.append(dict(
                title=display, source=source.get('name') or 'yts.gg',
                type='Movie', kind='Movie', scope='Movie', category='Movies',
                resolution=quality, language=movie.get('language') or '',
                size=torrent.get('size') or '', size_bytes=number('size_bytes'),
                seeders=number('seeds'), leechers=number('peers'),
                date=torrent.get('date_uploaded') or '',
                info_hash=info_hash.lower(),
                link=torrent.get('url') or metadata_url({'info_hash': info_hash}, source),
                link_usable=True, link_kind='Torrent', detail_url=movie.get('url') or '',
            ))
    return results


def is_yts_item(item, source):
    host = (urlsplit(source.get('url') or '').hostname or '').lower()
    return (source.get('builtin_id') == 'yts' or host in ('yts.gg', 'yts.mx')
            or str(item.get('source') or '').lower() in ('yts.gg', 'yts.mx', 'yts'))


def metadata_url(item, source):
    from reliability import torrent_identity
    identity = torrent_identity(item)
    code = identity.removeprefix('btih:')
    if not re.fullmatch(r'[0-9a-fA-F]{40}', code):
        match = re.search(r'/torrent/download/([0-9a-fA-F]{40})', item.get('link') or '')
        if not match:
            raise ValueError('YTS release has no valid torrent hash. Search for it again.')
        code = match[1]
    configured = urlsplit(source.get('url') or 'https://yts.gg')
    origin = f'{configured.scheme or "https"}://{configured.netloc or "yts.gg"}'
    return origin + '/torrent/download/' + code.upper()


def fetch_metadata(item, source, api):
    url = metadata_url(item, source)
    expected = url.rsplit('/', 1)[-1].lower()
    try:
        data = api.fetch_torrent_payload(url, source=source, item=item, timeout=20, attempts=2)
        if not data.startswith(b'd'):
            raise ValueError('Invalid torrent metadata')
        position = 1
        while position < len(data) and data[position:position+1] != b'e':
            key, position = api.bdecode_torrent_value(data, position)
            start = position
            value, position = api.bdecode_torrent_value(data, position)
            if key == b'info':
                if hashlib.sha1(data[start:position]).hexdigest() != expected:
                    raise ValueError('Torrent metadata hash does not match the selected release')
                return data
        raise ValueError('Torrent has no metadata dictionary')
    except Exception as exc:
        raise RuntimeError('YTS metadata could not be fetched. The item remains in the cart; retry sending it. ' + str(exc)) from exc


def fetch_yts(source, query, timeout=15):
    configured = urlsplit(source.get('url') or 'https://yts.gg')
    origin = f'{configured.scheme or "https"}://{configured.netloc or "yts.gg"}'
    response = requests.get(origin + '/api/v2/list_movies.json',
                            params={'query_term': query, 'limit': 50, 'page': 1},
                            timeout=timeout, headers={'User-Agent': 'AMF movie search'})
    response.raise_for_status()
    payload = response.json()
    results = parse_yts(payload, source)
    data = payload['data']
    loaded = len(data.get('movies', []))
    return results, f"YTS • {len(results)} releases • {loaded} of {data['movie_count']} matching movies"
