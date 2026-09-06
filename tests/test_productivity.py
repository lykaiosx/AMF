import sys, json, tempfile, hashlib, base64
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'payload'))
import app
from reliability import *
from update_manager import release_asset, version_tuple, UpdateWorker
from PySide6.QtWidgets import QApplication, QPushButton, QInputDialog, QMessageBox, QComboBox
qt=QApplication([])
with tempfile.TemporaryDirectory(prefix='amf-productivity-') as directory:
    root=Path(directory)
    app.APP_DIR,app.CONFIG_FILE,app.CART_FILE,app.PID_FILE=root,root/'config.json',root/'cart.json',root/'amf.pid'
    app.migrate_previous_state=lambda:None
    store=CredentialStore()
    targets=[]
    secret='synthetic-AMF-test-秘密'
    try:
        original={'qbittorrent':{'password':secret},'client_profiles':{'Deluge':{'password':secret+'2'}}}
        secured=protect_config(original,app.CONFIG_FILE,store)
        targets=[secured['qbittorrent']['password']['__amf_credential__'],secured['client_profiles']['Deluge']['password']['__amf_credential__']]
        assert secret not in json.dumps(secured)
        assert hydrate_config(secured,store)==original
        app.CONFIG_FILE.write_text(json.dumps(original),encoding='utf-8')
        window=app.AnimeDownloader()
        assert window.qb_password.text()==secret
        assert secret not in app.CONFIG_FILE.read_text()
        assert window.tabs.count()==5
        assert window.tabs.tabText(4)=='History'
        assert not window._update_worker, 'Tests unexpectedly contacted GitHub'
        print('PASS: real Windows Credential Manager round trip; plaintext migration; history/settings UI.')

        raw=bytes.fromhex('ab'*20)
        a={'source':'Site A','title':'Release A','link':'magnet:?xt=urn:btih:'+raw.hex()+'&dn=A'}
        b={'source':'Site B','title':'Different title','link':'magnet:?dn=B&xt=urn:btih:'+base64.b32encode(raw).decode()+'&tr=test'}
        merged=merge_duplicates([a,b,{'source':'Site C','title':'Different','link':'https://example.com/book'}])
        assert len(merged)==2 and merged[0]['available_sources']==['Site A','Site B']
        assert app.canonical_url_key(a['link'])==app.canonical_url_key(b['link'])
        assert window.add_import_items([a,b])==(1,1)
        window.search_finished([a,b],{'Site A':('OK','1 result'),'Site B':('OK','1 result')})
        assert len(window.search_results)==1
        window.source_filter.setCurrentIndex(window.source_filter.findData('Site B'))
        assert window.results_table.rowCount()==1
        print('PASS: hex/base32 magnet duplicates grouped across sources and excluded from cart imports; alternate source filtering.')

        def click(text):
            next(button for button in window.findChildren(QPushButton) if button.text()==text).click()
        window.search_input.setText('saved title')
        window.min_seeders.setValue(30)
        with patch.object(QInputDialog,'getText',return_value=('Test preset',True)): click('Save Search')
        window.search_input.clear()
        window.min_seeders.setValue(0)
        click('Load Search')
        assert window.search_input.text()=='saved title' and window.min_seeders.value()==30
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes): click('Delete Saved Search')
        assert not window.config['saved_searches']
        item=dict(a,_queue_id='receipt-test',save_path=r'D:\Movies')
        record_history(root,item,'Deluge','Sent')
        record_history(root,item,'Deluge','Sent')
        assert len(history_rows(root,'Release A'))==1
        assert torrent_identity(item) in previously_sent(root)
        window.refresh_history()
        backup=root/'cart_backups'
        backup.mkdir(exist_ok=True)
        unsent={'title':'Recover this','link':'magnet:?xt=urn:btih:'+'cd'*20,'type':'Series'}
        (backup/'cart-restore-test.json').write_text(json.dumps([a,unsent]),encoding='utf-8')
        with patch.object(QInputDialog,'getItem',return_value=('cart-restore-test.json',True)), patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
            click('Restore Cart Backup')
        assert len(window.cart)==1 and window.cart[0]['title']=='Recover this'
        (root/'startup-error.log').write_text('RuntimeError '+secret+' https://host/?password='+secret,encoding='utf-8')
        report=json.dumps(diagnostic_report(root,'4.12',{'private source':('ERROR',secret+' timeout')}))
        assert secret not in report and 'private source' not in report and str(root) not in report
        assert error_guidance('403 Cloudflare')[0]=='Browser verification required'
        assert error_guidance('401 password rejected')[0]=='Sign-in failed'
        print('PASS: saved-search CRUD, searchable/idempotent history, duplicate-history lookup and allowlisted diagnostics.')

        data=b'MZ synthetic test installer (never executed)'
        asset={'name':'AMF-4.13-Setup.exe','browser_download_url':'https://github.com/lykaiosx/AMF/releases/download/v4.13/AMF-4.13-Setup.exe',
               'digest':'sha256:'+hashlib.sha256(data).hexdigest(),'size':len(data)}
        release={'tag_name':'v4.13','assets':[asset]}
        assert version_tuple('4.10')>version_tuple('4.9')
        assert release_asset(release,'4.12')==asset
        assert release_asset(release,'4.13') is None
        try: release_asset({'tag_name':'4.13','assets':[dict(asset,browser_download_url='https://evil.example/x.exe')]},'4.12')
        except ValueError: pass
        else: raise AssertionError('Untrusted updater URL accepted')
        class Response:
            url='https://release-assets.githubusercontent.com/test'
            def raise_for_status(self): pass
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def iter_content(self,*args): yield data
        with patch('update_manager.requests.get',return_value=Response()):
            worker=UpdateWorker('4.12',root/'updates',asset)
            results=[]
            worker.result.connect(results.append)
            worker.run()
            assert Path(results[0]['path']).read_bytes()==data
            damaged=UpdateWorker('4.12',root/'bad',dict(asset,digest='sha256:'+'0'*64))
            errors=[]
            damaged.error.connect(errors.append)
            damaged.run()
            assert errors and not list((root/'bad').glob('*'))
            cancelled=UpdateWorker('4.12',root/'cancelled',asset)
            cancelled.isInterruptionRequested=lambda:True
            cancelled.run()
            assert not list((root/'cancelled').glob('*'))
        print('PASS: version ordering, trusted update origin, verified download and damaged-download removal; no installer executed.')
        window.close()
        assert not (root/'session-active.json').exists()
        (root/'session-active.json').write_text('{}')
        recovered=app.AnimeDownloader()
        from PySide6.QtWidgets import QLabel
        assert any('interrupted session' in label.text() for label in recovered.findChildren(QLabel))
        recovered.close()
        app.CART_FILE.write_text('{broken',encoding='utf-8')
        corrupted=app.AnimeDownloader()
        assert any('could not be read' in label.text() for label in corrupted.findChildren(QLabel))
        assert list((root/'cart_backups').glob('corrupt-cart-*.json'))
        corrupted.close()
        print('PASS: clean-close marker removal and interrupted-session recovery notice.')
    finally:
        for target in targets: store.delete(target)



