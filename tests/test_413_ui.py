"""Regression checks for theme, layout, source toggles and YTS releases."""
import sys, tempfile, json
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'payload'))
import app
from PySide6.QtWidgets import QApplication, QLabel, QComboBox, QPushButton
from PySide6.QtCore import QPoint
from yts_provider import parse_yts, fetch_yts

qt = QApplication([])
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    app.APP_DIR, app.CONFIG_FILE, app.CART_FILE, app.PID_FILE = root, root/'config.json', root/'cart.json', root/'amf.pid'
    app.migrate_previous_state = lambda: None
    window = app.AnimeDownloader()
    assert [window.tabs.tabText(i) for i in range(5)] == ['Search', 'Cart', 'Sources', 'History', 'Settings']
    window.tabs.setCurrentIndex(window.tabs.count()-1)
    assert window.tabs.currentIndex() == 4
    window.show()
    logo_keys = []
    for theme in ('Dark', 'Light', 'High Contrast'):
        window.findChildren(QComboBox, 'appearanceChoice')[0].setCurrentText(theme)
        window.config['appearance'] = {'theme': theme, 'text_size': 13, 'density': 1.0}
        window.apply_theme()
        for width, height in ((900, 650), (1380, 900)):
            window.resize(width, height)
            window.adapt_layout()
            qt.processEvents()
            sheet = window.styleSheet()
            assert 'QLabel, QCheckBox { background: transparent; }' in sheet
            accent = app.PALETTES[theme]['accent']
            foreground = '#000000' if theme == 'High Contrast' else '#ffffff'
            assert f'color: {foreground}; background: {accent}' in sheet
            badge = window.findChild(QLabel, 'versionBadge')
            assert badge.text() == app.APP_VERSION and badge.width() >= badge.fontMetrics().horizontalAdvance(badge.text())
            edits = [window.games_path_edit, window.movies_path_edit, window.series_path_edit,
                     *window.extra_path_edits.values()]
            positions = [e.mapTo(window, QPoint(0, 0)).x() for e in edits]
            assert max(positions) - min(positions) <= 1, positions
            for combo in window.findChildren(QComboBox, 'appearanceChoice'):
                label = combo.parentWidget().findChild(QLabel)
                assert abs(label.geometry().center().y() - combo.geometry().center().y()) <= 1
                assert combo.width() < 200, combo.width()
            if len(sys.argv) > 1:
                window.grab().save(str(Path(sys.argv[1]) / f'413-{theme.replace(" ", "-")}-{width}.png'))
        logo_image = window.findChild(QLabel, 'brandIcon').pixmap().toImage()
        logo_keys.append(logo_image.pixelColor(logo_image.width()//2, logo_image.height()//2).name())
    assert logo_keys[0] == '#ffffff' and logo_keys[1] == '#000000', logo_keys

    window.config['sources'] = [{'name': 'A', 'enabled': True}, {'name': 'B', 'enabled': False}]
    window.source_status = {'A': ('OK', ''), 'B': ('OK', ''), 'Removed': ('OK', '')}
    window.search_results = [dict(source='A', title='A', available_sources=['A', 'B']), dict(source='B', title='B')]
    window.refresh_sources()
    def names(): return [window.source_filter.itemData(i) for i in range(window.source_filter.count())]
    assert names() == ['', 'A']
    window.apply_result_filters()
    assert window.results_table.rowCount() == 1
    window.sources_table.cellWidget(1, 0).setChecked(True)
    assert names() == ['', 'A', 'B'] and window.results_table.rowCount() == 2
    window.source_filter.setCurrentIndex(2)
    window.sources_table.cellWidget(1, 0).setChecked(False)
    assert names() == ['', 'A'] and window.source_filter.currentData() == ''
    assert window.total_results_label.text() == '1 total results'
    window.close()

source = {'name': 'yts.gg', 'url': 'https://yts.gg/search-movies?query={query}'}
movie = {'title_long': 'Example (2024)', 'language': 'en', 'torrents': [
    {'hash': 'ab'*20, 'quality': '1080p', 'size_bytes': 123, 'seeds': 9},
    {'hash': 'cd'*20, 'quality': '2160p', 'size_bytes': 456, 'peers': 3},
    {'hash': 'invalid'}]}
payload = {'status': 'ok', 'data': {'movie_count': 1, 'movies': [movie]}}
rows = parse_yts(payload, source)
assert len(rows) == 2 and rows[0]['resolution'] == '1080p' and rows[1]['size_bytes'] == 456
assert all(row['type'] == 'Movie' and row['link_usable'] for row in rows)
assert parse_yts({'status': 'ok', 'data': {'movie_count': 0}}, source) == []
with patch('yts_provider.requests.get', return_value=Mock(json=lambda: payload)) as get:
    rows, status = fetch_yts(source, 'War & Peace')
    assert get.call_args.args == ('https://yts.gg/api/v2/list_movies.json',)
    assert get.call_args.kwargs['params']['query_term'] == 'War & Peace'
    assert '1 of 1 matching movies' in status
print('PASS: theme/resize contrast, logo variants, tab navigation, aligned controls, live source toggles and YTS parsing.')
