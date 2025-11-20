TuwsBE — Local development and test instructions

Quick start
-----------

PowerShell (Windows) — run the server:

```powershell
Set-Location 'C:\Users\INS BANDUNG\Videos\tuwsbe'
# Optional: persistent sqlite DB (avoid spaces in path)
$env:DATABASE_URL = 'sqlite:///C:/temp/tuwsbe.db'
python run.py
```

Run tests (recommended: in-memory DB, scheduler disabled):

```powershell
Set-Location 'C:\Users\INS BANDUNG\Videos\tuwsbe'
$env:PYTHONPATH = 'C:\Users\INS BANDUNG\Videos\tuwsbe'
$env:DISABLE_SCHEDULER_FOR_TESTS = 1
$env:DATABASE_URL = 'sqlite:///:memory:'
python -m pytest -q
```

APIs
----
- Base path: `/api`
- Endpoints: `/api/data`, `/api/graph`, `/api/history`, `/api/health`

Notes
-----
- The `/api/metrics` endpoint and the `prometheus-client` runtime dependency were removed; metric recording calls were also removed from background jobs.
- Tests use an in-process Flask test client and seed a minimal dataset (Model, Label, Weather logs, PredictionLog) so they are deterministic and do not require external services.
- API responses include `meta` fields with `created_at` and `request_time` converted to WIB (UTC+7) ISO timestamps.

If you want me to also add CI config (GitHub Actions) or convert other scripts, tell me which you prefer next.

