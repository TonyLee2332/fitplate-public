# FitPlate on Render

Follow **DEPLOY_RENDER.md**. This is the tested public-visitor Agent Ready application with SQLite. No Supabase changes are included.

- Hobby workspace; paid 1 CPU / 2 GB web service; one instance.
- Build: `bash deploy/build.sh`
- Start: `bash deploy/start.sh`
- Persistent disk: 1 GB at `/var/data`.
- Data setting: `FITPLATE_DATA_DIR=/var/data/fitplate`.
- Health check: `/_stcore/health`.

Set administrator AI credentials in Render Environment. Visitors do not register or configure AI. The build installs CPU PyTorch and downloads the pinned depth model.

The optional `render.yaml` Blueprint describes the same configuration. Use either manual creation or the Blueprint, not both. Preparing this folder has not created a live service.
