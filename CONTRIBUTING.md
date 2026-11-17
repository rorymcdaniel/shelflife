# Contributing to Shelflife

Small changes with a clear user outcome are welcome. Check [the product contract](docs/shelflife/product.md) before changing retention behavior. Keep GPL-3.0 and upstream attribution intact. Never include service credentials, media inventories, personal deployment files, logs or database backups.

## Local checks

```sh
uv sync --group dev --extra desktop --frozen
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
cd frontend
npm ci
npm run check
npm run build
npx playwright install chromium
npx playwright test
```

Use Python 3.13 and Node 26 to match CI. Browser failures retain traces in ignored `frontend/test-results/`. See [testing](docs/shelflife/testing.md) for integration checks.

## Design expectations

Keep decisions in `backend/shelflife/engine.py`, time/notice rules in `policy.py`, and external observations in `library.py`. Reuse Reclaimerr's service-aware deletion and playback checks; do not add direct filesystem deletion.

Retention is monotonic: no user action shortens a deadline or reverses a permanent keep. Failed, stale, incomplete or ambiguous observations must not authorize deletion. Persist keeps before acknowledging success, independently of rescannable candidates. Test behavior through policy, engine or HTTP interfaces, including failure paths and exact media scope.

Server-side identity and visibility checks are authoritative. Never put administrator service credentials in browser code or use them to submit another person's request. Avoid logging authentication headers, cookies and URL tokens.

Changes enter `main` through pull requests with required CI. Solo maintenance does not require another person's approval. Follow [SECURITY.md](SECURITY.md) for security reports.
