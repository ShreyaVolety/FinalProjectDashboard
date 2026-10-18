"""Initialize only missing display files; never make provider requests."""
from pathlib import Path
import io, zipfile
from controller import import_archive

def initialize_seed(app, workspace):
    app, workspace = Path(app), Path(workspace)
    marker = workspace / '.seed_initialized'
    if marker.exists():
        return
    archive = app / 'dashboard_seed.zip'
    if archive.exists():
        with zipfile.ZipFile(archive) as source:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as out:
                for member in source.infolist():
                    parts = Path(member.filename).parts
                    if len(parts) == 2 and parts[0] in ('exports', 'data') and parts[1].endswith(('.csv', '.json')):
                        out.writestr('exports/' + parts[1], source.read(member))
            import_archive(buffer.getvalue(), workspace)
    else:
        files = list((app / 'data').glob('*.csv')) + list((app / 'data').glob('*.json'))
        if not files:
            return
        target = workspace / 'exports'
        target.mkdir(parents=True, exist_ok=True)
        for file in files:
            destination = target / file.name
            if not destination.exists():
                destination.write_bytes(file.read_bytes())
    marker.write_text('Bundled display snapshot initialized. No API calls.\n')

