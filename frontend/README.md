# Reconciliation Agent — Frontend

React + Vite + Tailwind interface for the GL transaction reconciliation engine.

---

## Quick start

**Step 1 — Start the backend:**
```bash
docker pull aya2603/reconciliation-engine:v1
docker run -d -p 8000:8000 --name reconciliation aya2603/reconciliation-engine:v1
```

**Step 2 — Create the .env file inside the frontend/ folder:**

VITE_API_URL=http://localhost:8000

**Step 3 — Start the frontend:**
```bash
cd frontend
npm install
npm run dev
```

**Step 4 — Open browser:**

http://localhost:5173

---

## Running the app

```powershell
cd frontend
npm install      # first time only
npm run dev      # http://localhost:5173
```

| Command | What it does |
| --- | --- |
| `npm run dev` | Dev server with hot reload on port 5173 |
| `npm run build` | Production build into `dist/` |
| `npm run preview` | Serve the built `dist/` locally |

---

## Demo flow

1. **Start the backend** using the Docker command above.
2. **Create the .env file** with `VITE_API_URL=http://localhost:8000`.
3. **Start the frontend** with `npm run dev`.
4. **Check the header.** Top right should show a green dot and **Live**.
5. **Upload a CSV.** Drag a GL export onto the drop zone, or click to browse.
6. **Run reconciliation.** The button turns amber once a file is selected. While running you will see a spinner cycling through the engine stages. Elapsed time is shown when it finishes.
7. **Read the metrics.** Four cards — balance rate, coverage, balanced coverage, unmatched — with the group topology breakdown (`1:1`, `1:m`, `m:1`, `m:m`) underneath.
8. **Inspect matched groups.** Filter by mechanism, topology, and balanced state. Click any row to expand it and see every member transaction plus the full justification for the match.
9. **Review the unmatched tail.** Everything the engine could not place, flagged for manual audit.
10. **Optional — LLM review.** Paste an OpenRouter API key and run it. Recovered groups are appended to the matched table with a purple border and an **LLM** badge.
11. **Export.** Download matched and unmatched CSVs. The LLM results button appears once a review has run.

---

## How the screen is organised

Header always visible · health badge · polls /health every 30s
UploadSection always visible · file picker + Run button

── after POST /reconcile succeeds ──
MetricsRow summary cards + topology pills
MatchedGroupsTable engine groups, expandable
UnmatchedTable rows requiring manual review
LLMReviewSection optional second pass
DownloadButtons matched + unmatched CSV

── after POST /review succeeds ──
MatchedGroupsTable LLM groups appended, purple styling
UnmatchedTable recovered rows removed
MetricsRow unmatched count updated
DownloadButtons LLM results CSV button appears

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
- Confirm the Docker container is running: `docker ps`
- Confirm you created `frontend/.env` with `VITE_API_URL=http://localhost:8000`
- Restart `npm run dev` after editing `.env`

**Reconciliation fails but the file stays selected**
Fix the backend and press Run again without re-picking the file.

**LLM review fails**
Check the key is a valid OpenRouter key and that the model still exists. To swap models edit `LLM_MODELS` in `src/constants.js`.

**Downloads do nothing**
If the Docker container was restarted after running reconciliation, the `run_id` no longer exists — re-run the upload.

---

## Project layout

frontend/
├── .env ← create manually: VITE_API_URL=http://localhost:8000
├── index.html
├── vite.config.js
└── src/
├── main.jsx
├── App.jsx
├── api.js
├── constants.js
├── utils.js
├── index.css
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

---

## Author
Aya Benmalek — Master 2 Internship, SHB Bank Vietnam, 2026
Supervised by Prof. Kherbachi Hamid, ESTIN