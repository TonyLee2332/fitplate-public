# Deployment validation

Application source and assets match the public-visitor Agent Ready version (347 passing tests and 204 passing subtests). No Supabase adapter is included.

Deployment checks passed: the official Render Blueprint JSON schema, shell syntax, administrator startup preflight, rejection of a missing data path, consistent SQLite backup and signing-key restore. The backup helper explicitly closes database connections before removing temporary files.

The pinned CPU PyTorch wheel exists for Python 3.13 on Linux x86-64 in the official CPU index. A native Render Linux build was not run locally. Mounted storage, real capacity, permissions and public access remain first-deployment acceptance checks. No Render service, charge or public URL was created by preparing this folder.
