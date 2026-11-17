# Deploy FitPlate on Render

## Cost

Hobby is the free workspace plan, not free compute. Use a paid 1 CPU / 2 GB service (`1c-2g`, legacy Standard) with a 1 GB persistent disk. Current published base cost is approximately USD 25.25/month: USD 25 compute and USD 0.25 disk. API usage, overages and tax are separate. Confirm the actual checkout total in Render.

## 1. Upload to GitHub

Create a private repository named `fitplate-public`. Upload the contents of this folder, not the ZIP itself and not an extra containing folder. At repository root you must see `app.py`, `.python-version`, `render.yaml`, `requirements-lock.txt`, `deploy/`, `fitplate/`, `assets/` and `.streamlit/`. Commit to `main`.

Exclude `.venv`, `__pycache__`, real `secrets.toml` files, root runtime `data/` and private backups. Keep `fitplate/data/`, which contains the food references. The largest included file is approximately 20 MB. The depth model is downloaded during build, so it does not need to be committed to GitHub.

## 2. Create a Render Web Service

In the Hobby workspace, choose New -> Web Service -> Git Provider. Connect GitHub and select the repository.

| Field | Value |
|---|---|
| Name | fitplate-public or another available name |
| Region | Singapore |
| Branch | main |
| Root Directory | Blank if app.py is at repository root |
| Language | Python |
| Build Command | bash deploy/build.sh |
| Start Command | bash deploy/start.sh |
| Instance | 1 CPU / 2 GB, 1c-2g / Standard |
| Instance count | 1 |
| Health Check Path | /_stcore/health |

The `.python-version` file selects Python 3.13. There is no need for a Pro workspace or a separate database service. Public application users are not Render workspace team members.

## 3. Attach persistent storage

Add a disk under Advanced / Disks:

- Name: `fitplate-data`
- Mount path: `/var/data`
- Size: `1 GB`

Paid compute alone does not preserve filesystem changes. If the creation page does not offer disk settings, add the disk from the service Disk page after creation, wait for redeployment, and only then start acceptance testing or share the URL.

## 4. Configure environment variables

| Key | Value |
|---|---|
| DASHSCOPE_API_KEY | Existing working Model Studio API key |
| MODEL_STUDIO_WORKSPACE_ID | Existing workspace ID, without URL or domain |
| MODEL_STUDIO_REGION | Matching region, currently cn-beijing |
| FITPLATE_DATA_DIR | /var/data/fitplate |
| FITPLATE_VISITOR_DAILY_REQUESTS | 30 |
| FITPLATE_GLOBAL_DAILY_REQUESTS | 300 |
| OMP_NUM_THREADS | 1 |
| MKL_NUM_THREADS | 1 |

The existing private AI values are in `%APPDATA%/FitPlate/secrets.toml` on the development computer. Copy the three values into Render Environment, not GitHub or chat. Credentials, workspace, region, model permissions and provider credit must match.

Do not use Supabase settings or a Windows secret-file path with this package. It retains the original SQLite-backed storage.

## 5. Deploy

Review the service and disk charges, then click Create Web Service / Deploy Web Service yourself. First build may take longer while dependencies and the pinned model download.

Expected logs include successful dependency checks, `FitPlate depth model is ready.`, and startup configuration readiness. Streamlit must bind `0.0.0.0` and Render's `$PORT` (normally 10000). The prepared commands handle this. Do not use Gunicorn, Windows CMD or PowerShell as the cloud start command.

When status becomes Live, open the assigned `https://...onrender.com` address. Do not replace the existing trimodalmdd.com website or its DNS records. A new domain is not required.

## 6. Acceptance tests

1. Open the public URL without registering or entering API settings.
2. Describe two boiled eggs and 150 g cooked rice; verify quantities, review assumptions and save.
3. Reload in the same browser; the record should remain.
4. Open an incognito/different browser profile; it should have a separate empty workspace.
5. Test all three languages, photo upload, speech transcription, goals, weekly review and depth inference.
6. Monitor memory. The 2 GB instance is a starting size, not a proven capacity guarantee. Report OOM/killed errors before changing a paid plan or removing features.
7. Restart the service, then verify the original browser still has its meals and targets. Repeat after a redeploy.

The persistent directory contains visitor databases, `.visitor_key` and the AI usage ledger. Preserve the directory and signing key across updates. Anonymous access also depends on the visitor's browser storage and a stable website origin.

The real Linux build, disk, service permissions and capacity are confirmed by the first Render deployment. They were not verified on a Linux host locally. No service has been created by preparing these files.

## 7. Sharing, updates and backups

After acceptance, anyone with the public URL can use the app. Your provider account funds shared AI requests; daily request budgets are not currency spending caps or complete bot protection.

Keep the hostname stable. Moving to a custom domain changes browser storage origin; anonymous records do not automatically follow the visitor. Export/import meals when changing origin.

For updates, use the same repository, service and disk. Disk-backed deploys can briefly interrupt service. Before an update, use the service Shell:

```bash
python deploy/backup.py
```

Private backup ZIPs are stored in `/var/data/backups`. They contain consistent database snapshots and the signing key. Download them securely for off-server retention. A backup on the same disk does not protect against deletion of that disk. Do not publish backups or overwrite live databases while the application is writing.

## Troubleshooting

- Build package/wheel failure: provide the package name and sanitized error.
- Model download timeout: retry one build for a transient failure; preserve the error if repeated.
- No open port / 502: check the Start Command and `0.0.0.0:$PORT` binding.
- Startup configuration failure: check the three AI settings, absolute data path and disk permissions.
- AI 401/403: verify key, workspace/region, provider account and model permissions.
- Records disappear after restart: stop collecting real records and check the disk and path.
- Workspace verification error: investigate the signing key and hostname rather than replacing the key.
- OOM/killed: inspect actual memory usage before deciding on a larger paid plan.

## Official references

- https://render.com/docs/web-services
- https://render.com/docs/python-version
- https://render.com/docs/disks
- https://render.com/docs/compute-plans
- https://render.com/docs/configure-environment-variables
- https://render.com/pricing
