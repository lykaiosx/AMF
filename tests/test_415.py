import sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'payload'))
import app
from fitgirl_provider import parse_index
from transfer_status import explain
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
qt=QApplication([])
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    app.APP_DIR,app.CONFIG_FILE,app.CART_FILE,app.PID_FILE=root,root/'config.json',root/'cart.json',root/'amf.pid'
    app.migrate_previous_state=lambda:None
    window=app.AnimeDownloader()
    window.show()
    qt.processEvents()
    logo=window.findChild(QLabel,'brandIcon').pixmap()
    assert logo.width()==round(42*window.devicePixelRatioF())
    assert logo.devicePixelRatio()==window.devicePixelRatioF()
    assert sum(s.get('builtin_id')=='fitgirl' for s in window.config['sources'])==1
    assert not app.ensure_builtin_default_sources(window.config)
    source_name=next(s['name'] for s in window.config['sources'] if s.get('builtin_id')=='yts')
    window.search_results=[dict(source=source_name,title='Selection example',link='magnet:?xt=urn:btih:'+'ab'*20)]
    window.apply_result_filters()
    table=window.results_table
    check=table.cellWidget(0,0)
    position=table.visualItemRect(table.item(0,1)).center()
    QTest.mouseDClick(table.viewport(),Qt.LeftButton,pos=position)
    assert check.isChecked()
    QTest.mouseDClick(table.viewport(),Qt.LeftButton,pos=position)
    assert not check.isChecked()
    check.setChecked(True)
    table.selectRow(0)
    qt.processEvents()
    assert 'background: #22c55e' in window.styleSheet()
    assert 'selection-background-color: #293548' in window.styleSheet()
    if len(sys.argv)>1: window.grab().save(str(Path(sys.argv[1])/'415-selection.png'))
    window.close()
assert explain(dict(state='stalledDL',num_seeds=0)).startswith('Waiting for seeds')
assert explain(dict(state='metaDL')).startswith('Waiting for metadata')
assert explain(dict(state='stoppedDL')).startswith('Stopped')
assert explain(dict(state='stalledUP',progress=1))=='Download complete'
assert parse_index('<div class="entry-content"><ul class="lcp_catlist"><li><a href="/example/">Example Game</a></li></ul></div>')==[('Example Game','https://fitgirl-repacks.site/example/')]
print('PASS: high-DPI pixmap, checked-row contrast, double-click toggles, default-source migration and download-state explanations.')
