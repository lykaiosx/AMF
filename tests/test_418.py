import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'payload'))
import app
from PySide6.QtWidgets import QApplication,QComboBox,QLabel
qt=QApplication([])
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory)
 app.APP_DIR,app.CONFIG_FILE,app.CART_FILE,app.PID_FILE=root,root/'config.json',root/'cart.json',root/'amf.pid'
 app.migrate_previous_state=lambda:None
 window=app.AnimeDownloader();window.show()
 choices=window.findChildren(QComboBox,'appearanceChoice');choice=choices[0]
 window.tabs.setCurrentIndex(window.tabs.count()-1)
 for theme in ['Dark','Light']:
  choice.setCurrentText(theme);window.apply_theme();qt.processEvents()
  icon=window.windowIcon().pixmap(32,32).toImage()
  pixels=[icon.pixelColor(x,y) for x in range(32) for y in range(32) if icon.pixelColor(x,y).alpha()>240]
  assert pixels and all(c.red()>240 for c in pixels)
  logo=window.findChild(QLabel,'brandIcon').pixmap().toImage()
  assert logo.pixelColor(logo.width()//2,logo.height()//2).red()==(0 if theme=='Light' else 255)
  choice.showPopup();qt.processEvents()
  view=choice.view();rect=view.visualRect(view.model().index(0,0))
  assert rect.left()==0 and rect.width()==view.viewport().width(),(rect,view.viewport().rect())
  if len(sys.argv)>1:view.grab().save(str(Path(sys.argv[1])/('418-'+theme+'.png')))
  choice.hidePopup()
 window.close()
print('PASS white title-bar icon, theme-specific header logo, full-width dropdown rows')
