"""Notebook adapters and refresh accounting. Credentials are supplied in memory only."""
import ast,contextlib,hashlib,json,os,threading,uuid
from pathlib import Path
import pandas as pd
import numpy as np

APP=Path(__file__).resolve().parent

def atomic(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(data,indent=2,default=str));tmp.replace(path)

def latest(paths):
    paths=list(paths)
    if not paths:raise FileNotFoundError('Required upstream data missing. Import your seed or run the earlier stage.')
    return max(paths,key=lambda p:p.stat().st_mtime)

def cells(name):return json.loads((APP/'notebooks'/name).read_text())['cells']

def execute(source,ns,overrides=None):
    # Notebook source is bundled/reviewable; never execute user-uploaded code.
    lines=[l for l in source.splitlines() if not l.lstrip().startswith(('%','!'))]
    tree=ast.parse('\n'.join(lines));overrides=overrides or {}
    class Adapt(ast.NodeTransformer):
        def visit_Try(self,node):
            if 'google.colab' in ast.unparse(node):return None
            return self.generic_visit(node)
        def visit_Assign(self,node):
            if len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in overrides:
                node.value=ast.Subscript(value=ast.Name(id='_OVERRIDES',ctx=ast.Load()),slice=ast.Constant(node.targets[0].id),ctx=ast.Load())
            return node
    ns['_OVERRIDES']=overrides
    tree=ast.fix_missing_locations(Adapt().visit(tree));exec(compile(tree,'<bundled-notebook-cell>','exec'),ns)

def run_cell(name,index,ns,overrides=None,patch=None):
    source=''.join(cells(name)[index]['source'])
    if patch:source=patch(source)
    execute(source,ns,overrides)

def context():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.show=lambda *a,**k:plt.close('all')
    def display(*frames):
        for f in frames:
            if isinstance(f,pd.DataFrame):print('Table:',f.shape)
    return {'__name__':'dashboard_worker','display':display}

class BudgetStop(RuntimeError):pass
class Ledger:
    """Cumulative NEW refresh cost/reserves in this workspace, across jobs and sessions."""
    def __init__(self,path,caps):
        self.path=Path(path);self.caps=caps;self.lock=threading.Lock()
        self.data=json.loads(self.path.read_text()) if self.path.exists() else {}
    def spent(self,kind):return sum(r['amount'] for r in self.data.values() if r['kind']==kind)
    def reserve(self,token,kind,amount):
        with self.lock:
            if token in self.data:raise RuntimeError('Request already recorded; uncertain requests are not automatically retried.')
            if amount<0 or self.spent(kind)+amount>self.caps[kind]+1e-12:raise BudgetStop(f'{kind} workspace refresh budget reached')
            self.data[token]={'kind':kind,'amount':float(amount),'status':'reserved'};atomic(self.path,self.data)
    def finish(self,token,amount,status='completed'):
        with self.lock:
            if amount<0:raise ValueError('Negative recorded charge')
            self.data[token].update(amount=float(amount),status=status);atomic(self.path,self.data)
    def remaining(self,kind):return max(0.,self.caps[kind]-self.spent(kind))

CAT={
'negative_share':('economic_tone',['Negative'],['Positive','Negative','Neutral','Mixed']),
'positive_share':('economic_tone',['Positive'],['Positive','Negative','Neutral','Mixed']),
'emotional_share':('emotional_wording',['Present'],['Present','Absent']),
'price_levels_share':('price_frame',['Price levels','Both'],['Price levels','Inflation rate','Both','Neither']),
'household_frame_share':('experience_frame',['Household-local experience','Both'],['National aggregates','Household-local experience','Both','Neither']),
'future_frame_share':('time_frame',['Future expectations','Both'],['Current-recent conditions','Future expectations','Both','Neither']),
'blame_share':('political_attribution',['Blame','Both'],['Credit','Blame','Both','Neither'])}

def aggregate(ns):
    pred=ns['predictions_for'](ns['cohort']);scored=ns['cohort'].merge(pred,on='item_id',validate='one_to_one');run=ns['RUN']
    scored.to_csv(run/'ai_predictions_all_statuses.csv',index=False)
    p=scored.loc[scored.production_sample.astype(str).str.lower().isin(['true','1'])].copy();p['has_labels']=p.ai_status.isin(['ok','warning'])
    ready=p.groupby(['platform','analysis_month']).agg(planned_items=('item_id','size'),scored_items=('has_labels','sum')).reset_index()
    ready['scoring_completion']=ready.scored_items/ready.planned_items
    ready.to_csv(run/'monthly_scoring_readiness.csv',index=False)
    e=p.loc[p.has_labels&p.relevance.eq('Relevant')&p.geography.isin(['US','US-linked international'])]
    def measures(g):
        r={'eligible_items':len(g)}
        for name,(field,positive,valid) in CAT.items():
            v=g.loc[g[field].isin(valid),field];r[name]=v.isin(positive).mean() if len(v) else np.nan;r[name+'_n']=len(v)
        for field in ns['BINARY_RULES']:
            v=pd.to_numeric(g[field],errors='coerce');v=v.loc[v.isin([0,1])];r[field+'_share']=v.mean();r[field+'_share_n']=len(v)
        return r
    rate=list(CAT)+[f+'_share' for f in ns['BINARY_RULES']]
    rows=[];outlets=[]
    for (month,source),g in e.loc[e.platform.eq('News')].groupby(['analysis_month','source']):outlets.append(dict(analysis_month=month,source=source,**measures(g)))
    outlets=pd.DataFrame(outlets)
    outlets.to_csv(run/'monthly_media_by_outlet.csv',index=False)
    if len(outlets):
        for month,g in outlets.groupby('analysis_month'):
            r=dict(platform='News',analysis_month=month,eligible_items=int(g.eligible_items.sum()),eligible_sources=len(g))
            for field in rate:r[field]=g[field].mean();r[field+'_n']=g[field+'_n'].sum();r[field+'_contributing_outlets']=g[field].notna().sum()
            rows.append(r)
    for month,g in e.loc[e.platform.eq('X')].groupby('analysis_month'):rows.append(dict(platform='X',analysis_month=month,eligible_sources=g.source.nunique(),**measures(g)))
    if not rows:raise ValueError('No eligible scored items; scoring or imported predictions are required for aggregates.')
    long=ready.merge(pd.DataFrame(rows),on=['platform','analysis_month'],how='left',validate='one_to_one')
    long.to_csv(run/'monthly_media_for_section4_long.csv',index=False)
    wide=long.pivot(index='analysis_month',columns='platform',values=[c for c in long if c not in ['analysis_month','platform']])
    wide.columns=[f'{platform.lower()}_{measure}' for measure,platform in wide.columns]
    wide.index=pd.to_datetime(wide.index,format='%Y-%m');wide.index.name='month'
    wide=wide.reindex(pd.date_range(wide.index.min(),wide.index.max(),freq='MS')).rename_axis('month').reset_index()
    # Ensure the schema is explicit even before a platform has eligible scored observations.
    for platform in ['news','x']:
        for measure in rate:
            if platform+'_'+measure not in wide:wide[platform+'_'+measure]=np.nan
    wide.to_csv(run/'media_monthly_for_section4.csv',index=False)
    return run
