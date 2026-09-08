"""Validated appearance presets, routing and local destination checks."""
import json, re, shutil, socket, tempfile
from pathlib import Path
from urllib.parse import urlsplit

PALETTES = {
 'Dark': dict(background='#0a0a0c', surface='#17171c', text='#f5f5f5', muted='#aaaaaf', accent='#e23636', border='#414149'),
 'Light': dict(background='#f5f6f8', surface='#ffffff', text='#202124', muted='#555963', accent='#a51d2d', border='#a1a5ae'),
 'High Contrast': dict(background='#000000', surface='#000000', text='#ffffff', muted='#ffffff', accent='#ffff00', border='#ffffff')}

def validate_theme(data):
    if not isinstance(data,dict) or set(data)!=set(PALETTES['Dark']): raise ValueError('A theme must contain exactly six appearance colours.')
    if not all(isinstance(v,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',v) for v in data.values()): raise ValueError('Theme colours must use #RRGGBB format.')
    return dict(data)

def theme_css(base, palette, text_size=13, density=1):
    palette=validate_theme(palette)
    def colour(match):
        code=match[0]
        channels=[int(code[i:i+2],16) for i in (1,3,5)]
        r,g,b=channels
        if r>g*1.35 and r>b*1.15: return palette['accent']
        brightness=sum(channels)/3
        return palette['text' if brightness>190 else 'muted' if brightness>90 else 'border' if brightness>35 else 'surface' if brightness>14 else 'background']
    css=re.sub(r'#[0-9A-Fa-f]{6}',colour,base)
    css=re.sub(r'(\d+)px',lambda m:f'{max(1,round(int(m[1])*density))}px',css)
    css=re.sub(r'font-size:\s*(\d+)px',lambda m:f'font-size: {max(10,round(int(m[1])/density*text_size/13))}px',css)
    # Keep text readable on accent-coloured controls, including high contrast.
    rgb=[int(palette['accent'][i:i+2],16) for i in (1,3,5)]
    foreground='#000000' if sum(rgb)>430 else '#ffffff'
    selection = '#dce8f7' if palette['background'] == PALETTES['Light']['background'] else '#293548'
    checkmark = (Path(__file__).parent/('checkmark-black.svg' if foreground == '#000000' else 'checkmark.svg')).as_posix()
    return css+f'''
        QAbstractItemView {{ selection-background-color: {selection}; selection-color: {palette['text']}; }}
        QAbstractItemView::item:selected {{ background: {selection}; color: {palette['text']}; }}
        QCheckBox::indicator:checked {{ background: {palette['accent']}; border: 2px solid {palette['accent']}; image: url("{checkmark}"); }}
        QCheckBox::indicator:unchecked {{ background: {palette['surface']}; border: 2px solid {palette['muted']}; }}
        QLabel, QCheckBox {{ background: transparent; }}
        QLabel#versionBadge {{ color: {foreground}; background: {palette['accent']}; }}
        QPushButton#primaryButton {{ color: {foreground}; }}
        QListView#choicePopup {{ padding: 0px; margin: 0px; outline: 0px; }}
        QListView#choicePopup::item {{ margin: 0px; padding: 6px 8px; border: 1px solid transparent; }}
        QListView#choicePopup::item:selected {{ border: 1px solid {palette['muted']}; background: {selection}; }}
        QComboBox#appearanceChoice {{ padding: 4px 8px; min-height: 20px; }}
        QPushButton:focus, QLineEdit:focus, QComboBox:focus {{border:2px solid {palette["accent"]};}}
    '''

def routed_destination(item,rules):
    if item.get('destination_custom') or item.get('save_path_custom'): return None
    for rule in rules:
        field=rule.get('field')
        needle=str(rule.get('contains','')).strip().casefold()
        if field in ('source','title','category') and needle and needle in str(item.get(field,'')).casefold():
            return rule.get('destination')
    return None

def client_is_remote(config):
    name=config.get('torrent_client','qBittorrent')
    if name in ('uTorrent','Other desktop client'): return False
    profile=config.get('qbittorrent',{}) if name=='qBittorrent' else config.get('client_profiles',{}).get(name,{})
    host=str(profile.get('host') or '127.0.0.1')
    parsed=urlsplit(host if '://' in host else '//'+host)
    return (parsed.hostname or host).lower() not in ('localhost','127.0.0.1','::1',socket.gethostname().lower())

def check_destinations(items,remote=False):
    if remote: return [],'Remote client: check free space and permissions on that computer; local disk checks do not apply.'
    errors,volumes=[],{}
    for folder in {str(item.get('save_path') or '') for item in items}:
        path=Path(folder)
        if not folder or not path.is_absolute():
            errors.append(f'{folder or "Missing folder"}: choose an absolute download folder.'); continue
        parent=path
        while not parent.exists() and parent!=parent.parent: parent=parent.parent
        if not parent.is_dir(): errors.append(f'{folder}: drive or folder is unavailable.'); continue
        try:
            with tempfile.TemporaryFile(dir=parent): pass
            drive=path.anchor
            volumes.setdefault(drive,[parent,0])
            volumes[drive][1]+=sum(max(0,int(i.get('size_bytes') or 0)) for i in items if str(i.get('save_path') or '')==folder)
        except (OSError,ValueError): errors.append(f'{folder}: folder is not writable.')
    for parent,required in volumes.values():
        try:
            free=shutil.disk_usage(parent).free
            if required and required>free: errors.append(f'{parent.anchor}: insufficient free space ({required/1024**3:.1f} GB requested; {free/1024**3:.1f} GB free).')
        except OSError: errors.append(f'{parent}: free space could not be checked.')
    return errors,'Space estimates exclude torrents whose sizes are unknown.'

def portable_settings(config):
    # Export preferences only, never client profiles, source URLs or credentials.
    allowed={'appearance','routing_rules','retention_days','backup_limit','automatic_update_checks'}
    return {key:value for key,value in config.items() if key in allowed}
