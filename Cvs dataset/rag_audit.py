# %% [markdown]
# # RAG data audit (run before ingesting into Supabase)
# Procedural style: plain functions, lists and dicts, no classes.
# Put this file next to your JSON files (or change DATA_DIR) and run the cells top to bottom.
# Every problem is appended to the `issues` list and summarised in the last cell.

# %% 1. Config
import json, re, os, glob, hashlib
from collections import Counter, defaultdict
import numpy as np

DATA_DIR = "."

# Real, public knowledge base (your file)
KB_FILE = "olivesoft_knowledge_base.jsonl"

# Teammate files that would be embedded (adapt after reading the audit of step 4)
CORPUS_FILES = [
    "cvs_clean.json",
    "projects_clean.json",
    "tech_stacks.json",
    "client_portfolio.json",
    "olivesoft_projects.json",
]
# Files that contain invented data
SYNTHETIC_FILES = ["cvs_clean.json", "projects_clean.json", "client_portfolio.json", "fake_cvs.json", "fake_projects.json", "fake_tools.json"]
# Older / overlapping versions, loaded only to compare against the clean ones
LEGACY_FILES = ["fake_cvs.json", "fake_projects.json", "fake_tools.json", "olivesoft_projects.json"]
# Evaluation files
GT_FILES = ["ground_truth.json", "Tender_matches.json", "Tender_matches_cvs.json", "Tender_matches_projects.json"]

ID_KEYS = ["id", "cv_id", "project_id", "tool_id", "client_id", "uid"]
# Metadata fields that are not part of the embedded text (URLs contain French slugs, etc.)
NON_TEXT_KEYS = ID_KEYS + ["source_url", "lang", "category", "synthetic"]
MIN_TOKENS = 30
MAX_TOKENS = 500
NEAR_DUP_THRESHOLD = 0.90

KNOWN_TOOLS = [
    "Talend", "SSIS", "MuleSoft", "Boomi", "Workato", "n8n", "Make", "Power Automate",
    "Power BI", "Tableau", "Qlik", "Looker", "BigQuery", "Snowflake", "Databricks", "Kafka",
    "Dataform", "Azure", "GCP", "Google Cloud", "Salesforce", "LangGraph", "FAISS", "CoAtNet",
    "Vertex AI", "Sage X3", "Cegid", "SuccessFactors", "Datadog", "Python", "SQL",
]
KNOWN_CLIENTS = [
    "BNP Paribas", "Bouygues", "BVLGARI", "CELINE", "COFIROUTE", "GIVENCHY", "BPCE", "CISION",
    "Courreges", "Intersport", "Jacquemus", "Kenzo", "Lefebvre", "Lemaire", "Loewe", "Marc Jacobs",
    "MBPS", "Rimowa", "RTE", "Timbu", "TotalEnergies", "SATISFY", "SOEUR", "BEACHCOMBER", "Electre", "Etam",
]

issues = []  # list of (level, source, message)


def flag(level, source, message):
    issues.append((level, source, message))


# %% 2. Loading helpers
def find_file(name):
    """Case-insensitive lookup so Tender_matches.json and tender_matches.json both work."""
    for p in glob.glob(os.path.join(DATA_DIR, "*")):
        if os.path.basename(p).lower() == name.lower():
            return p
    return None


def load_any(path):
    with open(path, encoding="utf-8") as f:
        raw = f.read().strip()
    if path.lower().endswith(".jsonl"):
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    data = json.loads(raw)
    if isinstance(data, list):
        return [r if isinstance(r, dict) else {"value": r} for r in data]
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        if lists:
            return max(lists, key=len)
        out = []
        for k, v in data.items():
            out.append(dict(v, _key=k) if isinstance(v, dict) else {"_key": k, "value": v})
        return out
    return [{"value": data}]


def get_id(rec):
    for k in ID_KEYS:
        if k in rec and rec[k] not in (None, ""):
            return str(rec[k])
    return None


def flatten(v):
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return ", ".join(flatten(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {flatten(x)}" for k, x in v.items())
    return ""


def record_to_text(rec):
    return flatten({k: v for k, v in rec.items() if k not in NON_TEXT_KEYS})


def n_tokens(text):
    return int(len(text.split()) * 1.3)


def normalize(text):
    return re.sub(r"\W+", " ", text.lower()).strip()


# %% 3. Load everything
corpus = {}  # name -> list of records
kb_path = find_file(KB_FILE)
if kb_path:
    corpus[KB_FILE] = load_any(kb_path)
else:
    flag("ERROR", KB_FILE, "file not found")

for name in CORPUS_FILES + LEGACY_FILES:
    p = find_file(name)
    if p is None:
        # a missing file that should be ingested blocks the audit, a missing legacy file does not
        flag("ERROR" if name in CORPUS_FILES else "WARN", name, "file not found in DATA_DIR")
        continue
    try:
        corpus[name] = load_any(p)
    except Exception as e:
        flag("ERROR", name, f"cannot parse: {e}")

for name, recs in corpus.items():
    print(f"{name:35s} {len(recs):5d} records")

# %% 4. Schema discovery (read this output, then adapt the config above)
for name, recs in corpus.items():
    key_counts = Counter(k for r in recs for k in r.keys())
    print(f"\n== {name} ({len(recs)} records)")
    for k, c in key_counts.most_common():
        print(f"   {k:25s} {c}/{len(recs)}")
    if recs:
        print("   sample:", json.dumps(recs[0], ensure_ascii=False)[:300])

# %% 5. Field coverage, empty values, ids
def check_structure(name, recs):
    # group by doc_type when a file mixes several kinds of records (e.g. tech_stacks.json)
    groups = defaultdict(list)
    for r in recs:
        groups[str(r.get("doc_type", "all"))].append(r)
    for gname, grecs in groups.items():
        label = name if gname == "all" else f"{name}[{gname}]"
        key_counts = Counter(k for r in grecs for k in r.keys())
        for k, c in key_counts.items():
            if c < len(grecs):
                flag("WARN", label, f"field '{k}' present in only {c}/{len(grecs)} records")
    # one line per field instead of one line per record
    empty_ids = defaultdict(list)  # field -> ids of records where it is empty
    no_id = 0
    for i, r in enumerate(recs):
        rid = get_id(r) or f"#{i}"
        if get_id(r) is None:
            no_id += 1
        for k, v in r.items():
            if v in (None, "", [], {}):
                empty_ids[k].append(rid)
        if not record_to_text(r).strip():
            flag("ERROR", name, f"{rid}: no text content")
    if no_id:
        flag("WARN", name, f"{no_id} records have no id field (check ID_KEYS)")
    for k, ids in empty_ids.items():
        flag("WARN", name, f"field '{k}' empty in {len(ids)}/{len(recs)} records, e.g. {ids[:5]}")


for name, recs in corpus.items():
    check_structure(name, recs)

# ids unique within each file and across the corpus files that will be ingested
seen_ids = defaultdict(list)  # id -> [file names]
for name in [KB_FILE] + CORPUS_FILES:
    for r in corpus.get(name, []):
        rid = get_id(r)
        if rid is not None:
            seen_ids[rid].append(name)
for rid, files in seen_ids.items():
    if len(files) > 1:
        flag("ERROR", ",".join(sorted(set(files))), f"id '{rid}' appears {len(files)} times")

# %% 6. Text length and language
FR_WORDS = set("le la les des du de un une et en pour avec dans sur par au aux est sont qui que ce cette ses nos notre vos".split())
EN_WORDS = set("the and of to in for with on by is are that this which our their from as at an".split())


def guess_lang(text):
    words = re.findall(r"[a-zA-Zéèêàùçîô']+", text.lower())
    if not words:
        return "unknown"
    fr = sum(w in FR_WORDS for w in words) / len(words)
    en = sum(w in EN_WORDS for w in words) / len(words)
    return "fr" if fr > en else "en"


lengths_by_file = {}
lang_by_file = {}
for name in [KB_FILE] + CORPUS_FILES:
    recs = corpus.get(name, [])
    toks = [n_tokens(record_to_text(r)) for r in recs]
    lengths_by_file[name] = toks
    lang_by_file[name] = Counter(guess_lang(record_to_text(r)) for r in recs)
    for r, t in zip(recs, toks):
        rid = get_id(r) or "?"
        if t < MIN_TOKENS:
            flag("WARN", name, f"{rid}: only ~{t} tokens (too thin to retrieve well)")
        if t > MAX_TOKENS:
            flag("WARN", name, f"{rid}: ~{t} tokens (consider splitting)")
    if toks:
        print(f"{name:30s} tokens min/median/max = {min(toks)}/{int(np.median(toks))}/{max(toks)}   langs={dict(lang_by_file[name])}")

all_langs = set()
for c in lang_by_file.values():
    all_langs.update(c.keys())
if len(all_langs - {"unknown"}) > 1:
    flag("WARN", "corpus", f"mixed languages {sorted(all_langs)}: use a multilingual embedding model or translate")

# %% 7. Synthetic vs real, and PII
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+|00)\d[\d\s().-]{8,}\d")
LINKEDIN_RE = re.compile(r"linkedin\.com/in/[\w-]+", re.I)

for name in CORPUS_FILES:
    is_synth = name.lower() in [s.lower() for s in SYNTHETIC_FILES]
    for r in corpus.get(name, []):
        rid = get_id(r) or "?"
        text = flatten(r)
        if is_synth:
            if EMAIL_RE.search(text) or PHONE_RE.search(text) or LINKEDIN_RE.search(text):
                flag("ERROR", name, f"{rid}: looks like real contact data in a synthetic file")
            if "synthetic" not in r:
                flag("INFO", name, f"{rid}: no 'synthetic' field, add synthetic=true before ingestion")
                break  # one message per file is enough
        else:
            if "synthetic" in r and r["synthetic"]:
                flag("WARN", name, f"{rid}: marked synthetic but file is not in SYNTHETIC_FILES")

# real KB must not be mixed with invented projects
kb_titles = " | ".join(r.get("title", "") for r in corpus.get(KB_FILE, []))
print("Real KB records:", len(corpus.get(KB_FILE, [])))

# %% 8. Consistency of synthetic data with the real KB
def mentions(text, vocab):
    t = text.lower()
    return [v for v in vocab if v.lower() in t]


for name in CORPUS_FILES:
    if name.lower() not in [s.lower() for s in SYNTHETIC_FILES]:
        continue
    no_tool = 0
    unknown_clients = Counter()
    for r in corpus.get(name, []):
        text = flatten(r)
        if not mentions(text, KNOWN_TOOLS):
            no_tool += 1
        for k in ("client", "clients", "company", "employer"):
            v = r.get(k)
            vals = v if isinstance(v, list) else [v] if v else []
            for c in vals:
                c = flatten(c)
                if c and not mentions(c, KNOWN_CLIENTS):
                    unknown_clients[c] += 1
    if no_tool:
        flag("INFO", name, f"{no_tool} records mention none of the known OliveSoft tools")
    if unknown_clients:
        top = ", ".join(f"{c} ({n})" for c, n in unknown_clients.most_common(8))
        flag("INFO", name, f"clients not in the real client list (fine if invented on purpose, but label them): {top}")

# %% 9. Duplicates: exact and near-duplicates
def find_duplicates(records, source):
    texts = [normalize(record_to_text(r)) for r in records]
    ids = [get_id(r) or f"#{i}" for i, r in enumerate(records)]
    by_hash = defaultdict(list)
    for i, t in enumerate(texts):
        by_hash[hashlib.md5(t.encode()).hexdigest()].append(ids[i])
    for h, group in by_hash.items():
        if len(group) > 1:
            flag("ERROR", source, f"exact duplicate text: {group}")
    if len(texts) < 2:
        return
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        print("scikit-learn missing, skipping near-duplicate check (pip install scikit-learn)")
        return
    X = TfidfVectorizer(ngram_range=(1, 2), min_df=1).fit_transform(texts)
    sim = (X @ X.T).toarray()
    np.fill_diagonal(sim, 0)
    rows, cols = np.where(np.triu(sim) > NEAR_DUP_THRESHOLD)
    for i, j in zip(rows, cols):
        flag("WARN", source, f"near-duplicate ({sim[i, j]:.2f}): {ids[i]} ~ {ids[j]}")


for name in [KB_FILE] + CORPUS_FILES:
    find_duplicates(corpus.get(name, []), name)

# %% 10. Overlap between legacy and clean files (which one is the source of truth?)
def id_set(recs):
    return set(get_id(r) for r in recs if get_id(r))


pairs = [
    ("fake_cvs.json", "cvs_clean.json"),
    ("fake_projects.json", "projects_clean.json"),
    ("olivesoft_projects.json", "projects_clean.json"),
    ("fake_tools.json", "tech_stacks.json"),
]
for old, new in pairs:
    if old in corpus and new in corpus:
        a, b = id_set(corpus[old]), id_set(corpus[new])
        print(f"{old:28s} vs {new:22s} old={len(corpus[old])} new={len(corpus[new])} shared_ids={len(a & b)}")
        if a & b:
            flag("INFO", f"{old}/{new}", f"{len(a & b)} shared ids: only ingest one of the two versions")

# %% 11. Ground truth: do the referenced ids exist?
known_ids = set(seen_ids.keys())
gt = {}
for name in GT_FILES:
    p = find_file(name)
    if p is None:
        flag("WARN", name, "ground truth file not found")
        continue
    gt[name] = load_any(p)


def collect_id_values(obj, out):
    """Recursively collect values stored under keys that contain 'id'."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "id" in k.lower():
                if isinstance(v, (str, int)):
                    out.append(str(v))
                elif isinstance(v, list):
                    out.extend(str(x) for x in v if isinstance(x, (str, int)))
            collect_id_values(v, out)
    elif isinstance(obj, list):
        for x in obj:
            collect_id_values(x, out)


for name, recs in gt.items():
    refs = []
    collect_id_values(recs, refs)
    missing = sorted(set(r for r in refs if r not in known_ids))
    print(f"{name:30s} {len(recs)} records, {len(set(refs))} distinct id refs, {len(missing)} not in corpus")
    if recs:
        print("   keys:", list(recs[0].keys()))
    if missing:
        flag("WARN", name, f"{len(missing)} referenced ids missing from the corpus, e.g. {missing[:8]}")

# %% 12. Retrieval baseline (TF-IDF, no embeddings needed)
# Set these two after reading the keys printed in step 11.
GT_FILE_FOR_EVAL = "ground_truth.json"
GT_QUERY_KEY = None      # e.g. "query" or "tender_text"
GT_RELEVANT_KEY = None   # e.g. "relevant_ids" or "expected"
K_VALUES = [1, 3, 5, 10]


def tfidf_hit_at_k(queries, relevant, doc_ids, doc_texts, ks):
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
    D = vec.fit_transform(doc_texts)
    Q = vec.transform(queries)
    sims = (Q @ D.T).toarray()
    hits = {k: 0 for k in ks}
    rr = []
    for qi in range(len(queries)):
        order = np.argsort(-sims[qi])
        ranked = [doc_ids[j] for j in order]
        rel = set(relevant[qi])
        first = next((rank for rank, d in enumerate(ranked, 1) if d in rel), None)
        rr.append(1.0 / first if first else 0.0)
        for k in ks:
            if any(d in rel for d in ranked[:k]):
                hits[k] += 1
    n = len(queries)
    return {f"hit@{k}": hits[k] / n for k in ks} | {"MRR": float(np.mean(rr))}


if GT_QUERY_KEY and GT_RELEVANT_KEY and GT_FILE_FOR_EVAL in gt:
    doc_ids, doc_texts = [], []
    for name in [KB_FILE] + CORPUS_FILES:
        for r in corpus.get(name, []):
            if get_id(r):
                doc_ids.append(get_id(r))
                doc_texts.append(record_to_text(r))
    queries, relevant = [], []
    for r in gt[GT_FILE_FOR_EVAL]:
        rel = r.get(GT_RELEVANT_KEY)
        if r.get(GT_QUERY_KEY) and rel:
            queries.append(flatten(r[GT_QUERY_KEY]))
            relevant.append([str(x) for x in (rel if isinstance(rel, list) else [rel])])
    print(len(queries), "evaluation queries")
    if queries:
        print(tfidf_hit_at_k(queries, relevant, doc_ids, doc_texts, K_VALUES))
else:
    print("Set GT_QUERY_KEY and GT_RELEVANT_KEY (see step 11 output) to run the retrieval baseline.")

# %% 13. Summary
order = {"ERROR": 0, "WARN": 1, "INFO": 2}
counts = Counter(level for level, _, _ in issues)
print("ERROR:", counts["ERROR"], "| WARN:", counts["WARN"], "| INFO:", counts["INFO"])
for level, source, message in sorted(issues, key=lambda x: (order[x[0]], x[1])):
    print(f"[{level:5s}] {source:30s} {message}")
print("\nReady to ingest" if counts["ERROR"] == 0 else "\nFix the ERRORs before ingesting")
def show(file, ids):
    for r in corpus[file]:
        if get_id(r) in ids:
            print(get_id(r), "|", record_to_text(r)[:400], "\n")

show("tech_stacks.json", ["TECH-080", "TECH-082"])
show("tech_stacks.json", ["TECH-015", "TECH-016"])
show("cvs_clean.json", ["CV-0039", "CV-0041"])
show("cvs_clean.json", ["CV-0054", "CV-0056"])

def same_content(file_a, key, file_b, ignore=("built_for_tender",)):
    b = {r[key]: r for r in load_any(find_file(file_b))}
    diff = []
    for r in load_any(find_file(file_a)):
        other = b.get(r[key])
        a_clean = {k: v for k, v in r.items() if k not in ignore}
        if other is None or a_clean != other:
            diff.append(r[key])
    return diff

print(same_content("Tender_matches_cvs.json", "cv_id", "cvs_clean.json"))
print(same_content("Tender_matches_projects.json", "project_id", "projects_clean.json"))