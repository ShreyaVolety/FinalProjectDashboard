"""Refresh worker. Receives secrets through stdin, never through files or CLI arguments."""
import sys,os,json,hashlib,shutil,traceback,time,gzip,re,threading
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import pandas as pd
from runtime import atomic,latest,cells,run_cell,execute,context,Ledger,BudgetStop,aggregate,APP

N1='module_01_economic_baseline.ipynb';N2='module_02_headline_corpus.ipynb';N3='module_03_ai_measurement.ipynb';N4='module_04_association_analysis.ipynb'

class Pipeline:
    def __init__(self,workspace,config,secrets):
        self.ws=Path(workspace);self.root=self.ws/'project';self.root.mkdir(parents=True,exist_ok=True)
        self.c=config;self.secrets=secrets
        self.job_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+os.urandom(3).hex()
        self.job=self.ws/'jobs'/self.job_id;self.job.mkdir(parents=True)
        self.ledger=Ledger(self.ws/'refresh_ledger.json',config['budgets'])
        self.macro=None;self.media=None;self.analysis=None
        self.asof=min(pd.Timestamp(config['as_of']).date(),datetime.now(ZoneInfo('America/Chicago')).date()).isoformat()
        self.snapshot=self.asof+'_'+self.job_id
        for key,env in [('fred','FRED_API_KEY'),('bea','BEA_API_KEY'),('twitter','TWITTERAPI_IO_KEY'),('openai','OPENAI_API_KEY')]:
            if secrets.get(key):os.environ[env]=secrets[key]
        import getpass
        getpass.getpass=lambda *args:(_ for _ in ()).throw(RuntimeError('Required credential missing in configuration'))
        atomic(self.job/'configuration.json',config) # Non-secret fields only.
    def redact(self,text):
        def values(obj):
            if isinstance(obj,str):yield obj
            elif isinstance(obj,dict):
                for value in obj.values():yield from values(value)
        for value in values(self.secrets):
            if value:
                text=text.replace(value,'[redacted]').replace(json.dumps(value)[1:-1],'[redacted]')
        return text
    def redact_bytes(self,body):return self.redact(body.decode('utf-8')).encode('utf-8')
    def credentials(self):
        info=self.secrets.get('gcp_service_account')
        if info:
            from google.oauth2 import service_account
            return service_account.Credentials.from_service_account_info(info)
        import google.auth
        return google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])[0]
    def macro_stage(self):
        if not self.secrets.get('fred') or not self.secrets.get('bea'):raise ValueError('FRED and BEA keys required for macro refresh')
        ns=context();run_cell(N1,1,ns)
        run_cell(N1,2,ns,dict(PROJECT_ROOT=self.root,AS_OF=self.asof,SNAPSHOT_ID=self.snapshot,MONITOR_START=self.c['monitor_start'],MONITOR_END=self.asof[:7]))
        for i in [4,6,8,10,12,14,16,18]:
            def patch(source):
                if i==4:source=source.replace('temporary=path.with_suffix', 'body=REDACT_BYTES(body)\n    temporary=path.with_suffix')
                if i==6:source=source.replace("float(r['value'])","pd.to_numeric(r['value'],errors='coerce')")
                if i==8:
                    source=source.replace("return fetch_json(name,FRED_BASE+endpoint,dict(api_key=FRED_KEY,file_type='json',**params))", "params['realtime_end']=min(params.get('realtime_end',AS_OF),AS_OF) if params.get('realtime_end')!='9999-12-31' else '9999-12-31'\n    if 'observation_end' in params:params['observation_end']=min(params['observation_end'],AS_OF)\n    return fetch_json(name,FRED_BASE+endpoint,dict(api_key=FRED_KEY,file_type='json',**params))")
                return source
            ns['REDACT_BYTES']=self.redact_bytes
            print('Macro cell',i,flush=True);run_cell(N1,i,ns,patch=patch)
        self.macro=ns['PROCESSED'];print('Economic refresh complete.',flush=True)
    def collection_namespace(self):
        ns=context();run_cell(N2,1,ns)
        end=min(pd.Timestamp(self.c['end_exclusive']).date(),datetime.now(timezone.utc).date()).isoformat()
        if pd.Timestamp(self.c['start'])>=pd.Timestamp(end):raise ValueError('Collection start must precede end-exclusive date')
        overrides=dict(PROJECT_ROOT=self.root,GCP_PROJECT=self.c.get('gcp_project') or 'not-used',NEWS_START=self.c['start'],NEWS_END_EXCLUSIVE=end,SNAPSHOT_ID=self.snapshot,
            EXECUTE_NEWS=False,EXECUTE_X=False,NEWS_MODE='full',NEWS_TERMS_REVIEWED=False,X_MODE='history',X_START=self.c['start'],X_END_EXCLUSIVE=end,
            BIGQUERY_USD_PER_TIB=self.c['bq_price'],BIGQUERY_BUDGET_USD=self.c['budgets']['bigquery'],
            X_BUDGET_USD=self.c['budgets']['twitter'],X_USD_PER_TWEET=self.c['tweet_price'],X_TARGET_PER_COMPLETE_MONTH=self.c['x_monthly_target'])
        run_cell(N2,2,ns,overrides);run_cell(N2,4,ns)
        return ns
    def news_stage(self,dry=False):
        if not self.c.get('gcp_project'):raise ValueError('GCP billing project ID required')
        ns=self.collection_namespace();ns['_GCP_CREDENTIALS']=self.credentials()
        run_cell(N2,6,ns,patch=lambda s:s.replace('client=bigquery.Client(project=GCP_PROJECT,location=LOCATION)','client=bigquery.Client(project=GCP_PROJECT,location=LOCATION,credentials=_GCP_CREDENTIALS)'))
        plan=ns['plan'];print('Unsaved dry-run list-cost estimate $',round(plan.loc[~plan.already_saved,'estimated_list_usd'].sum(),4),flush=True)
        if dry:return
        from google.cloud import bigquery
        for row in plan.to_dict('records'):
            fingerprint,path=ns['query_identity'](row['month'])
            if path.exists():print('News cache:',row['month'],flush=True);continue
            token='bq:'+hashlib.sha256((self.c['gcp_project']+fingerprint).encode()).hexdigest()
            maxbytes=int(max(row['estimated_bytes']*1.05,10*1024**2));reserve=maxbytes/1024**4*self.c['bq_price']
            self.ledger.reserve(token,'bigquery',reserve)
            jid='refresh_'+token[3:43]
            job=ns['client'].query(ns['SQL'],job_id=jid,location=ns['LOCATION'],job_retry=None,
                job_config=bigquery.QueryJobConfig(query_parameters=ns['query_params'](row['start'],row['end_exclusive']),maximum_bytes_billed=maxbytes,use_query_cache=True))
            records=job.result();temp=path.with_suffix(path.suffix+'.tmp')
            with gzip.open(temp,'wt',encoding='utf-8') as stream:
                for record in records:stream.write(json.dumps(dict(record),default=str)+'\n')
            temp.replace(path)
            actual=int(job.total_bytes_billed or 0)/1024**4*self.c['bq_price'];self.ledger.finish(token,actual)
            atomic(ns['JOBDIR']/(jid+'.json'),dict(job_id=jid,status='done',budget_bytes=int(job.total_bytes_billed or 0),path=str(path)))
            print('News downloaded:',row['month'],'| $',round(actual,4),flush=True)
        run_cell(N2,10,ns)
        if not ns['news'].empty:
            # Preserve the agreed broader geography screen: US + unclear candidates.
            pool=pd.read_csv(ns['RUN']/'news_economic_candidates_all_geographies.csv',keep_default_na=False)
            candidate=pool.loc[pool.geographic_relevance_status.isin(['Likely US-focused','Geographically unclear'])].copy()
            candidate.to_csv(ns['RUN']/'news_headline_candidates.csv',index=False);ns['candidates']=candidate
            run_cell(N2,12,ns)
        print('News refresh complete.',flush=True)
    def x_stage(self):
        if not self.secrets.get('twitter'):raise ValueError('twitterapi.io key required')
        ns=self.collection_namespace()
        # Only function/constant definitions from the original planner, not its interactive driver.
        execute(''.join(cells(N2)[16]['source']).split('xplan=pd.DataFrame()')[0],ns)
        plan=ns['x_windows'](ns['SEARCH_TERMS']);plan.to_csv(ns['RUN']/'x_all_query_windows.csv',index=False)
        ns['xplan']=plan
        import urllib.request,urllib.parse,urllib.error
        for window in plan.to_dict('records'):
            identity=json.dumps(dict(endpoint='advanced_search',query=window['query'],queryType='Latest',cursor=''),sort_keys=True)
            digest=ns['sha'](identity);path=ns['XRAW']/(digest+'.json');meta_path=ns['XRAW']/(digest+'.meta.json')
            if path.exists():continue
            if meta_path.exists():raise RuntimeError('Uncertain old X request retained; inspect it before retrying')
            token='x:'+digest;reserve=100*self.c['tweet_price']
            self.ledger.reserve(token,'twitter',reserve)
            meta=dict(query=window['query'],group=window['group'],date=window['date'],month=window['month'],start_utc=window['start_utc'],end_utc=window['end_utc'],slot=window['slot'],sample_window_id=window['sample_window_id'],terms_hash=window['terms_hash'],complete_calendar_month=window['complete_calendar_month'],retrieved_at_utc=datetime.now(timezone.utc).isoformat(),status='requesting',budget_usd=reserve)
            atomic(meta_path,meta)
            url='https://api.twitterapi.io/twitter/tweet/advanced_search?'+urllib.parse.urlencode(dict(query=window['query'],queryType='Latest',cursor=''))
            request=urllib.request.Request(url,headers={'X-API-Key':self.secrets['twitter']})
            with urllib.request.urlopen(request,timeout=60) as response:payload=json.load(response)
            if not isinstance(payload.get('tweets'),list):raise ValueError('Unexpected X schema; reserve retained')
            charge=max(.00015,len(payload['tweets'])*self.c['tweet_price']);atomic(path,payload)
            self.ledger.finish(token,charge)
            meta.update(status='done',budget_usd=charge,has_next_page=bool(payload.get('has_next_page')),returned_posts=len(payload['tweets']));atomic(meta_path,meta)
            print('X window:',window['date'],window['group'],'| returned:',len(payload['tweets']),flush=True)
            if len(payload['tweets'])>100:raise RuntimeError('X response exceeded assumed reserve; inspect provider billing')
            time.sleep(self.c['x_spacing'])
        ns['normalize_title']=lambda text:re.sub(r'\s+',' ',str(text)).strip()
        run_cell(N2,18,ns)
        print('X refresh complete.',flush=True)
    def combine_inputs(self):
        folder=self.root/'02_media_corpus/combined';folder.mkdir(parents=True,exist_ok=True)
        for name,idcol in [('news_headline_candidates.csv','article_id'),('x_posts_for_labeling.csv','post_id')]:
            paths=list((self.root/'02_media_corpus/snapshots').glob('**/'+name))
            previous=folder/name
            if previous.exists():paths=[previous]+paths
            if not paths:raise FileNotFoundError(f'Import existing {name} or run collection first')
            frames=[pd.read_csv(p,dtype=str,keep_default_na=False) for p in sorted(paths,key=lambda p:p.stat().st_mtime)]
            merged=pd.concat(frames,ignore_index=True).drop_duplicates(idcol,keep='last')
            merged.to_csv(previous,index=False)
        return folder
    def scoring_stage(self,score=True):
        folder=self.combine_inputs();news=folder/'news_headline_candidates.csv';tweets=folder/'x_posts_for_labeling.csv'
        fingerprint=hashlib.sha256(news.read_bytes()+tweets.read_bytes()).hexdigest()[:14]
        ns=context();run_cell(N3,1,ns)
        run_cell(N3,2,ns,dict(PROJECT_ROOT=self.root,NEWS_PATH=news,TWEETS_PATH=tweets,STUDY_VERSION='dashboard-'+fingerprint,
            MODEL=self.c['model'],API_BUDGET_USD=self.c['budgets']['openai'],INPUT_USD_PER_M=self.c['input_price'],OUTPUT_USD_PER_M=self.c['output_price'],RUN_STAGE='off',FREEZE_METHOD=False,
            NEWS_PER_OUTLET_MONTH=self.c['news_quota'],TWEETS_PER_MONTH=self.c['tweet_quota']))
        run_cell(N3,4,ns);run_cell(N3,6,ns)
        original=self.root/'03_ai_measurement/headline-measurement-v1/human_annotation/human_sample_manifest.csv'
        if original.exists():
            human=pd.read_csv(original,dtype=str,keep_default_na=False);human=human.loc[human.item_id.isin(ns['corpus'].item_id)]
        else:human=pd.DataFrame(columns=['item_id','platform','source','split'])
        ns['human']=human
        run_cell(N3,9,ns);run_cell(N3,11,ns)
        self.scoring_namespace=ns
        if score:
            if not self.secrets.get('openai'):raise ValueError('OpenAI key required to score new items')
            self.score_pending(ns)
        self.media=aggregate(ns)
        print('Media aggregated:',self.media,flush=True)
    def score_pending(self,ns):
        from openai import OpenAI
        from jsonschema import validate
        import concurrent.futures as cf
        pending=[ns['model_input'](r) for _,r in ns['cohort'].iterrows()]
        pending=[i for i in pending if ns['input_key'](i) not in ns['CACHE'] and ns['input_key'](i) not in ns['UNRESOLVED']]
        pending=pending[:self.c['max_new_items']]
        print('New items selected for this cycle:',len(pending),flush=True)
        batches=iter([pending[i:i+ns['BATCH_SIZE']] for i in range(0,len(pending),ns['BATCH_SIZE'])]);lock=threading.Lock()
        def worker(items):
            request_hash=ns['digest'](ns['CONFIG_HASH']+json.dumps(items,sort_keys=True,ensure_ascii=False));path=ns['CALLS']/(request_hash+'.json')
            token='ai:'+request_hash
            text=json.dumps(items,ensure_ascii=False)
            reserve=(len((ns['SYSTEM']+text+json.dumps(ns['SCHEMA'])).encode())+10000)/1e6*self.c['input_price']+ns['MAX_OUTPUT_TOKENS']/1e6*self.c['output_price']
            self.ledger.reserve(token,'openai',reserve)
            record=dict(status='requesting',config_hash=ns['CONFIG_HASH'],inputs=items,budget_usd=reserve,timestamp_utc=datetime.now(timezone.utc).isoformat())
            atomic(path,record)
            try:
                with OpenAI(api_key=self.secrets['openai'],max_retries=0,timeout=180) as client:
                    response=client.responses.create(model=ns['MODEL'],input=[dict(role='system',content=ns['SYSTEM']),dict(role='user',content=text)],reasoning={'effort':'none'},text={'format':dict(type='json_schema',name='economic_item_labels',strict=True,schema=ns['SCHEMA'])},max_output_tokens=ns['MAX_OUTPUT_TOKENS'],store=False)
                record['raw_response']=response.model_dump(mode='json')
                if response.usage:
                    usage=response.usage.model_dump(mode='json');cost=(usage.get('input_tokens',0)*self.c['input_price']+usage.get('output_tokens',0)*self.c['output_price'])/1e6
                    record.update(usage=usage,budget_usd=cost);self.ledger.finish(token,cost)
                atomic(path,record)
                if response.status!='completed':raise ValueError('Incomplete AI response retained')
                output=json.loads(response.output_text);validate(output,ns['SCHEMA'])
                got=[r['item_id'] for r in output['items']]
                if len(got)!=len(set(got)) or set(got)!={i['item_id'] for i in items}:raise ValueError('Output ID set differs from input')
                lookup={i['item_id']:i for i in items};results=[]
                for label in output['items']:
                    item=lookup[label['item_id']];issues=ns['evidence_problems'](label,item['text']);logical=[]
                    if label['political_attribution'] in ['Neither','Not applicable'] and (label['attribution_target'] or label['attribution_voice']!='Not applicable'):logical=['Attribution inconsistency']
                    results.append(dict(input_key=ns['input_key'](item),item_id=item['item_id'],labels=label,status='warning' if issues or logical else 'ok',evidence_errors=issues,logic_errors=logical,returned_model=response.model,request_file=path.name))
                record.update(status='completed',results=results);atomic(path,record)
                with lock:
                    for r in results:ns['CACHE'][r['input_key']]=r
                return len(items)
            except Exception as exc:
                # Explicit server rejection with no response usage is not a completed inference.
                if getattr(exc,'status_code',None) in [400,401,403,404,429] and 'raw_response' not in record:
                    record['budget_usd']=0.;self.ledger.finish(token,0.,'rejected')
                record.update(status='failed_or_uncertain',error_type=type(exc).__name__,error_message=self.redact(str(exc))[:700]);atomic(path,record)
                raise RuntimeError(type(exc).__name__+': '+self.redact(str(exc))[:300]) from None
        done=0
        with cf.ThreadPoolExecutor(max_workers=self.c['workers']) as executor:
            active=set()
            def add():
                batch=next(batches,None)
                if batch is not None:active.add(executor.submit(worker,batch));return True
                return False
            for _ in range(self.c['workers']):add()
            stopped=False;errors=[]
            while active:
                finished,_=cf.wait(active,return_when=cf.FIRST_COMPLETED)
                for f in finished:
                    active.remove(f)
                    try:done+=f.result();print('Scored new items:',done,flush=True)
                    except Exception as exc:stopped=True;errors.append(str(exc));print('Stopping new AI requests; finishing in-flight batches.',flush=True)
                if not stopped:
                    while len(active)<self.c['workers'] and add():pass
            if errors:
                self.media=aggregate(ns) # Publish successful labels even when a later batch fails.
                raise RuntimeError(errors[0])
    def regression_stage(self):
        info=latest((self.root/'01_economic_baseline/processed').glob('*/monthly_information_sets.csv'))
        macro=info.parent;results=self.root/'01_economic_baseline/results'/macro.name
        media=self.media/'media_monthly_for_section4.csv' if self.media else latest((self.root/'03_ai_measurement').glob('**/media_monthly_for_section4.csv'))
        ns=context()
        # display import is available via requirements; strip it so worker summaries stay compact.
        override=dict(ROOT=self.root,SNAPSHOT=macro.name,MEDIA_PATH=media,ECON_PATH=info,OUTCOMES_PATH=macro/'survey_forecast_outcomes.csv',BASE_PRED_PATH=results/'out_of_sample_predictions.csv',LAST_COMPLETE_MONTH=self.c['complete_through'])
        for i,c in enumerate(cells(N4)):
            if c['cell_type']=='code':
                print('Regression cell',i,flush=True)
                execute(''.join(c['source']).replace('from IPython.display import display',''),ns,override)
        self.analysis=ns['OUT'];self.macro=macro;self.media=media.parent
    def publish(self):
        export=self.ws/'exports';export.mkdir(parents=True,exist_ok=True)
        def copy(src,dest):
            src=Path(src)
            if src.exists():shutil.copy2(src,export/dest)
        try:
            info=latest((self.root/'01_economic_baseline/processed').glob('*/monthly_information_sets.csv'));macro=self.macro or info.parent
            copy(macro/'monthly_current_official.csv','survey_current.csv')
            copy(self.root/'01_economic_baseline/results'/macro.name/'out_of_sample_predictions.csv','baseline_predictions.csv')
        except FileNotFoundError:pass
        try:
            media=self.media or latest((self.root/'03_ai_measurement').glob('**/media_monthly_for_section4.csv')).parent
            for name,dest in [('media_monthly_for_section4.csv','media_monthly.csv'),('monthly_media_by_outlet.csv','media_outlets.csv'),('monthly_scoring_readiness.csv','scoring_readiness.csv')]:copy(media/name,dest)
        except FileNotFoundError:pass
        try:
            analysis=self.analysis or latest((self.root/'04_association_analysis').glob('*/forecast_performance.csv')).parent
            for name in ['forecast_performance.csv','rolling_forecasts.csv','media_associations_hac.csv','residual_diagnostics.csv','sensitivity_common_dates.csv']:copy(analysis/name,name)
        except FileNotFoundError:analysis=None
        oldstudy=self.root/'03_ai_measurement/headline-measurement-v1'
        copy(oldstudy/'economic_event_register.csv','events.csv')
        for key,filename in [('human_agreement.csv','human_agreement.csv'),('heldout_summary_metrics.csv','human_validation.csv')]:
            candidates=list(oldstudy.glob('model_runs/*/'+key))
            if candidates and not (export/filename).exists():copy(latest(candidates),filename)
        atomic(export/'metadata.json',dict(snapshot=self.asof,complete_through=self.c['complete_through'],analysis_run=analysis.name if analysis else 'Unavailable',job_id=self.job_id,updated_utc=datetime.now(timezone.utc).isoformat()))
    def run(self,stages):
        actions={'macro':self.macro_stage,'news_dry_run':lambda:self.news_stage(True),'news':self.news_stage,'twitter':self.x_stage,'score':self.scoring_stage,'aggregate':lambda:self.scoring_stage(False),'regression':self.regression_stage}
        for stage in stages:
            print('START',stage,flush=True);atomic(self.job/'status.json',dict(status='running',stage=stage,job_id=self.job_id))
            actions[stage]();self.publish();print('DONE',stage,flush=True)
        atomic(self.job/'status.json',dict(status='completed',job_id=self.job_id));print('REFRESH COMPLETE',flush=True)

def main():
    payload=json.load(sys.stdin);ws=Path(payload['workspace']);ws.mkdir(parents=True,exist_ok=True)
    p=Pipeline(ws,payload['config'],payload.get('secrets',{}))
    lock=ws/'refresh.lock'
    try:
        with lock.open('x') as f:f.write(str(os.getpid()))
    except FileExistsError:raise RuntimeError('A workspace refresh lock exists; stop the old worker or inspect it before another refresh')
    try:p.run(payload['stages'])
    except Exception as exc:
        message=p.redact(type(exc).__name__+': '+str(exc));atomic(p.job/'status.json',dict(status='failed',error=message,job_id=p.job_id));print('REFRESH FAILED:',message,flush=True);sys.exit(1)
    finally:lock.unlink(missing_ok=True)
if __name__=='__main__':main()
