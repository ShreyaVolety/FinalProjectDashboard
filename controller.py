"""Session-private worker control. No credentials written to disk."""
import io,json,os,subprocess,sys,threading,time,zipfile,stat,uuid
from pathlib import Path
APP=Path(__file__).resolve().parent

def scrub(text,secrets):
    def strings(value):
        if isinstance(value,str):yield value
        elif isinstance(value,dict):
            for x in value.values():yield from strings(x)
    for secret in strings(secrets):
        if secret:text=text.replace(secret,'[redacted]').replace(json.dumps(secret)[1:-1],'[redacted]')
    return text

class Job:
    def __init__(self,workspace,config,secrets,stages):
        self.lines=[];self.lock=threading.Lock();self.started=time.time();self.secrets=secrets.copy()
        self.process=subprocess.Popen([sys.executable,'-u',str(APP/'pipeline.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,cwd=str(APP),env={**os.environ,'MPLBACKEND':'Agg'})
        payload=dict(workspace=str(workspace),config=config,secrets=secrets,stages=stages)
        self.process.stdin.write(json.dumps(payload));self.process.stdin.close()
        self.thread=threading.Thread(target=self._read,daemon=True);self.thread.start()
    def _read(self):
        for line in self.process.stdout:
            clean=scrub(line.rstrip(),self.secrets)
            with self.lock:self.lines.append(clean);self.lines=self.lines[-500:]
        self.process.wait();self.secrets={}
    def running(self):return self.process.poll() is None
    def tail(self):
        with self.lock:return '\n'.join(self.lines[-100:])
    def stop(self):
        if self.running():self.process.terminate()
    def code(self):return self.process.poll()

def import_archive(blob,workspace):
    """Only data files under project/ or exports/. No uploaded executable files."""
    workspace=Path(workspace);items=[];total=0
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for info in z.infolist():
            if info.is_dir():continue
            relative=Path(info.filename)
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe archive path')
            if stat.S_ISLNK(info.external_attr>>16):raise ValueError('Symlinks not allowed')
            if relative.parts[0]=='data':relative=Path('exports',*relative.parts[1:])
            if relative.parts[0] not in ['project','exports']:continue
            if not str(relative).endswith(('.csv','.json','.jsonl.gz')):continue
            if any(x in relative.name.lower() for x in ['credential','service_account','secrets','api_key']):continue
            total+=info.file_size
            if total>1024**3:raise ValueError('Uncompressed import exceeds 1 GiB; reduce the seed')
            items.append((info,relative))
        if not items:raise ValueError('No project/ or data/exports files found. Use the supplied Colab export helper.')
        count=0
        for info,relative in items:
            target=workspace/relative
            # Never silently replace a running workspace's cached results or ledgers.
            if target.exists():continue
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(info));count+=1
    return count

def export_workspace(workspace):
    workspace=Path(workspace);b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        for parent in ['exports','project']:
            for p in (workspace/parent).rglob('*'):
                if p.is_file() and p.name.endswith(('.csv','.json')) and '/raw/' not in str(p):z.write(p,str(p.relative_to(workspace)))
        ledger=workspace/'refresh_ledger.json'
        if ledger.exists():z.write(ledger,ledger.name)
    return b.getvalue()
