# Deployment validation

Application source and assets match the public-visitor Agent Ready version (347 passing tests and 204 passing subtests). No Supabase adapter is included.

Deployment checks passed: the official Render Blueprint JSON schema, shell syntax, administrator startup preflight, rejection of a missing data path, consistent SQLite backup and signing-key restore. The backup helper explicitly closes database connections before removing temporary files.

The pinned CPU PyTorch wheel exists for Python 3.13 on Linux x86-64 in the official CPU index. A native Render Linux build was not run locally. Mounted storage, real capacity, permissions and public access remain first-deployment acceptance checks. No Render service, charge or public URL was created by preparing this folder.


## Photo upload and unlimited AI update (18 November 2026)

Regression run: 368 tests and 204 subtests passed in 53.20 seconds; pip check passed. Coverage includes 11 image codecs, 48-megapixel JPEG fixtures padded to 1 and 6 MiB, EXIF orientation/privacy, transparency, CMYK, animation first-frame selection, corrupt/oversize rejection, six composer upload formats, retained voice handling and request-slot release. Legacy daily allowance variables do not restrict requests. JPEG size fixtures are synthetic; the user's original phone files were not supplied. Real phone browser and Linux Render acceptance remain necessary. This change does not resolve the separately confirmed 512 MB depth-model OOM.


## Mobile focus zoom correction (18 November 2026)

Mobile/coarse-pointer form inputs, comboboxes, date segments, editable fields and portalled options use 16 px text. Desktop fine-pointer inputs retain 14 px. No viewport zoom restrictions, touch-event interception or forced scale reset were introduced. A 390 x 844 browser check confirmed 16 px controls and working navigation/language menus; the desktop energy input remained 14 px. All six application smoke tests passed. Physical iOS Safari auto-zoom still requires a phone check; desktop emulation does not reproduce every Safari behavior.


## Mobile voice input correction (18 November 2026)

379 Python tests and 204 subtests passed in 41.93 seconds; pip check passed. Six JavaScript simulations covered unavailable APIs, denied permission, missing device, Safari MP4 and Chrome WebM recording lifecycles. Actual M4A/WebM/Ogg/FLAC conversion passed. The configured ASR returned the expected transcript from a synthetic M4A sample; the local browser upload/preview/use flow visibly prefilled it into chat. No physical microphone was recorded. Real phone capture/permission and Linux Render acceptance remain pending; a denied browser permission cannot be bypassed by application code.


## Recording icon restoration (18 November 2026)

The recording start control displays a compact inline SVG microphone instead of a visible text label. Localized aria-label/title and the 44 px touch target remain. All six recorder simulations passed. A 390 x 844 browser view confirmed the icon renders. Recording behavior, permissions and transcription were unchanged.


## Inline microphone and simplified controls (18 November 2026)

The dedicated Upload recording button was removed. The microphone and stop/cancel controls now attach inside the native chat input beside Send; a scoped style reserves text space without changing the native file attachment or Send handlers. On unmount, the observer, microphone stream and inserted controls are cleaned up. Permission failures suggest browser settings or text input. Six recorder simulations and 40 voice/application tests passed. Browser verification at 390 x 844 confirmed the microphone is inside the chat input, has a 44 px touch target, and no Upload recording button exists. Navigating away and back restored exactly one microphone. Physical phone capture and Render deployment still require verification.
