# GL Transaction Reconciliation Engine
##  Bank — Automated General Ledger Reconciliation

### What it does
This system automatically reconciles General Ledger transactions using a
five-stage pipeline: template discovery, association rule mining, probabilistic
matching (Fellegi-Sunter), balance-driven group resolution, and per-prediction
explanation. It achieves 84% balanced coverage with 100% balance rate on real
production data.

### Five-stage pipeline

| Stage | Method | Output |
|---|---|---|
| 1 — Template Discovery | BGE-M3 + UMAP + HDBSCAN | 35 transaction templates |
| 2 — Association Rule Mining | FP-Growth | 16 rules (lift 1.33–30.28) |
| 3 — Matching Engine | Fellegi-Sunter calibrated scoring | Pair scores + mechanisms |
| 4 — Group Resolution | Balance-driven greedy expansion | Matched groups |
| 5 — Explanation | Multi-label mechanism tags | Audit justifications |

### Performance results

| Metric | Labelled data | Real production data |
|---|---|---|
| Pair F1 | 0.919 | — |
| Balance rate | — | 100% |
| Coverage | — | 84.4% |
| Balanced coverage | — | 84.4% |

### Running with Docker

**Requirements:** Docker Desktop installed ([docker.com/products/docker-desktop](https://docker.com/products/docker-desktop))

**Step 1 — Start the backend:**
```bash
docker pull aya2603/reconciliation-engine:v1
docker run -d -p 8000:8000 --name reconciliation aya2603/reconciliation-engine:v1
```
Wait for: `Application startup complete`

**Step 2 — Start the frontend:**
```bash
cd frontend
npm install
npm run dev
```

**Step 3 — Open browser:**

http://localhost:5173

### API endpoints

| Endpoint | Method | Description |
|---|---|---|
| /health | GET | Engine status |
| /reconcile | POST | Upload CSV, get matched groups |
| /review | POST | LLM review of unmatched transactions |
| /results/{run_id}/download/matched | GET | Download matched CSV |
| /results/{run_id}/download/unmatched | GET | Download unmatched CSV |
| /results/{run_id}/download/llm_matched | GET | Download LLM results CSV |

### Required CSV columns
SOGD_ID, GHI_CO, GHI_NO, NGAYGD, SO_TAI_KHOAN,
CHI_NHANH, CUST_REMARKS, CUST_REMARKS2


### Matching mechanisms

| Mechanism | Description |
|---|---|
| same_sogd | Same SOGD base identifier — two legs of the same accounting event |
| refno_in_custremarks | Reference number found in partner remarks |
| keywords | Shared 12 or 15-digit structured identifier |
| one_one_sogd_prefix | Sequential SOGD prefix — interbank settlement |
| llm_tail | LLM-identified match with human-readable explanation |

### Note on artifacts
The `template_clusters.pkl` file (115MB) is bundled inside the Docker image.
All other artifacts are available in this repository under `artifacts/`.

### Author
Aya Benmalek — Master 2 Internship, SHB Bank Vietnam, 2026
Supervised by Prof. Kherbachi Hamid, ESTIN