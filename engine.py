"""
SHB Bank Reconciliation Engine — V1 (production)
Extracted from ENGINE_SOURCE in the Colab notebook.
All functions are identical to the notebook version.

Overview
--------
Given a general-ledger export, this engine decides which transactions offset one
another — a debit against its matching credit, a reversal against its original,
a multi-leg settlement against its counterparties — and emits balanced *match
groups* together with a human-readable reason for every match.

Remarks in the source data are free-text Vietnamese, so the engine deliberately
leans on structured evidence (SOGD reference identifiers, amounts, shared long
numeric IDs, branch codes) and treats the text only as a coarse *template*
signal obtained from an embedding/UMAP/HDBSCAN clustering of normalised remarks.

Architecture — five layers
--------------------------
1. **Vocabulary.** The fixed, hand-curated symbol set the rest of the engine is
   allowed to reason with: `normalise_remark` plus `TemplateClassifier` turn raw
   remarks into a single template label per row, and `PATTERN_FEATURES`,
   `KEYWORD_FINGERPRINTS`, `NAMED_PREFIX_COMBOS` and `MECHANISM_PRIORITY`
   enumerate the debit/credit template pairings, keyword fingerprints, SOGD
   prefix combinations and mechanism names that carry evidential weight.
   `extract_signals` is the entry point: it decorates the frame with the
   `_`-prefixed columns every later layer reads.

2. **Pair feature engineering.** `generate_candidates` blocks the frame on
   ``(SO_TAI_KHOAN, NGAYGD)`` and enumerates every within-block pair;
   `compute_pair_features` turns each pair into a dictionary of boolean
   evidence vectors (amount agreement, shared SOGD base, cross-referenced
   remarks, shared 12-/15-digit identifiers, template pattern, keyword and
   prefix-combination indicators).

3. **Fellegi-Sunter scoring.** `calibrate` (offline) estimates, for every
   boolean feature, the probability of firing among matched versus unmatched
   pairs and stores the two log-likelihood ratios in a `FeatureWeight`.
   `score_pairs` (online) sums the appropriate LLR per feature onto
   `Calibration.base_log_odds` and squashes the total through a sigmoid, then
   applies deterministic overrides for evidence considered conclusive and a
   plausibility gate that zeroes anything neither balanced nor sharing a SOGD
   base. Production always loads frozen weights via `load_calibration`.

4. **Balance-driven resolution.** `resolve_groups` consumes the surviving pairs
   highest-score-first and grows each seed pair into a group that closes to zero
   within `BALANCE_TOL`, pulling in further unassigned rows from the same block
   when the seed alone does not balance. Row assignment is exclusive: once a row
   joins a group it is never reconsidered.

5. **Per-prediction explanation.** Every scored pair carries a `mechanism`
   string built from `MECHANISM_PRIORITY` — a `|`-joined multi-label summary of
   *why* the pair scored (``same_sogd``, ``refno_in_custremarks``, ``keywords``,
   ``one_one_sogd_prefix``) or ``balanced_only`` when nothing but the amounts
   lined up. `resolve_groups` propagates the seed pair's mechanism onto the
   resulting `MatchGroup`, so each group ships with its own justification.

Data flow
---------
    extract_signals(df, classifier)      # layer 1 — mutates df in place
        -> generate_candidates(df)       # layer 2
        -> score_pairs(df, cand, calib)  # layers 3 and 5
        -> resolve_groups(df, scored)    # layer 4
    predict(df, calib)                   # runs layers 2-5 in one call

Callers must run `extract_signals` themselves before `predict`, because building
the `TemplateClassifier` is expensive and is meant to be hoisted out of the loop.

Coupling
--------
The normalisation regexes, the cluster vocabularies and the calibration weights
form one unit. Renaming a feature, editing a surname list or regenerating the
cluster artifact renumbers or relabels clusters and silently invalidates the
stored weights; all three must be regenerated together.
"""

import re
import pickle
import numpy as np
import pandas as pd
import torch
import hdbscan
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from sentence_transformers import SentenceTransformer

# ── Constants ──────────────────────────────────────────────────────────────
AMT_TOL             = 1.0
BALANCE_TOL         = 1.0
PAIR_SCORE_THRESHOLD= 0.50
EXPANSION_PRIMARY   = 0.50
EXPANSION_SECONDARY = 0.0

# ── Vietnamese normalisation ───────────────────────────────────────────────
VN_SURNAMES = (
    r"nguyen|tran|le|pham|hoang|huynh|phan|vo|vu|dang|bui|do|ho|"
    r"ngo|duong|ly|truong|lam|dinh|cao|mai|trinh|tang|to|ha|chau|luu|kieu|"
    r"thai|trung|kha|ka|tu|ton|chu|ban|au|bach|diep|hua|kim|la|lieu|luong|"
    r"ma|nhan|ong|quach|son|than|tieu|trieu|truc|ung|vien|vinh|xuong|y"
)
NAME_RE = re.compile(
    rf"\b(?:{VN_SURNAMES})(?:\s+\w+){{1,5}}?"
    rf"(?=\s+(?:gttt|cn|nc|cua|ngay|gn|thanh|tat|theo|so|\d|<|$))",
    re.IGNORECASE,
)
STANDALONE_SURNAME = re.compile(rf"\b(?:{VN_SURNAMES})\b", re.IGNORECASE)
NOISE_TOKENS = re.compile(
    r"\b(thi|van|ngoc|huu|cong|tien|duy|quoc|anh|hong|kim|ba|ut|sang|"
    r"hieu|truc|chi|nam|hung|long|hoa|huong|hue|trang|lan|tam|hanh|phuong|thanh|thuy|"
    r"thuong|hai|son|trung|dung|cuong|tuan|nga|linh|tu|chau|khanh|loi|dai|toan|phong|"
    r"ban|bac|nhan|sau|chai|teo|hau|loan|luc|tham|tinh|nhi|ven|chuc|sang|khoa|nghia|"
    r"kien|tho|chien|chau|cuc|tieu|nhung|y|bon|nguyet|mai|oanh|hoan|chanh|cam|xuan|thu|minh|le)\b",
    re.IGNORECASE,
)


def normalise_remark(text: str) -> str:
    """Strip volatile and identifying tokens from a raw remark so that remarks
    describing the same kind of transaction collapse onto the same string.

    Parameters
    ----------
    text : str
        Raw remark text (``CUST_REMARKS`` concatenated with ``CUST_REMARKS2``
        upstream). Non-string input is tolerated and yields ``""``.

    Returns
    -------
    str
        The normalised remark, whitespace-collapsed and lower-cased. Empty
        string when the input is not a string, is blank, or is reduced to
        nothing by the substitutions.

    Notes
    -----
    Substitution order is load-bearing. Numeric runs are removed *before* name
    matching so that ``NAME_RE``'s lookahead terminators (``gttt``, ``cn``,
    ``ngay``, a digit, end-of-string, ...) still line up once amounts and
    account numbers are gone.

    The passes, in order:

    1. Pipe-delimited interbank headers ``|<6+ digits>|<2-3>|<2-3>|`` -> ``<PIPE>``.
    2. ``d/m/y`` dates -> ``<DATE>``.
    3. Runs of 8+ digits (account numbers, long reference IDs) -> removed.
    4. Separator-formatted amounts with an optional currency suffix -> removed.
    5. Runs of 3-7 digits -> removed.
    6. Person names matched by ``NAME_RE`` (a Vietnamese surname followed by 1-5
       words and a terminator) -> ``<NAME>``.
    7. Leftover standalone surnames -> removed.
    8. The abbreviation ``kh`` -> removed.
    9. Common given names in ``NOISE_TOKENS`` -> removed.

    Finally, a string longer than 20 characters whose two halves are identical
    is collapsed to a single half; the source system duplicates some remarks.

    Editing ``VN_SURNAMES``, ``NOISE_TOKENS`` or ``NAME_RE`` changes the text fed
    to the embedder, which changes cluster assignment, which invalidates the
    stored calibration weights.
    """
    if not isinstance(text, str):
        return ""
    s = text.lower().strip()
    if not s:
        return ""
    s = re.sub(r"\|\d{6,}\|\d{2,3}\|\d{2,3}\|", " <PIPE> ", s)
    s = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", " <DATE> ", s)
    s = re.sub(r"\b\d{8,}\b", " ", s)
    s = re.sub(r"\b\d[\d,.]{2,}\s*(?:vnd|d|usd|eur)?\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d{3,7}\b", " ", s)
    s = NAME_RE.sub(" <NAME> ", s)
    s = STANDALONE_SURNAME.sub(" ", s)
    s = re.sub(r"\bkh\b", " ", s)
    s = NOISE_TOKENS.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 20:
        h = len(s) // 2
        if s[:h].strip() == s[h:].strip():
            s = s[:h].strip()
    return re.sub(r"\s+", " ", s).strip()


# ── Template classifier ────────────────────────────────────────────────────
class TemplateClassifier:
    """Assign each transaction remark to a recurring *template* cluster.

    Wraps the frozen three-stage pipeline fitted offline in the Colab notebook:
    a sentence-transformer embedding, a UMAP projection, and an HDBSCAN cluster
    model queried through ``hdbscan.approximate_predict``. Nothing here is
    refitted at predict time — the models are loaded from a pickled artifact and
    used purely for inference.

    The resulting template label is what the pair-feature layer consumes: the
    debit/credit template pairings in ``PATTERN_FEATURES`` are expressed in terms
    of the human-readable names this class resolves.

    Attributes
    ----------
    embedder : sentence_transformers.SentenceTransformer
        Encoder producing L2-normalised sentence embeddings.
    umap_model : umap.UMAP
        Fitted dimensionality reducer; only ``transform`` is called.
    hdb_model : hdbscan.HDBSCAN
        Fitted cluster model, queried via ``approximate_predict``.
    normalise_fn : Callable[[str], str]
        Text normaliser applied before embedding, normally `normalise_remark`.
    ctfidf : Any
        Top class-based TF-IDF terms per cluster, carried for interpretability;
        not consulted during classification.
    cluster_names : dict[int, str]
        Optional map from cluster id to human-readable name.
    """

    def __init__(self, embedder, umap_model, hdb_model, normalise_fn, ctfidf, cluster_names=None):
        """Store the pre-fitted components that make up the classifier.

        Parameters
        ----------
        embedder : sentence_transformers.SentenceTransformer
            Encoder used to embed normalised remarks.
        umap_model : umap.UMAP
            Fitted UMAP reducer.
        hdb_model : hdbscan.HDBSCAN
            Fitted HDBSCAN model, must have been fitted with
            ``prediction_data=True`` for ``approximate_predict`` to work.
        normalise_fn : Callable[[str], str]
            Normaliser applied to each remark before embedding.
        ctfidf : Any
            Per-cluster top terms, retained for inspection only.
        cluster_names : dict[int, str] or None, optional
            Cluster id to display name. ``None`` becomes an empty dict, in which
            case `cluster_name` falls back to ``cluster_NN`` labels.
        """
        self.embedder      = embedder
        self.umap_model    = umap_model
        self.hdb_model     = hdb_model
        self.normalise_fn  = normalise_fn
        self.ctfidf        = ctfidf
        self.cluster_names = cluster_names or {}

    @classmethod
    def load(cls, artifact_path, normalise_fn, names_csv=None, device=None):
        """Build a classifier from the pickled cluster artifact on disk.

        Parameters
        ----------
        artifact_path : str or pathlib.Path
            Path to the pickle produced by the training notebook. Must contain
            the keys ``embed_model_name``, ``umap_model``, ``hdbscan_model`` and
            ``ctfidf_top_terms``. Note the shipped file's name contains a space
            before the extension: ``template_clusters .pkl``.
        normalise_fn : Callable[[str], str]
            Normaliser to apply before embedding, normally `normalise_remark`.
        names_csv : str or pathlib.Path or None, optional
            CSV mapping clusters to display names. Requires ``cluster_id`` and
            ``human_name`` columns; rows with a missing or blank ``human_name``
            are skipped. A path that does not exist is ignored silently.
        device : str or None, optional
            Torch device for the encoder. Defaults to ``"cuda"`` when CUDA is
            available, otherwise ``"cpu"``.

        Returns
        -------
        TemplateClassifier
            Ready-to-use classifier.

        Notes
        -----
        The encoder is fetched by name through `SentenceTransformer`, so the
        first call on a cold machine needs network access to the model hub.

        The ``cluster_name`` column that also exists in the names CSV is *not*
        read — only ``human_name`` is.
        """
        with open(artifact_path, "rb") as f:
            art = pickle.load(f)
        device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        emb    = SentenceTransformer(art["embed_model_name"], device=device)
        names  = {}
        if names_csv and Path(names_csv).exists():
            ndf   = pd.read_csv(names_csv)
            names = {
                int(r["cluster_id"]): str(r["human_name"]).strip()
                for _, r in ndf.iterrows()
                if pd.notna(r.get("human_name", None)) and str(r["human_name"]).strip()
            }
        return cls(emb, art["umap_model"], art["hdbscan_model"], normalise_fn,
                   art["ctfidf_top_terms"], names)

    def classify_batch(self, remarks):
        """Assign a template cluster id to each remark in a batch.

        Parameters
        ----------
        remarks : Sequence[str]
            Raw remark strings, one per transaction row.

        Returns
        -------
        numpy.ndarray
            Integer array of shape ``(len(remarks),)`` holding one cluster id per
            input. ``-1`` marks noise.

        Notes
        -----
        Remarks that normalise to fewer than 3 characters never reach the model
        and are returned as ``-1``, which makes them indistinguishable from rows
        HDBSCAN genuinely labelled as noise. That conflation is intentional —
        both are treated as the ``noise`` template downstream.

        When every remark in the batch is filtered out, an all-``-1`` array is
        returned without touching the encoder.

        Embedding runs with ``batch_size=64`` and L2 normalisation, matching the
        settings the UMAP and HDBSCAN models were fitted under; changing them
        shifts the projection and corrupts cluster assignment.
        """
        normed = [self.normalise_fn(r) for r in remarks]
        valid  = [(i, n) for i, n in enumerate(normed) if n and len(n) >= 3]
        if not valid:
            return np.full(len(remarks), -1, dtype=int)
        vi, vn = zip(*valid)
        vi, vn = list(vi), list(vn)
        emb    = self.embedder.encode(
            vn, convert_to_numpy=True, normalize_embeddings=True,
            batch_size=64, show_progress_bar=False,
        )
        red          = self.umap_model.transform(emb)
        labels, _    = hdbscan.approximate_predict(self.hdb_model, red)
        out          = np.full(len(remarks), -1, dtype=int)
        for i, l in zip(vi, labels):
            out[i] = int(l)
        return out

    def cluster_name(self, cid: int) -> str:
        """Resolve a cluster id to the display name used by the feature vocabulary.

        Parameters
        ----------
        cid : int
            Cluster id as returned by `classify_batch`.

        Returns
        -------
        str
            ``"noise"`` for ``-1``; otherwise the human name from
            ``cluster_names`` if one was supplied, else a zero-padded
            ``cluster_NN`` fallback.

        Notes
        -----
        These names are the literal strings `PATTERN_FEATURES` and the pattern
        feature keys are written against, so regenerating the cluster artifact
        (which renumbers clusters) invalidates that vocabulary.
        """
        if cid == -1:
            return "noise"
        return self.cluster_names.get(cid, f"cluster_{cid:02d}")


# ── Vocabulary ─────────────────────────────────────────────────────────────
PATTERN_FEATURES = [
    ("contract_payment_simple",            "contract_payment_simple"),
    ("contract_payment_simple",            "noise"),
    ("police_admin_payment_canonical",     "police_admin_payment_canonical"),
    ("police_admin_payment_with_date",     "police_admin_payment_canonical"),
    ("noise",                              "interbank_pipe_fx_value_same_day"),
    ("interbank_pipe_fx_value_same_day",   "treasury_xnmb_pgd"),
    ("interbank_pipe_fx_value_same_day",   "treasury_hcm_fx_mbnt"),
    ("treasury_xnmb_pgd",                  "interbank_pipe_fx_value_same_day"),
    ("loan_settlement_hdtg_shbfc",         "interbank_pipe_mm_treasury"),
    ("interbank_pipe_mm_treasury",         "loan_settlement_hdtg_shbfc"),
]

KEYWORD_FINGERPRINTS = [
    ("kw_hdtg",    re.compile(r"\bhdtg\b")),
    ("kw_xnmb",    re.compile(r"\bxnmb\b")),
    ("kw_shbfc",   re.compile(r"\bshbfc\b")),
    ("kw_interest", re.compile(r"\binterest\b")),
]

NAMED_PREFIX_COMBOS = [
    (("CTSF", "SBS"), "ctsf_sbs"),
    (("AFSF", "CTSF"), "afsf_ctsf"),
]

MECHANISM_PRIORITY = [
    ("is_base_reversal",                                                          "same_sogd",           30.28),
    ("has_sogd_base_in_partner_remarks",                                          "refno_in_custremarks", 15.34),
    ("pattern_dr_noise_cr_interbank_pipe_fx_value_same_day",                      "one_one_sogd_prefix",  3.59),
    ("pattern_dr_interbank_pipe_fx_value_same_day_cr_treasury_xnmb_pgd",          "one_one_sogd_prefix",  3.59),
    ("pattern_dr_interbank_pipe_fx_value_same_day_cr_treasury_hcm_fx_mbnt",       "one_one_sogd_prefix",  3.59),
    ("pattern_dr_treasury_xnmb_pgd_cr_interbank_pipe_fx_value_same_day",          "one_one_sogd_prefix",  3.59),
    ("pattern_dr_loan_settlement_hdtg_shbfc_cr_interbank_pipe_mm_treasury",       "one_one_sogd_prefix",  3.59),
    ("pattern_dr_interbank_pipe_mm_treasury_cr_loan_settlement_hdtg_shbfc",       "one_one_sogd_prefix",  3.59),
    ("pattern_dr_police_admin_payment_with_date_cr_police_admin_payment_canonical","keywords",             1.70),
    ("pattern_dr_police_admin_payment_canonical_cr_police_admin_payment_canonical","keywords",             1.68),
    ("has_shared_12_digit_id",                                                    "keywords",             1.66),
    ("has_shared_15_digit_id",                                                    "keywords",             1.66),
    ("pattern_dr_contract_payment_simple_cr_contract_payment_simple",             "keywords",             1.66),
    ("prefix_combo_ctsf_sbs",                                                     "keywords",             1.65),
    ("pattern_dr_contract_payment_simple_cr_noise",                               "keywords",             1.57),
    ("prefix_combo_afsf_ctsf",                                                    "keywords",             1.33),
]


# ── Signal extraction ──────────────────────────────────────────────────────
def extract_signals(df: pd.DataFrame, classifier: TemplateClassifier) -> pd.DataFrame:
    """Decorate a raw transaction frame with every per-row signal the pair layer needs.

    Parameters
    ----------
    df : pandas.DataFrame
        Transaction frame. ``GHI_CO``, ``GHI_NO``, ``NGAYGD`` and ``SOGD_ID`` are
        required; ``REFS_STR``, ``found_by``, ``CUST_REMARKS``, ``CUST_REMARKS2``,
        ``CHI_NHANH`` and ``SO_TAI_KHOAN`` are created as empty strings when
        absent.
    classifier : TemplateClassifier
        Loaded template classifier used to label remarks.

    Returns
    -------
    pandas.DataFrame
        The same object that was passed in — **the frame is mutated in place**
        and returned for convenience, not copied.

    Notes
    -----
    Columns added, all prefixed with ``_``:

    ``_sogd_base``, ``_sogd_suffix``
        ``SOGD_ID`` split on the first ``.``; a missing suffix becomes ``""``.
    ``_sogd_prefix``
        First four characters of the base, upper-cased (``CTSF``, ``AFSF``, ...).
    ``_remarks``
        Lower-cased ``CUST_REMARKS`` and ``CUST_REMARKS2`` joined with a space.
    ``_tokens``
        Set of alphanumeric tokens of length >= 4. Computed but not read by any
        current feature.
    ``_long_nums``, ``_12_ids``, ``_15_ids``
        Sets of 8+ digit runs, and the exactly-12 and exactly-15 digit subsets.
    ``_cluster_id``, ``_template_dom``
        Template cluster id and its resolved display name.
    ``_kw_*``
        One boolean per `KEYWORD_FINGERPRINTS` entry.

    ``GHI_CO`` and ``GHI_NO`` are coerced to numeric with non-parseable values
    becoming ``0.0``, so a malformed amount silently reads as a zero leg rather
    than raising.

    ``REFS_STR`` and ``found_by`` are ground-truth columns. They are normalised
    here for convenience but must never reach a scored feature — only the
    offline `calibrate` may read them.
    """
    df["GHI_CO"] = pd.to_numeric(df["GHI_CO"], errors="coerce").fillna(0.0)
    df["GHI_NO"] = pd.to_numeric(df["GHI_NO"], errors="coerce").fillna(0.0)
    for c in ["REFS_STR", "found_by", "CUST_REMARKS", "CUST_REMARKS2", "SOGD_ID", "CHI_NHANH"]:
        df[c] = df[c].fillna("").astype(str).str.strip() if c in df.columns else ""
    df["NGAYGD"]       = pd.to_datetime(df["NGAYGD"], errors="coerce")
    df["SO_TAI_KHOAN"] = df["SO_TAI_KHOAN"].fillna("").astype(str).str.strip() if "SO_TAI_KHOAN" in df.columns else ""
    df["_sogd_base"]   = df["SOGD_ID"].str.split(".").str[0]
    df["_sogd_suffix"] = df["SOGD_ID"].str.split(".").str[1].fillna("")
    df["_sogd_prefix"] = df["_sogd_base"].str[:4].str.upper()
    df["_remarks"]     = (df["CUST_REMARKS"].str.lower() + " " + df["CUST_REMARKS2"].str.lower()).str.strip()
    df["_tokens"]      = df["_remarks"].apply(lambda s: set(re.findall(r"[a-z0-9]{4,}", s)))
    df["_long_nums"]   = df["_remarks"].apply(lambda s: set(re.findall(r"\b\d{8,}\b", s)))
    df["_12_ids"]      = df["_long_nums"].apply(lambda s: {t for t in s if len(t) == 12})
    df["_15_ids"]      = df["_long_nums"].apply(lambda s: {t for t in s if len(t) == 15})
    cids               = classifier.classify_batch(df["_remarks"].tolist())
    df["_cluster_id"]  = cids
    df["_template_dom"]= [classifier.cluster_name(int(c)) for c in cids]
    for kw, kre in KEYWORD_FINGERPRINTS:
        df[f"_{kw}"] = df["_remarks"].str.contains(kre, regex=True, na=False)
    return df


# ── Candidate generation ───────────────────────────────────────────────────
def generate_candidates(df: pd.DataFrame) -> pd.DataFrame:
    """Enumerate every candidate pair of transactions within an account-day block.

    Parameters
    ----------
    df : pandas.DataFrame
        Frame already processed by `extract_signals`; needs ``SO_TAI_KHOAN`` and
        a datetime ``NGAYGD``.

    Returns
    -------
    pandas.DataFrame
        One row per candidate pair with columns:

        ``a_idx``, ``b_idx`` : int
            Row labels of the two members, always ``a_idx`` before ``b_idx`` in
            the block's internal order (upper triangle only, no self-pairs and
            no duplicates).
        ``block_id`` : str
            ``"{account}|{date}"``, with ``NA`` as the date when ``NGAYGD`` is
            missing.

    Notes
    -----
    Blocking is on ``(SO_TAI_KHOAN, NGAYGD)``: **cross-account and cross-day
    matches are structurally impossible.** A genuine match the engine misses is
    far more often a blocking-key problem than a scoring problem.

    Blocks with fewer than two rows are skipped. Pair count is quadratic in
    block size, so a single account with a very heavy posting day dominates both
    runtime and memory.
    """
    a, b, bid = [], [], []
    for (acct, date), blk in df.groupby(["SO_TAI_KHOAN", "NGAYGD"], sort=False):
        idx = blk.index.to_numpy()
        n   = len(idx)
        if n < 2:
            continue
        ia, ja = np.triu_indices(n, k=1)
        a.extend(idx[ia].tolist())
        b.extend(idx[ja].tolist())
        bid.extend([f"{acct}|{date.date() if pd.notna(date) else 'NA'}"] * len(ia))
    return pd.DataFrame({"a_idx": a, "b_idx": b, "block_id": bid})


# ── Pair features ──────────────────────────────────────────────────────────
def compute_pair_features(df, a_idx, b_idx):
    """Compute the vectorised boolean evidence for a batch of candidate pairs.

    Parameters
    ----------
    df : pandas.DataFrame
        Frame already processed by `extract_signals`.
    a_idx : array-like of int
        Positional indices of the first member of each pair.
    b_idx : array-like of int
        Positional indices of the second member, same length as ``a_idx``.

    Returns
    -------
    dict[str, numpy.ndarray]
        Feature name to array of length ``len(a_idx)``. All entries are boolean
        except ``a_amt`` and ``b_amt``, which are floats.

        Amount and side
            ``is_amount_match`` (within `AMT_TOL`), ``is_opposite_sides``,
            ``same_side``, ``is_balanced_pair`` (amount match *and* opposite
            sides), ``a_amt``, ``b_amt``.
        SOGD structure
            ``same_prefix``, ``same_suffix``, ``has_same_sogd_base``,
            ``is_base_reversal`` (same base, different suffix),
            ``same_side_shared_base``, ``sequential_sogd``.
        Cross-reference
            ``same_branch``, ``has_sogd_base_in_partner_remarks``,
            ``has_shared_12_digit_id``, ``has_shared_15_digit_id``,
            ``share_long_number_any``.
        Template pattern
            One ``pattern_dr_<debit>_cr_<credit>`` flag per `PATTERN_FEATURES`
            entry, plus the catch-all ``pattern_dr_other_cr_other``.
        Keyword
            One flag per `KEYWORD_FINGERPRINTS` entry, true when *either* side
            of the pair contains the keyword.
        Prefix combination
            One flag per `NAMED_PREFIX_COMBOS` entry, plus
            ``prefix_combo_other``.

    Notes
    -----
    Each side's amount is whichever of its credit or debit leg is positive, so a
    row with both legs zero contributes ``0.0`` and trivially "matches" any other
    zero row; the plausibility gate in `score_pairs` is what stops such pairs
    from scoring.

    ``sequential_sogd`` compares the numeric tail from character 10 onward of
    both bases and fires when they differ by 1 to 3. Bases of 10 characters or
    fewer, or with a non-numeric tail, never fire.

    ``same_branch`` compares ``CHI_NHANH`` verbatim, so two rows with a missing
    branch code count as *the same* branch.

    ``has_sogd_base_in_partner_remarks`` requires a base of at least 4
    characters and tests containment in either direction.

    ``debit_dom`` / ``credit_dom`` pick the template of whichever side carries
    the debit and credit leg respectively; when neither side has a debit (or
    neither a credit) the corresponding role falls back to ``"noise"``, which is
    itself a legitimate template name in the pattern vocabulary.

    The pattern and prefix-combination groups are mutually exclusive and
    exhaustive by construction — the ``_other`` catch-all is the negation of
    everything else in its group.
    """
    co  = df["GHI_CO"].values;       no  = df["GHI_NO"].values
    bs  = df["_sogd_base"].values;   sf  = df["_sogd_suffix"].values
    pf  = df["_sogd_prefix"].values; rm  = df["_remarks"].values
    br  = df["CHI_NHANH"].values;    ln  = df["_long_nums"].values
    d12 = df["_12_ids"].values;      d15 = df["_15_ids"].values
    td  = df["_template_dom"].values

    aco, bco = co[a_idx], co[b_idx]
    ano, bno = no[a_idx], no[b_idx]
    abs_, bbs = bs[a_idx], bs[b_idx]
    asf, bsf  = sf[a_idx], sf[b_idx]
    apf, bpf  = pf[a_idx], pf[b_idx]
    arm, brm  = rm[a_idx], rm[b_idx]
    abr, bbr  = br[a_idx], br[b_idx]
    aln, bln  = ln[a_idx], ln[b_idx]
    a12, b12  = d12[a_idx], d12[b_idx]
    a15, b15  = d15[a_idx], d15[b_idx]
    atd, btd  = td[a_idx], td[b_idx]
    n         = len(a_idx)

    a_amt = np.where(aco > 0, aco, ano)
    b_amt = np.where(bco > 0, bco, bno)
    is_amount_match      = np.abs(a_amt - b_amt) < AMT_TOL
    a_is_cr              = aco > 0
    b_is_cr              = bco > 0
    is_opposite          = a_is_cr != b_is_cr
    is_balanced          = is_amount_match & is_opposite
    same_side            = a_is_cr == b_is_cr
    same_prefix          = (apf == bpf) & (apf != "")
    same_suffix          = (asf == bsf) & (asf != "")
    has_same_base        = (abs_ == bbs) & (abs_ != "")
    is_base_reversal     = has_same_base & (asf != bsf)
    same_side_shared_base= has_same_base & same_side

    seq = np.zeros(n, dtype=bool)
    for i in range(n):
        x = abs_[i][10:] if len(abs_[i]) > 10 else ""
        y = bbs[i][10:]  if len(bbs[i])  > 10 else ""
        if x.isdigit() and y.isdigit():
            seq[i] = 0 < abs(int(x) - int(y)) <= 3

    same_branch = abr == bbr
    a_in_b = np.array([len(abs_[i]) >= 4 and abs_[i].lower() in brm[i] for i in range(n)])
    b_in_a = np.array([len(bbs[i]) >= 4 and bbs[i].lower() in arm[i] for i in range(n)])
    has_sogd_base_in_partner_remarks = a_in_b | b_in_a

    share_12     = np.array([bool(a12[i] & b12[i]) for i in range(n)])
    share_15     = np.array([bool(a15[i] & b15[i]) for i in range(n)])
    share_long_any = np.array([len(aln[i] & bln[i]) > 0 for i in range(n)])

    debit_dom  = np.where(ano > 0, atd, np.where(bno > 0, btd, "noise"))
    credit_dom = np.where(aco > 0, atd, np.where(bco > 0, btd, "noise"))
    pat     = {}
    matched = np.zeros(n, dtype=bool)
    for dr, cr in PATTERN_FEATURES:
        f = (debit_dom == dr) & (credit_dom == cr)
        pat[f"pattern_dr_{dr}_cr_{cr}"] = f
        matched |= f
    pat["pattern_dr_other_cr_other"] = ~matched

    kw = {}
    for kwn, _ in KEYWORD_FINGERPRINTS:
        c = df[f"_{kwn}"].values
        kw[kwn] = c[a_idx] | c[b_idx]

    sc = np.empty(n, dtype=object)
    for i in range(n):
        sc[i] = tuple(sorted([apf[i], bpf[i]]))
    pcomb = {}
    mc    = np.zeros(n, dtype=bool)
    for ct, suf in NAMED_PREFIX_COMBOS:
        tgt  = tuple(sorted(ct))
        f    = np.array([c == tgt for c in sc], dtype=bool)
        pcomb[f"prefix_combo_{suf}"] = f
        mc |= f
    pcomb["prefix_combo_other"] = ~mc

    out = {
        "is_balanced_pair":               is_balanced,
        "is_amount_match":                is_amount_match,
        "is_opposite_sides":              is_opposite,
        "same_side":                      same_side,
        "same_prefix":                    same_prefix,
        "same_suffix":                    same_suffix,
        "has_same_sogd_base":             has_same_base,
        "is_base_reversal":               is_base_reversal,
        "same_side_shared_base":          same_side_shared_base,
        "sequential_sogd":                seq,
        "same_branch":                    same_branch,
        "has_sogd_base_in_partner_remarks": has_sogd_base_in_partner_remarks,
        "has_shared_12_digit_id":         share_12,
        "has_shared_15_digit_id":         share_15,
        "share_long_number_any":          share_long_any,
        "a_amt":                          a_amt,
        "b_amt":                          b_amt,
    }
    out.update(pat)
    out.update(kw)
    out.update(pcomb)
    return out


# ── Calibration dataclasses ────────────────────────────────────────────────
@dataclass
class FeatureWeight:
    """Fellegi-Sunter log-likelihood ratios for a single boolean feature.

    Attributes
    ----------
    name : str
        Feature name, matching a key of the `compute_pair_features` result.
    p_pos : float
        Smoothed probability the feature fires on a matched pair (the m-value).
    p_neg : float
        Smoothed probability the feature fires on an unmatched pair (u-value).
    llr_true : float
        ``log(p_pos / p_neg)`` — evidence contributed when the feature fires.
    llr_false : float
        ``log((1 - p_pos) / (1 - p_neg))`` — evidence contributed when it does
        not. Absence is informative too, which is why both are stored.
    """

    name:      str
    p_pos:     float
    p_neg:     float
    llr_true:  float
    llr_false: float


@dataclass
class Calibration:
    """A complete, frozen scoring model for the pair layer.

    Attributes
    ----------
    weights : dict[str, FeatureWeight]
        Feature name to its learned log-likelihood ratios. `score_pairs`
        iterates *this* mapping, not `CALIB_BOOL_FEATURES`, so a feature absent
        here simply contributes nothing.
    base_log_odds : float
        Prior log-odds of a match, ``log(n_positive / n_negative)`` from the
        training data. Strongly negative, since most candidate pairs in a block
        are non-matches.
    threshold : float, default `PAIR_SCORE_THRESHOLD`
        Minimum sigmoid score for a pair to be emitted by `score_pairs`.
    """

    weights:       dict
    base_log_odds: float
    threshold:     float = PAIR_SCORE_THRESHOLD


CALIB_BOOL_FEATURES = [
    "is_balanced_pair", "is_amount_match", "is_opposite_sides", "same_side",
    "same_prefix", "same_suffix", "has_same_sogd_base", "is_base_reversal",
    "same_side_shared_base", "sequential_sogd", "same_branch",
    "has_sogd_base_in_partner_remarks", "has_shared_12_digit_id",
    "has_shared_15_digit_id", "share_long_number_any",
] + [f"pattern_dr_{d}_cr_{c}" for d, c in PATTERN_FEATURES] \
  + ["pattern_dr_other_cr_other"] \
  + [k for k, _ in KEYWORD_FINGERPRINTS] \
  + [f"prefix_combo_{s}" for _, s in NAMED_PREFIX_COMBOS] \
  + ["prefix_combo_other"]


def load_calibration(path: str) -> Calibration:
    """Load pre-computed calibration weights from JSON. Never recomputes.

    This is the production path: weights are frozen at training time and read
    back verbatim, so scoring is deterministic across runs and machines.

    Parameters
    ----------
    path : str
        Path to the weights JSON, normally
        ``artifacts/calibration_weights.json``. Must contain ``weights``,
        ``base_log_odds`` and ``threshold``.

    Returns
    -------
    Calibration
        Populated calibration. Unlike `calibrate`, the threshold comes from the
        file rather than defaulting to `PAIR_SCORE_THRESHOLD`.

    Notes
    -----
    The shipped file carries 32 weights while `CALIB_BOOL_FEATURES` lists 33
    candidates — `calibrate` drops features that never fired during training.
    The gap is harmless, but it does mean adding a feature to the vocabulary has
    no effect on scoring until the weights are regenerated.
    """
    import json
    with open(path) as f:
        d = json.load(f)
    weights = {
        name: FeatureWeight(
            name      = w["name"],
            p_pos     = w["p_pos"],
            p_neg     = w["p_neg"],
            llr_true  = w["llr_true"],
            llr_false = w["llr_false"],
        )
        for name, w in d["weights"].items()
    }
    return Calibration(
        weights       = weights,
        base_log_odds = d["base_log_odds"],
        threshold     = d["threshold"],
    )


def calibrate(df: pd.DataFrame, candidates: pd.DataFrame) -> Calibration:
    """Compute calibration from labelled data. Only used offline.

    Estimates each feature's m- and u-values by counting how often it fires
    among known-matched versus known-unmatched pairs, then converts them to the
    two log-likelihood ratios stored on a `FeatureWeight`.

    Parameters
    ----------
    df : pandas.DataFrame
        Labelled frame already processed by `extract_signals`. Ground truth is
        read from ``REFS_STR``.
    candidates : pandas.DataFrame
        Candidate pairs from `generate_candidates`.

    Returns
    -------
    Calibration
        Learned weights and prior. ``threshold`` is left at the
        `PAIR_SCORE_THRESHOLD` default, since it is a policy choice rather than
        something estimated here.

    Notes
    -----
    A pair is labelled positive when both rows carry the *same* ``REFS_STR``.
    Rows whose ``REFS_STR`` is a sentinel (``"true"``, ``"false"``, ``""``,
    ``"nan"``) are unlabelled and are dropped along with any pair touching them.

    Counts are smoothed with ``eps = 0.5`` (Jeffreys-style) so that a feature
    firing in only one class still yields finite log ratios. Features that fire
    in neither class are omitted entirely rather than given zero weight.

    Features are assumed conditionally independent given match status — the
    standard Fellegi-Sunter simplification. Several features here are plainly
    correlated (``is_balanced_pair`` implies ``is_amount_match``;
    ``is_base_reversal`` implies ``has_same_sogd_base``), so the summed evidence
    is over-confident and the resulting scores should be read as a ranking
    rather than as calibrated probabilities.

    This function reads ground-truth columns and must never be called on the
    prediction path.
    """
    refs  = df["REFS_STR"].values.astype(str)
    sent  = np.isin(refs, ["true", "false", "", "nan"])
    ai    = candidates["a_idx"].values
    bi    = candidates["b_idx"].values
    keep  = ~(sent[ai] | sent[bi])
    ak, bk= ai[keep], bi[keep]
    labels= (refs[ak] == refs[bk]).astype(int)
    feats = compute_pair_features(df, ak, bk)
    npos, nneg = int(labels.sum()), int((1 - labels).sum())
    eps   = 0.5
    weights = {}
    pm, nm  = labels == 1, labels == 0
    for name in CALIB_BOOL_FEATURES:
        if name not in feats:
            continue
        col = feats[name].astype(bool)
        npf = int(col[pm].sum())
        nnf = int(col[nm].sum())
        if npf == 0 and nnf == 0:
            continue
        mp  = (npf + eps) / (npos + 2 * eps)
        up  = (nnf + eps) / (nneg + 2 * eps)
        weights[name] = FeatureWeight(
            name, float(mp), float(up),
            float(np.log(mp / up)),
            float(np.log((1 - mp) / (1 - up))),
        )
    return Calibration(weights, float(np.log(npos / nneg)))


# ── Scoring ────────────────────────────────────────────────────────────────
def score_pairs(df: pd.DataFrame, candidates: pd.DataFrame,
                calib: Calibration) -> pd.DataFrame:
    """Score every candidate pair and return those at or above the threshold.

    Parameters
    ----------
    df : pandas.DataFrame
        Frame already processed by `extract_signals`.
    candidates : pandas.DataFrame
        Candidate pairs from `generate_candidates`.
    calib : Calibration
        Frozen weights, prior and threshold.

    Returns
    -------
    pandas.DataFrame
        Surviving pairs only, with columns ``a_idx``, ``b_idx``, ``block_id``,
        ``score`` (float in ``[0, 1]``) and ``mechanism`` (str).

    Notes
    -----
    Scoring proceeds in four steps, and the order matters:

    1. **Accumulate.** Start at ``calib.base_log_odds`` and add ``llr_true`` or
       ``llr_false`` for each feature in ``calib.weights``, then apply a sigmoid.
    2. **Override.** Evidence treated as conclusive bypasses the model — a base
       reversal that is opposite-sided and balanced, or a SOGD base found in the
       partner's remarks while balanced, is forced to ``1.0``; a same-side base
       reversal is floored at ``0.95``.
    3. **Gate.** Any pair that is neither ``is_balanced_pair`` nor
       ``same_side_shared_base`` is forced to ``0.0``. This runs *after* the
       overrides and therefore outranks them: the gate is the single strongest
       determinant of the output.
    4. **Explain and filter.** Attach a mechanism label, keep ``score >=
       calib.threshold``.

    The mechanism string is multi-label: `MECHANISM_PRIORITY` is walked in order
    and every firing feature contributes its label, de-duplicated and joined
    with ``|`` (several features map to the same label). Pairs that fire nothing
    are labelled ``balanced_only``. The float in each `MECHANISM_PRIORITY` tuple
    is association-rule lift carried for reference and is not read here.
    """
    ai = candidates["a_idx"].values
    bi = candidates["b_idx"].values
    f  = compute_pair_features(df, ai, bi)
    n  = len(ai)

    plausible = f["is_balanced_pair"] | f["same_side_shared_base"]
    lo        = np.full(n, calib.base_log_odds)
    for name, w in calib.weights.items():
        col = f[name].astype(bool)
        lo += np.where(col, w.llr_true, w.llr_false)
    score = 1.0 / (1.0 + np.exp(-lo))

    # Deterministic overrides
    score = np.where(
        f["is_base_reversal"] & f["is_opposite_sides"] & f["is_balanced_pair"],
        1.0, score)
    score = np.where(
        f["is_base_reversal"] & f["same_side"],
        np.maximum(score, 0.95), score)
    score = np.where(
        f["has_sogd_base_in_partner_remarks"] & f["is_balanced_pair"],
        1.0, score)
    score = np.where(plausible, score, 0.0)

    # Multi-label mechanisms
    mechanisms = [[] for _ in range(n)]
    for feat_name, label, _ in MECHANISM_PRIORITY:
        if feat_name not in f:
            continue
        col = f[feat_name].astype(bool)
        for i in np.where(col)[0]:
            if label not in mechanisms[i]:
                mechanisms[i].append(label)
    mech_str = np.array(
        ["|".join(m) if m else "balanced_only" for m in mechanisms],
        dtype=object,
    )
    above = score >= calib.threshold
    return pd.DataFrame({
        "a_idx":    ai[above],
        "b_idx":    bi[above],
        "block_id": candidates["block_id"].values[above],
        "score":    score[above],
        "mechanism":mech_str[above],
    })


# ── Match group ────────────────────────────────────────────────────────────
@dataclass
class MatchGroup:
    """A set of transactions the engine believes settle against one another.

    Attributes
    ----------
    members : list[int]
        Row labels of the transactions in the group, seed pair first followed by
        any rows added during expansion.
    block_id : str
        The ``"{account}|{date}"`` block the group was resolved within.
    score : float
        Score of the *seed pair*, not of the group as a whole; rows added during
        expansion do not lower it.
    is_balanced : bool
        Whether credits and debits close to within `BALANCE_TOL`. Unbalanced
        groups are still returned, flagged false, rather than discarded.
    mechanism : str
        Justification inherited from the seed pair.
    """

    members:    list
    block_id:   str
    score:      float
    is_balanced:bool
    mechanism:  str


# ── Group resolution ───────────────────────────────────────────────────────
def resolve_groups(df: pd.DataFrame, scored: pd.DataFrame) -> list:
    """Turn scored pairs into disjoint groups that balance to zero.

    Parameters
    ----------
    df : pandas.DataFrame
        Frame already processed by `extract_signals`.
    scored : pandas.DataFrame
        Surviving pairs from `score_pairs`.

    Returns
    -------
    list[MatchGroup]
        Resolved groups in the order they were formed, i.e. by descending seed
        score. Rows never matched simply do not appear in any group.

    Notes
    -----
    Greedy and order-dependent. Pairs are consumed highest score first; a pair
    whose rows are both still free becomes a seed, and **once a row is assigned
    it is never reconsidered**, so a high-scoring pair can starve a lower-scoring
    one that would have balanced better.

    If the seed pair already closes within `BALANCE_TOL` it is emitted as-is.
    Otherwise the group expands from unassigned rows in the same block:

    1. *Primary expansion*, only for a same-side seed: pull in one row from the
       opposite side whose pair score against either seed member is at least
       `EXPANSION_PRIMARY`. Ties resolve to the last candidate examined.
    2. *Secondary expansion*: repeatedly add whichever remaining row most
       reduces the absolute gap, requiring a strict improvement of more than
       ``1e-9``. Stops when no row improves the gap or the pool empties.

    `EXPANSION_SECONDARY` is ``0.0`` and the guard reads
    ``bl < EXPANSION_SECONDARY`` against a score that is always non-negative, so
    **the secondary score floor never fires** — expansion is currently bounded
    only by the gap arithmetic. Raising the constant above zero activates it.

    Because secondary expansion optimises the gap alone, it can attach rows with
    no textual or reference link to the seed; a group's ``mechanism`` describes
    why its *seed pair* matched, not why every member belongs.
    """
    co   = df["GHI_CO"].values
    no   = df["GHI_NO"].values
    psc  = {}
    for ai, bi, s in zip(scored["a_idx"].values,
                         scored["b_idx"].values,
                         scored["score"].values):
        psc[(int(ai), int(bi))] = float(s)
        psc[(int(bi), int(ai))] = float(s)

    acct = df["SO_TAI_KHOAN"].values
    date = df["NGAYGD"].values
    b2r  = defaultdict(list)
    for r in df.index:
        key = f"{acct[r]}|{pd.Timestamp(date[r]).date() if pd.notna(date[r]) else 'NA'}"
        b2r[key].append(int(r))

    assigned = {}
    groups   = []
    for _, row in scored.sort_values("score", ascending=False).iterrows():
        ai, bi = int(row["a_idx"]), int(row["b_idx"])
        if ai in assigned or bi in assigned:
            continue
        aco, ano = co[ai], no[ai]
        bco, bno = co[bi], no[bi]
        members  = [ai, bi]
        gap      = (aco + bco) - (ano + bno)

        if abs(gap) <= BALANCE_TOL:
            for m in members:
                assigned[m] = len(groups)
            groups.append(MatchGroup(
                members, row["block_id"], float(row["score"]), True, row["mechanism"]))
            continue

        same_side = (aco > 0) == (bco > 0)
        pool      = [i for i in b2r[row["block_id"]]
                     if i not in assigned and i not in members]

        if same_side:
            want_cr = not (aco > 0)
            best = None
            best_s = EXPANSION_PRIMARY
            for ci in pool:
                if (co[ci] > 0) != want_cr:
                    continue
                s = max(psc.get((ai, ci), 0.0), psc.get((bi, ci), 0.0))
                if s >= best_s:
                    best_s = s
                    best   = ci
            if best is not None:
                members.append(best)
                gap = sum(co[m] for m in members) - sum(no[m] for m in members)
                pool.remove(best)

        while abs(gap) > BALANCE_TOL and pool:
            bc  = None
            bng = abs(gap)
            bsg = gap
            for ci in pool:
                ng = gap + co[ci] - no[ci]
                if abs(ng) < bng - 1e-9:
                    bng = abs(ng)
                    bc  = ci
                    bsg = ng
            if bc is None:
                break
            bl = max(psc.get((m, bc), 0.0) for m in members)
            if bl < EXPANSION_SECONDARY and len(members) >= 2:
                break
            members.append(bc)
            gap = bsg
            pool.remove(bc)

        for m in members:
            assigned[m] = len(groups)
        groups.append(MatchGroup(
            members, row["block_id"], float(row["score"]),
            abs(gap) <= BALANCE_TOL, row["mechanism"]))

    return groups


# ── Full predict pipeline ──────────────────────────────────────────────────
def predict(df: pd.DataFrame, calib: Calibration):
    """Run the full V1 matching pipeline. Returns (groups, scored_pairs).

    Chains candidate generation, scoring and group resolution — layers 2 to 5 of
    the architecture described in the module docstring.

    Parameters
    ----------
    df : pandas.DataFrame
        Frame that has **already** been through `extract_signals`. This function
        does not call it, because constructing the `TemplateClassifier` is
        expensive and belongs outside any per-batch loop.
    calib : Calibration
        Frozen weights, normally from `load_calibration`.

    Returns
    -------
    tuple[list[MatchGroup], pandas.DataFrame]
        The resolved groups, and the scored pairs that produced them. The pair
        frame is returned alongside so callers can audit near-misses and rows
        that scored but lost their members to a higher-scoring group.

    Raises
    ------
    KeyError
        If ``df`` is missing the ``_``-prefixed columns, i.e. `extract_signals`
        was not run first.
    """
    cand   = generate_candidates(df)
    scored = score_pairs(df, cand, calib)
    return resolve_groups(df, scored), scored
