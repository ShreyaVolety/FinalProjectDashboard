"""Run: python prepare_dashboard_seed.py /path/to/project_seed.zip"""
from pathlib import Path
import sys, zipfile

source = Path(sys.argv[1])
destination = Path(__file__).resolve().parent / 'dashboard_seed.zip'
if source.resolve() == destination.resolve():
    raise ValueError('Choose the original project_seed.zip as input')
with zipfile.ZipFile(source) as incoming:
    members = [m for m in incoming.infolist() if len(Path(m.filename).parts) == 2
               and Path(m.filename).parts[0] == 'exports'
               and m.filename.endswith(('.csv', '.json'))]
    if not members:
        raise ValueError('No exports found in project seed')
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as outgoing:
        for member in members:
            outgoing.writestr(member.filename, incoming.read(member))
print(f'Created {destination.name}: {len(members)} display files. Include it with your app when hosting.')
