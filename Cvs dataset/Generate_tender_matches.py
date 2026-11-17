"""
For each tender, generate 3 matching fake CVs and 2 matching fake projects.
All records are synthetic (synthetic: true). IDs continue after the existing
CV-0020 and PRJ-0012.

Usage:  python generate_tender_matches.py
Output: tender_matches_cvs.json, tender_matches_projects.json, tender_matches.json
"""
import json
import random

rng = random.Random(42)

# Skills an employee may have without using them at Olivesoft
EXTRA = ["Flutter", "Swift", "Kotlin", "Django", "Spring Boot", "MongoDB",
         "Redis", "GraphQL", "TensorFlow"]
GENERAL = ["Git", "SQL", "Docker", "CI/CD", "Python", "Azure DevOps"]

# key = must-have skills (every match has ALL of them)
# core = other relevant skills (each match gets some of them)
TENDERS = {
    "tender-001": dict(
        key=["MuleSoft", "REST APIs"],
        core=["DataWeave", "API Management", "Master Data Management", "Azure DevOps", "SAP SuccessFactors", "Datadog"],
        roles=["Integration Architect", "MuleSoft Developer", "Solutions Architect"],
        projects=[("HR systems integration layer", "consumer goods"), ("Versioned API platform with handover documentation", "retail")],
        certs=["MuleSoft Certified Developer", "PMP"]),
    "tender-002": dict(
        key=["Talend", "SQL"],
        core=["SSIS", "SQL Server", "Apache Airflow", "Azure DevOps", "Data Quality"],
        roles=["Data Engineer", "ETL Developer", "Data Engineer"],
        projects=[("Incremental ETL pipeline migration from SSIS", "logistics"), ("Workforce data warehouse with reconciliation reports", "logistics")],
        certs=["Talend Data Integration Certified Developer", "Microsoft Azure Fundamentals"]),
    "tender-003": dict(
        key=["Power BI", "DAX"],
        core=["SQL", "Azure SQL", "Row-Level Security", "Data Modelling", "Azure DevOps"],
        roles=["BI Developer", "Data Analyst", "Business Analyst"],
        projects=[("Executive HR analytics semantic model", "manufacturing"), ("Divisional reporting consolidation in Power BI", "manufacturing")],
        certs=["Microsoft Power BI Data Analyst", "Scrum Master (CSM)"]),
    "tender-004": dict(
        key=["GCP", "BigQuery"],
        core=["MuleSoft", "Talend", "Identity Resolution", "Terraform", "Python"],
        roles=["Data Engineer", "Cloud Architect", "Integration Architect"],
        projects=[("Customer 360 on BigQuery", "retail"), ("Multi-channel customer identity resolution", "retail")],
        certs=["Google Professional Cloud Architect", "Google Professional Data Engineer"]),
    "tender-005": dict(
        key=["Kafka", "Databricks"],
        core=["Python", "Spark", "Datadog", "GCP", "Azure", "Terraform"],
        roles=["Data Engineer", "Streaming Engineer", "Cloud Architect"],
        projects=[("Real-time order event streaming platform", "retail"), ("Databricks lakehouse with late-event handling", "retail")],
        certs=["Databricks Certified Data Engineer", "Confluent Certified Developer"]),
    "tender-006": dict(
        key=["Salesforce Service Cloud", "Apex"],
        core=["Lightning", "Talend", "MuleSoft", "Data Migration", "Azure DevOps"],
        roles=["Salesforce Developer", "Salesforce Consultant", "Solutions Architect"],
        projects=[("Service Cloud contact centre implementation", "insurance"), ("Case history migration and omnichannel routing", "insurance")],
        certs=["Salesforce Certified Administrator", "Salesforce Platform Developer I"]),
    "tender-007": dict(
        key=["Python", "Scikit-learn"],
        core=["TensorFlow", "PyTorch", "BigQuery", "Power BI", "MLOps", "Time-Series Forecasting"],
        roles=["Data Scientist", "AI/ML Engineer", "Data Scientist"],
        projects=[("Demand forecasting with confidence bands", "manufacturing"), ("Forecast override dashboard with feedback loop", "manufacturing")],
        certs=["Google Professional Machine Learning Engineer", "Microsoft Azure Fundamentals"]),
    "tender-008": dict(
        key=["RAG", "Python"],
        core=["LangChain", "FastAPI", "ChromaDB", "OpenAI", "Prompt Evaluation", "Pinecone"],
        roles=["AI/ML Engineer", "AI/ML Engineer", "Backend Developer"],
        projects=[("Grounded RAG support assistant with citations", "retail"), ("RAG evaluation harness against historical queries", "retail")],
        certs=["Microsoft Azure Fundamentals", "AWS Certified Developer"]),
    "tender-009": dict(
        key=["Computer Vision", "PyTorch"],
        core=["OpenCV", "Edge AI", "MLOps", "Python", "ONNX", "Docker"],
        roles=["AI/ML Engineer", "Computer Vision Engineer", "Data Scientist"],
        projects=[("Automated visual inspection on a production line", "textile manufacturing"), ("Offline edge inference with opportunistic sync", "manufacturing")],
        certs=["AWS Certified Developer", "NVIDIA Deep Learning Institute Certificate"]),
    "tender-010": dict(
        key=["NLP", "Computer Vision"],
        core=["PyTorch", "HuggingFace", "Python", "Elasticsearch", "FastAPI", "Audit Logging"],
        roles=["AI/ML Engineer", "Data Scientist", "AI/ML Engineer"],
        projects=[("Document similarity detection with ranked evidence", "public administration"), ("Image and text matching with auditable decision trail", "public administration")],
        certs=["AWS Certified Developer", "Microsoft Azure Fundamentals"]),
    "tender-011": dict(
        key=["Salesforce", "CRM Analytics"],
        core=["Apex", "Lightning", "Offline Sync", "Data Residency", "Azure DevOps"],
        roles=["Salesforce Developer", "Salesforce Consultant", "Business Analyst"],
        projects=[("Citizen services CRM Analytics", "public administration"), ("Offline-capable case management with reconciliation", "public administration")],
        certs=["Salesforce Certified Administrator", "Salesforce CRM Analytics Consultant"]),
    "tender-012": dict(
        key=["BigQuery", "Snowflake"],
        core=["GCP", "Python", "Apache Airflow", "Terraform", "Data Lineage", "dbt"],
        roles=["Data Engineer", "Data Architect", "Data Engineer"],
        projects=[("Public statistics warehouse on BigQuery", "public administration"), ("Open data portal with lineage and de-identification", "public administration")],
        certs=["Google Professional Data Engineer", "SnowPro Core"]),
    "tender-013": dict(
        key=["REST APIs", "Flutter"],
        core=["MuleSoft", "FastAPI", "Kotlin", "Offline Sync", "Docker", "Telematics"],
        roles=["Mobile Developer", "Integration Developer", "Full Stack Developer"],
        projects=[("Telematics API integration with maintenance and fuel systems", "logistics"), ("Driver app with offline proof of delivery", "logistics")],
        certs=["MuleSoft Certified Developer", "Scrum Master (CSM)"]),
}

# tender-014 is catering/facilities: no IT match, so nothing is generated.
# tender-015 is a re-post of tender-004: it reuses tender-004's matches.
SKIP = {"tender-014": "Catering and facilities services - no IT match in Olivesoft's scope."}
DUPLICATE_OF = {"tender-015": "tender-004"}


def article(word):
    return "an" if word[0].lower() in "aeiou" else "a"


cvs, projects, matches = [], [], {}
cv_n, prj_n = 21, 13

for tid, t in TENDERS.items():
    # --- 2 projects ---
    prj_ids = []
    prj_objs = []
    for name, sector in t["projects"]:
        stack = t["key"] + rng.sample(t["core"], k=3)
        p = {
            "project_id": f"PRJ-{prj_n:04d}",
            "name": name,
            "client_sector": sector,
            "tech_stack": stack,
            "description": f"{name} for {article(sector)} {sector} client, using {', '.join(stack)}.",
            "outcome": f"Delivered on schedule with a {rng.randint(15, 45)}% reduction in manual effort.",
            "synthetic": True,
            "built_for_tender": tid,
        }
        projects.append(p)
        prj_objs.append(p)
        prj_ids.append(p["project_id"])
        prj_n += 1

    # --- 3 CVs ---
    cv_ids = []
    for role, years in zip(t["roles"], rng.sample(range(3, 15), k=3)):
        main = t["key"] + rng.sample(t["core"], k=rng.randint(3, 4)) + rng.sample(GENERAL, k=2)
        skills = list(dict.fromkeys(main + rng.sample(EXTRA, k=rng.randint(0, 2))))
        past = []
        for p in rng.sample(prj_objs, k=rng.randint(1, 2)):
            past.append({
                "project_name": p["name"],
                "client_sector": p["client_sector"],
                "description": f"Contributed as {role.lower()} on {article(p['client_sector'])} {p['client_sector']} sector project, working with {', '.join(p['tech_stack'][:3])}.",
                "tech_stack": p["tech_stack"][:3],
            })
        cv = {
            "cv_id": f"CV-{cv_n:04d}",
            "name": f"Employee_{cv_n:03d}",
            "role": role,
            "years_experience": years,
            "skills": skills,
            "past_projects": past,
            "certifications": [rng.choice(t["certs"])],
            "synthetic": True,
            "built_for_tender": tid,
        }
        cvs.append(cv)
        cv_ids.append(cv["cv_id"])
        cv_n += 1

    matches[tid] = {"cv_ids": cv_ids, "project_ids": prj_ids, "note": ""}

for dup, original in DUPLICATE_OF.items():
    matches[dup] = {**matches[original], "note": f"Re-post of {original}; same matches."}
for tid, why in SKIP.items():
    matches[tid] = {"cv_ids": [], "project_ids": [], "note": why}

for path, data in [("tender_matches_cvs.json", cvs),
                   ("tender_matches_projects.json", projects),
                   ("tender_matches.json", dict(sorted(matches.items())))]:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

print(f"{len(cvs)} CVs, {len(projects)} projects, {len(matches)} tenders mapped")