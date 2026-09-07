"""Search FitGirl repack posts with bounded pagination."""
from urllib.parse import urlsplit, urljoin
import requests
from bs4 import BeautifulSoup
INDEX = 'https://fitgirl-repacks.site/all-my-repacks-a-z/'


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




def parse_search(content, page_url):
    soup = BeautifulSoup(content, 'html.parser')
    rows = []
    for article in soup.select('article'):
        anchor = article.select_one('.entry-title a[href]')
        if anchor is None:
            continue
        # WordPress search also returns announcements; only repack posts belong here.
        categories = [a.get_text(' ', strip=True).casefold() for a in article.select('.cat-links a')]
        if categories and not any('repack' in c for c in categories):
            continue
        url = urljoin(page_url, anchor['href'])
        if urlsplit(url).hostname == 'fitgirl-repacks.site':
            rows.append((anchor.get_text(' ', strip=True), url))
    if not soup.select('article') and not soup.select('.no-results'):
        raise ValueError('FitGirl search is unavailable or requires browser verification.')
    following = soup.select_one('a.next.page-numbers')
    next_url = urljoin(page_url, following['href']) if following else None
    if next_url and urlsplit(next_url).hostname != 'fitgirl-repacks.site':
        next_url = None
    return rows, next_url


def fetch_fitgirl(source, query, timeout=20):
    from urllib.parse import urlencode
    if not query.strip():
        return [], 'FitGirl • Enter a game title'
    url = 'https://fitgirl-repacks.site/?' + urlencode({'s': query.strip()})
    rows, seen = [], set()
    # Bound requests per search; report partial coverage rather than fetching 144 catalogue pages.
    for _ in range(3):
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        matches, following = parse_search(response.content, url)
        for title, link in matches:
            if link in seen:
                continue
            seen.add(link)
            rows.append(dict(title=title, source=source.get('name', 'FitGirl Repacks'),
                link=link, detail_url=link, link_kind='Page URL', link_usable=False,
                category='Games', type='Games', kind='Game', scope='Unknown',
                description='Game repack; torrent link resolved when added to cart.'))
        if not following or following == url:
            break
        url = following
    suffix = ' • more matches available on the site; narrow your search' if following else ''
    return rows, f'FitGirl • {len(rows)} search results{suffix}'
