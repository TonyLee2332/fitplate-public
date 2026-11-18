# FitPlate on Render

Follow **DEPLOY_RENDER.md**. This is the tested public-visitor Agent Ready application with SQLite. No Supabase changes are included.

- Hobby workspace; paid 1 CPU / 2 GB web service; one instance.
- Build: `bash deploy/build.sh`
- Start: `bash deploy/start.sh`
- Persistent disk: 1 GB at `/var/data`.
- Data setting: `FITPLATE_DATA_DIR=/var/data/fitplate`.
- Health check: `/_stcore/health`.

Set administrator AI credentials in Render Environment. Visitors do not register or configure AI. The build installs CPU PyTorch and downloads the pinned depth model.

The optional `render.yaml` Blueprint describes the same configuration. Use either manual creation or the Blueprint, not both. Apply service configuration in Render before sharing the public URL.

Photos are decoded by content, corrected for orientation and converted to a metadata-free JPEG before AI, preview and depth processing. JPEG/JFIF, PNG, HEIC/HEIF, AVIF, WebP, GIF (first frame), TIFF, BMP and other installed Pillow image decoders are supported. Uploads are bounded at 20 MB and 80 megapixels; arbitrary RAW, SVG, PDF or damaged files are not guaranteed to decode. WAV/MP3 voice attachments retain the transcription service limits.

FitPlate imposes no daily AI allowance, even if historical daily-limit environment variables remain set. Two simultaneous public AI requests and one photo decode are permitted to protect availability. Provider billing and provider-side restrictions still apply.
