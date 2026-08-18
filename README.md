# GL Transaction Reconciliation Engine
##  Bank — Automated General Ledger Reconciliation

### What it does
This system automatically reconciles General Ledger transactions using a
five-stage pipeline: template discovery, association rule mining, probabilistic
matching (Fellegi-Sunter), balance-driven group resolution, and per-prediction
explanation. It achieves 84% balanced coverage with 100% balance rate on real
production data.

### Five-stage pipeline
Stage 1 — Template Discovery     BGE-M3 + UMAP + HDBSCAN → 35 templates
Stage 2 — Association Rule Mining FP-Growth → 16 rules (lift 1.33–30.28)
Stage 3 — Matching Engine         Fellegi-Sunter calibrated scoring
Stage 4 — Group Resolution        Balance-driven greedy expansion
Stage 5 — Explanation             Multi-label mechanism tags


### Running with Docker

Step 1 — Pull and start the backend:
    docker pull aya2603/reconciliation-engine:v1
    docker run -p 8000:8000 aya2603/reconciliation-engine:v1

Wait for: Application startup complete

Step 2 — Start the frontend:
    cd frontend
    npm install
    npm run dev

Step 3 — Open browser:
    http://localhost:5173

### API endpoints
| Endpoint                                  | Method | Description              |
|-------------------------------------------|--------|--------------------------|
| /health                                   | GET    | Engine status            |
| /reconcile                                | POST   | Upload CSV, get results  |
| /review                                   | POST   | LLM review of unmatched  |
| /results/{run_id}/download/matched        | GET    | Download matched CSV     |
| /results/{run_id}/download/unmatched      | GET    | Download unmatched CSV   |
| /results/{run_id}/download/llm_matched    | GET    | Download LLM results     |

### Required CSV columns
SOGD_ID, GHI_CO, GHI_NO, NGAYGD, SO_TAI_KHOAN,
CHI_NHANH, CUST_REMARKS, CUST_REMARKS2

### Matching mechanisms
| Mechanism           | Description                            |
|---------------------|----------------------------------------|
| same_sogd           | Same SOGD base identifier              |
| refno_in_custremarks| Reference number in partner remarks    |
| keywords            | Shared 12 or 15-digit identifier       |
| one_one_sogd_prefix | Sequential SOGD prefix                 |
| llm_tail            | LLM-identified match with explanation  |

### Author
Aya Benmalek — Master 2 Internship, 2026
