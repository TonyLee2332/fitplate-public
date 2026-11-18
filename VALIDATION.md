# Deployment validation

Application source and assets match the public-visitor Agent Ready version (347 passing tests and 204 passing subtests). No Supabase adapter is included.

Deployment checks passed: the official Render Blueprint JSON schema, shell syntax, administrator startup preflight, rejection of a missing data path, consistent SQLite backup and signing-key restore. The backup helper explicitly closes database connections before removing temporary files.

The pinned CPU PyTorch wheel exists for Python 3.13 on Linux x86-64 in the official CPU index. A native Render Linux build was not run locally. Mounted storage, real capacity, permissions and public access remain first-deployment acceptance checks. No Render service, charge or public URL was created by preparing this folder.


## Photo upload and unlimited AI update (18 November 2026)

Regression run: 368 tests and 204 subtests passed in 53.20 seconds; pip check passed. Coverage includes 11 image codecs, 48-megapixel JPEG fixtures padded to 1 and 6 MiB, EXIF orientation/privacy, transparency, CMYK, animation first-frame selection, corrupt/oversize rejection, six composer upload formats, retained voice handling and request-slot release. Legacy daily allowance variables do not restrict requests. JPEG size fixtures are synthetic; the user's original phone files were not supplied. Real phone browser and Linux Render acceptance remain necessary. This change does not resolve the separately confirmed 512 MB depth-model OOM.
