# M4 product interface

The React/TypeScript/Vite workbench lets visitors select a fixture, follow recorded events, inspect the diagnosis and unified patch, compare measured trajectories, inspect independent checks and download evidence. Operator controls require separate server enablement and a credential held only in component memory. There are no public uploads, code editor, execution routes or arbitrary targets.

## Local operation

Use Node 24 LTS, the repository Python environment and the M1–M3 Linux runner/control-worker setup. Keep API signing credentials, inference credentials and runner configuration separate; see [security operations](security.md). Do not give Vite cloud or model keys.

```
make web-setup
make web-dev
```

Start the API with its signing key loaded from its private credential environment:

```
.venv/bin/python -m apps.api --root runtime/control \
  --origin http://127.0.0.1:5173 --allow-http-local
```

Start the real control worker with its inference-only environment and private runner socket as described in the M3 operations. Open http://127.0.0.1:5173. Vite proxies only /api and /health to loopback port 8000, preserving Host and Origin for the exact-origin checks. ED_API_PROXY may select another loopback HTTP API port. The API origin must match the browser origin exactly. For `npm run preview` on port 4173, adjust the API origin accordingly.

The development server binds loopback. Production TLS, static reverse proxy, deployment and publication remain M5. Vite reads its environment from apps/web, not the root private .env. Any VITE_* value is a public build input and must never contain a credential.

## Contracts and evidence

`packages/contracts/presentation.py` defines the read-only browser view. Its projection copies trusted verifier results and binds runner artifacts to public snapshots by size/hash; it never infers a scientific verdict. Existing API routes remain supported.

```
make web-contracts   # Python schema → generated TypeScript
make web-check      # contract drift, numeric tests, typecheck and build
make web-e2e
```

The recent list and experiment UUID in the URL restore owned work after reload or a lost submit response. Cookies remain HttpOnly; CSRF tokens stay in memory. Mutations are never automatically replayed. Connection/session errors stop polling and offer explicit reconnect. A UUID alone grants no access. The existing 24-hour evidence retention and session expiration still apply.

Plots fetch owner-scoped CSV attachments, check size/SHA-256, strictly parse finite bounded t,x rows and draw at most 801 samples per curve. Slider readouts use raw samples. The analytical overlay does not confer a verdict. Missing, malformed, oversized, corrupt and expired files never produce fabricated curves. Model/source/log text is escaped or downloaded as attachment bytes; sandbox HTML/SVG is never embedded. Tables show actual measurements and tolerances separately from execution exit status and cleanup.

Owned ZIP exports contain sources, per-revision/per-job parameters, raw numeric results, bounded logs, repair.patch when present, report.json, replay/environment notes and a SHA-256 manifest. The report records model mode/usage, timestamps, runtime policy, Git SHA and image/verifier hashes. Exports verify stored bytes and enforce size/concurrency bounds. A manifest proves byte identity, not correctness. Replay needs the matching repository revision and pinned Linux runner images; model prose/choices need not be identical.

## Acceptance tests

Playwright starts a **test-only** loopback API (`tests/browser_server.py`) and Vite. The API uses real signed cookies, CSRF, queue ownership, report projection and ZIP export. Doctor uses the existing explicit offline numeric execution client and deterministic model fixture. The trusted checker evaluates those fixed inputs; candidate code never runs on the host. Reports visibly say `offline-e2e fixture`. This is not a production worker mode or live-model fallback.

Desktop/mobile tests cover coarse-step repair, healthy control, reload, foreign-session denial, timeline, patch, plots/readout, checks, provenance, evidence downloads, harmless rendering of injection strings, and incomplete/cancelled/expired-session states. Browser edge fixtures explicitly intercept requests. API tests inspect ZIP hashes/content and corrupt/expired evidence. These tests do not establish fresh live inference or container containment; separate M2/M3 evidence covers those gates.

Local tests use installed Chrome in an isolated Playwright profile. Linux CI installs the pinned Chromium with `cd apps/web && npx playwright install --with-deps chromium`. The Python test server uses `.venv/bin/python`; no secrets or paid services are needed. Repeated manual runs can hit the unchanged session rate limit: restart the disposable test server or wait for the window, rather than weakening production limits.

M5 adds a local read-only web container at `http://experiment-doctor.local:8080`; see [delivery operations](delivery.md). Its explicitly offline preview now labels the landing page as well as reports. Browser artifact SHA-256 checks use a pinned portable implementation so the named HTTP development origin retains integrity checks even without secure-context Web Crypto.
