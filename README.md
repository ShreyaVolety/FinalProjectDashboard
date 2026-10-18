# Integrated economic sentiment research dashboard

## What is included
- Streamlit monitor with Configuration, Refresh analysis, Data/methods and monitoring views.
- Config fields for twitterapi.io, OpenAI, FRED, BEA, GCP project and optional GCP service-account JSON.
- Modules 01–05, frozen source/vocabulary JSON, human-benchmark notebook/helpers and a native refresh adapter.
- Versioned economic snapshots; new candidate collection; hash-based AI cache reuse; monthly aggregation; Module 04 chronological regressions; display exports.
- Cumulative new-refresh spending/reservation ledger, BigQuery maximum-bytes-billed guard, bounded AI concurrency, stop-on-error and preservation of uncertain requests.
- Optional timed cycles while a browser session is active. This is not an unattended hosted scheduler.

## First use with your actual project
1. Unzip locally. Use Python 3.12.
2. Upload export_project_seed.py to your existing Colab runtime with Google Drive mounted.
3. Run `%run /content/export_project_seed.py`. Download project_seed.zip.
4. Install and start:

```bash
pip install -r requirements.txt
streamlit run app.py
```

5. In Data and methods, import project_seed.zip. Existing files are never silently overwritten.
6. View your existing outputs immediately. Under Configuration, enter credentials and apply settings.
7. Try News dry-run first. Choose only desired stages under Refresh analysis. Paid stages require the explicit enable checkbox.

A previous dashboard_data.zip can also be imported for viewing, but it lacks raw candidate input histories and AI caches needed to refresh the full historical analysis. The new seed contains those files without needing another paid historical collection. The seed contains research content and caches; keep it private and import through the app, rather than publishing it to the repository.

## Stage behavior
- **Macro:** executes the original baseline with pinned settings adapted to the host. BLS '-' values become missing, FRED date bounds are clamped to the chosen/current Chicago cutoff, and echoed credentials are redacted from saved response bodies. Source schemas must still match; an upstream change stops the run.
- **News dry-run:** schema/authentication and query-byte estimates only. No paid query is submitted.
- **News:** queries only the requested UTC window, writes cached raw title versions, and retains US-focused plus unclear keyword candidates. BigQuery project ID alone is not authentication; use the uploaded service-account credential or host ADC.
- **X:** frozen term groups, deterministic rotating two-hour windows, one page/window, English/no-retweets. The default reproduces 600 expected returned posts/month; sparse windows can miss targets. Provider rate entitlement is not inferred from your key; spacing is configurable and defaults to 5.1 seconds. One incomplete window is not called a complete calendar month.
- **Score/aggregate:** combines imported candidate snapshots with refreshed snapshots, preserving IDs/history; creates a new input-version study and reuses only exact configuration/input cache matches. The original human manifest is retained if available. Defaults to max 500 new items/cycle, four batches concurrently and the project's saved model/price assumptions. Old failed/uncertain batches are not silently retried. A failed batch stops new submissions, saves completed outputs and retains uncertain reserves. If no human manifest exists, the app does not fabricate human annotations.
- **Aggregate only:** no paid calls. Missing cached labels stay missing. News rates average outlets equally; X rates pool posts. Valid tone denominators include Mixed.
- **Regression:** reuses Module 04: 36 eligible initial training outcomes, one-month media lag, three economic/media/control models plus persistence benchmarks, common chronological months, HAC associations, Holm adjustment and sensitivity checks. Required historical economic/media rows must exist. No future outcomes enter training.

## Secrets, storage and hosting
Credentials entered in the Configuration tab stay in Streamlit session memory and are passed to a child worker through stdin. They are not placed in config JSON, command-line arguments, exported notebooks, logs or data backups. The worker runs in a separate process, so session keys do not mutate the parent server environment. Service-account JSON is used directly in memory. The host operator can access memory; only use this with a trusted/private deployment and HTTPS. Never commit credentials.

Each browser session has its own randomly named workspace. Default storage is workspaces/ under this application folder, excluded by .gitignore. Set DASHBOARD_WORKSPACES to a persistent disk directory for a durable host. Browser session loss creates a new session workspace; export/import backups to retain data. Standard ephemeral hosting restarts can lose local files. This app is intended as a private research tool, not an anonymously shared multiuser billing service.

For Streamlit Community Cloud, put app.py, requirements.txt and the other source folders at the repository root, choose app.py as entry point and select Python 3.12. Existing-data viewing is lightweight; full history ingestion and regression use more memory/time. No Drive mount is used by the hosted app. Import the seed through the UI. Data and credentials are not bundled in this code ZIP.

## Monitoring
Run one refresh, then enable timed monitoring and choose an interval. The session must remain active. With the rolling-date option, each timed cycle advances the economic cutoff and refreshes a collection window starting at the first day of the month containing UTC today minus 30 days; this may span two calendar months. Complete-month analysis advances only through the previous month. Without that option, configured dates remain fixed. Provider budgets are cumulative across cycles in that workspace; automatic monitoring cannot reset them. Existing partial-month queries can incur new scan costs when the end date advances.

For truly unattended monitoring, deploy on a persistent private server and schedule the pipeline separately with credentials loaded from that server's secret manager. No external scheduler or public deployment has been created by this package.

## Budget interpretation and recovery
Default price assumptions reproduce the prior project settings; they are estimates, not current-price guarantees. Verify account/model prices before paid work. Local caps apply only to NEW refresh costs in this workspace, not past charges before importing history. They reserve conservatively; provider bills remain authoritative. Pending reserves can make totals temporarily fall when actual usage arrives. BigQuery uses maximum_bytes_billed. Other providers do not expose a universal dollar cap; returned data/usage may exceed an assumption, so the app stops if detected.

Quota/authentication 4xx rejections without a response release the local OpenAI reserve but preserve the rejected record; these records are not automatically retried. Transport interruptions/incomplete responses retain their reserves and raw responses. Do not delete ledgers to force a retry. Stop terminates the worker; an in-flight provider request may still finish. A stale process-lock release verifies that its PID no longer exists and leaves billing reserves intact.

## Human validation
The historical project has fewer than the required 300 independent double-labeled items. The app does not upgrade AI-assisted adjudication into independent human gold. Use Data and methods to import completed human_agreement.csv and ai_summary_by_field_source.csv; retain actual denominators and scope. Updating media inputs does not recompute human agreement automatically or fabricate new gold labels. Bundled human-validation code supports a separate explicit validation workflow.

## Deliberate limits
No respondent exposure is observed; engagement is not exposure. Factual calibration, verified matched events, subgroup analysis and survey-mode break adjustments remain unassessed unless actual evidence is supplied. The viewer labels these omissions. Media lags do not prove historical availability, eliminate confounding or establish causal effects. Source/sampling comparability can change with refreshes; inspect coverage and missingness panels.

## Code validation
Offline checks cover date/path overrides, ledger concurrency, request rejection, cache protection, imports/path traversal, aggregation, model wrapper and secret redaction. Live FRED/BEA/BigQuery/X/OpenAI calls require your credentials and were not charged or exercised during package creation. Hosted UI behavior must be verified in your deployment. Save the resulting pip freeze after a successful deployment for an exact environment record.

## Official references
https://docs.streamlit.io/develop/concepts/architecture/fragments
https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state
https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization
https://docs.cloud.google.com/bigquery/docs/authentication
https://docs.twitterapi.io/api-reference/endpoint/tweet_advanced_search
https://developers.openai.com/api/reference/resources/responses/methods/create

## Automatic startup snapshot for hosting
After generating project_seed.zip in Colab, run locally:

```bash
python prepare_dashboard_seed.py /path/to/project_seed.zip
```
Deploy dashboard_seed.zip alongside app.py. Each new visitor workspace initializes
from the bundled display exports, without API keys or paid requests. Existing
workspace results are never overwritten. Only processed CSV/JSON exports are bundled;
raw caches and credentials are excluded. Review these outputs before publishing.
Alternatively place processed display CSVs and metadata.json under data/.
The code package does not include your actual project results: generate this seed first.
