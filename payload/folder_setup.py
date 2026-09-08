"""First-run destination selection; no folders are created until requested."""
from pathlib import Path
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QHBoxLayout,QLineEdit,QPushButton,QLabel,QDialogButtonBox,QFileDialog,QWidget
FIELDS = [('games_path','Games'),('movies_path','Films'),('series_path','Series'),('anime_movies_path','Anime films'),('anime_series_path','Anime series'),('music_path','Music'),('books_path','Books')]
class FolderSetup(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.setWindowTitle('Choose your download folders')
        self.resize(660,420)
        layout=QVBoxLayout(self)
        note=QLabel('Choose a folder for each category. You can create a folder in the folder picker, and change these choices later in Settings.')
        note.setWordWrap(True);layout.addWidget(note)
        form=QFormLayout();layout.addLayout(form);self.fields={}
        base=Path(QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or str(Path.home()/'Downloads'))
        for key,label in FIELDS:
            row=QWidget();line=QHBoxLayout(row);line.setContentsMargins(0,0,0,0)
            current=owner.config.get(key,'')
            if not current or current.lower().startswith('d:'):current=str(base/label)
            edit=QLineEdit(current);self.fields[key]=edit
            browse=QPushButton('Browse…');browse.clicked.connect(lambda checked=False,e=edit:self.choose(e))
            line.addWidget(edit,1);line.addWidget(browse);form.addRow(label,row)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
    def choose(self, edit):
        selected=QFileDialog.getExistingDirectory(self,'Choose download folder',edit.text())
        if selected:edit.setText(selected)
    def values(self):return {key:edit.text().strip() for key,edit in self.fields.items() if edit.text().strip()}

def setup_folders(owner, persist):
    dialog=FolderSetup(owner)
    if dialog.exec()==QDialog.Accepted:
        for key,value in dialog.values().items():
            owner.config[key]=value
            edit=getattr(owner,key+'_edit',None) or getattr(owner,'extra_path_edits',{}).get(key)
            if edit is not None:edit.setText(value)
        owner.config['folder_setup_complete']=True
        persist();owner.refresh_paths();owner.refresh_cart()
