"""Bounded HTTP metadata preparation, cached before client submission."""
import hashlib,re,os,time,uuid
from pathlib import Path
from urllib.parse import urlsplit,urljoin
import requests
from PySide6.QtCore import QObject,QThread,Signal,QTimer
from reliability import torrent_identity

LIMIT=20*1024*1024

def validate(data,item,api):
    if len(data)>LIMIT or not data.startswith(b'd'):raise ValueError('Invalid torrent metadata')
    position=1;info=None
    while position<len(data) and data[position:position+1]!=b'e':
        key,position=api.bdecode_torrent_value(data,position);start=position
        value,position=api.bdecode_torrent_value(data,position)
        if key==b'info':
            if not isinstance(value,dict) or b'name' not in value:raise ValueError('Invalid torrent info dictionary')
            info=hashlib.sha1(data[start:position]).hexdigest()
    if not info or position!=len(data)-1 or data[position:]!=b'e':raise ValueError('Incomplete torrent metadata')
    identity=torrent_identity(item)
    match=re.search(r'/torrent/download/([0-9a-fA-F]{40})',item.get('link') or '')
    if match:identity='btih:'+match[1].lower()
    if identity.startswith('btih:') and identity[5:].lower()!=info:raise ValueError('Metadata hash does not match the selected torrent')
    return info

def read_cached(item,api):
    path=item.get('metadata_path')
    if not path and isinstance(getattr(api,'APP_DIR',None),Path):
        identity=torrent_identity(item)
        if identity.startswith('btih:'):path=api.APP_DIR/'metadata_cache'/(identity[5:]+'.torrent')
    if not path:return None
    try:
        file=Path(path)
        if file.stat().st_size>LIMIT:return None
        data=file.read_bytes();validate(data,item,api);return data
    except (OSError,ValueError,IndexError,TypeError,RecursionError):return None

def download(url,source,item,api):
    with requests.get(url,headers=api.torrent_download_headers(source,item),timeout=(6,15),stream=True) as response:
        response.raise_for_status();data=bytearray()
        started=time.monotonic()
        for block in response.iter_content(65536):
            if time.monotonic()-started>30:raise TimeoutError('Metadata request timed out')
            data.extend(block)
            if len(data)>LIMIT:raise ValueError('Metadata response exceeds 20 MB')
    return bytes(data)

def prepare(item,source,root,api):
    if item.get('local_torrent_path'):
        data=api.local_torrent_payload(item['local_torrent_path'])
    else:
        cached=read_cached(item,api)
        if cached:return str(Path(root)/'metadata_cache'/(validate(cached,item,api)+'.torrent')) if not item.get('metadata_path') else item['metadata_path']
        from yts_provider import is_yts_item,metadata_url
        candidates=[]
        link=item.get('link','')
        if is_yts_item(item,source):candidates.append(metadata_url(item,source))
        elif api.classify_link(link)[1] and link.startswith(('http://','https://')):candidates.append(link)
        detail=item.get('detail_url') or item.get('guid') or ''
        host=(urlsplit(detail).hostname or '').lower()
        match=re.search(r'/view/(\d+)',detail)
        if host=='nyaa.si' and match:candidates.append('https://nyaa.si/download/'+match[1]+'.torrent')
        if not candidates and detail.startswith(('http://','https://')):
            from bs4 import BeautifulSoup
            page=download(detail,source,item,api)
            soup=BeautifulSoup(page,'html.parser')
            for anchor in soup.select('a[href]'):
                url=urljoin(detail,anchor['href'])
                if url.startswith(('http://','https://')) and api.torrent_specific_http_url(url):candidates.append(url)
        if not candidates:raise ValueError('No .torrent file exposed by this source; magnet metadata requires reachable peers.')
        error=None
        for url in list(dict.fromkeys(candidates))[:3]:
            try:
                data=download(url,source,item,api);validate(data,item,api);break
            except Exception as exc:error=exc
        else:raise ValueError(str(error))
    digest=validate(data,item,api)
    folder=Path(root)/'metadata_cache';folder.mkdir(exist_ok=True,parents=True)
    target=folder/(digest+'.torrent');temporary=folder/(digest+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_bytes(data);os.replace(temporary,target)
    return str(target)

class PreparationWorker(QThread):
    result=Signal(str,str,str)
    def __init__(self,batch,root,api,parent=None,profile=None):
        super().__init__(parent);self.batch,self.root,self.api=batch,root,api;self.profile=profile
    def peer_metadata(self,item):
        if not self.profile or not item.get('link','').startswith('magnet:'):return False
        client=None
        try:
            p=self.profile
            client=self.api.qbittorrentapi.Client(host=p.get('host','127.0.0.1'),port=int(p.get('port',8080)),username=p.get('username',''),password=p.get('password',''),REQUESTS_ARGS={'timeout':(5,10)})
            client.auth_log_in()
            version=tuple(int(n) for n in str(client.app_web_api_version()).split('.'))
            if version<(2,11,9):return False
            # This API fetches metadata without adding or downloading content.
            for _ in range(6):
                if self.isInterruptionRequested():return False
                if client.torrents_fetch_metadata(source=item['link']):return True
                for _ in range(25):
                    if self.isInterruptionRequested():return False
                    self.msleep(100)
        except Exception:return False
        finally:
            if client:
                try:client.close()
                except Exception:pass
        return False
    def run(self):
        for item,source in self.batch:
            if self.isInterruptionRequested():break
            link=item.get('link') or item.get('local_torrent_path','')
            try:self.result.emit(link,prepare(item,source,self.root,self.api),'')
            except Exception as exc:
                if self.peer_metadata(item):self.result.emit(link,'client-ready','')
                else:self.result.emit(link,'',str(exc))

class MetadataManager(QObject):
    def __init__(self,owner,api):
        super().__init__(owner);self.owner,self.api=owner,api
        for item in owner.cart:
            if item.get('cart_status') in ('Preparing metadata','Metadata ready in qBittorrent'):
                item.pop('metadata_checked_link',None)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.start)
    def request(self):
        if self.api.BACKGROUND_SERVICES:self.timer.start(100)
    def start(self):
        owner=self.owner
        if getattr(owner,'metadata_worker',None) and owner.metadata_worker.isRunning():return
        if getattr(owner,'cart_sender',None) and owner.cart_sender.isRunning():return
        from book_downloads import is_book_page
        batch=[]
        for item in owner.cart:
            key=item.get('link') or item.get('local_torrent_path')
            if is_book_page(item) or item.get('metadata_checked_link')==key:continue
            if not item.get('link') and not item.get('local_torrent_path'):continue
            item['metadata_checked_link']=key
            item['cart_status']='Preparing metadata'
            batch.append((dict(item),dict(owner.source_config_for_result(item))))
            if len(batch)==8:break
        if not batch:return
        if getattr(owner,'metadata_worker',None):owner.metadata_worker.deleteLater()
        profile=dict(owner.config.get('qbittorrent',{})) if owner.config.get('torrent_client','qBittorrent')=='qBittorrent' else None
        owner.metadata_worker=PreparationWorker(batch,self.api.APP_DIR,self.api,owner,profile)
        owner.metadata_worker.result.connect(self.result)
        owner.metadata_worker.finished.connect(self.request)
        owner.metadata_worker.start();owner.cart_table.viewport().update()
    def result(self,link,path,error):
        for item in self.owner.cart:
            if (item.get('link') or item.get('local_torrent_path',''))!=link:continue
            if path and path!='client-ready':item['metadata_path']=path
            if item.get('cart_status') not in ('Sending','Sent','Failed'):
                item['cart_status']=('Metadata ready in qBittorrent' if path=='client-ready' else 'Metadata ready') if path else 'Metadata unavailable'
                item['last_error']=error
        self.api.save_json(self.api.CART_FILE,self.owner.cart)
        self.owner.cart_table.viewport().update()
