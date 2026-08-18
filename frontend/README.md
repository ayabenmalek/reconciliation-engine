# Reconciliation Agent — Frontend

React + Vite + Tailwind interface for the GL transaction reconciliation engine.
The backend runs in a Google Colab notebook and is exposed to the internet through ngrok.

---

## Where to put the ngrok URL

**Every time you restart the Colab backend you get a new ngrok URL, and you must update it here.**

1. Copy the forwarding URL that ngrok prints in the Colab output, e.g.

   ```
   https://a1b2-34-56-78-90.ngrok-free.app
   ```

2. Open `frontend/.env` and set it as the only value in the file:

   ```
   VITE_API_URL=https://a1b2-34-56-78-90.ngrok-free.app
   ```

   No quotes, no trailing slash.

3. **Restart the dev server.** Vite reads `.env` once at startup — editing the file while the
   server is running has no effect, and hot reload will not pick it up.

   ```powershell
   # Ctrl+C to stop, then:
   npm run dev
   ```

If `VITE_API_URL` is unset, the app falls back to `http://localhost:8000`.

The URL currently in use is printed in small text at the bottom of the page, so you can always
see which backend the UI is talking to.

---

## Running the app

```powershell
cd frontend
npm install      # first time only
npm run dev      # http://localhost:5173
```

Other scripts:

| Command | What it does |
| --- | --- |
| `npm run dev` | Dev server with hot reload on port 5173 |
| `npm run build` | Production build into `dist/` |
| `npm run preview` | Serve the built `dist/` locally |

Note that `npm run build` **bakes the current `.env` value into the bundle**. A production build
is tied to whatever ngrok URL was set when you built it — for day-to-day demo use, stay on
`npm run dev`.

---

## Demo flow

1. **Start the backend.** Run the Colab notebook until ngrok prints its forwarding URL.
2. **Point the frontend at it.** Update `frontend/.env`, then `npm run dev`.
3. **Check the header.** Top right should show a green dot and **Live**. If it shows a red dot and
   *"Backend offline — start the Colab notebook"*, see Troubleshooting below. The app re-checks
   `/health` every 30 seconds, so it will recover on its own once the backend is up.
4. **Upload a CSV.** Drag a GL export onto the drop zone, or click to browse.
5. **Run reconciliation.** The button turns amber once a file is selected. While `POST /reconcile`
   is in flight you'll see a spinner cycling through the engine's stages. Elapsed time is shown
   when it finishes.
6. **Read the metrics.** Four cards — balance rate, coverage, balanced coverage, unmatched — with
   the group topology breakdown (`1:1`, `1:m`, `m:1`, `m:m`) underneath.
7. **Inspect matched groups.** Filter by mechanism, topology, and balanced state. Click any row to
   expand it and see every member transaction plus the full justification for the match.
8. **Review the unmatched tail.** Everything the engine could not place, flagged for manual audit.
9. **Optional — LLM review.** Paste an OpenRouter API key and run it (`qwen/qwen3-8b:free`). Recovered
   groups are appended to the matched table with a purple border and an **LLM** badge, and the
   recovered rows disappear from the unmatched table.
10. **Export.** Download matched and unmatched CSVs; the LLM results button appears once a review
    has run.

---

## How the screen is organised

```
Header                    always visible · health badge · polls /health every 30s
UploadSection             always visible · file picker + Run button

── after POST /reconcile succeeds ──
MetricsRow                summary cards + topology pills
MatchedGroupsTable        engine groups, expandable
UnmatchedTable            rows requiring manual review
LLMReviewSection          optional second pass
DownloadButtons           matched + unmatched CSV

── after POST /review succeeds ──
MatchedGroupsTable        LLM groups appended, purple styling
UnmatchedTable            recovered rows removed
MetricsRow                unmatched count updated
DownloadButtons           LLM results CSV button appears
```

State is plain `useState` / `useEffect` in `src/App.jsx` — no Redux, no external state library.

---

## Backend requirements

Two things the Colab backend must do, or the UI cannot talk to it:

**1. CORS.** The browser sends requests from `http://localhost:5173` to your ngrok domain, which is
a cross-origin request. FastAPI needs the middleware:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # or ["http://localhost:5173"]
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Without this, every call fails with a network error even though the URL is correct and the
notebook is running.

**2. The ngrok interstitial.** ngrok's free tier serves an HTML warning page instead of your JSON
for requests that look like browser navigation. The frontend already sends the
`ngrok-skip-browser-warning` header on every request to opt out — just make sure your CORS config
allows that header (`allow_headers=["*"]` covers it).

---

## Endpoints consumed

| Method | Path | Used by |
| --- | --- | --- |
| `GET` | `/health` | Header status badge, polled every 30s |
| `POST` | `/reconcile` | Upload (multipart, field name `file`) |
| `POST` | `/review` | LLM review section |
| `GET` | `/results/{run_id}/download/matched` | Download button |
| `GET` | `/results/{run_id}/download/unmatched` | Download button |
| `GET` | `/results/{run_id}/download/llm_matched` | Download button, after review |

---

## Troubleshooting

**Header stuck on "Offline"**
- The ngrok URL in `.env` is stale — restarting Colab always issues a new one.
- You edited `.env` but didn't restart `npm run dev`.
- CORS middleware is missing on the backend (see above). Check the browser console: a CORS
  rejection looks like a network error in the UI but names the blocked origin in the console.
- The Colab runtime disconnected.

**Reconciliation fails but the file stays selected**
That's intentional — fix the backend and press Run again without re-picking the file. The error
text under the button carries the backend's own `detail` message where there is one.

**LLM review fails**
Engine results are left untouched; the error appears inside the LLM section only. Check the key is
a valid OpenRouter key and that `qwen/qwen3-8b:free` still exists — free model IDs on OpenRouter
are retired fairly often. To swap or add models, edit `LLM_MODELS` in `src/constants.js`.

**Downloads do nothing**
The `run_id` belongs to a specific backend process. If Colab restarted after you ran the
reconciliation, that `run_id` no longer exists server-side — re-run the upload.

---

## Project layout

```
frontend/
├── .env                  ← the ngrok URL goes here
├── index.html            Google Fonts (Inter, JetBrains Mono)
├── vite.config.js
└── src/
    ├── main.jsx
    ├── App.jsx           all state + the /reconcile and /review calls
    ├── api.js            axios client, error messages, blob downloads
    ├── constants.js      colours, labels, model list
    ├── utils.js          VND formatting, mechanism parsing, justifications
    ├── index.css         design tokens as Tailwind theme variables
    └── components/
        ├── Header.jsx
        ├── UploadSection.jsx
        ├── MetricsRow.jsx
        ├── MatchedGroupsTable.jsx
        ├── UnmatchedTable.jsx
        ├── LLMReviewSection.jsx
        ├── DownloadButtons.jsx
        ├── ErrorBoundary.jsx
        └── Spinner.jsx
```
