"""
Build client_portfolio.json and tech_stacks.json from the existing data files,
so the numbers in these two files always match your CVs and projects.

Inputs (same folder):
    olivesoft_projects.json        real PFE project references   (required)
    fake_cvs.json                  first fake CVs                (required)
    fake_projects.json             first fake projects           (optional)
    tender_matches_cvs.json        CVs made for the tenders      (required)
    tender_matches_projects.json   projects made for the tenders (required)

Outputs:
    client_portfolio.json   one record per client (synthetic, except clients
                            that are named in the real PFE projects, e.g. KWORE)
    tech_stacks.json        one record per technology + one per domain stack

Usage:
    python generate_portfolio_and_stacks.py
"""
import argparse
import collections
import json
import os
import random

rng = random.Random(7)

# Different spellings of the same technology -> one name
ALIASES = {
    "REST API": "REST APIs",
    "Talend Open Studio": "Talend",
    "Google Cloud": "GCP",
    "HuggingFace Transformers": "HuggingFace",
    "Airflow": "Apache Airflow",
    "Salesforce Sales Cloud": "Salesforce",
    "Salesforce Core": "Salesforce",
    "Salesforce Data Cloud": "Salesforce",
    "Salesforce Service Cloud": "Salesforce",
    "GPT": "OpenAI",
}

CATEGORY_GROUPS = {
    "Data integration and ETL": ["Talend", "Apache Airflow", "SSIS", "Kafka", "dbt", "Apache Camel", "ESB", "TMC", "ETL"],
    "API and integration": ["MuleSoft", "DataWeave", "REST APIs", "API Management", "Microservices", "LinkedIn API", "Meta API", "BoondManager API"],
    "CRM and business applications": ["Salesforce", "Apex", "Lightning", "Einstein Agentforce", "HubSpot", "Odoo Community", "Boond", "ServiceNow", "SAP SuccessFactors"],
    "BI and reporting": ["Power BI", "DAX", "DAX Studio", "Tabular Editor", "Google Analytics", "Google Search Console", "BI"],
    "Cloud platforms": ["Azure", "GCP", "AWS", "Cloud Run", "Pub/Sub", "Key Vault", "Azure ML"],
    "Data platforms and databases": ["BigQuery", "Snowflake", "Databricks", "SQL", "Azure SQL", "PostgreSQL", "SQL Server", "MongoDB", "Redis", "Spark", "Elasticsearch"],
    "Vector databases": ["Qdrant", "ChromaDB", "Pinecone"],
    "DevOps and observability": ["Azure DevOps", "Terraform", "Docker", "Kubernetes", "Helm", "Git", "GitHub Actions", "CI/CD", "Grafana", "Prometheus", "Datadog", "Keycloak", "YAML Pipelines", "Unit testing"],
    "AI and machine learning": ["Python", "R", "PyTorch", "TensorFlow", "Scikit-learn", "HuggingFace", "Diffusers", "MLOps", "RAG", "LangChain", "LlamaIndex",
                                "OpenAI", "Claude", "Gemini", "Mistral", "Ollama", "Rasa", "Dialogflow", "LLM", "AI Chain", "OpenCV", "ONNX",
                                "Computer Vision", "NLP", "Edge AI", "Time-Series Forecasting", "Prompt Evaluation"],
    "Languages and frameworks": ["Java", "JavaScript", "TypeScript", "React", "Next.js", "Angular", "FastAPI", "Django", "Spring Boot", "Node.js",
                                 "Flutter", "Swift", "Kotlin", "GraphQL"],
    "Web and design": ["Drupal", "HTML", "CSS", "XML", "Figma", "Tailwind CSS"],
    "Marketing and sales tools": ["LinkedIn", "Clay", "Apollo", "Brevo", "Mailchimp", "ValueOrbit"],
    "Process, automation and governance": ["BPMN", "Power Automate", "n8n", "Agile", "Scrum", "Product Management", "ISO 27001", "ISMS", "GED", "Jira", "Confluence"],
    "Data and integration techniques": ["Master Data Management", "Data Quality", "Identity Resolution", "Data Lineage", "Data Migration", "Data Modelling",
                                        "Row-Level Security", "Offline Sync", "Data Residency", "Audit Logging", "Telematics", "CRM Analytics"],
}
CATEGORY = {t: cat for cat, techs in CATEGORY_GROUPS.items() for t in techs}

SECTOR_MAP = {"textile manufacturing": "manufacturing"}

# name, sector, sub-sector, region  (all invented, except where noted in the output)
CLIENTS = [
    ("Lumera Energy", "energy", "electricity and gas utility", "Tunisia (simulated)"),
    ("Corvia Manufacturing", "manufacturing", "industrial equipment manufacturing", "France (simulated)"),
    ("Tessara Textiles", "manufacturing", "textile and garment production", "Tunisia (simulated)"),
    ("Orvane Bank", "banking", "retail and corporate banking", "Tunisia (simulated)"),
    ("Marlowe Freight", "logistics", "road freight and warehousing", "Europe (simulated)"),
    ("Nautica Port Services", "logistics", "port and supply-chain services", "Tunisia (simulated)"),
    ("Haldane Properties", "real estate", "commercial property management", "Gulf region (simulated)"),
    ("Dunmere Telecom", "telecom", "mobile and fixed telecom operator", "Tunisia (simulated)"),
    ("Solenne Retail", "retail", "multi-brand fashion and lifestyle retail", "France (simulated)"),
    ("Avenir Distribution", "retail", "supermarket and convenience retail", "Tunisia (simulated)"),
    ("Tamarin Insurance", "insurance", "general insurance", "Tunisia (simulated)"),
    ("Brightwell Health Network", "healthcare", "private clinic network", "Tunisia (simulated)"),
    ("Alvara Public Services Agency", "public administration", "national citizen services agency", "Europe (simulated)"),
    ("Civica Records Authority", "public administration", "civil registry and records", "Tunisia (simulated)"),
    ("Brightmoor Foods", "consumer goods", "packaged food manufacturer", "Europe (simulated)"),
]

VARIANTS = collections.defaultdict(set)


def norm(tech):
    tech = tech.strip()
    name = ALIASES.get(tech, tech)
    if name != tech:
        VARIANTS[name].add(tech)
    return name


def norm_list(items):
    return list(dict.fromkeys(norm(t) for t in items))


def load(path, required=True):
    if not os.path.exists(path):
        if required:
            raise SystemExit(f"Missing required file: {path}")
        print(f"(optional file not found, skipped: {path})")
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def evidence_level(n):
    return "strong" if n >= 5 else "moderate" if n >= 2 else "limited" if n == 1 else "none"


def main():
    ap = argparse.ArgumentParser(description="Build client_portfolio.json and tech_stacks.json")
    ap.add_argument("--real", default="olivesoft_projects.json")
    ap.add_argument("--cvs", default="fake_cvs.json")
    ap.add_argument("--fake-projects", default="fake_projects.json")
    ap.add_argument("--tender-cvs", default="tender_matches_cvs.json")
    ap.add_argument("--tender-projects", default="tender_matches_projects.json")
    ap.add_argument("--clients-out", default="client_portfolio.json")
    ap.add_argument("--stacks-out", default="tech_stacks.json")
    args = ap.parse_args()

    # ---------- load everything with normalised technology names ----------
    real = []
    for p in load(args.real):
        real.append({
            "id": p["id"], "name": p["name"], "domain": p.get("domain", []),
            "client": p.get("client"), "tech": norm_list(p["tech_stack"]["technologies"]),
        })

    synthetic = []
    for p in load(args.fake_projects, required=False):
        synthetic.append({"id": p["project_id"], "name": p.get("summary") or p.get("name"),
                          "sector": p["client_sector"], "tech": norm_list(p["tech_stack"])})
    for p in load(args.tender_projects):
        synthetic.append({"id": p["project_id"], "name": p["name"],
                          "sector": p["client_sector"], "tech": norm_list(p["tech_stack"])})

    cvs = [{"id": c["cv_id"], "skills": norm_list(c["skills"])}
           for c in load(args.cvs) + load(args.tender_cvs)]

    # ---------- count technologies ----------
    real_by = collections.defaultdict(list)
    syn_by = collections.defaultdict(set)
    cv_by = collections.defaultdict(set)
    co_real = collections.defaultdict(collections.Counter)
    co_syn = collections.defaultdict(collections.Counter)

    for p in real:
        for a in p["tech"]:
            real_by[a].append(p)
            for b in p["tech"]:
                if a != b:
                    co_real[a][b] += 1
    for p in synthetic:
        for a in p["tech"]:
            syn_by[a].add(p["id"])
            for b in p["tech"]:
                if a != b:
                    co_syn[a][b] += 1
    for c in cvs:
        for a in c["skills"]:
            cv_by[a].add(c["id"])

    def related(tech):
        ordered = [t for t, _ in co_real[tech].most_common()]
        ordered += [t for t, _ in co_syn[tech].most_common() if t not in ordered]
        return ordered[:5]

    all_techs = set(real_by) | set(syn_by) | set(cv_by)
    ordered_techs = sorted(all_techs, key=lambda t: (-len(real_by[t]), -len(cv_by[t]), t))

    stacks = []
    for i, t in enumerate(ordered_techs, 1):
        rp, sn, cn = real_by[t], len(syn_by[t]), len(cv_by[t])
        cat = CATEGORY.get(t, "other")
        rel = related(t)
        parts = [f"{t} is a technology in the category '{cat}'."]
        if rp:
            ex = "; ".join(p["name"] for p in rp[:3])
            parts.append(f"It appears in {len(rp)} of Olivesoft's real PFE project references (for example: {ex}).")
        else:
            parts.append("It does not appear in Olivesoft's real PFE project references; it only appears in synthetic CVs and projects.")
        if sn:
            parts.append(f"It is used in {sn} synthetic past projects.")
        if cn:
            parts.append(f"{cn} CVs in the CV bank list it as a skill.")
        if rel:
            parts.append("It is often used together with " + ", ".join(rel) + ".")
        stacks.append({
            "id": f"TECH-{i:03d}",
            "doc_type": "technology",
            "name": t,
            "category": cat,
            "variants_seen": sorted(VARIANTS.get(t, [])),
            "real_project_count": len(rp),
            "synthetic_project_count": sn,
            "cv_count": cn,
            "real_project_evidence": evidence_level(len(rp)),
            "synthetic_only": len(rp) == 0,
            "example_real_projects": [{"id": p["id"], "name": p["name"]} for p in rp[:3]],
            "related_technologies": rel,
            "document_text": " ".join(parts),
        })

    # ---------- stack per domain (from real projects) ----------
    by_domain = collections.defaultdict(list)
    for p in real:
        for d in p["domain"]:
            by_domain[d].append(p)
    n = 0
    for d, plist in sorted(by_domain.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(plist) < 2:
            continue
        n += 1
        top = collections.Counter(t for p in plist for t in p["tech"]).most_common(8)
        text = (f"In Olivesoft's real PFE project references, {d} projects typically use: "
                + ", ".join(f"{t} ({c} projects)" for t, c in top)
                + ". Projects: " + "; ".join(p["name"] for p in plist) + ".")
        stacks.append({
            "id": f"STACK-{n:03d}",
            "doc_type": "stack_by_domain",
            "domain": d,
            "project_count": len(plist),
            "typical_technologies": [{"name": t, "projects": c} for t, c in top],
            "project_ids": [p["id"] for p in plist],
            "document_text": text,
        })

    # ---------- client portfolio ----------
    clients = list(CLIENTS)
    by_sector = collections.defaultdict(list)
    for p in sorted(synthetic, key=lambda x: x["id"]):
        by_sector[SECTOR_MAP.get(p["sector"], p["sector"])].append(p)
    for sector in by_sector:
        if not any(c[1] == sector for c in clients):
            clients.append((f"{sector.title()} Partner Co", sector, sector, "Europe (simulated)"))

    assigned = collections.defaultdict(list)
    for sector, plist in by_sector.items():
        mine = [c for c in clients if c[1] == sector]
        for i, p in enumerate(plist):
            assigned[mine[i % len(mine)][0]].append(p)

    portfolio = []
    for name, sector, sub, region in clients:
        projs = assigned.get(name, [])
        if not projs:
            continue
        counts = collections.Counter(t for p in projs for t in p["tech"])
        top_tech = [t for t, _ in counts.most_common(10)]
        since = rng.randint(2014, 2023)
        status = rng.choice(["active", "active", "active", "past"])
        names = [p["name"] for p in projs]
        art = "an" if sub[0].lower() in "aeiou" else "a"
        text = (f"{name} is {art} {sub} client in the {sector} sector. Region: {region}. "
                f"Client of Olivesoft since {since}; relationship status: {status}. "
                f"Olivesoft delivered {len(projs)} project(s): {'; '.join(names)}. "
                f"Main technologies: {', '.join(top_tech)}.")
        portfolio.append({
            "name": name, "sector": sector, "sub_sector": sub, "region": region,
            "relationship_since": since, "status": status,
            "services_delivered": names, "technologies": top_tech,
            "project_ids": [p["id"] for p in projs], "project_count": len(projs),
            "document_text": text, "origin": "synthetic", "synthetic": True,
        })

    # external clients that are named in the real PFE projects (e.g. KWORE)
    ext = collections.defaultdict(list)
    for p in real:
        c = p["client"]
        if c and "olivesoft" not in c.lower():
            ext[c].append(p)
    for cname, plist in ext.items():
        sector = " and ".join(plist[0]["domain"]) or "not specified"
        counts = collections.Counter(t for p in plist for t in p["tech"])
        top_tech = [t for t, _ in counts.most_common(10)]
        names = [p["name"] for p in plist]
        text = (f"{cname} is a client named in Olivesoft's real PFE project reference(s): {'; '.join(names)}. "
                f"Sector: {sector}. Main technologies: {', '.join(top_tech)}. "
                f"Contract details are not available; this is a PFE internship project, not confirmed delivered work.")
        portfolio.append({
            "name": cname, "sector": sector, "sub_sector": "client named in a PFE internship project",
            "region": None, "relationship_since": None, "status": "named_in_pfe_project",
            "services_delivered": names, "technologies": top_tech,
            "project_ids": [p["id"] for p in plist], "project_count": len(plist),
            "document_text": text, "origin": "real_pfe_reference", "synthetic": False,
        })

    for i, c in enumerate(portfolio, 1):
        c["client_id"] = f"CLIENT-{i:03d}"
    portfolio = [{"client_id": c.pop("client_id"), **c} for c in portfolio]

    with open(args.clients_out, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)
    with open(args.stacks_out, "w", encoding="utf-8") as f:
        json.dump(stacks, f, indent=2, ensure_ascii=False)

    n_tech = sum(1 for s in stacks if s["doc_type"] == "technology")
    print(f"{len(portfolio)} clients -> {args.clients_out}")
    print(f"{n_tech} technologies + {len(stacks) - n_tech} domain stacks -> {args.stacks_out}")
    other = [s["name"] for s in stacks if s["doc_type"] == "technology" and s["category"] == "other"]
    print("Technologies without a category:", other)


if __name__ == "__main__":
    main()