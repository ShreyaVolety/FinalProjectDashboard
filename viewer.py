from pathlib import Path
import json, os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st

DATA=Path(os.environ.get('DASHBOARD_DATA_DIR',str(Path(__file__).parent/'data')))
def read_optional(path):
    if not path.exists():return pd.DataFrame()
    try:return pd.read_csv(path)
    except pd.errors.EmptyDataError:return pd.DataFrame()

def load_dashboard():
    metadata_path=DATA/'metadata.json'
    metadata=json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    files={
      'baseline':'baseline_predictions.csv','survey':'survey_current.csv',
      'media':'media_monthly.csv','outlets':'media_outlets.csv','readiness':'scoring_readiness.csv',
      'agreement':'human_agreement.csv','validation':'human_validation.csv','events':'events.csv',
      'claims':'claims.csv','performance':'forecast_performance.csv','forecasts':'rolling_forecasts.csv',
      'associations':'media_associations_hac.csv','diagnostics':'residual_diagnostics.csv',
      'sensitivity':'sensitivity_common_dates.csv'}
    d={'analysis_folder':metadata.get('analysis_run','Not supplied')}
    for key,name in files.items():
        f=read_optional(DATA/name)
        for column in ['month','observation_month','analysis_month']:
            if column in f:
                f[column]=pd.to_datetime(f[column],errors='coerce')
                f=f.loc[f[column].le(pd.Timestamp(COMPLETE_THROUGH))].copy()
        d[key]=f
    return d

def note(text):st.markdown(text)

def draw_dashboard(panel,platform,start,end):
    d=load_dashboard()
    lo=pd.Timestamp(start);hi=pd.Timestamp(end)
    def window(frame,col='month'):
        return frame.loc[frame[col].between(lo,hi)].sort_values(col) if col in frame else frame
    note(f'**Snapshot:** {SNAPSHOT}. **Completed-month limit:** {COMPLETE_THROUGH}. '
         f'**Display window:** {start} to {end}.')
    if panel=='Sentiment and gap':
        b=d['baseline']
        if b.empty:note('Economic baseline outputs unavailable.');return
        b=window(b.loc[b.target.eq('sentiment')&b.model.eq('economic_core')],'observation_month')
        if b.empty:note('No forecasts in selected window.');return
        fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True)
        axes[0].plot(b.observation_month,b.actual,color='black',label='First-archived sentiment')
        axes[0].plot(b.observation_month,b.predicted,label='Economic-only OOS prediction')
        if {'pi_lower','pi_upper'}.issubset(b):
            axes[0].fill_between(b.observation_month,pd.to_numeric(b.pi_lower,errors='coerce'),pd.to_numeric(b.pi_upper,errors='coerce'),alpha=.2,label='Nominal 95% interval')
        axes[0].legend();axes[0].set_ylabel('Index points')
        axes[1].plot(b.observation_month,b.sentiment_gap);axes[1].axhline(0,color='black',lw=.8)
        axes[1].set_ylabel('Observed minus predicted');fig.tight_layout();st.pyplot(plt.gcf());plt.close(plt.gcf())
        note('Negative gaps are model-dependent unexplained sentiment, not proof of bias. Nominal intervals can under-cover; consult performance.')
        survey=window(d['survey'],'observation_month')
        cols=[c for c in ['sentiment','current_conditions','expectations'] if c in survey]
        if cols and len(survey):
            survey.set_index('observation_month')[cols].plot(figsize=(12,3),title='Survey components: current official history (descriptive)');st.pyplot(plt.gcf());plt.close(plt.gcf())
    elif panel=='Media measures':
        m=window(d['media'])
        if m.empty:note('Monthly media export unavailable.');return
        families={
            'Tone':['negative_share','positive_share','emotional_share'],
            'Framing':['price_levels_share','household_frame_share','future_frame_share'],
            'Salience':['layoffs_share','hiring_share','rising_prices_share','falling_inflation_share','growth_expansion_share','recession_risk_share'],
            'Political attribution':['blame_share']}
        selected=['news','x'] if platform=='Both' else [platform.lower()]
        for title,measures in families.items():
            columns=[p+'_'+measure for p in selected for measure in measures if p+'_'+measure in m]
            if columns:
                ax=m.set_index('month')[columns].plot(figsize=(12,3.5),title=title)
                ax.set_ylabel('Share');ax.set_ylim(0,1);ax.legend(fontsize=8,ncol=2);st.pyplot(plt.gcf());plt.close(plt.gcf())
        note('News: equal averages across contributing outlets. X: pooled eligible sampled posts. Denominators exclude unclassifiable labels; Mixed tone is included as classifiable. Rates do not measure exposure.')
        note('**Factual calibration: not assessed.** Official-claim detection is not verification; no accuracy time series is displayed.')
    elif panel=='Coverage and missingness':
        m=window(d['media'])
        if not m.empty:
            for columns,title in [(['news_scoring_completion','x_scoring_completion'],'Scoring completion'),(['news_eligible_items','x_eligible_items'],'Eligible scored content'),(['news_eligible_sources'],'Contributing news outlets')]:
                columns=[c for c in columns if c in m]
                if columns:m.set_index('month')[columns].plot(figsize=(12,3),title=title);st.pyplot(plt.gcf());plt.close(plt.gcf())
            st.dataframe(m[['month']+[c for c in m if c.endswith(('scoring_completion','eligible_items'))]].tail(12))
        o=window(d['outlets'],'analysis_month')
        if len(o):
            matrix=o.pivot(index='source',columns='analysis_month',values='eligible_items')
            fig,ax=plt.subplots(figsize=(13,max(4,len(matrix)*.3)))
            image=ax.imshow(np.ma.masked_invalid(matrix.to_numpy(float)),aspect='auto',cmap='Blues')
            ax.set_yticks(range(len(matrix)));ax.set_yticklabels(matrix.index)
            tick=list(range(0,len(matrix.columns),max(1,len(matrix.columns)//10)))
            ax.set_xticks(tick);ax.set_xticklabels([matrix.columns[i].strftime('%Y-%m') for i in tick],rotation=45)
            ax.set_title('Eligible scored headlines by outlet/month; blanks = unavailable, not zero')
            fig.colorbar(image,ax=ax,label='Headlines');fig.tight_layout();st.pyplot(plt.gcf());plt.close(plt.gcf())
        note('These are counts in the scoring sample, not total output by each publisher. Geographic-unclear content is excluded from main aggregates. Failed requests and source composition can affect comparability.')
    elif panel=='Model performance':
        note('Performance tables use the full saved common evaluation window; display-date filters do not refit models.')
        for key,title in [('performance','Out-of-sample accuracy and coverage'),('associations','Media associations with HAC uncertainty and Holm adjustment'),('diagnostics','Residual diagnostics'),('sensitivity','Sensitivity checks on common dates')]:
            note('**'+title+'**');st.dataframe(d[key]) if len(d[key]) else note('Not available.')
        f=window(d['forecasts'])
        if len(f):
            chart=f.pivot(index='month',columns='model',values='predicted')
            chart=chart[[c for c in ['M1_economics','M2_plus_media','M3_plus_controls','last_available'] if c in chart]]
            ax=chart.plot(figsize=(12,4));f.drop_duplicates('month').set_index('month').actual.plot(ax=ax,color='black',lw=2,label='Observed');ax.legend(fontsize=8);st.pyplot(plt.gcf());plt.close(plt.gcf())
    elif panel=='Human validation':
        a=d['agreement'];v=d['validation']
        if len(a) and 'n' in a and pd.to_numeric(a.n,errors='coerce').gt(0).any():
            note('**Human agreement**');st.dataframe(a.loc[a.grouping.eq('all')] if 'grouping' in a else a)
        else:note('Human agreement pending: no nonempty completed-label results found.')
        if len(v):
            note('**Held-out AI performance**');st.dataframe(v.loc[v.grouping.eq('overall')] if 'grouping' in v else v)
        else:note('Held-out AI accuracy pending.')
        note('Report the actual shared human sample and field-specific denominators from the tables. The assignment requires 300 independently double-labeled items. Disclose any AI-assisted adjudication separately; preserve original human agreement.')
    else:
        e=d['events']
        if len(e):st.dataframe(e)
        else:note('No populated verified event register. Candidate-release plots do not establish matched events.')
        note("""**Scope and causal limits**
- No respondent exposure data or audience weighting. Likes/reposts do not establish exposure.
- Demographic and political-affiliation subgroup estimates unavailable: no suitable subgroup inputs supplied.
- Survey-method comparability has not been formally adjusted here. Document Michigan collection-method changes before interpreting breaks.
- Campaign timing alone does not identify an election effect. This snapshot ends before election day.

**Prospective updates:** refresh Modules 01–02; score only new items with frozen settings and explicit budget; refresh validation and Module 03 aggregates; rerun Module 04; then press Refresh here. Preserve vintages, cutoff, configuration hashes and prior results. Advance completed-month cutoff only after that month is complete. No automatic paid updates occur.""")
    note('Analysis folder: `'+d['analysis_folder']+'`')

def main():
    st.set_page_config(page_title='Economic sentiment monitor',page_icon='📊',layout='wide')
    st.title('Economic sentiment monitor')
    st.caption('Economics, media coverage and consumer perceptions | Research dashboard')
    metadata_path=DATA/'metadata.json'
    metadata=json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    global SNAPSHOT, COMPLETE_THROUGH
    SNAPSHOT=metadata.get('snapshot','2026-10-16')
    COMPLETE_THROUGH=metadata.get('complete_through','2026-09-01')
    if not (DATA/'media_monthly.csv').exists():
        st.info('Add exported CSVs to the data/ folder. Run export_dashboard_data.py in Colab, download dashboard_data.zip, and extract it beside app.py.')
    with st.sidebar:
        st.header('Explore')
        panel=st.selectbox('Panel',['Sentiment and gap','Media measures','Coverage and missingness','Model performance','Human validation','Events and limitations'])
        platform=st.selectbox('Media platform',['Both','News','X'])
        start=st.date_input('From',value=pd.Timestamp('2019-10-01').date())
        end=st.date_input('Through',value=pd.Timestamp(COMPLETE_THROUGH).date())
        st.caption('Date filters select views; they do not refit models. Performance tables retain the full saved evaluation window.')
        st.button('Refresh saved data')
    if start>end:
        st.error('From date must precede Through date.');return
    try:
        draw_dashboard(panel,platform,str(start),str(end))
    except (KeyError,ValueError,TypeError) as exc:
        st.error('A data file is missing required fields or has incompatible values: '+str(exc))
    with st.expander('Download the saved monthly media data'):
        p=DATA/'media_monthly.csv'
        if p.exists():st.download_button('Download CSV',p.read_bytes(),file_name='media_monthly.csv',mime='text/csv')
    st.caption('Refresh reloads local exports only. Data collection and model updates run separately; no API calls are made by this app.')

if __name__=='__main__':main()
