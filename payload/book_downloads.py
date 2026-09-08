"""Book detail pages are saved in the cart, not submitted as torrent files."""
from urllib.parse import urlsplit

BOOK_GUIDANCE = 'This is a book download page, not a torrent. Select it and choose Open Book Download Page. Complete any site verification there; qBittorrent requires a magnet or .torrent file.'

def is_book_page(item):
    if item.get('local_torrent_path'):
        return False
    url = urlsplit(str(item.get('link') or ''))
    host = (url.hostname or '').lower()
    return url.scheme in ('http', 'https') and host in ('annas-archive.gl', 'annas-archive.pk', 'annas-archive.gd', 'annas-archive.li', 'annas-archive.org') and url.path.startswith('/md5/')

def prepare_book(item):
    item.update(link_kind='Book page', link_usable=False, type='Books', category='Books',
                cart_status='Open book page', last_error=BOOK_GUIDANCE)
    item.pop('destination_custom', None)
    return item
