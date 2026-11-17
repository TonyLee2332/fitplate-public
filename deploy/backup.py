"""Create a private, consistent SQLite backup without deleting existing data."""
from datetime import datetime,timezone
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile


def backup():
    root=Path(os.environ.get('FITPLATE_DATA_DIR','/var/data/fitplate')).resolve()
    if not root.is_dir() or not (root/'.visitor_key').is_file():
        raise RuntimeError('Persistent visitor data directory was not found.')
    target=root.parent/'backups'
    target.mkdir(exist_ok=True)
    archive=target/('fitplate-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.zip')
    with tempfile.TemporaryDirectory() as temporary,zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        z.write(root/'.visitor_key','.visitor_key')
        for index,path in enumerate(root.rglob('*.sqlite3')):
            copied=Path(temporary)/f'{index}.sqlite3'
            with closing(sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True)) as source,closing(sqlite3.connect(copied)) as destination:
                source.backup(destination)
            z.write(copied,path.relative_to(root).as_posix())
    if os.name!='nt':
        archive.chmod(0o600)
    print(archive)
    return archive


if __name__=='__main__':
    backup()
