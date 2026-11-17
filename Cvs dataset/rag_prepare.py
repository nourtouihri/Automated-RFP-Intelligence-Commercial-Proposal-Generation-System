# %% [markdown]
# # RAG prepare: build clean, ready-to-ingest chunk files
# Reads the raw JSON files, builds ONE clean chunk per record in a single schema,
# checks the result and writes everything to OUT_DIR (default: rag_ready/).
# Your original files are never modified.
# Procedural style: plain functions, lists and dicts, no classes.
#
# Output chunk schema (same for every source):
#   id, doc_type, title, text (what you embed), lang, synthetic, source_file,
#   chunk_version, content_hash, metadata (filterable fields, empty values removed)

# %% 1. Config
import json, re, os, glob, hashlib, shutil, statistics
from collections import Counter, defaultdict

DATA_DIR = "."
OUT_DIR = "rag_ready"

KB_FILE = "olivesoft_knowledge_base.jsonl"
CV_FILE = "cvs_clean.json"
PROJECT_FILE = "projects_clean.json"
TECH_FILE = "tech_stacks.json"
CLIENT_FILE = "client_portfolio.json"
OLIVESOFT_PROJECTS_FILE = "olivesoft_projects.json"
TOOLS_FILE = "fake_tools.json"
INCLUDE_TOOLS = False  # set True if the 6 tools/accelerators should be searchable
GROUND_TRUTH_FILES = ["ground_truth.json"]  # validated, then copied unchanged to OUT_DIR/eval/

# Deliberately NOT embedded:
#  - fake_cvs.json, fake_projects.json: older versions, same ids with different content
#  - Tender_matches_cvs.json, Tender_matches_projects.json: subsets of the clean files
#  - Tender_matches.json: evaluation file, not a document

NEAR_DUP_THRESHOLD = 0.90   # near-duplicates are flagged for review, never deleted
MIN_TOKENS = 30
MAX_TOKENS = 500
CHUNK_VERSION = "v1"
ADD_EVIDENCE_NOTE = True    # adds one sentence to technologies that only exist in synthetic data

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+|00)\d[\d\s().-]{8,}\d")

issues = []  # (level, source, message)


def flag(level, source, message):
    issues.append((level, source, message))


# %% 2. Loading helpers
def find_file(name):
    for p in glob.glob(os.path.join(DATA_DIR, "*")):
        if os.path.basename(p).lower() == name.lower():
            return p
    return None


def load_any(path):
    with open(path, encoding="utf-8-sig") as f:
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


# %% 3. Text helpers
def clean_str(v):
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def is_empty(v):
    return v is None or v == "" or v == [] or v == {}


def flatten_values(v):
    """Flat list of non-empty strings from a string, a list, or nested dicts/lists."""
    if is_empty(v):
        return []
    if isinstance(v, dict):
        out = []
        for x in v.values():
            out.extend(flatten_values(x))
        return out
    if isinstance(v, list):
        out = []
        for x in v:
            out.extend(flatten_values(x))
        return out
    text = clean_str(v)
    return [text] if text else []


def join_list(v):
    return ", ".join(flatten_values(v))


def add_part(parts, label, value):
    text = join_list(value)
    if text:
        parts.append(as_sentence(f"{label}: {text}"))


def as_sentence(text):
    text = clean_str(text)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def n_tokens(text):
    return int(len(text.split()) * 1.3)


def normalize(text):
    return re.sub(r"\W+", " ", text.lower()).strip()


def string_list(v):
    return flatten_values(v)


def make_chunk(cid, doc_type, title, text, synthetic, source_file, metadata, lang="en"):
    cid = clean_str(cid)
    text = clean_str(text)
    if not cid:
        raise ValueError("record has no id")
    if not text:
        raise ValueError("record has no text")
    return {
        "id": cid,
        "doc_type": doc_type,
        "title": clean_str(title),
        "text": text,
        "lang": lang,
        "synthetic": bool(synthetic),
        "source_file": source_file,
        "chunk_version": CHUNK_VERSION,
        "content_hash": hashlib.md5(text.encode("utf-8")).hexdigest(),
        "metadata": {k: v for k, v in metadata.items() if not is_empty(v)},
    }


# %% 4. One builder per source (each returns one chunk)
def build_kb(r, fname):
    title = clean_str(r.get("title")).rstrip(".")
    body = clean_str(r.get("text"))
    text = f"{title}. {body}" if title and not body.startswith(title) else body
    category = clean_str(r.get("category")) or "kb"
    return make_chunk(r.get("id"), category, title, text, False, fname,
                      {"category": category, "source_url": r.get("source_url")},
                      lang=clean_str(r.get("lang")) or "en")


def describe_past_project(p):
    name = clean_str(p.get("project_name") or p.get("name") or p.get("project_id"))
    sector = clean_str(p.get("client_sector"))
    techs = flatten_values(p.get("tech_stack"))
    extras = []
    for k, v in p.items():
        if k in ("project_name", "name", "client_sector", "project_id") or is_empty(v):
            continue
        value = join_list(v)
        # skip a description that only restates the technologies already listed
        if k == "description" and techs and all(t.lower() in value.lower() for t in techs):
            continue
        extras.append(f"{k.replace('_', ' ')} {value}")
    out = name
    if sector:
        out += f" ({sector})"
    if extras:
        out += " - " + ", ".join(extras)
    return out.rstrip(" .")


def build_cv(r, fname):
    cid = clean_str(r.get("cv_id"))
    name = clean_str(r.get("name"))
    role = clean_str(r.get("role"))
    head = f"{cid} ({name}) - {role}" if name else f"{cid} - {role}"
    if not is_empty(r.get("years_experience")):
        head += f", {r.get('years_experience')} years of experience"
    parts = [head + "."]
    add_part(parts, "Skills", r.get("skills"))
    add_part(parts, "Certifications", r.get("certifications"))
    past = [p for p in (r.get("past_projects") or []) if isinstance(p, dict)]
    if past:
        parts.append("Past projects: " + "; ".join(describe_past_project(p) for p in past) + ".")
    metadata = {
        "role": role,
        "years_experience": r.get("years_experience"),
        "skills": string_list(r.get("skills")),
        "certifications": string_list(r.get("certifications")),
        "project_ids": [clean_str(p.get("project_id")) for p in past if p.get("project_id")],
    }
    return make_chunk(cid, "cv", f"{role} - {name}" if name else role, " ".join(parts),
                      r.get("synthetic", True), fname, metadata)


def build_project(r, fname):
    pid = clean_str(r.get("project_id"))
    name = clean_str(r.get("name"))
    desc = clean_str(r.get("description"))
    techs = string_list(r.get("tech_stack"))
    head = f"Project {pid}:"
    if desc and name and desc.lower().startswith(name.lower()):
        parts = [f"{head} {as_sentence(desc)}"]  # description already starts with the name
    else:
        parts = [f"{head} {as_sentence(name)}"]
        if desc:
            parts.append(as_sentence(desc))
    add_part(parts, "Sector", r.get("client_sector"))
    # skip the tech list when the description already names every technology
    if techs and not all(t.lower() in desc.lower() for t in techs):
        add_part(parts, "Tech stack", techs)
    add_part(parts, "Outcome", r.get("outcome"))
    metadata = {
        "client_sector": clean_str(r.get("client_sector")),
        "tech_stack": techs,
        "has_outcome": not is_empty(r.get("outcome")),
    }
    return make_chunk(pid, "project", name, " ".join(parts), r.get("synthetic", True), fname, metadata)


def build_tech(r, fname):
    dtype = clean_str(r.get("doc_type")) or "technology"
    title = clean_str(r.get("name") or r.get("domain"))
    text = clean_str(r.get("document_text"))
    if not text:
        parts = [as_sentence(title)]
        add_part(parts, "Category", r.get("category"))
        add_part(parts, "Related technologies", r.get("related_technologies"))
        add_part(parts, "Typical technologies", r.get("typical_technologies"))
        text = " ".join(parts)
        flag("WARN", fname, f"{r.get('id')}: no document_text, built a fallback text")
    synthetic_only = bool(r.get("synthetic_only", False))
    low = text.lower()
    if ADD_EVIDENCE_NOTE and dtype == "technology" and synthetic_only \
            and "synthetic" not in low and "simulated" not in low:
        text += (" Evidence: this technology appears only in synthetic (simulated) CV and project data,"
                 " not in documented real OliveSoft projects.")
    examples = [e for e in (r.get("example_real_projects") or []) if isinstance(e, dict)]
    metadata = {
        "name": clean_str(r.get("name")),
        "category": clean_str(r.get("category")),
        "domain": clean_str(r.get("domain")),
        "real_project_evidence": r.get("real_project_evidence"),
        "real_project_count": r.get("real_project_count"),
        "synthetic_project_count": r.get("synthetic_project_count"),
        "cv_count": r.get("cv_count"),
        "synthetic_only": synthetic_only if dtype == "technology" else None,
        "has_real_evidence": ((r.get("real_project_count") or 0) > 0) if dtype == "technology" else None,
        "related_technologies": string_list(r.get("related_technologies")),
        "typical_technologies": string_list(r.get("typical_technologies")),
        "variants_seen": string_list(r.get("variants_seen")),
        "project_ids": string_list(r.get("project_ids")),
        "example_real_project_ids": [clean_str(e.get("id")) for e in examples if e.get("id")],
        "mixed_sources": True,
    }
    return make_chunk(r.get("id"), dtype, title, text, synthetic_only, fname, metadata)


def build_client(r, fname):
    title = clean_str(r.get("name"))
    text = clean_str(r.get("document_text"))
    if not text:
        parts = [as_sentence(title)]
        add_part(parts, "Sector", r.get("sector"))
        add_part(parts, "Services delivered", r.get("services_delivered"))
        add_part(parts, "Technologies", r.get("technologies"))
        text = " ".join(parts)
        flag("WARN", fname, f"{r.get('client_id')}: no document_text, built a fallback text")
    metadata = {
        "name": title,
        "sector": clean_str(r.get("sector")),
        "sub_sector": clean_str(r.get("sub_sector")),
        "region": clean_str(r.get("region")),
        "relationship_since": r.get("relationship_since"),
        "status": clean_str(r.get("status")),
        "services_delivered": string_list(r.get("services_delivered")),
        "technologies": string_list(r.get("technologies")),
        "project_ids": string_list(r.get("project_ids")),
        "project_count": r.get("project_count"),
        "origin": clean_str(r.get("origin")),
    }
    return make_chunk(r.get("client_id"), "client", title, text, r.get("synthetic", False), fname, metadata)


def build_olivesoft_project(r, fname):
    name = clean_str(r.get("name"))
    relationship = clean_str(r.get("relationship")).replace("_", " ")
    edition = clean_str(r.get("edition"))
    parts = [f"OliveSoft project: {as_sentence(name)}"]
    if relationship or edition:
        parts.append(f"Type: {relationship}{', edition ' + edition if edition else ''}.")
    add_part(parts, "Domain", r.get("domain"))
    if clean_str(r.get("description")):
        parts.append(as_sentence(r.get("description")))
    add_part(parts, "Tech stack", r.get("tech_stack"))
    outcome = clean_str(r.get("outcome"))
    # a one or two word value such as "proposed" is a status, not a real outcome
    add_part(parts, "Status" if len(outcome.split()) <= 2 else "Outcome", outcome)
    add_part(parts, "Client", r.get("client"))
    add_part(parts, "Notes", r.get("notes"))
    metadata = {
        "relationship": clean_str(r.get("relationship")),
        "edition": edition,
        "domain": string_list(r.get("domain")),
        "tech_stack": string_list(r.get("tech_stack")),
        "client": clean_str(r.get("client")),
        "outcome": outcome,
        "confidence": r.get("confidence"),
        "sources": r.get("sources"),
    }
    return make_chunk(r.get("id"), "olivesoft_project", name, " ".join(parts), False, fname, metadata)


def build_tool(r, fname):
    name = clean_str(r.get("name"))
    parts = [f"Tool {clean_str(r.get('tool_id'))}: {as_sentence(name)}"]
    add_part(parts, "Category", r.get("category"))
    if clean_str(r.get("description")):
        parts.append(as_sentence(r.get("description")))
    add_part(parts, "Capabilities", r.get("capabilities"))
    add_part(parts, "Technologies", r.get("technologies"))
    add_part(parts, "Use cases", r.get("use_cases"))
    add_part(parts, "Certifications", r.get("certifications"))
    metadata = {
        "category": clean_str(r.get("category")),
        "technologies": string_list(r.get("technologies")),
    }
    return make_chunk(r.get("tool_id"), "tool", name, " ".join(parts), r.get("synthetic", True), fname, metadata)


# %% 5. Build all chunks
SOURCES = [
    (KB_FILE, build_kb),
    (CV_FILE, build_cv),
    (PROJECT_FILE, build_project),
    (TECH_FILE, build_tech),
    (CLIENT_FILE, build_client),
    (OLIVESOFT_PROJECTS_FILE, build_olivesoft_project),
]
if INCLUDE_TOOLS:
    SOURCES.append((TOOLS_FILE, build_tool))

chunks = []
records_in = {}
for fname, builder in SOURCES:
    path = find_file(fname)
    if path is None:
        flag("ERROR", fname, "file not found in DATA_DIR")
        continue
    records = load_any(path)
    records_in[fname] = len(records)
    for r in records:
        try:
            chunks.append(builder(r, fname))
        except Exception as e:
            rid = r.get("id") or r.get("cv_id") or r.get("project_id") or r.get("client_id") or r.get("tool_id")
            flag("ERROR", fname, f"record {rid}: cannot build chunk ({e})")

for fname, n in records_in.items():
    built = sum(1 for c in chunks if c["source_file"] == fname)
    print(f"{fname:32s} {n:5d} records -> {built:5d} chunks")

# %% 6. Clean-up and checks
# 6a. ids must be unique across everything that will be ingested
for cid, n in Counter(c["id"] for c in chunks).items():
    if n > 1:
        flag("ERROR", "chunks", f"id '{cid}' appears {n} times")

# 6b. drop exact duplicates (same type, same text)
seen_hash = {}
kept = []
for c in chunks:
    key = (c["doc_type"], hashlib.md5(normalize(c["text"]).encode("utf-8")).hexdigest())
    if key in seen_hash:
        flag("INFO", c["source_file"], f"{c['id']}: exact duplicate of {seen_hash[key]}, dropped")
        continue
    seen_hash[key] = c["id"]
    kept.append(c)
chunks = kept

# 6c. size and personal-data checks
for c in chunks:
    t = n_tokens(c["text"])
    if t < MIN_TOKENS:
        flag("WARN", c["source_file"], f"{c['id']}: only ~{t} tokens")
    if t > MAX_TOKENS:
        flag("WARN", c["source_file"], f"{c['id']}: ~{t} tokens, consider splitting")
    if c["synthetic"] and (EMAIL_RE.search(c["text"]) or PHONE_RE.search(c["text"])):
        flag("ERROR", c["source_file"], f"{c['id']}: looks like real contact data in a synthetic chunk")

# 6d. near-duplicates inside the same doc_type: flagged for review, never deleted
review = {"near_duplicates": [], "dangling_references": [], "ground_truth_missing_ids": []}
by_type = defaultdict(list)
for c in chunks:
    by_type[c["doc_type"]].append(c)

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    have_sklearn = True
except ImportError:
    have_sklearn = False
    print("scikit-learn missing, skipping near-duplicate check (pip install scikit-learn)")

if have_sklearn:
    for dtype, group in by_type.items():
        if len(group) < 2:
            continue
        X = TfidfVectorizer(ngram_range=(1, 2)).fit_transform([normalize(c["text"]) for c in group])
        sim = (X @ X.T).toarray()
        n_pairs = 0
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if sim[i, j] > NEAR_DUP_THRESHOLD:
                    a, b = group[i], group[j]
                    review["near_duplicates"].append(
                        {"doc_type": dtype, "ids": [a["id"], b["id"]], "similarity": round(float(sim[i, j]), 3)})
                    a["metadata"].setdefault("near_duplicate_of", []).append(b["id"])
                    b["metadata"].setdefault("near_duplicate_of", []).append(a["id"])
                    n_pairs += 1
        if n_pairs:
            flag("WARN", dtype, f"{n_pairs} near-duplicate pairs, see review_needed.json")

# 6e. references between chunks must point to chunks that exist
all_ids = set(c["id"] for c in chunks)
for c in chunks:
    for key in ("project_ids", "example_real_project_ids"):
        for ref in c["metadata"].get(key, []):
            if ref not in all_ids:
                review["dangling_references"].append({"chunk": c["id"], "field": key, "missing": ref})
if review["dangling_references"]:
    missing = sorted(set(d["missing"] for d in review["dangling_references"]))
    flag("WARN", "references", f"{len(review['dangling_references'])} references to ids that are not chunks, e.g. {missing[:6]}")


# 6f. ground truth: every referenced id must exist among the chunks
def collect_id_values(obj, out):
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


gt_paths = []
for gname in GROUND_TRUTH_FILES:
    gpath = find_file(gname)
    if gpath is None:
        flag("WARN", gname, "ground truth file not found")
        continue
    gt_paths.append(gpath)
    refs = []
    collect_id_values(load_any(gpath), refs)
    missing = sorted(set(r for r in refs if r not in all_ids))
    if missing:
        review["ground_truth_missing_ids"].append({"file": gname, "missing": missing})
        flag("ERROR", gname, f"{len(missing)} ids not found among the chunks, e.g. {missing[:6]}")

# %% 7. Write the output files
def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


os.makedirs(os.path.join(OUT_DIR, "by_type"), exist_ok=True)
os.makedirs(os.path.join(OUT_DIR, "eval"), exist_ok=True)

with open(os.path.join(OUT_DIR, "all_chunks.jsonl"), "w", encoding="utf-8") as f:
    for c in chunks:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")

for dtype, group in by_type.items():
    write_json(os.path.join(OUT_DIR, "by_type", f"{dtype}.json"), group)

for gpath in gt_paths:
    shutil.copy2(gpath, os.path.join(OUT_DIR, "eval", os.path.basename(gpath)))

tokens = [n_tokens(c["text"]) for c in chunks]
report = {
    "chunk_version": CHUNK_VERSION,
    "total_chunks": len(chunks),
    "chunks_per_doc_type": dict(Counter(c["doc_type"] for c in chunks)),
    "synthetic_chunks": sum(1 for c in chunks if c["synthetic"]),
    "real_chunks": sum(1 for c in chunks if not c["synthetic"]),
    "tokens_min_median_max": [min(tokens), int(statistics.median(tokens)), max(tokens)] if tokens else [],
    "issues": [{"level": a, "source": b, "message": m} for a, b, m in issues],
}
write_json(os.path.join(OUT_DIR, "report.json"), report)
write_json(os.path.join(OUT_DIR, "review_needed.json"), review)

# %% 8. Summary
order = {"ERROR": 0, "WARN": 1, "INFO": 2}
counts = Counter(level for level, _, _ in issues)
print(f"\nWrote {len(chunks)} chunks to {OUT_DIR}/  (real: {report['real_chunks']}, synthetic: {report['synthetic_chunks']})")
print("per doc_type:", report["chunks_per_doc_type"])
if tokens:
    print("tokens min/median/max:", report["tokens_min_median_max"])
print("ERROR:", counts["ERROR"], "| WARN:", counts["WARN"], "| INFO:", counts["INFO"])
for level, source, message in sorted(issues, key=lambda x: (order[x[0]], x[1])):
    print(f"[{level:5s}] {source:30s} {message}")
print("\nChunk files are ready to embed" if counts["ERROR"] == 0 else "\nFix the ERRORs, then run again")
print(f"Open {OUT_DIR}/review_needed.json for the items that need a human decision.")
