from pathlib import Path
from datetime import datetime,timezone
import importlib.util,json,os,time,uuid
import pandas as pd
import streamlit as st
from controller import Job,import_archive,export_workspace
from seed import initialize_seed

APP=Path(__file__).resolve().parent
st.set_page_config(page_title='Economic sentiment research monitor',page_icon='📊',layout='wide')
st.title('Economic sentiment research monitor')
st.caption('Historical evidence, media coverage and controlled refreshes')
if 'workspace_id' not in st.session_state:st.session_state.workspace_id=uuid.uuid4().hex
storage=Path(os.environ.get('DASHBOARD_WORKSPACES',str(APP/'workspaces')))
ws=storage/st.session_state.workspace_id;ws.mkdir(parents=True,exist_ok=True)
initialize_seed(APP,ws)
if 'credentials' not in st.session_state:st.session_state.credentials={}
if 'refresh_config' not in st.session_state:
    today=datetime.now(timezone.utc).date();complete=(pd.Timestamp(today).to_period('M')-1).to_timestamp().date()
    st.session_state.refresh_config=dict(as_of=str(today),start=str(pd.Timestamp(today).replace(day=1).date()),end_exclusive=str(today),complete_through=str(complete),monitor_start='2026-07',gcp_project='',budgets=dict(bigquery=5.,twitter=2.,openai=5.),bq_price=6.25,tweet_price=.00015,input_price=.75,output_price=4.50,model='gpt-5.4-mini-2026-03-17',news_quota=10,tweet_quota=100,x_monthly_target=600,x_spacing=5.1,workers=4,max_new_items=500)
job=st.session_state.get('job');running=bool(job and job.running())
tabs=st.tabs(['Monitor','Configuration','Refresh analysis','Data and methods'])
with tabs[1]:
    st.subheader('Credentials and refresh settings')
    st.caption('Keys are held in this browser session’s server memory and passed only to its worker. They are not saved in config files, downloadable exports or source code. The hosting operator can access the server; use a trusted/private deployment.')
    cfg=st.session_state.refresh_config;secret=st.session_state.credentials
    with st.form('configuration'):
        left,right=st.columns(2)
        with left:
            twitter=st.text_input('twitterapi.io key',value=secret.get('twitter',''),type='password')
            openai=st.text_input('OpenAI API key',value=secret.get('openai',''),type='password')
            fred=st.text_input('FRED API key',value=secret.get('fred',''),type='password')
            bea=st.text_input('BEA API key',value=secret.get('bea',''),type='password')
            gcp=st.text_input('GCP billing project ID',value=cfg['gcp_project'])
            service_account=st.file_uploader('GCP service-account JSON (optional if host has ADC)',type=['json'])
            st.caption('Project ID is not authentication. Existing Application Default Credentials are used if no service-account JSON is supplied.')
        with right:
            as_of=st.date_input('Economic retrieval cutoff',value=pd.Timestamp(cfg['as_of']).date())
            start=st.date_input('News/X refresh start (UTC)',value=pd.Timestamp(cfg['start']).date())
            end=st.date_input('News/X end-exclusive (UTC)',value=pd.Timestamp(cfg['end_exclusive']).date())
            complete=st.date_input('Last complete analysis month',value=pd.Timestamp(cfg['complete_through']).date())
            model=st.text_input('Frozen scoring model',value=cfg['model'])
            workers=st.number_input('Concurrent AI batches',1,8,value=cfg['workers'])
            max_items=st.number_input('Maximum new AI items per cycle',8,50000,value=cfg['max_new_items'],step=8)
        st.markdown('**Cumulative budgets for new refreshes in this workspace (USD)**')
        a,b,c=st.columns(3)
        bq_cap=a.number_input('BigQuery cap',min_value=0.,value=cfg['budgets']['bigquery'],step=1.)
        x_cap=b.number_input('twitterapi.io cap',min_value=0.,value=cfg['budgets']['twitter'],step=1.)
        ai_cap=c.number_input('OpenAI cap',min_value=0.,value=cfg['budgets']['openai'],step=1.)
        st.caption('Limits include pending reserves and do not reset on each cycle. Historical costs before import are not counted. These are local estimated guards, not provider-enforced account caps.')
        with st.expander('Sampling and accounting assumptions'):
            nq=st.number_input('News items per outlet/month',1,1000,value=cfg['news_quota'])
            tq=st.number_input('X items scored per month',1,10000,value=cfg['tweet_quota'])
            xt=st.number_input('X returned-post target per complete month',20,10000,value=cfg['x_monthly_target'],step=20)
            spacing=st.number_input('Seconds between X requests',min_value=.11,value=cfg['x_spacing'],step=.1)
            st.caption('Keep spacing consistent with your provider entitlement. Collection retains one page per fixed window; targets can be missed.')
            bq_price=st.number_input('BigQuery USD per TiB assumption',min_value=.01,value=cfg['bq_price'])
            tweet_price=st.number_input('USD per returned X post assumption',min_value=.000001,value=cfg['tweet_price'],format='%.6f')
            in_price=st.number_input('OpenAI input USD per million tokens assumption',min_value=.01,value=cfg['input_price'])
            out_price=st.number_input('OpenAI output USD per million tokens assumption',min_value=.01,value=cfg['output_price'])
            st.caption('Defaults reproduce the project’s saved accounting assumptions; verify provider/account pricing before enabling paid stages. Changing the model may require schema/reasoning compatibility changes.')
        save=st.form_submit_button('Apply configuration',disabled=running)
    if save:
        try:
            if start>=end:raise ValueError('Collection start must precede end-exclusive date')
            if complete.day!=1:raise ValueError('Choose the first day of the last completed month')
            if pd.Timestamp(complete)>=pd.Timestamp(as_of).to_period('M').to_timestamp():raise ValueError('The analysis cutoff must be a completed month before retrieval cutoff')
            credentials=dict(twitter=twitter,openai=openai,fred=fred,bea=bea)
            if service_account is not None:
                info=json.loads(service_account.getvalue())
                if info.get('type')!='service_account':raise ValueError('Expected service-account JSON')
                credentials['gcp_service_account']=info
            elif secret.get('gcp_service_account'):credentials['gcp_service_account']=secret['gcp_service_account']
            st.session_state.credentials=credentials
            st.session_state.refresh_config=dict(as_of=str(as_of),start=str(start),end_exclusive=str(end),complete_through=str(complete),monitor_start='2026-07',gcp_project=gcp.strip(),budgets=dict(bigquery=bq_cap,twitter=x_cap,openai=ai_cap),bq_price=bq_price,tweet_price=tweet_price,input_price=in_price,output_price=out_price,model=model.strip(),news_quota=int(nq),tweet_quota=int(tq),x_monthly_target=int(xt),x_spacing=float(spacing),workers=int(workers),max_new_items=int(max_items))
            st.success('Settings applied for this session. No requests made.')
        except Exception as exc:st.error(str(exc))
with tabs[2]:
    st.subheader('Refresh pipeline')
    options={'Economic baseline (FRED/BEA/BLS/Michigan)':'macro','News dry-run only (no paid query)':'news_dry_run','Collect news (BigQuery paid queries)':'news','Collect X posts (twitterapi.io paid requests)':'twitter','Score new items and aggregate (OpenAI paid requests)':'score','Aggregate existing cached labels only':'aggregate','Refit regressions from saved monthly files':'regression'}
    selected=st.multiselect('Stages to run in order',list(options),default=['Aggregate existing cached labels only','Refit regressions from saved monthly files'])
    stages=[options[x] for x in selected]
    paid=any(x in stages for x in ['news','twitter','score'])
    allow=st.checkbox('Enable the selected paid stages under the configured cumulative budgets',value=False) if paid else True
    order=['macro','news_dry_run','news','twitter','score','aggregate','regression']
    if 'score' in stages and 'aggregate' in stages:st.caption('The score stage already aggregates; redundant aggregate stage is skipped.')
    def start_job(rolling=False):
        cfg=dict(st.session_state.refresh_config)
        if rolling:
            today=datetime.now(timezone.utc).date()
            cfg['as_of']=str(today);cfg['end_exclusive']=str(today)
            cfg['start']=str((pd.Timestamp(today)-pd.Timedelta(days=30)).replace(day=1).date())
            cfg['complete_through']=str((pd.Timestamp(today).to_period('M')-1).to_timestamp().date())
        ordered=[x for x in order if x in stages and not(x=='aggregate' and 'score' in stages)]
        if not ordered:raise ValueError('Select at least one stage')
        credentials=st.session_state.credentials
        required={'macro':['fred','bea'],'twitter':['twitter'],'score':['openai']}
        for stage in ordered:
            for key in required.get(stage,[]):
                if not credentials.get(key):raise ValueError(f'Missing {key} credential in Configuration')
        if any(x in ordered for x in ['news','news_dry_run']) and not cfg.get('gcp_project'):raise ValueError('Enter a GCP project ID and authentication')
        st.session_state.job=Job(ws,cfg,credentials,ordered);st.session_state.last_launch=time.time()
    if st.button('Run selected refresh',type='primary',disabled=running or not allow):
        try:start_job();st.rerun()
        except Exception as exc:st.error(str(exc))
    auto=st.checkbox('Enable timed monitoring while this session is active',value=False)
    advance_dates=st.checkbox('Advance cutoff and use a rolling last-30-days collection window for timed cycles',value=True)
    interval=st.number_input('Hours between refresh cycles',min_value=1.,max_value=168.,value=24.)
    st.caption('Timed cycles use the selected stages, configured settings and cumulative budgets; dates advance only if the option above is selected. Advance the configured date window when appropriate. Run one refresh to start the timer. This is not an unattended scheduler: closing/suspending the session or restarting the host stops monitoring.')
    @st.fragment(run_every='10s')
    def monitor_job():
        j=st.session_state.get('job')
        if auto and allow and stages and not(j and j.running()) and time.time()-st.session_state.get('last_launch',time.time())>=interval*3600:
            try:start_job(rolling=advance_dates);j=st.session_state.job
            except Exception as exc:st.error(str(exc));st.session_state.last_launch=time.time()
        if j:
            st.write('Running' if j.running() else f'Finished (exit code {j.code()})')
            st.code(j.tail() or 'Starting worker…',language='text')
            if j.running() and st.button('Stop submitting work / terminate worker'):
                j.stop();st.warning('Worker terminated. In-flight provider requests may finish and retain reserves. Inspect unresolved ledger entries before retrying; do not clear reserves blindly.')
        ledger=ws/'refresh_ledger.json'
        if ledger.exists():
            records=json.loads(ledger.read_text());summary=[]
            for kind,cap in st.session_state.refresh_config['budgets'].items():
                amount=sum(r['amount'] for r in records.values() if r['kind']==kind)
                summary.append(dict(provider=kind,spent_or_reserved=amount,cap=cap))
            st.dataframe(pd.DataFrame(summary),hide_index=True)
        if (ws/'refresh.lock').exists() and not(j and j.running()):
            st.info('A worker lock remains after interruption. The button below only removes this session’s stale process lock; paid request reserves remain intact.')
            if st.button('Release stale process lock'):
                # Only release if the recorded process demonstrably no longer exists.
                try:
                    pid=int((ws/'refresh.lock').read_text());os.kill(pid,0)
                    st.error('Recorded worker process still exists; lock retained.')
                except ProcessLookupError:(ws/'refresh.lock').unlink();st.success('Stale lock removed; reserves retained.')
                except (ValueError,PermissionError):st.error('Cannot verify lock owner; inspect host process state.')
    monitor_job()
with tabs[0]:
    st.subheader('Research dashboard')
    panel=st.selectbox('View',['Sentiment and gap','Media measures','Coverage and missingness','Model performance','Human validation','Events and limitations'])
    cols=st.columns(3);platform=cols[0].selectbox('Media',['Both','News','X']);start=cols[1].date_input('Display from',value=pd.Timestamp('2019-10-01').date());end=cols[2].date_input('Display through',value=pd.Timestamp(st.session_state.refresh_config['complete_through']).date())
    if st.button('Reload displayed outputs'):st.rerun()
    if not (ws/'exports').exists():st.info('Import your project seed under Data and methods, or run refresh stages. No example values are presented as your results.')
    else:
        spec=importlib.util.spec_from_file_location('private_view_'+st.session_state.workspace_id,APP/'viewer.py');view=importlib.util.module_from_spec(spec);spec.loader.exec_module(view)
        view.DATA=ws/'exports';meta=view.DATA/'metadata.json';metadata=json.loads(meta.read_text()) if meta.exists() else {}
        view.SNAPSHOT=metadata.get('snapshot',st.session_state.refresh_config['as_of']);view.COMPLETE_THROUGH=metadata.get('complete_through',st.session_state.refresh_config['complete_through'])
        try:view.draw_dashboard(panel,platform,str(start),str(end))
        except Exception as exc:st.error('Data unavailable or incompatible: '+str(exc))
with tabs[3]:
    st.subheader('Import existing work')
    seed=st.file_uploader('Project seed ZIP or earlier dashboard_data.zip',type=['zip'])
    if st.button('Import data',disabled=running or seed is None):
        try:count=import_archive(seed.getvalue(),ws);st.success(f'Imported {count} new data files. Existing files retained.');st.rerun()
        except Exception as exc:st.error(str(exc))
    st.markdown('**Add completed human-validation outputs**')
    agreement_upload=st.file_uploader('Human agreement CSV',type=['csv'],key='agreement_csv')
    validation_upload=st.file_uploader('AI summary metrics CSV',type=['csv'],key='validation_csv')
    if st.button('Import validation outputs',disabled=running):
        try:
            import io
            for upload,name,required in [(agreement_upload,'human_agreement.csv',{'field','n','agreement','kappa'}),(validation_upload,'human_validation.csv',{'field','n','accuracy','macro_f1'})]:
                if upload:
                    frame=pd.read_csv(io.BytesIO(upload.getvalue()))
                    if not required.issubset(frame):raise ValueError('Missing required columns in '+name)
                    (ws/'exports').mkdir(exist_ok=True)
                    frame.to_csv(ws/'exports'/name,index=False)
            st.success('Validation outputs imported; original annotation files are unchanged.')
        except Exception as exc:st.error(str(exc))
    st.caption('Run export_project_seed.py in Colab to package the historical candidate data, AI cache and outputs needed to continue the analysis. An earlier dashboard-only export supports viewing, but not historical rescoring or refitting without its upstream data.')
    if st.button('Prepare download of this workspace',disabled=running):st.session_state.backup=export_workspace(ws)
    if st.session_state.get('backup'):st.download_button('Download workspace data',st.session_state.backup,file_name='research_workspace.zip',mime='application/zip')
    st.markdown('''**Methods and interpretation**
- Bundled Modules 01–05 preserve the coding guide, vocabulary, sources, baseline and regression specifications.
- Refresh adapters retain US-focused and geographically unclear keyword candidates; analytical aggregates use coded Relevant and US/US-linked items.
- New input snapshots create a versioned measurement study. Existing completed predictions are reused only when their input/configuration hashes match.
- All figures describe content supply, not individual exposure. Engagement is not respondent exposure.
- Factual calibration and demographic comparisons remain unavailable without additional evidence/data. Human validation retains its actual sample size and AI-adjudication disclosure.
- The monitored period and cutoff are explicit. Campaign timing alone does not identify an election effect.
- Erroring/uncertain paid requests are saved and not retried automatically. Paid-stage errors stop new submissions. Never remove request ledgers merely to rerun.
- Active-session monitoring does not provide persistent server scheduling. Use a private host with persistent disk and a separate scheduler for unattended operation; it must load credentials from the host’s secret manager.
''')
    st.caption('Workspace data is isolated by session ID. Browser/session loss creates a new workspace; export a backup or configure persistent host storage. No entered keys are included in that backup.')
    with st.expander('Frozen source selection and vocabulary'):st.json(json.loads((APP/'vocabulary.json').read_text()))
