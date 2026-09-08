"""Read AnimeTosho's published search rows, including archived swarm counts."""
import re
from datetime import datetime,timezone
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

def parse_page(source,content,api):
    soup=BeautifulSoup(content,'html.parser');results=[]
    for row in soup.select('.home_list_entry'):
        title_link=row.select_one('.link a[href]')
        torrent=row.select_one('a[href*=".torrent"]');magnet=row.select_one('a[href^="magnet:"]')
        if title_link is None or (torrent is None and magnet is None):continue
        title=title_link.get_text(' ',strip=True)
        link=urljoin('https://animetosho.org/',(torrent or magnet)['href'])
        size=row.select_one('.size');size_bytes=None
        if size:
            count=re.search(r'([\d,]+) bytes',size.get('title',''))
            size_bytes=int(count[1].replace(',','')) if count else api.parse_size_to_bytes(size.get_text())
        swarm=row.select_one('[title*="Seeders:"]')
        counts=re.search(r'Seeders:\s*([\d,]+)\s*/\s*Leechers:\s*([\d,]+)',swarm.get('title','')) if swarm else None
        date=row.select_one('.date');stamp=None;display=''
        if date:
            match=re.search(r'(\d{2}/\d{2}/\d{4} \d{2}:\d{2})',date.get('title',''))
            if match:
                stamp=datetime.strptime(match[1],'%d/%m/%Y %H:%M').replace(tzinfo=timezone.utc).timestamp();display=match[1]
        kind=api.detect_kind(title,'Anime')
        results.append(dict(title=title,source=source.get('name','Anime Tosho'),link=link,
            detail_url=title_link['href'],link_kind='Torrent' if torrent else 'Magnet',link_usable=True,
            size=size.get_text(strip=True) if size else None,size_bytes=size_bytes,
            seeders=int(counts[1].replace(',','')) if counts else None,
            leechers=int(counts[2].replace(',','')) if counts else None,
            date=display,date_ts=stamp,language=api.detect_language(title),resolution=api.detect_resolution(title),
            kind=kind,scope=api.detect_release_scope(title,'Anime'),type='Anime Movie' if kind=='Movie' else 'Anime Series',
            category='Anime',description='AnimeTosho archived metadata; counts are not live.',metadata_archived=True))
    if not results and not any(text in soup.get_text(' ',strip=True).lower() for text in ('no results','nothing found','no entries')):
        raise ValueError('AnimeTosho search rows could not be read; the site may be unavailable.')
    return results

def fetch(source,query,timeout,api):
    response=requests.get('https://animetosho.org/',params={'q':query},timeout=timeout)
    response.raise_for_status()
    rows=parse_page(source,response.content,api)
    return rows,f'{len(rows)} results • Archived metadata: AnimeTosho stopped updates in May 2026; seeds and peers are not live.'
