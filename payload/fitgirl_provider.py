"""Search the public A-Z catalogue, caching it instead of fetching every game page."""
import re, time, threading
from urllib.parse import urlsplit, urljoin
import requests
from bs4 import BeautifulSoup
INDEX = 'https://fitgirl-repacks.site/all-my-repacks-a-z/'
_cache = None
_lock = threading.Lock()


def parse_index(content):
    soup = BeautifulSoup(content, 'html.parser')
    rows, seen = [], set()
    for anchor in soup.select('.entry-content .lcp_catlist li a[href]'):
        url = urljoin(INDEX, anchor['href'])
        title = anchor.get_text(' ', strip=True)
        if title and urlsplit(url).hostname == 'fitgirl-repacks.site' and url not in seen:
            rows.append((title, url))
            seen.add(url)
    if not rows:
        raise ValueError('FitGirl catalogue is unavailable or requires browser verification.')
    return rows


def fetch_fitgirl(source, query, timeout=20):
    global _cache
    with _lock:
        if _cache is None or time.monotonic() - _cache[0] > 900:
            response = requests.get(INDEX, timeout=timeout)
            response.raise_for_status()
            _cache = (time.monotonic(), parse_index(response.content))
        catalogue = _cache[1]
    terms = re.findall(r'\w+', query.casefold())
    rows = []
    for title, url in catalogue:
        normalized = ' '.join(re.findall(r'\w+', title.casefold()))
        if terms and all(term in normalized for term in terms):
            rows.append(dict(title=title, source=source.get('name', 'FitGirl Repacks'),
                link=url, detail_url=url, link_kind='Page URL', link_usable=False,
                category='Games', type='Games', kind='Game', scope='Unknown',
                destination_custom=True, description='Game repack; torrent link resolved when added to cart.'))
    return rows, f'FitGirl • {len(rows)} matching games • A–Z catalogue'
