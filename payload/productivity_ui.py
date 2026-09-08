"""History, presets, recovery and explicit update installation controls."""
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLineEdit,QLabel,QComboBox,
    QInputDialog,QMessageBox,QFileDialog,QCheckBox,QTableWidget,QTableWidgetItem,QAbstractItemView,QGroupBox)
from reliability import history_rows, history_entries, history_download, diagnostic_report, error_guidance, previously_sent, torrent_identity
from cart_sender import replay_receipts
from scalable_ui import FlowLayout
from usability_core import PALETTES, validate_theme, check_destinations, portable_settings
from update_manager import UpdateWorker


def install_productivity(owner, api):
    owner._update_worker = None
    owner._update_asset = None
    owner._update_path = None
    settings = owner.settings_tab.layout()
    appearance_box = QGroupBox('Appearance')
    appearance_layout = FlowLayout(appearance_box)
    appearance_layout.setContentsMargins(12, 8, 12, 10)
    theme_choice = QComboBox(); theme_choice.addItems(list(PALETTES))
    theme_choice.setCurrentText(owner.config.get('appearance', {}).get('theme', 'Dark'))
    text_size = QComboBox(); text_size.addItems(['Small (11)', 'Normal (13)', 'Large (15)', 'Extra large (17)'])
    text_size.setCurrentText({'11':'Small (11)','13':'Normal (13)','15':'Large (15)','17':'Extra large (17)'}.get(str(owner.config.get('appearance',{}).get('text_size',13)), 'Normal (13)'))
    density = QComboBox(); density.addItems(['Compact', 'Comfortable']); density.setCurrentText('Compact' if owner.config.get('appearance',{}).get('density',1.0)<.95 else 'Comfortable')
    for caption, choice in [('Theme', theme_choice), ('Text size', text_size), ('Spacing', density)]:
        pair = QWidget()
        pair.setObjectName('appearancePair')
        pair.setStyleSheet('QWidget#appearancePair { background: transparent; }')
        row = QHBoxLayout(pair)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        label = QLabel(caption)
        label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        choice.setObjectName('appearanceChoice')
        from PySide6.QtWidgets import QListView, QStyledItemDelegate
        popup = QListView(choice)
        popup.setObjectName('appearancePopup')
        popup.setSpacing(0)
        popup.setItemDelegate(QStyledItemDelegate(popup))
        choice.setView(popup)
        choice.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        row.addWidget(label, 0, Qt.AlignVCenter)
        row.addWidget(choice, 0, Qt.AlignVCenter)
        appearance_layout.addWidget(pair)
    def update_appearance():
        sizes={'Small (11)':11,'Normal (13)':13,'Large (15)':15,'Extra large (17)':17}
        owner.config['appearance']={'theme':theme_choice.currentText(),'text_size':sizes[text_size.currentText()], 'density':.85 if density.currentText()=='Compact' else 1.0}
        persist(); owner.apply_theme()
    theme_choice.currentTextChanged.connect(lambda _:update_appearance()); text_size.currentTextChanged.connect(lambda _:update_appearance()); density.currentTextChanged.connect(lambda _:update_appearance())
    settings.insertWidget(1, appearance_box)
    owner.apply_theme()
    tools = FlowLayout()
    status = QLabel('Passwords are stored in Windows Credential Manager.')
    status.setWordWrap(True)
    settings.addWidget(status)
    def check_transfers():
        if owner.config.get('torrent_client', 'qBittorrent') != 'qBittorrent':
            QMessageBox.information(owner, 'Download status', 'Open your selected torrent client to inspect its download and tracker status.')
            return
        if getattr(owner, '_transfer_status_worker', None) is not None and owner._transfer_status_worker.isRunning():
            return
        from transfer_status import TransferStatusWorker
        owner._transfer_status_worker = TransferStatusWorker(owner.config.get('qbittorrent', {}), owner)
        owner._transfer_status_worker.report.connect(lambda text: QMessageBox.information(owner, 'qBittorrent download status', text))
        owner._transfer_status_worker.start()
    transfer_check = QPushButton('Check Download Status')
    transfer_check.clicked.connect(check_transfers)
    settings.addWidget(transfer_check, 0, Qt.AlignLeft)

    def persist(): api.save_json(api.CONFIG_FILE, owner.config)
    def button(layout, text, handler):
        item = QPushButton(text)
        item.clicked.connect(handler)
        layout.addWidget(item)
        return item

    # Search presets contain filters and enabled source names, never passwords.
    presets = owner.config.setdefault('saved_searches', {})
    preset_row = FlowLayout()
    preset_choice = QComboBox()
    preset_row.addWidget(preset_choice)
    def choices():
        preset_choice.clear()
        preset_choice.addItems(['Saved searches…'] + sorted(presets))
    choices()
    def save_preset():
        name, ok = QInputDialog.getText(owner, 'Save Search', 'Name for this search and its filters:')
        name = name.strip()
        if not ok or not name: return
        if name in presets and QMessageBox.question(owner,'Replace Search','Replace this saved search?') != QMessageBox.Yes: return
        presets[name] = dict(query=owner.search_input.text(), scope=owner.scope_filter.currentText(),
            resolution=owner.resolution_filter.currentText(), min_seeds=owner.min_seeders.value(), max_gb=owner.max_size_gb.value(),
            sources=[s['name'] for s in owner.config.get('sources',[]) if s.get('enabled')])
        persist()
        choices()
        preset_choice.setCurrentText(name)
    def load_preset():
        preset = presets.get(preset_choice.currentText())
        if not preset: return
        owner.search_input.setText(preset.get('query',''))
        owner.scope_filter.setCurrentText(preset.get('scope','All Releases'))
        owner.resolution_filter.setCurrentText(preset.get('resolution','Any'))
        owner.min_seeders.setValue(preset.get('min_seeds',0))
        owner.max_size_gb.setValue(preset.get('max_gb',0))
        for source in owner.config.get('sources',[]): source['enabled'] = source['name'] in preset.get('sources',[])
        persist()
        owner.refresh_sources()
        owner.toast.show_message('Saved search loaded. Press Search when ready.',4000)
    def delete_preset():
        name = preset_choice.currentText()
        if name in presets and QMessageBox.question(owner,'Delete Saved Search',f'Delete {name}?') == QMessageBox.Yes:
            del presets[name]
            persist()
            choices()
    button(preset_row,'Save Search',save_preset)
    button(preset_row,'Load Search',load_preset)
    button(preset_row,'Delete Saved Search',delete_preset)
    owner.anime_tab.layout().insertLayout(2,preset_row)

    history = QWidget()
    history_layout = QVBoxLayout(history)
    history_note = QLabel('Sent means accepted by the torrent client. Use Settings → Check Download Status to inspect downloading or stalled items.')
    history_note.setWordWrap(True)
    history_layout.addWidget(history_note)
    find = QLineEdit()
    find.setPlaceholderText('Search history by title or client…')
    history_layout.addWidget(find)
    from selection_ui import ToggleRowTable
    table = ToggleRowTable(0,6)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setHorizontalHeaderLabels(['Time (UTC)','Title','Client','Save Location','Status','Details'])
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setColumnWidth(1,320)
    table.setColumnWidth(3,250)
    table.setColumnWidth(5,300)
    history_layout.addWidget(table,1)
    history_controls = FlowLayout()
    history_layout.addLayout(history_controls)
    page = [0]
    page_label = QLabel()
    def refresh_history():
        entries = history_entries(api.APP_DIR,find.text(),page[0]*200)
        rows = [[entry.get(key) for key in ('time','title','client','destination','status','error')] for entry in entries]
        table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate(row):
                item=QTableWidgetItem(str(value or ''))
                item.setToolTip(str(value or ''))
                item.setData(Qt.UserRole, entries[r])
                table.setItem(r,c,item)
        page_label.setText(f'Page {page[0]+1} • {len(rows)} records')
        previous.setEnabled(page[0]>0)
        following.setEnabled(len(rows)==200)
    def turn_page(delta):
        page[0]=max(0,page[0]+delta)
        refresh_history()
    previous=button(history_controls,'Previous',lambda:turn_page(-1))
    following=button(history_controls,'Next',lambda:turn_page(1))
    button(history_controls,'Refresh History',refresh_history)
    history_status = QLabel('')
    history_status.setWordWrap(True)
    history_layout.addWidget(history_status)
    def resend_history():
        if any(getattr(owner, key, None) is not None and getattr(owner, key).isRunning() for key in ('history_sender','cart_sender')):
            history_status.setText('Wait for the current send to finish.')
            return
        indexes = table.selectionModel().selectedRows()
        if not indexes:
            history_status.setText('Select a history row first.')
            return
        import uuid
        from cart_sender import CartSender
        batch, seen = [], set()
        try:
            for index in indexes:
                entry = table.item(index.row(),0).data(Qt.UserRole)
                item = history_download(entry)
                identity = torrent_identity(item)
                if identity in seen: continue
                seen.add(identity)
                item['_queue_id'] = uuid.uuid4().hex
                source = owner.source_config_for_result(item)
                if '[yts]' in item['title'].lower():
                    source = next((s for s in owner.config.get('sources',[]) if api.source_provider_identity(s)=='yts'), {'builtin_id':'yts','url':'https://yts.gg'})
                batch.append((item, dict(source)))
        except Exception as exc:
            history_status.setText(str(exc))
            return
        profile = dict(owner.config.get('qbittorrent',{}))
        def client_factory():
            return api.qbittorrentapi.Client(host=profile.get('host','127.0.0.1'),port=int(profile.get('port',8080)),
                username=profile.get('username',''),password=profile.get('password',''),REQUESTS_ARGS={'timeout':(10,30)})
        owner.history_sender = CartSender(client_factory, batch, api.APP_DIR/'history-resend-receipts.jsonl',api,owner)
        outcomes=[]
        fatal=[]
        def progress(key,state,error):
            if state in ('Sent','Failed'): outcomes.append((state,error))
            history_status.setText(f'{len(outcomes)} of {len(batch)} processed. '+(error or state))
        def finished():
            resend.setEnabled(True)
            refresh_history()
            failed=[error for state,error in outcomes if state=='Failed']
            history_status.setText(f'{sum(state=="Sent" for state,_ in outcomes)} added to qBittorrent.'+ (' '+(failed+fatal)[0] if failed or fatal else ''))
        owner.history_sender.progress.connect(progress)
        owner.history_sender.failed.connect(lambda error: (fatal.append(error), history_status.setText(error)))
        owner.history_sender.finished.connect(finished)
        resend.setEnabled(False)
        history_status.setText('Adding selected history entries to qBittorrent…')
        owner.history_sender.start()
    resend=button(history_controls,'Add to qBittorrent',resend_history)
    history_controls.addWidget(page_label)
    search_timer=QTimer(owner)
    search_timer.setSingleShot(True)
    search_timer.timeout.connect(lambda:turn_page(-page[0]))
    find.textChanged.connect(lambda:search_timer.start(200))
    owner.tabs.insertTab(3,history,'History')
    owner.tabs.currentChanged.connect(lambda i: refresh_history() if owner.tabs.widget(i) is history else None)
    owner.refresh_history=refresh_history
    refresh_history()

    def export_diagnostics():
        path,_=QFileDialog.getSaveFileName(owner,'Export Private Diagnostics','AMF-diagnostics.json','JSON (*.json)')
        if path:
            Path(path).write_text(json.dumps(diagnostic_report(api.APP_DIR,api.APP_VERSION,owner.source_status),indent=2),encoding='utf-8')
            owner.toast.show_message('Diagnostic report saved without credentials, titles, URLs or local paths.',6000)
    def check_folders():
        errors,note=check_destinations(owner.cart, __import__('usability_core').client_is_remote(owner.config))
        if errors: QMessageBox.warning(owner,'Download folders','\n'.join(errors)+'\n\n'+note)
        else: QMessageBox.information(owner,'Download folders','All current destinations are available and writable.\n\n'+note)
    def restore_backup():
        worker=getattr(owner,'cart_sender',None)
        if worker and worker.isRunning():
            QMessageBox.information(owner,'Recovery','Cancel sending and wait for the current request before restoring a cart.')
            return
        backups=sorted((api.APP_DIR/'cart_backups').glob('cart-*.json'),reverse=True)
        if not backups:
            QMessageBox.information(owner,'Recovery','No cart backups are available yet.')
            return
        name,ok=QInputDialog.getItem(owner,'Restore Cart','Choose a saved cart:',[p.name for p in backups],0,False)
        if not ok: return
        try:
            restored=json.loads(next(p for p in backups if p.name==name).read_text(encoding='utf-8-sig'))
            if not isinstance(restored,list) or not all(isinstance(x,dict) for x in restored): raise ValueError('Invalid cart backup')
            sent=previously_sent(api.APP_DIR)
            restored=[item for item in replay_receipts(restored,api.APP_DIR/'sent-receipts.jsonl') if torrent_identity(item) not in sent]
            if QMessageBox.question(owner,'Restore Cart',f'Restore {len(restored)} unsent items? Your current cart will be backed up first.') != QMessageBox.Yes: return
            owner.backup_cart_snapshot('before-restore')
            owner.cart=restored
            owner.save_cart()
            owner.refresh_cart()
            status.setText('Cart restored. Previously confirmed sends were excluded.')
        except Exception as exc: QMessageBox.warning(owner,'Recovery',str(exc))
    button(tools,'Restore Cart Backup',restore_backup)
    button(tools,'Export Diagnostics',export_diagnostics)
    button(tools,'Check Download Folders',check_folders)

    def source_help():
        lines=[]
        for name,(state,message) in owner.source_status.items():
            category,action=error_guidance(message)
            healthy=state=='OK' and category!='No matching results'
            lines.append(f'{name}: {"Connected" if healthy else category}\n{message}\n{action if not healthy else ""}')
        dialog=QMessageBox(owner)
        dialog.setWindowTitle('Source Health')
        dialog.setText('Source health and next steps')
        dialog.setDetailedText('\n\n'.join(lines) or 'Run a search or Test All Sources first.')
        retry=dialog.addButton('Retry Search',QMessageBox.ActionRole)
        dialog.addButton(QMessageBox.Close)
        dialog.exec()
        if dialog.clickedButton() is retry and owner.search_btn.isEnabled(): owner.search_sources()
    button(tools,'Source Health / Retry',source_help)
    button(owner.sources_tab.layout(),'Source Health / Retry',source_help)
    settings.addLayout(tools)

    update_row=FlowLayout()
    settings.addLayout(update_row)
    automatic=QCheckBox('Check GitHub for updates at startup')
    automatic.setChecked(owner.config.get('automatic_update_checks',True))
    def change_auto(value):
        owner.config['automatic_update_checks']=bool(value)
        persist()
    automatic.toggled.connect(change_auto)
    settings.addWidget(automatic)
    update_status=QLabel('Update checks contact only the AMF GitHub release API. Installation always asks first.')
    update_status.setWordWrap(True)
    settings.addWidget(update_status)

    def worker_finished():
        check.setEnabled(True)
        download.setEnabled(owner._update_asset is not None)
        cancel.setEnabled(False)
    def result(data):
        if 'path' in data:
            owner._update_path=data['path']
            install.setEnabled(True)
            update_status.setText('Installer downloaded and SHA-256 verified. Choose Install Update when ready.')
        else:
            owner._update_asset=data.get('asset')
            owner._update_notes=data.get('notes','')
            update_status.setText(f"Update {data['version']} available. Download it below." if owner._update_asset else 'You have the latest stable version.')
    def begin(asset=None):
        if owner._update_worker and owner._update_worker.isRunning(): return
        if owner._update_worker: owner._update_worker.deleteLater()
        owner._update_worker=UpdateWorker(api.APP_VERSION,api.APP_DIR/'updates',asset,owner)
        owner._update_worker.result.connect(result)
        owner._update_worker.error.connect(lambda error:update_status.setText('Update failed: '+error+' • Check your connection and retry.'))
        owner._update_worker.progress.connect(lambda value:update_status.setText(f'Downloading installer: {value}%'))
        owner._update_worker.finished.connect(worker_finished)
        check.setEnabled(False)
        download.setEnabled(False)
        cancel.setEnabled(True)
        update_status.setText('Downloading…' if asset else 'Checking GitHub…')
        owner._update_worker.start()
    def install_update():
        if not owner._update_path: return
        import hashlib
        with Path(owner._update_path).open('rb') as installer:
            digest='sha256:'+hashlib.file_digest(installer,'sha256').hexdigest()
        if not owner._update_asset or digest != owner._update_asset['digest']:
            QMessageBox.warning(owner,'Update','The installer changed after download. Download it again.')
            return
        if QMessageBox.question(owner,'Install Update','Close AMF and open the verified update installer now?') != QMessageBox.Yes: return
        if owner.close():
            subprocess.Popen([owner._update_path],shell=False)
    check=button(update_row,'Check for Updates',lambda:begin())
    download=button(update_row,'Download Update',lambda:begin(owner._update_asset))
    download.setEnabled(False)
    button(update_row,'Release Notes',lambda:QMessageBox.information(owner,'Release Notes',getattr(owner,'_update_notes','Check for updates first.')))
    cancel=button(update_row,'Cancel Download',lambda:owner._update_worker.requestInterruption() if owner._update_worker else None)
    cancel.setEnabled(False)
    install=button(update_row,'Install Update',install_update)
    install.setEnabled(False)
    if getattr(api,'BACKGROUND_SERVICES',False) and automatic.isChecked(): QTimer.singleShot(3000,lambda:begin())

    marker=api.APP_DIR/'session-active.json'
    if marker.exists():
        status.setText('An interrupted session was detected. Unsent cart items were recovered; Restore Cart Backup is available below.')
    if api.CART_FILE.exists():
        try:
            saved=json.loads(api.CART_FILE.read_text(encoding='utf-8-sig'))
            if not isinstance(saved,list): raise ValueError('Invalid cart data')
        except (ValueError,OSError):
            backup=api.APP_DIR/'cart_backups'
            backup.mkdir(parents=True,exist_ok=True)
            shutil.copy2(api.CART_FILE,backup/('corrupt-cart-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json'))
            status.setText('The saved cart could not be read. A copy was preserved. Use Restore Cart Backup to recover a previous cart.')
    marker.write_text(json.dumps({'version':api.APP_VERSION,'started':datetime.now().isoformat()}),encoding='utf-8')
    owner._session_marker=marker
    # First-run tour uses sample data and never sends a torrent.
    if owner.config.get('show_first_run_tour', True) and getattr(api,'BACKGROUND_SERVICES',False):
        def tour():
            dialog=QMessageBox(owner); dialog.setWindowTitle('Welcome to AMF'); dialog.setText('AMF searches your enabled sources and lets you route results to your torrent client.'); dialog.setInformativeText('Use Search to find releases, select rows, add them to Cart, review the destination, then send the cart to your client. A sample item is never downloaded.'); skip=dialog.addButton('Skip Tour',QMessageBox.RejectRole); nxt=dialog.addButton('Next',QMessageBox.AcceptRole); dialog.exec()
            if dialog.clickedButton() is nxt:
                steps=[('Search','Enter a title and press Search. Sources are queried together.'),('Cart','Select results, add them to Cart, and review folders before sending.'),('Settings','Choose themes, locations, clients, history and recovery tools here.')]
                for title,text in steps:
                    box=QMessageBox(owner); box.setWindowTitle(f'AMF Tour • {title}'); box.setText(text); box.addButton('Back',QMessageBox.RejectRole); box.addButton('Next',QMessageBox.AcceptRole); box.addButton('Finish',QMessageBox.DestructiveRole); box.exec()
            owner.config['show_first_run_tour']=False; persist()
        QTimer.singleShot(700,tour)
