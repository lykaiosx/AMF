import sys,tempfile,ctypes
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'payload'))
import app
from ui_controls import ChoiceBox,PlainCellDelegate
from folder_setup import FolderSetup,setup_folders,FIELDS
from PySide6.QtWidgets import QApplication,QPushButton,QGroupBox,QDialog,QTableWidget
from PySide6.QtCore import QTimer,Qt
qt=QApplication([])
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory)
 app.APP_DIR,app.CONFIG_FILE,app.CART_FILE,app.PID_FILE=root,root/'config.json',root/'cart.json',root/'amf.pid'
 app.migrate_previous_state=lambda:None
 window=app.AnimeDownloader();window.show();qt.processEvents()
 assert not any(s.get('builtin_id')=='annas_archive' for s in window.config['sources'])
 assert not any('Anna' in b.text() for b in window.findChildren(QPushButton))
 assert any('Read EZTV' in b.text() for b in window.findChildren(QPushButton))
 assert not any(g.title()=='Routing' for g in window.findChildren(QGroupBox))
 assert isinstance(window.results_table.itemDelegate(),PlainCellDelegate)
 choices=window.findChildren(ChoiceBox)
 for choice in choices:
  assert choice.view().objectName()=='choicePopup'
 theme=next(c for c in choices if c.findText('High Contrast')>=0)
 from native_icons import _cache
 for name in ['Light','Dark','High Contrast']:
  theme.setCurrentText(name);qt.processEvents()
  if sys.platform=='win32':
   from ctypes import wintypes
   user=ctypes.WinDLL('user32');user.SendMessageW.argtypes=[wintypes.HWND,wintypes.UINT,ctypes.c_size_t,ctypes.c_ssize_t];user.SendMessageW.restype=ctypes.c_ssize_t
   assert user.SendMessageW(int(window.winId()),0x7f,0,0)==_cache[('AMF.ico',32)]
   assert user.SendMessageW(int(window.winId()),0x7f,1,0)==_cache[('AMF-light.ico' if name=='Light' else 'AMF.ico',48)]
 dialog=FolderSetup(window);assert len(dialog.fields)==7
 chosen={key:str(root/label) for key,label in FIELDS}
 with patch('folder_setup.FolderSetup.exec',return_value=QDialog.Accepted),patch('folder_setup.FolderSetup.values',return_value=chosen):
  setup_folders(window,lambda:None)
 assert all(window.config[k]==v for k,v in chosen.items())
 assert window.extra_path_edits['books_path'].text()==chosen['books_path']
 window.cart=[dict(title='Example',type='Movie',link='magnet:?xt=urn:btih:'+'a'*40)];window.refresh_cart()
 with patch.object(app.QFileDialog,'getExistingDirectory',return_value=str(root/'Custom')):
  window.cart_cell_double_clicked(0,9)
 assert window.cart[0]['save_path_custom'] and window.cart[0]['save_path']==str(root/'Custom')
 delegate=window.cart_table.itemDelegateForColumn(3);index=window.cart_model.index(0,3)
 from PySide6.QtWidgets import QStyleOptionViewItem
 editor=delegate.createEditor(window.cart_table,QStyleOptionViewItem(),index)
 assert editor.findText('Custom destination…')>=0
 editor.setCurrentText('Custom destination…')
 with patch.object(app.QFileDialog,'getExistingDirectory',return_value=''):
  delegate.setModelData(editor,window.cart_model,index);qt.processEvents()
 assert window.cart[0]['save_path']==str(root/'Custom')
 window.close()
print('PASS folder setup, removed source/panel, native icons, dropdowns and cart folder picker')

