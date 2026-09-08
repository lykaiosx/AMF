import sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'payload'))
import app
from book_downloads import is_book_page
from PySide6.QtWidgets import QApplication
qt=QApplication([])
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory)
 app.APP_DIR,app.CONFIG_FILE,app.CART_FILE,app.PID_FILE=root,root/'config.json',root/'cart.json',root/'amf.pid'
 app.migrate_previous_state=lambda:None
 window=app.AnimeDownloader()
 source=next(s for s in window.config['sources'] if s.get('builtin_id')=='annas_archive');source['enabled']=True
 book=dict(source=source['name'],title='Example book',link='https://annas-archive.gl/md5/'+'a'*32,link_usable=False,type='Books',destination_custom=True)
 window.search_results=[book];window.apply_result_filters()
 window.results_table.cellWidget(0,0).setChecked(True)
 with patch.object(app,'resolve_result_download_link',side_effect=AssertionError('Must not scrape a book as a torrent')):
  window.add_selected_to_cart()
 assert len(window.cart)==1 and window.cart[0]['cart_status']=='Open book page'
 assert window.cart[0]['save_path']==window.config['books_path'],window.cart
 with patch.object(app.QMessageBox,'information'):
  window.send_cart_to_qbittorrent()
 assert not getattr(window,'cart_sender',None)
 window.cart_table.selectRow(0)
 with patch('PySide6.QtGui.QDesktopServices.openUrl',return_value=True) as opened:
  window.open_selected_book_page();assert opened.call_count==1
 assert not is_book_page(dict(link='magnet:?xt=urn:btih:'+'a'*40))
 assert not is_book_page(dict(link='https://annas-archive.gl/example.torrent'))
 window.cart.append(dict(title='Example torrent',link='magnet:?xt=urn:btih:'+'a'*40,save_path=str(root),save_path_custom=True))
 with patch.object(app.QMessageBox,'information'), patch('cart_sender.CartSender.start'):
  window.send_cart_to_qbittorrent()
 assert len(window.cart_sender.batch)==1 and not is_book_page(window.cart_sender.batch[0][0])
 assert len(window._sending_items)==1 and len(window.cart)==2
 window.close()
print('PASS book page cart, Books routing, browser action and no torrent submission')
