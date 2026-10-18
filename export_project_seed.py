"""Run in Colab with Drive mounted to export ONLY the pipeline inputs/caches/outputs."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import json
ROOT=Path('/content/drive/MyDrive/NLP-FinalProject')
DEST=Path('/content/project_seed.zip')
def newest(paths):
    paths=list(paths)
    return max(paths,key=lambda p:p.stat().st_mtime) if paths else None
selected=set()
# Latest complete baseline directory pair; raw official API responses are not exported.
info=newest((ROOT/'01_economic_baseline/processed').glob('*/monthly_information_sets.csv'))
if info:
    selected.update(info.parent.glob('*.csv'))
    selected.update((ROOT/'01_economic_baseline/results'/info.parent.name).glob('*.csv'))
# Historical candidate snapshots preserve your collected history without another query.
for pattern in ['**/news_headline_candidates.csv','**/x_posts_for_labeling.csv','**/source_registry.csv','**/search_terms.json','**/reviewed_news_terms.json']:
    selected.update((ROOT/'02_media_corpus').glob(pattern))
# Deterministic caches: completed/failed/uncertain states remain intact, never fabricate retries.
selected.update((ROOT/'03_ai_measurement/api_calls').glob('*.json'))
for pattern in ['**/media_monthly_for_section4.csv','**/monthly_media_by_outlet.csv','**/monthly_scoring_readiness.csv','**/human_agreement.csv','**/heldout_summary_metrics.csv','**/human_sample_manifest.csv','**/source_and_split_key.csv','**/economic_event_register.csv']:
    selected.update((ROOT/'03_ai_measurement').glob(pattern))
analysis=newest((ROOT/'04_association_analysis').glob('*/forecast_performance.csv'))
if analysis:selected.update(analysis.parent.glob('*.csv'))
# Avoid collecting credentials, source code, uploaded originals, raw official responses or notebooks.
selected={p for p in selected if p.is_file() and p.suffix in ['.csv','.json'] and not any(x in p.name.lower() for x in ['credential','service_account','secrets','api_key'])}
if not selected:raise FileNotFoundError('No project data found; check ROOT.')
with ZipFile(DEST,'w',ZIP_DEFLATED) as z:
    for p in sorted(selected):z.write(p,'project/'+str(p.relative_to(ROOT)))
    # Also add ready-to-view flat exports to avoid requiring a refresh on first launch.
    exports={}
    if info:
        exports['survey_current.csv']=info.parent/'monthly_current_official.csv'
        exports['baseline_predictions.csv']=ROOT/'01_economic_baseline/results'/info.parent.name/'out_of_sample_predictions.csv'
    monthly=newest((ROOT/'03_ai_measurement').glob('**/media_monthly_for_section4.csv'))
    if monthly:
        exports.update({'media_monthly.csv':monthly,'media_outlets.csv':monthly.parent/'monthly_media_by_outlet.csv','scoring_readiness.csv':monthly.parent/'monthly_scoring_readiness.csv'})
        for src,dest in [('human_agreement.csv','human_agreement.csv'),('heldout_summary_metrics.csv','human_validation.csv')]:exports[dest]=monthly.parent/src
    if analysis:
        for name in ['forecast_performance.csv','rolling_forecasts.csv','media_associations_hac.csv','residual_diagnostics.csv','sensitivity_common_dates.csv']:exports[name]=analysis.parent/name
    for name,p in exports.items():
        if p.exists():z.write(p,'exports/'+name)
    z.writestr('exports/metadata.json',json.dumps({'snapshot':'2026-10-16','complete_through':'2026-09-01','analysis_run':analysis.parent.name if analysis else 'Unavailable'}))
print('Exported files:',len(selected),'| ZIP MiB:',round(DEST.stat().st_size/1024**2,2))
from google.colab import files
files.download(str(DEST))
