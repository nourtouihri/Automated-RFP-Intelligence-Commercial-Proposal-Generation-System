# UI preview

The approved **Final** design, wired to the live services through a small proxy (`server/`). Every screen reads
and acts on real data: nothing is mocked, and there is no preview mode. The backend services gained the
endpoints it needs (listed in the root README's API table), and the proxy adds no new dependencies.

## Open it

Run the stack and open the `ui` service, which serves this app and proxies `/api/*` to the services:

```bash
docker compose up --build -d
```

Then open `http://127.0.0.1:8005`. On a fresh database the app shows an empty state; **Load Simulated Feed** on
Tenders brings in the sample tenders.

To work on the UI without Docker, run detection, research, proposal (and any other service you need) locally
with the same token, then the proxy on port 8005:

```bash
export INTERNAL_SERVICE_TOKEN=dev-token-123456
python -m uvicorn detection.main:app --port 8000
python -m uvicorn server.app:app --app-dir ui-preview --host 127.0.0.1 --port 8005
```

and open `http://127.0.0.1:8005`. The same command is the `ui-live` entry in `.claude/launch.json`. The proxy
finds the services on `localhost:8000` to `8004` (and n8n on `5678`); override any with `UIP_<NAME>_URL` (for
example `UIP_RAG_URL`). Loading needs detection, research and proposal up; Generate Deck also needs retrieval
(RAG), and fetching notices needs ingestion. The routes and variables are listed in the root
[README.md](../README.md#the-ui-service).

| URL parameter | Effect |
| --- | --- |
| `?theme=dark` / `?theme=light` | Force a theme at load (otherwise the Settings switch, then the system) |

## Tests

```bash
node --test "ui-preview/tests/*.test.js"   # the api.js error mapping, no browser needed
python -m pytest ui-preview/server/tests -q # the proxy
```

## What is where

| Path | What |
| --- | --- |
| `server/` | The FastAPI proxy: serves this folder at `/`, adds the internal token, and maps every failure to the shared error envelope |
| `vendor/final/` | Final's `bundle.js` / `bundle.css` / `tokens.json` exactly as published, `tokens.css` compiled from it |
| `scripts/build_tokens.py` | Recompiles `tokens.css` from `tokens.json` |
| `src/types.d.ts` | Backend contracts, mirrored from `shared/schemas.py`, `proposal/schemas.py`, `proposal/main.py`, `ingestion/utils/schema.py`, `shared/errors.py` |
| `src/api.js` | `get` / `post` to `/api/*`; every failure becomes a `CapturedError` (`toCaptured`) |
| `src/store.js` | The app's state and actions; loads tenders, research and decks, then calls the services for every action |
| `src/future.js` | Designed features the backend cannot back yet |
| `src/screens/` | Overview, Tenders, Research, Match, Draft / Review / Export, Library, Security, Settings, Alerts |

## What is real, derived or saved locally

- **Alerts** (bell on Overview, `#/alerts`) are derived from service responses: hidden characters stripped by
  detection, possible duplicates, degraded research runs, refused decks, unsupported claims, no-bid decks.
- **Settings** are saved in this browser only: which intake sources show on Tenders, the first TED page,
  whether research runs on closed tenders (`force=true`), Library defaults and theme. Service health calls each
  service's `GET /health`. Fit thresholds are shown read-only from `proposal/schemas.py`.
- **Deck parameters** (Draft screen) edit the proposal `Config` fields (signatory, letter title, day rate, team
  size, pricing note) and preview the new total with the service's own formula. **Rebuild Deck** sends them as
  `settings` to the proposal service.

## Tender sources

TED EU and SAM.gov notices are fetched with `POST /ingest/TED` and `POST /ingest/SAM`. Either can be sent to
detection, which accepts `TED`, `SAM`, `manual` and `simulated_feed` as a source (SAM.gov was finding B1 in
[FUTURE.md](FUTURE.md), now fixed).

## Live features

Beyond reading and generating, the app does these against the services:

- **Rebuild Deck** with new deck parameters, **Generate Anyway** on a no-bid recommendation, and a strict claim
  check toggle in Settings.
- **Archive** and restore a tender, with a working Archived filter.
- **Review**: a status per section and a typed, named sign-off, saved with the deck. Regenerating the deck resets
  them.
- **Provenance**: a source citation on every research fact, the steps the deck's writer took per section, and
  a "How this was researched" layer with the audit trail of the research run.
- **Tender details**: country and notice-type chips, a country filter and the tender documents.
- **Library counts** per record type, from the knowledge base.
- **Downloads** of the deck, PDF and matrix through the proxy.

## Future features

Everything in the design that the backend does not support yet renders with a **Future** chip and does nothing:
section edit / history / prompt-edit, resolving a conflict, Share, email and push alerts, server-side settings,
single sign-on, team workspace, Salesforce and Google Drive connectors.

When the backend ships one, delete its key from `src/future.js` and replace each `FUTURE.<key>` use (grep for it)
with the real feature. The full backlog, with the backend changes that would retire each item, is in
[FUTURE.md](FUTURE.md); the plan to connect the live services is in [WIRING_PLAN.md](WIRING_PLAN.md).

## Known limits

- The records behind a deck's evidence (CV and project text) come back when a deck is generated. After a page
  reload, a citation on Review shows its record id only (with a note) until the deck is generated again; the
  Match screen instead searches the requirement again (`store.loadHit`, top 5) when a row is opened, so a
  record the search no longer returns shows as not found.
- Manual intake checks the fields in the browser first (`store.validateIngest`, mirroring
  `detection/normalize.py`); detection makes the final decision and does the sector tagging.
