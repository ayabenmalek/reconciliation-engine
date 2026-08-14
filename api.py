"""FastAPI backend for the Bank GL Transaction Reconciliation Engine.

This module is the HTTP layer in front of ``engine.py``, the SHB general-ledger
reconciliation engine. It exposes the engine's batch pipeline as a small REST
API that a browser frontend can drive:

* ``GET  /health``                                  — readiness / status probe.
* ``POST /reconcile``                               — upload a day's GL CSV, run
  the full match pipeline, get back match groups plus leftovers.
* ``GET  /results/{run_id}/download/{file_type}``   — download the persisted
  ``matched.csv`` / ``unmatched.csv`` for a previous run.
* ``GET  /results/{run_id}/download/llm_matched``   — download the LLM pass's
  ``llm_matched.csv`` for a previous run.
* ``POST /review``                                  — optional second pass: send
  the still-unmatched rows to an LLM to recover extra balanced groups.

Lifecycle
---------
Heavy engine state is loaded once at application startup by the ``lifespan``
context manager and cached in the module-level ``STATE`` dict: the
``TemplateClassifier`` (sentence-transformer + UMAP + HDBSCAN template model)
and the calibration weights. Loading is expensive, so no request path ever
reloads them.

Persistence
-----------
There is no database. Each ``/reconcile`` call mints a ``run_id`` (UUID4) and
writes ``results/<run_id>/matched.csv`` and ``results/<run_id>/unmatched.csv``
to disk; ``/review`` adds ``results/<run_id>/llm_matched.csv``. The download
endpoints and ``/review`` locate prior work purely by that ``run_id``, so runs
survive only as long as the ``results/`` directory does, and state is lost if
the process is restarted with a fresh working directory.

Serialisation
-------------
The engine works in NumPy/pandas types, which FastAPI's default JSON encoder
rejects. Every response body is therefore pushed through ``to_serializable``
and returned as a raw ``JSONResponse``, bypassing the framework encoder.

Notes
-----
The artifact paths (``TEMPLATE_PKL``, ``CLUSTER_NAMES``, ``CALIB_WEIGHTS``)
point at Google Drive mount locations, i.e. this module is configured to run
inside a Colab notebook. Running it elsewhere requires editing those constants.

CORS is wide open (``allow_origins=["*"]``); this is a development/internal
deployment posture, not a public-internet one.
"""

import os, uuid, time, json, logging, io
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import numpy as np
import pandas as pd
import engine as eng

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("api")

# Engine artifact locations (Google Drive paths — this service is wired for Colab).
TEMPLATE_PKL  = "/content/drive/MyDrive/Project_Folder/Artifacts/template_clusters.pkl"   # pickled template-cluster model
CLUSTER_NAMES = "/content/drive/MyDrive/Project_Folder/Artifacts/cluster_names.csv"       # cluster_id -> human_name lookup
CALIB_WEIGHTS = "/content/drive/MyDrive/Project_Folder/Artifacts/calibration_weights.json"  # naive-Bayes feature weights + threshold
RESULTS_DIR   = Path("results")                                                            # per-run CSV output root

# Process-wide cache of everything loaded once at startup.
#   classifier : engine.TemplateClassifier, or None until lifespan finishes
#   calib      : engine calibration object (weights, base_log_odds, threshold), or None
#   last_run   : ISO-8601 timestamp of the most recent /reconcile call, or None
#   device     : "cuda" or "cpu", whichever torch reported at startup
STATE = {"classifier": None, "calib": None, "last_run": None, "device": "cpu"}

# ── The key fix: convert everything to native Python before JSON ───────────
def to_serializable(obj):
    """Recursively convert NumPy scalars/arrays into JSON-safe native Python.

    FastAPI's default encoder chokes on ``np.bool_``, ``np.int64``,
    ``np.float64`` and ``np.ndarray``, all of which leak out of the pandas-based
    engine. This walks dicts and lists and rewrites the leaves.

    Args:
        obj: Any value — dict, list, NumPy scalar/array, or plain Python object.
            Containers are traversed; anything unrecognised is returned as-is.

    Returns:
        The same structure with ``np.bool_`` -> ``bool``, ``np.integer`` ->
        ``int``, ``np.floating`` -> ``float``, ``np.ndarray`` -> ``list``, and
        non-finite Python floats (NaN/inf, which are not legal JSON) -> ``None``.

    Note:
        The NaN/inf guard runs *after* the ``np.floating`` branch, so a NumPy
        NaN becomes ``float('nan')`` rather than ``None``. Only a native Python
        NaN/inf reaching this function is nulled out.
    """
    if isinstance(obj, dict):
        return {k: to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_serializable(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown hook — loads the engine exactly once.

    Runs before the server accepts traffic: creates the results directory,
    loads the ``TemplateClassifier`` from the pickle (which also pulls the
    sentence-transformer by name, so the first run needs Hugging Face access),
    loads the calibration weights, and records whether CUDA is available. All
    of it is stashed in ``STATE`` so request handlers never pay this cost.

    Args:
        app (FastAPI): The application instance, supplied by FastAPI. Unused —
            state is kept in the module-level ``STATE`` dict instead.

    Yields:
        None: Control returns to FastAPI to serve requests. Nothing runs after
        the ``yield``; there is no explicit teardown.

    Raises:
        Exception: Propagates any artifact-loading failure (missing pickle,
            unreadable weights JSON, blocked native extension), which aborts
            startup rather than serving requests with a half-loaded engine.

    Note:
        ``torch`` is imported lazily here rather than at module scope, so the
        module can be imported for inspection even where the torch DLLs fail
        to load.
    """
    RESULTS_DIR.mkdir(exist_ok=True)
    log.info("Loading engine...")
    t0 = time.time()
    STATE["classifier"] = eng.TemplateClassifier.load(
        TEMPLATE_PKL, eng.normalise_remark, names_csv=CLUSTER_NAMES)
    STATE["calib"] = eng.load_calibration(CALIB_WEIGHTS)
    import torch
    STATE["device"] = "cuda" if torch.cuda.is_available() else "cpu"
    log.info(f"Ready in {time.time()-t0:.1f}s  features={len(STATE['calib'].weights)}")
    yield

app = FastAPI(title="SHB Reconciliation API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def safe(v, default=""):
    """Coerce a possibly-missing cell value into something JSON-safe.

    Args:
        v: Any cell value, typically straight out of a pandas row — may be
            ``None``, a float NaN, a NumPy scalar, or a string.
        default: Value returned when ``v`` is ``None`` or NaN. Defaults to ``""``.

    Returns:
        ``default`` if ``v`` is ``None`` or a float NaN; ``v`` unchanged if it is
        an ``int``, ``float``, or ``bool``; otherwise ``str(v)``.

    Note:
        Currently unused — ``row_detail`` does its own inline coercion. Kept as
        a helper for future field extraction.
    """
    if v is None: return default
    try:
        if isinstance(v, float) and np.isnan(v): return default
    except: pass
    return str(v) if not isinstance(v, (int, float, bool)) else v

def row_detail(df, idx):
    """Project one ledger row into the flat dict shape the frontend consumes.

    Pulls only the display-relevant columns, forces every value to a native
    Python type, and truncates the free-text Vietnamese remark fields so a
    response cannot balloon on verbose descriptions.

    Args:
        df (pandas.DataFrame): The ledger frame currently being reconciled,
            after ``engine.extract_signals`` has run.
        idx (int): Positional index of the row (used with ``.iloc``, not
            ``.loc``, so it is a position rather than a label).

    Returns:
        dict: Keys ``row_idx`` (int), ``sogd_id`` (str), ``ghi_co`` (float,
        credit), ``ghi_no`` (float, debit), ``ngaygd`` (str ``YYYY-MM-DD``, or
        ``""`` if the date is missing), ``so_tai_khoan`` (str, account),
        ``chi_nhanh`` (str, branch), ``cust_remarks`` (str, first 200 chars),
        ``cust_remarks2`` (str, first 100 chars), ``dien_giai`` (str, first
        200 chars). Missing columns fall back to empty string / ``0``.

    Raises:
        IndexError: If ``idx`` is out of range for ``df``.
        KeyError: If the ``NGAYGD`` column is absent entirely (it is accessed
            directly rather than via ``.get`` in the ``pd.Timestamp`` call).
    """
    r = df.iloc[int(idx)]
    return {
        "row_idx":       int(idx),
        "sogd_id":       str(r.get("SOGD_ID", "") or ""),
        "ghi_co":        float(r.get("GHI_CO", 0) or 0),
        "ghi_no":        float(r.get("GHI_NO", 0) or 0),
        "ngaygd":        str(pd.Timestamp(r["NGAYGD"]).date()) if pd.notna(r.get("NGAYGD")) else "",
        "so_tai_khoan":  str(r.get("SO_TAI_KHOAN", "") or ""),
        "chi_nhanh":     str(r.get("CHI_NHANH", "") or ""),
        "cust_remarks":  str(r.get("CUST_REMARKS", "") or "")[:200],
        "cust_remarks2": str(r.get("CUST_REMARKS2", "") or "")[:100],
        "dien_giai":     str(r.get("DIEN_GIAI", "") or "")[:200],
    }

@app.get("/health")
def health():
    """GET /health — readiness probe and service metadata.

    Reports whether the engine finished loading, how many calibrated features
    the scorer has, which compute device was selected, and when the last
    reconciliation ran. Takes no parameters and never fails, so it is safe to
    poll from a frontend or a container health check.

    Returns:
        JSONResponse: HTTP 200 with a body containing:
            - ``status`` (str): ``"ready"`` once calibration is loaded, else
              ``"loading"``.
            - ``n_features`` (int): Number of calibrated scoring weights; ``0``
              while still loading.
            - ``device`` (str): ``"cuda"`` or ``"cpu"``, as detected at startup.
            - ``last_run`` (str | None): ISO-8601 timestamp of the most recent
              ``/reconcile`` call, or ``None`` if none has run this process.
            - ``engine_version`` (str): Hard-coded engine revision tag.

    Error cases:
        None. There is no failure path — a not-yet-loaded engine is reported as
        ``status: "loading"`` with HTTP 200 rather than an error status.
    """
    c = STATE["calib"]
    return JSONResponse(content={
        "status":        "ready" if c else "loading",
        "n_features":    int(len(c.weights)) if c else 0,
        "device":        str(STATE["device"]),
        "last_run":      STATE["last_run"],
        "engine_version":"V1",
    })

@app.post("/reconcile")
async def reconcile(file: UploadFile = File(...)):
    """POST /reconcile — run the full reconciliation pipeline on an uploaded CSV.

    Accepts a day's GL export as ``multipart/form-data``, runs the four engine
    stages (signal extraction, candidate generation, pair scoring, group
    resolution), classifies each resulting group's topology, persists the
    results to disk under a fresh ``run_id``, and returns the full result set
    inline.

    Args:
        file (UploadFile): Multipart form field named ``file``. Must be a CSV
            whose filename ends in ``.csv`` and whose columns match the engine's
            expected schema (``SOGD_ID``, ``GHI_CO``, ``GHI_NO``, ``NGAYGD``,
            ``SO_TAI_KHOAN``, ``CHI_NHANH``, ``CUST_REMARKS``, ``CUST_REMARKS2``,
            ``DIEN_GIAI``); see ``sample_transactions.csv``.

    Returns:
        JSONResponse: HTTP 200 with:
            - ``run_id`` (str): UUID4 identifying this run; pass it to the
              download and ``/review`` endpoints.
            - ``elapsed_s`` (float): Wall-clock seconds for the whole request.
            - ``summary`` (dict): ``n_transactions`` (int), ``n_groups`` (int),
              ``balance_rate`` (float, balanced groups / total groups),
              ``coverage`` (float, grouped rows / total rows),
              ``balanced_coverage`` (float, rows in balanced groups / total
              rows), ``n_unmatched`` (int), and ``topology`` (dict mapping
              topology label to group count).
            - ``matched`` (list[dict]): One entry per group, with ``group_id``
              (``ENG_00000`` style), ``topology`` (``1_to_1`` / ``1_to_m`` /
              ``m_to_1`` / ``m_to_m``), ``mechanism`` (``|``-joined labels from
              the scorer), ``is_balanced`` (bool), ``sum_credit``, ``sum_debit``,
              ``gap`` (floats), and ``members`` (list of ``row_detail`` dicts).
            - ``unmatched`` (list[dict]): ``row_detail`` dicts for every row not
              assigned to any group.

    Side effects:
        Creates ``results/<run_id>/`` and writes ``matched.csv`` (one row per
        group member, group fields denormalised onto each row) and
        ``unmatched.csv``. Updates ``STATE["last_run"]``.

    Raises:
        HTTPException: 400 if the filename does not end in ``.csv``, if pandas
            cannot parse the upload, or if the parsed frame has zero rows.
        HTTPException: 500 if the engine itself raises — bad schema, missing
            required columns, or a classifier failure. The original exception is
            logged with a traceback and its message is echoed in the response
            detail.

    Note:
        Groups are emitted even when they do not balance; check ``is_balanced``
        per group rather than assuming every returned group nets to zero.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files accepted.")

    t0 = time.time()
    run_id  = str(uuid.uuid4())
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        content = await file.read()
        df = pd.read_csv(io.BytesIO(content), low_memory=False)
    except Exception as e:
        raise HTTPException(400, f"Cannot parse CSV: {e}")

    if len(df) == 0:
        raise HTTPException(400, "CSV is empty.")

    try:
        df = eng.extract_signals(df, STATE["classifier"])
        groups, _ = eng.predict(df, STATE["calib"])
    except Exception as e:
        log.error(f"Engine error: {e}", exc_info=True)
        raise HTTPException(500, f"Engine error: {e}")

    # Build matched groups
    matched  = []
    assigned = set()
    for gi, g in enumerate(groups):
        mems = [int(m) for m in g.members]
        sc   = float(sum(df["GHI_CO"].values[m] for m in mems))
        sd   = float(sum(df["GHI_NO"].values[m] for m in mems))
        nc   = int(sum(1 for m in mems if df["GHI_CO"].values[m] > 0))
        nd   = int(len(mems) - nc)
        topo = ("1_to_1" if nc==1 and nd==1 else
                "1_to_m" if nc==1 else
                "m_to_1" if nd==1 else "m_to_m")
        matched.append({
            "group_id":    f"ENG_{gi:05d}",
            "topology":    str(topo),
            "mechanism":   str(g.mechanism),
            "is_balanced": bool(g.is_balanced),
            "sum_credit":  sc,
            "sum_debit":   sd,
            "gap":         float(sc - sd),
            "members":     [row_detail(df, m) for m in mems],
        })
        assigned.update(mems)

    # Build unmatched
    unmatched = [row_detail(df, int(i))
                 for i in df.index if int(i) not in assigned]

    n_total  = int(len(df))
    n_groups = int(len(groups))
    n_bal    = int(sum(1 for g in groups if bool(g.is_balanced)))
    bal_rows = int(sum(len(g.members) for g in groups if bool(g.is_balanced)))
    topo_cnt = dict(Counter(g["topology"] for g in matched))

    # Save CSVs
    matched_rows = []
    for g in matched:
        for mem in g["members"]:
            matched_rows.append({
                **mem,
                "group_id":    g["group_id"],
                "topology":    g["topology"],
                "mechanism":   g["mechanism"],
                "is_balanced": g["is_balanced"],
                "sum_credit":  g["sum_credit"],
                "sum_debit":   g["sum_debit"],
                "gap":         g["gap"],
            })
    pd.DataFrame(matched_rows).to_csv(run_dir / "matched.csv", index=False)
    pd.DataFrame(unmatched).to_csv(run_dir / "unmatched.csv", index=False)

    STATE["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    elapsed = float(time.time() - t0)
    log.info(f"run={run_id[:8]} rows={n_total} groups={n_groups} "
             f"unmatched={n_total - len(assigned)} elapsed={elapsed:.1f}s")

    # Use to_serializable + JSONResponse to bypass FastAPI's encoder entirely
    result = to_serializable({
        "run_id":    run_id,
        "elapsed_s": round(elapsed, 2),
        "summary": {
            "n_transactions":    n_total,
            "n_groups":          n_groups,
            "balance_rate":      round(n_bal / max(n_groups, 1), 4),
            "coverage":          round(len(assigned) / max(n_total, 1), 4),
            "balanced_coverage": round(bal_rows / max(n_total, 1), 4),
            "n_unmatched":       n_total - len(assigned),
            "topology":          topo_cnt,
        },
        "matched":   matched,
        "unmatched": unmatched,
    })

    # Return as raw JSONResponse — bypasses FastAPI encoder completely
    return JSONResponse(content=result)

@app.get("/results/{run_id}/download/{file_type}")
def download(run_id: str, file_type: str):
    """GET /results/{run_id}/download/{file_type} — fetch a run's result CSV.

    Streams back one of the two CSVs that ``/reconcile`` wrote to disk for the
    given run.

    Args:
        run_id (str): Path parameter — the UUID4 returned by ``/reconcile``.
        file_type (str): Path parameter — either ``"matched"`` or
            ``"unmatched"``. Anything else is rejected.

    Returns:
        FileResponse: HTTP 200, ``text/csv``, served as an attachment named
        ``<file_type>_<first 8 chars of run_id>.csv``. ``matched.csv`` has one
        row per group member with the group's ``group_id``/``topology``/
        ``mechanism``/``is_balanced``/``sum_credit``/``sum_debit``/``gap``
        denormalised onto it; ``unmatched.csv`` is a plain row dump.

    Raises:
        HTTPException: 400 if ``file_type`` is not ``"matched"`` or
            ``"unmatched"``.
        HTTPException: 404 if no file exists at that path — an unknown
            ``run_id``, or results lost because the process restarted with a
            different working directory.

    Note:
        This route's ``{file_type}`` wildcard is registered before the
        ``llm_matched`` route below, so it matches that path first. Requests for
        ``/results/{run_id}/download/llm_matched`` land here and get the 400.
    """
    if file_type not in ("matched", "unmatched"):
        raise HTTPException(400, "file_type must be 'matched' or 'unmatched'")
    path = RESULTS_DIR / run_id / f"{file_type}.csv"
    if not path.exists():
        raise HTTPException(404, f"Not found: {run_id}/{file_type}")
    return FileResponse(str(path), media_type="text/csv",
                        filename=f"{file_type}_{run_id[:8]}.csv")
    
@app.get("/results/{run_id}/download/llm_matched")
def download_llm(run_id: str):
    """GET /results/{run_id}/download/llm_matched — fetch the LLM pass's CSV.

    Streams back ``llm_matched.csv``, the extra groups that ``/review``
    recovered from a run's unmatched tail. Written only when ``/review`` ran for
    this ``run_id`` and found at least one valid balanced group.

    Args:
        run_id (str): Path parameter — the UUID4 returned by ``/reconcile``.

    Returns:
        FileResponse: HTTP 200, ``text/csv``, served as an attachment named
        ``llm_matched_<first 8 chars of run_id>.csv``. One row per recovered
        group member, carrying ``group_id`` (``LLM_00000`` style), ``topology``,
        ``mechanism`` (``llm_tail:`` prefixed), ``is_balanced``, and
        ``confidence``.

    Raises:
        HTTPException: 404 if no ``llm_matched.csv`` exists for that run —
            unknown ``run_id``, ``/review`` never ran, or it recovered nothing.

    Note:
        Unreachable as registered: the preceding ``{file_type}`` wildcard route
        matches this path first and returns 400. Declaring this route before the
        wildcard one would fix it, but that is a code change, not a docstring.
    """
    path = RESULTS_DIR / run_id / "llm_matched.csv"
    if not path.exists():
        raise HTTPException(404, f"No LLM results for run_id: {run_id}")
    return FileResponse(str(path), media_type="text/csv",
                        filename=f"llm_matched_{run_id[:8]}.csv")


@app.post("/review")
async def review(payload: dict):
    """POST /review — second-pass LLM recovery over a run's unmatched rows.

    Reads the ``unmatched.csv`` written by a previous ``/reconcile``, regroups
    it into ``(account, date)`` blocks, and asks an OpenAI-compatible chat model
    to spot balanced groups the deterministic engine missed. Every group the
    model proposes is re-verified locally before it is accepted, so the LLM can
    only suggest — it cannot assert a match into the results.

    Args:
        payload (dict): JSON request body.
            - ``run_id`` (str): **Required.** UUID4 of the reconciliation run
              whose unmatched tail should be reviewed.
            - ``api_key`` (str): **Required.** Credential for the LLM provider,
              passed straight through to the OpenAI client. Not persisted.
            - ``model`` (str): Optional model name. Defaults to ``"qwen-plus"``.
            - ``base_url`` (str): Optional OpenAI-compatible endpoint. Defaults
              to ``"https://openrouter.ai/api/v1"``.

    Validation applied to each proposed group (a group failing any check is
    silently skipped):
        1. Every ``row_indices`` entry must belong to the block being reviewed.
        2. No row may already have been recovered by an earlier group.
        3. ``sum(GHI_CO)`` and ``sum(GHI_NO)`` must agree within 1 VND.
        Blocks with fewer than 2 rows are never sent to the model.

    Returns:
        JSONResponse: HTTP 200 with:
            - ``run_id`` (str): Echoed back.
            - ``new_groups`` (list[dict]): Accepted groups, each with
              ``group_id`` (``LLM_00000`` style), ``topology``, ``mechanism``
              (``llm_tail:<model's reason>``), ``is_balanced`` (always ``True``
              — unbalanced proposals are rejected), ``sum_credit``,
              ``sum_debit``, ``gap`` (always ``0.0``), ``confidence``
              (``high``/``medium``/``low``, as claimed by the model), and
              ``members``.
            - ``n_recovered`` (int): Rows pulled into new groups.
            - ``n_new_groups`` (int): Length of ``new_groups``.
            - ``still_unmatched`` (int): Unmatched rows remaining.
            - ``errors`` (list[dict]): Per-block failures, each ``{"block",
              "error"}`` — an LLM call that failed, timed out, or returned
              unparseable JSON. Present alongside a 200; a partial failure does
              not fail the request.
        The early-exit shape when ``unmatched.csv`` is empty omits
        ``n_new_groups`` and ``errors``, returning only ``run_id``,
        ``new_groups``, ``n_recovered``, and ``still_unmatched``.

    Side effects:
        Writes ``results/<run_id>/llm_matched.csv`` when at least one group is
        accepted. Makes one outbound LLM API call per qualifying block, billed
        to the supplied ``api_key``.

    Raises:
        HTTPException: 400 if ``run_id`` or ``api_key`` is missing or empty.
        HTTPException: 404 if no ``unmatched.csv`` exists for that ``run_id``.

    Note:
        Per-block LLM failures are caught and collected into ``errors`` rather
        than aborting the run, so a partially successful review still returns
        whatever it recovered.
    """
    import re
    from openai import OpenAI

    run_id  = payload.get("run_id")
    api_key = payload.get("api_key", "")
    model   = payload.get("model", "qwen-plus")

    if not run_id:
        raise HTTPException(400, "run_id is required.")
    if not api_key:
        raise HTTPException(400, "api_key is required.")

    unmatched_path = RESULTS_DIR / run_id / "unmatched.csv"
    if not unmatched_path.exists():
        raise HTTPException(404, f"No unmatched file for run_id: {run_id}")

    unmatched_df = pd.read_csv(unmatched_path)
    if len(unmatched_df) == 0:
        return JSONResponse(content={"run_id": run_id, "new_groups": [],
                                      "n_recovered": 0, "still_unmatched": 0})

    unmatched_df["_block"] = (unmatched_df["so_tai_khoan"].astype(str) + "|" +
                               unmatched_df["ngaygd"].astype(str))

    base_url = payload.get("base_url", "https://openrouter.ai/api/v1")
    client = OpenAI(
      api_key=api_key,
      base_url=base_url,
    )

    SYSTEM_PROMPT = """You are an expert bank auditor at SHB Bank Vietnam.
Given a block of unmatched GL transactions from the SAME account on the SAME date,
identify which transactions belong to the same accounting event.

Rules:
- Within every valid group sum(credits GHI_CO) MUST equal sum(debits GHI_NO) within 1 VND
- Supported topologies: 1:1, 1:m, m:1, m:m
- Only include rows that form a perfectly balanced group
- Each row appears in at most one group
- If no valid balanced groups exist return empty groups list

OUTPUT only valid JSON no explanation no markdown:
{"groups": [{"row_indices": [int, ...], "topology": "1:1", "mechanism": "reason", "confidence": "high|medium|low"}]}"""

    new_groups    = []
    recovered_idx = set()
    errors        = []

    for block_id, block_df in unmatched_df.groupby("_block"):
        if len(block_df) < 2:
            continue

        acct, date = block_id.split("|", 1)
        lines = [f"Block: account={acct}, date={date}, {len(block_df)} transactions\n"]
        lines.append("row_idx | side   | amount      | sogd_id                | remarks")
        lines.append("-" * 80)
        for _, r in block_df.iterrows():
            side   = "CREDIT" if float(r.get("ghi_co", 0) or 0) > 0 else "DEBIT"
            amount = float(r.get("ghi_co", 0) or 0) + float(r.get("ghi_no", 0) or 0)
            remarks = str(r.get("cust_remarks", "") or "")[:60]
            lines.append(f"{int(r['row_idx'])} | {side:<6s} | {amount:>11,.0f} | "
                         f"{str(r.get('sogd_id','')):<22s} | {remarks}")

        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0.0,
                max_tokens=1000,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": "\n".join(lines)}
                ]
            )
            raw = response.choices[0].message.content
            if raw is None:
                raise ValueError("LLM returned empty response")
            raw = raw.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            parsed = json.loads(raw)

            valid_row_ids = set(block_df["row_idx"].astype(int).tolist())

            for g in parsed.get("groups", []):
                row_indices = [int(i) for i in g.get("row_indices", [])]
                if not all(i in valid_row_ids for i in row_indices): continue
                if any(i in recovered_idx for i in row_indices): continue
                cr_sum = sum(float(block_df.loc[block_df["row_idx"]==i, "ghi_co"].values[0] or 0) for i in row_indices)
                dr_sum = sum(float(block_df.loc[block_df["row_idx"]==i, "ghi_no"].values[0] or 0) for i in row_indices)
                if abs(cr_sum - dr_sum) > 1.0: continue
                nc   = sum(1 for i in row_indices if float(block_df.loc[block_df["row_idx"]==i, "ghi_co"].values[0] or 0) > 0)
                nd   = len(row_indices) - nc
                topo = ("1_to_1" if nc==1 and nd==1 else "1_to_m" if nc==1 else "m_to_1" if nd==1 else "m_to_m")
                members = []
                for i in row_indices:
                    r = block_df[block_df["row_idx"]==i].iloc[0]
                    members.append({
                        "row_idx":      int(i),
                        "sogd_id":      str(r.get("sogd_id","") or ""),
                        "ghi_co":       float(r.get("ghi_co",0) or 0),
                        "ghi_no":       float(r.get("ghi_no",0) or 0),
                        "ngaygd":       str(r.get("ngaygd","") or ""),
                        "so_tai_khoan": str(r.get("so_tai_khoan","") or ""),
                        "cust_remarks": str(r.get("cust_remarks","") or "")[:200],
                        "dien_giai":    str(r.get("dien_giai","") or "")[:200],
                    })
                new_groups.append({
                    "group_id":    f"LLM_{len(new_groups):05d}",
                    "topology":    str(topo),
                    "mechanism":   f"llm_tail:{str(g.get('mechanism','llm'))}",
                    "is_balanced": True,
                    "sum_credit":  float(cr_sum),
                    "sum_debit":   float(dr_sum),
                    "gap":         0.0,
                    "confidence":  str(g.get("confidence","medium")),
                    "members":     members,
                })
                recovered_idx.update(row_indices)

        except Exception as e:
            errors.append({"block": block_id, "error": str(e)})
            log.warning(f"LLM error on block {block_id}: {e}")

    if new_groups:
        llm_rows = []
        for g in new_groups:
            for mem in g["members"]:
                llm_rows.append({**mem, "group_id": g["group_id"],
                    "topology": g["topology"], "mechanism": g["mechanism"],
                    "is_balanced": g["is_balanced"], "confidence": g["confidence"]})
        pd.DataFrame(llm_rows).to_csv(RESULTS_DIR / run_id / "llm_matched.csv", index=False)

    still_unmatched = int(len(unmatched_df) - len(recovered_idx))
    log.info(f"LLM review run_id={run_id[:8]} recovered={len(recovered_idx)} "
             f"groups={len(new_groups)} still_unmatched={still_unmatched}")

    return JSONResponse(content=to_serializable({
        "run_id":          run_id,
        "new_groups":      new_groups,
        "n_recovered":     int(len(recovered_idx)),
        "n_new_groups":    int(len(new_groups)),
        "still_unmatched": still_unmatched,
        "errors":          errors,
    }))
