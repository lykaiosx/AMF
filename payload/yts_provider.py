"""Read YTS's structured movie search instead of guessing its HTML layout."""
import re
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
                link='magnet:?xt=urn:btih:' + info_hash.lower() + '&dn=' + quote(display),
                link_usable=True, link_kind='Magnet', detail_url=movie.get('url') or '',
            ))
    return results


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
