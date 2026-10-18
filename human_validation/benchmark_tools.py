"""Human benchmark utilities. No model calls and no inferred annotation judgments."""
import json,re
from pathlib import Path
import numpy as np
import pandas as pd

def schema_at(folder):
    s=json.loads((Path(folder)/'coding_schema.json').read_text())
    rules={k:v[0] for k,v in s['RULES'].items()}
    rules.update({k:['0','1'] for k in s['BINARY_RULES']})
    return rules

def read_csv(path):return pd.read_csv(path,dtype=str,keep_default_na=False)

def load_pair(folder,scope='News'):
    a=read_csv(Path(folder)/'annotator_A_clean.csv');b=read_csv(Path(folder)/'annotator_B_clean.csv')
    for who,f in [('A',a),('B',b)]:
        if f.item_id.duplicated().any():raise ValueError(f'Duplicate IDs: {who}')
    if scope!='Both':a=a.loc[a.platform.eq(scope)].copy();b=b.loc[b.platform.eq(scope)].copy()
    common=sorted(set(a.item_id)&set(b.item_id))
    a=a.set_index('item_id').loc[common].reset_index();b=b.set_index('item_id').loc[common].reset_index()
    if not a.text.equals(b.text):raise ValueError('Texts differ for shared IDs; review before comparing.')
    if not a.platform.equals(b.platform):raise ValueError('Platforms differ for shared IDs.')
    return a,b

def agreement(x,y):
    x=list(x);y=list(y);n=len(x)
    if not n:return dict(n=0,agreement=np.nan,kappa=np.nan,agreement_lower95=np.nan,agreement_upper95=np.nan)
    observed=float(np.mean(np.array(x)==np.array(y)))
    px=pd.Series(x).value_counts(normalize=True);py=pd.Series(y).value_counts(normalize=True)
    expected=sum(px.get(k,0)*py.get(k,0) for k in set(px.index)|set(py.index))
    z=1.96;den=1+z*z/n;center=(observed+z*z/(2*n))/den;half=z*np.sqrt(observed*(1-observed)/n+z*z/(4*n*n))/den
    return dict(n=n,agreement=observed,kappa=(observed-expected)/(1-expected) if expected<1-1e-12 else np.nan,agreement_lower95=center-half,agreement_upper95=center+half)

def coarse_relevance(value):
    if value=='Relevant':return 'Relevant'
    if value=='Unclear':return 'Unclear'
    if value in ['Investment-only','Keyword false positive','Historical-fictional','Other non-economic','Irrelevant']:return 'Excluded'
    return '' # Generic Other is unresolved, not silently relabeled.

def agreement_tables(a,b,rules):
    rows=[];dist=[]
    for field,allowed in rules.items():
        va=a[field].isin(allowed);vb=b[field].isin(allowed)
        for subset,mask in [('all_shared',pd.Series(True,index=a.index)),('both_relevant',a.relevance.eq('Relevant')&b.relevance.eq('Relevant'))]:
            paired=mask&va&vb
            rows.append(dict(field=field,subset=subset,shared_items=int(mask.sum()),valid_A=int((mask&va).sum()),valid_B=int((mask&vb).sum()),**agreement(a.loc[paired,field],b.loc[paired,field])))
        for who,f in [('A',a),('B',b)]:
            for value,count in f[field].value_counts(dropna=False).items():dist.append(dict(annotator=who,field=field,label=value if value else '(blank)',count=int(count),canonical=value in allowed))
    ca=a.relevance.map(coarse_relevance);cb=b.relevance.map(coarse_relevance);use=ca.ne('')&cb.ne('')
    rows.append(dict(field='relevance_coarse',subset='all_shared',shared_items=len(a),valid_A=int(ca.ne('').sum()),valid_B=int(cb.ne('').sum()),**agreement(ca[use],cb[use])))
    return pd.DataFrame(rows),pd.DataFrame(dist)

def make_adjudication(a,b,rules,path):
    path=Path(path)
    existing=read_csv(path) if path.exists() else pd.DataFrame()
    previous={(r.item_id,r.field):r for r in existing.itertuples()} if len(existing) else {}
    rows=[]
    for i in range(len(a)):
        for field,allowed in rules.items():
            x,y=a.loc[i,field],b.loc[i,field]
            if x==y and x in allowed:continue
            old=previous.get((a.loc[i,'item_id'],field))
            if old is not None and (old.A_original!=x or old.B_original!=y):raise ValueError('Annotations changed after adjudication began; use a new output folder.')
            rows.append(dict(item_id=a.loc[i,'item_id'],platform=a.loc[i,'platform'],text=a.loc[i,'text'],field=field,A_original=x,B_original=y,
                issue='Missing/noncanonical answer' if x not in allowed or y not in allowed else 'Disagreement',
                final_label=old.final_label if old else '',reason=old.reason if old else '',adjudicator=old.adjudicator if old else ''))
    result=pd.DataFrame(rows,columns=['item_id','platform','text','field','A_original','B_original','issue','final_label','reason','adjudicator'])
    result.to_csv(path,index=False);return result

def build_gold(a,b,rules,work):
    gold=a[['item_id','platform','text']].copy()
    decisions={};issues=[]
    for r in work.itertuples():
        if not r.final_label:continue
        if r.field not in rules or r.final_label not in rules[r.field]:raise ValueError(f'Invalid final label: {r.item_id}, {r.field}')
        if not r.reason.strip() or not r.adjudicator.strip():raise ValueError('Completed adjudication needs a reason and adjudicator.')
        key=(r.item_id,r.field)
        if key in decisions:raise ValueError('Duplicate adjudication decision')
        decisions[key]=r.final_label
    for field,allowed in rules.items():
        vals=[]
        for i in range(len(a)):
            x,y=a.loc[i,field],b.loc[i,field]
            vals.append(x if x==y and x in allowed else decisions.get((a.loc[i,'item_id'],field),''))
        gold[field]=vals
    return gold

def class_metrics(gold,prediction):
    g=list(gold);p=list(prediction);rows=[]
    for label in sorted(set(g)|set(p)):
        tp=sum(x==label and y==label for x,y in zip(g,p));fp=sum(x!=label and y==label for x,y in zip(g,p));fn=sum(x==label and y!=label for x,y in zip(g,p))
        precision=tp/(tp+fp) if tp+fp else 0.;recall=tp/(tp+fn) if tp+fn else 0.
        rows.append(dict(label=label,precision=precision,recall=recall,f1=2*precision*recall/(precision+recall) if precision+recall else 0.,support=g.count(label)))
    supported=[r['f1'] for r in rows if r['support']]
    return pd.DataFrame(rows),dict(n=len(g),accuracy=float(np.mean(np.array(g)==np.array(p))) if len(g) else np.nan,macro_f1=float(np.mean(supported)) if supported else np.nan)

POSITIVE=['growth','gains','gain','hiring','improves','improved','improving','strong','stronger','resilient','recovery','recovering','affordable','easing','optimistic','optimism','boom','surplus','rally']
NEGATIVE=['recession','layoffs','layoff','unemployment','inflation','crisis','slump','weak','weaker','decline','declines','declining','struggling','strain','fear','fears','pessimism','bankruptcy','surge']
def dictionary_predict(text):
    pos=len(re.findall(r'\b(?:'+'|'.join(POSITIVE)+r')\b',text,re.I));neg=len(re.findall(r'\b(?:'+'|'.join(NEGATIVE)+r')\b',text,re.I))
    return 'Positive' if pos>neg else 'Negative' if neg>pos else 'Neutral'

def evaluate(gold,pred,metadata,rules):
    """Field-specific consensus/adjudicated benchmark; missing AI outputs count as errors."""
    g=gold.copy();meta=metadata.copy()
    for col in ['source','split']:
        if col not in meta:meta[col]='Unknown'
    g=g.merge(meta[['item_id','source','split']].drop_duplicates('item_id'),on='item_id',how='left',validate='one_to_one')
    g[['source','split']]=g[['source','split']].fillna('Unknown')
    p=pred.copy()
    if p.item_id.duplicated().any():raise ValueError('AI predictions contain duplicate IDs.')
    if 'ai_status' in p:
        accepted=p.ai_status.isin(['ok','warning'])
        for field in rules:
            if field in p:p.loc[~accepted,field]='Missing'
    for field in rules:
        if field not in p:p[field]='Missing'
    merged=g.merge(p[['item_id',*rules]],on='item_id',how='left',suffixes=('_gold','_ai'),validate='one_to_one')
    rows=[];summaries=[]
    for field,allowed in rules.items():
        base=merged.loc[merged[field+'_gold'].isin(allowed)].copy()
        # For substantive fields, require gold-relevant text. AI exclusions remain wrong predictions.
        if field not in ['relevance','geography','genre']:
            base=base.loc[base.relevance_gold.eq('Relevant')]
        if field=='economic_tone':
            pass # Full AI includes all gold tone categories; matched dictionary comparison is separate below.
        for scope,frame in [('all_completed_descriptive',base),('original_heldout',base.loc[base.split.eq('heldout')])]:
            groups=[('overall','all',frame)]+[('source',str(k),v) for k,v in frame.groupby('source') if k!='Unknown']
            for grouping,key,sub in groups:
                if sub.empty:continue
                predicted=sub[field+'_ai'].fillna('Missing');predicted=predicted.where(predicted.isin(allowed),'Missing')
                cm,summary=class_metrics(sub[field+'_gold'],predicted)
                info=dict(method='AI',field=field,scope=scope,grouping=grouping,group=key)
                rows.extend([{**info,**r} for r in cm.to_dict('records')]);summaries.append({**info,**summary})
    compatible=merged.loc[merged.relevance_gold.eq('Relevant')&merged.economic_tone_gold.isin(['Positive','Negative','Neutral'])].copy()
    compatible['dictionary']=compatible.text.map(dictionary_predict)
    comparisons=[]
    for scope,frame in [('all_completed_descriptive',compatible),('original_heldout',compatible.loc[compatible.split.eq('heldout')])]:
        for method,col in [('AI','economic_tone_ai'),('Dictionary','dictionary')]:
            predicted=frame[col].fillna('Missing')
            cm,summary=class_metrics(frame.economic_tone_gold,predicted)
            comparisons.append(dict(scope=scope,method=method,**summary))
            rows.extend([dict(method=method,field='tone_matched_dictionary_subset',scope=scope,grouping='overall',group='all',**r) for r in cm.to_dict('records')])
    return pd.DataFrame(rows),pd.DataFrame(summaries),pd.DataFrame(comparisons),merged
