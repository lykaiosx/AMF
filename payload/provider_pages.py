"""Exact provider-page parsing and user-visible browser fallback."""
import re
from urllib.parse import urljoin, urlsplit, quote, urlencode
from bs4 import BeautifulSoup
from PySide6.QtCore import Signal, QUrl
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import QLineEdit, QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QMessageBox


class NumberField(QLineEdit):
    valueChanged = Signal()
    def __init__(self, decimal=False):
        super().__init__('0')
        self.decimal = decimal
        self.setValidator(QDoubleValidator(0, 100000, 3, self) if decimal else QIntValidator(0, 999999, self))
        self.textChanged.connect(lambda _: self.valueChanged.emit())
        self.setMaximumWidth(120)
    def setRange(self, low, high):
        self.validator().setRange(low, high)
    def value(self):
        try: return float(self.text()) if self.decimal else int(self.text())
        except ValueError: return 0
    def setValue(self, value): self.setText(str(value))
    def setSpecialValueText(self, value): self.setPlaceholderText(value)


def provider_url(source, query):
    # Keep the complete query, including stop words, punctuation and spaces.
    template = source.get('url', '')
    if source.get('builtin_id') == 'annas_archive' or 'annas-archive.' in template:
        origin = urlsplit(template)
        return f'{origin.scheme}://{origin.netloc}/search?' + urlencode({'q':query, 'check':'1'})
    origin = urlsplit(template)
    return f'{origin.scheme}://{origin.netloc}/search/' + quote(query, safe='')


def parse_provider_page(source, content, url):
    soup = BeautifulSoup(content, 'html.parser')
    title = soup.title.get_text(' ', strip=True).lower() if soup.title else ''
    if any(x in title for x in ('just a moment', 'ddos-guard', 'access denied')):
        raise RuntimeError('Browser verification required. Use Read Provider Page to load this search and read its results.')
    anna = 'annas-archive.' in url or source.get('builtin_id') == 'annas_archive'
    results, seen = [], set()
    anchors = soup.select('.js-aarecord-list-outer a.js-vim-focus[href*="/md5/"]') if anna else soup.select('a.epinfo, a[href*="/ep/"]')
    for anchor in anchors:
        href = urljoin(url, anchor.get('href', ''))
        if href in seen: continue
        if anna:
            container = anchor.find_parent(class_=re.compile(r'js-aarecord-list-item'))
            if container is None:
                container = anchor
                for _ in range(4):
                    parent = container.parent
                    if parent is None or len({a.get('href') for a in parent.select('a[href*="/md5/"]')}) > 1: break
                    container = parent
            name = anchor.get_text(' ',strip=True)
        else:
            container = anchor.find_parent('tr') or anchor.parent
            name = anchor.get_text(' ',strip=True) or anchor.get('title','')
        if not name: continue
        seen.add(href)
        text = container.get_text(' ',strip=True)
        size = re.search(r'\b([\d.,]+)\s*(GiB|MiB|KiB|GB|MB|KB|TB)\b',text,re.I)
        size_text = size.group(0) if size else ''
        magnitude = float(size.group(1).replace(',','')) if size else 0
        power = {'KB':1,'KIB':1,'MB':2,'MIB':2,'GB':3,'GIB':3,'TB':4}.get(size.group(2).upper(),0) if size else 0
        magnet = container.select_one('a[href^="magnet:"]')
        torrent = container.select_one('a[href*=".torrent"]')
        direct = magnet or torrent
        link = urljoin(url,direct['href']) if direct else href
        cells = container.find_all('td',recursive=False) if not anna else []
        seed_text = cells[-1].get_text(strip=True) if cells else ''
        seeds = int(seed_text) if seed_text.isdigit() else None
        resolution = re.search(r'\b(2160p|1080p|720p|480p)\b',name,re.I)
        item = {'title':name,'source':source.get('name',''),'detail_url':href,'link':link,
            'link_usable':bool(direct),'link_kind':'Magnet' if magnet else ('Torrent' if torrent else 'Book page' if anna else 'Page URL'),
            'type':'Books' if anna else 'Series','destination_custom':True,'category':'Books' if anna else 'TV Series',
            'kind':'Book' if anna else 'Episode','scope':'Unknown' if anna else 'Single Episode',
            'size':size_text,'size_bytes':int(magnitude*1024**power),'seeders':seeds,
            'resolution':resolution.group(1).lower() if resolution else '',
            'description':text,'provider_page':url,'provider_order':len(results)}
        language = re.search(r'([A-Za-z]+)\s*\[[a-z]{2,3}\]',text)
        item['language'] = language.group(1) if language else ''
        if anna:
            item['format'] = (re.search(r'\b(PDF|EPUB|AZW3|MOBI|FB2|DOCX|RTF|LIT)\b',text,re.I) or [''])[0]
        results.append(item)
    if not results:
        visible = soup.get_text(' ',strip=True).lower()
        if not any(x in visible for x in ('no results','no torrents','nothing found','no files found','0 results')):
            raise RuntimeError('No recognizable search rows on this page. Use Read Provider Page; the site may require browser verification or have changed its layout.')
    summary = f'{len(results)} rows from this search page (provider order)'
    total = re.search(r'RESULTS\s+[\d,]+\s*[-–]\s*[\d,]+\s*\(([^)]+)\)',soup.get_text(' ',strip=True),re.I)
    if total: summary += ' • site: '+total.group(1)
    return results, summary


class ProviderPageDialog(QDialog):
    def __init__(self, parent, source, query):
        super().__init__(parent)
        from PySide6.QtWebEngineWidgets import QWebEngineView
        self.source = source
        self.rows = None
        self.setWindowTitle('Read Provider Page — '+source.get('name',''))
        self.resize(1100,800)
        layout=QVBoxLayout(self)
        self.note=QLabel('Wait for the search results to appear. Complete any site verification yourself, then click Read These Results. Only this displayed page is imported.')
        self.note.setWordWrap(True); layout.addWidget(self.note)
        self.browser=QWebEngineView(self); layout.addWidget(self.browser,1)
        row=QHBoxLayout(); layout.addLayout(row)
        read=QPushButton('Read These Results'); row.addWidget(read)
        read.clicked.connect(lambda: self.browser.page().toHtml(self.read_html))
        close=QPushButton('Close'); row.addWidget(close); close.clicked.connect(self.reject)
        self.browser.setUrl(QUrl(provider_url(source,query)))
    def read_html(self, content):
        try:
            self.rows, self.summary = parse_provider_page(self.source,content,self.browser.url().toString())
        except Exception as exc:
            self.note.setText(str(exc)); return
        self.accept()
