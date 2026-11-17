import json, collections, copy
UP='/mnt/user-data/uploads/'
t=json.load(open(UP+'tech_stacks.json'))
pfe=json.load(open(UP+'olivesoft_projects.json'))
scrap=json.load(open(UP+'olivesoft_projects_scrap.json'))

# website projects: ids follow scrape order (edit WEB_IDS to match your KB ids project-00X if you prefer)
WEB_IDS=['website-001','website-002','website-003','website-004','website-005']
INDUSTRY_TO_DOMAIN={'Human Resources':'HR','Retail and E-commerce':'retail','Luxury':'luxury'}
ALIAS={'Google Cloud Platform':'GCP'}   # scraped name -> existing technology chunk
NEW_CAT={'Cegid':'CRM and business applications','Sage X3':'CRM and business applications',
 'Google Cloud Storage':'Cloud platforms','Dataform':'Data integration and ETL',
 'CoAtNet':'AI and machine learning','FAISS':'Vector databases'}

web=[]
for i,s in zip(WEB_IDS,scrap):
    d=s['data']
    web.append(dict(id=i,name=d['project_name'],
        techs=[ALIAS.get(x,x) for x in d['technologies_used']],raw=d['technologies_used'],
        industry=d['industry_category'],url=s['url']))

tech={x['name']:x for x in t if x['doc_type']=='technology'}
nxt=max(int(x['id'].split('-')[1]) for x in t if x['doc_type']=='technology')+1
for w in web:
    for n in w['techs']:
        if n not in tech:
            e=dict(id=f'TECH-{nxt:03d}',doc_type='technology',name=n,category=NEW_CAT[n],variants_seen=[],
              real_project_count=0,synthetic_project_count=0,cv_count=0,real_project_evidence='none',
              synthetic_only=False,example_real_projects=[],related_technologies=[],document_text='')
            nxt+=1; t.insert(max(i for i,x in enumerate(t) if x['doc_type']=='technology')+1,e); tech[n]=e

def level(n): return 'strong' if n>=5 else 'moderate' if n>=2 else 'limited' if n==1 else 'none'
touched=collections.OrderedDict()
for w in web:
    for n in dict.fromkeys(w['techs']): touched.setdefault(n,[]).append(w)
for x in tech.values(): x.setdefault('website_project_count',0)
for n,ws in touched.items():
    x=tech[n]
    x['website_project_count']=len(ws)
    x['real_project_count']+=len(ws)
    x['real_project_evidence']=level(x['real_project_count'])
    x['synthetic_only']=False
    x['example_real_projects']+= [{'id':w['id'],'name':w['name']} for w in ws]
    for w in ws:
        for r,a in zip(w['raw'],w['techs']):
            if a==n and r!=n and r not in x['variants_seen']: x['variants_seen'].append(r)
    if not x['related_technologies']:
        rel=[]
        for w in ws:
            rel+= [o for o in w['techs'] if o!=n and o not in rel]
        x['related_technologies']=rel[:5]

def text(x):
    n=x['name']; pf=x['real_project_count']-x['website_project_count']
    pfe_ex=[e['name'] for e in x['example_real_projects'] if not e['id'].startswith('website-')]
    web_ex=[e['name'] for e in x['example_real_projects'] if e['id'].startswith('website-')]
    s=f"{n} is a technology in the category '{x['category']}'. "
    if x['real_project_count']==0:
        s+="It does not appear in Olivesoft's real project references; it only appears in synthetic CVs and projects. "
    else:
        s+=f"It appears in {x['real_project_count']} of Olivesoft's real project references"
        if x['website_project_count']:
            k=x['website_project_count']; w_=f"{k} client project{'s' if k!=1 else ''} published on the Olivesoft website"
            s+=f" ({pf} PFE internship project{'s' if pf!=1 else ''} and {w_})" if pf else f" ({w_})"
        s+=". "
        if pfe_ex: s+=f"PFE examples: {'; '.join(pfe_ex)}. "
        if web_ex: s+=f"Website client projects: {'; '.join(web_ex)}. "
    if x['synthetic_project_count']: s+=f"It is used in {x['synthetic_project_count']} synthetic past projects. "
    if x['cv_count']: s+=f"{x['cv_count']} CVs in the CV bank list it as a skill. "
    if x['related_technologies']: s+=f"It is often used together with {', '.join(x['related_technologies'])}."
    return s.strip()
for n in touched: tech[n]['document_text']=text(tech[n])

# stacks by domain (HR, retail, luxury are the only domains the website industries map to)
allp=[dict(id=x['id'],name=x['name'],domain=x['domain'],techs=x['tech_stack']['technologies'],web=False) for x in pfe]
allp+=[dict(id=w['id'],name=w['name'],domain=[INDUSTRY_TO_DOMAIN[w['industry']]] if w['industry'] in INDUSTRY_TO_DOMAIN else [],techs=w['techs'],web=True) for w in web]
def stack_entry(d,ex_id=None):
    ps=[p for p in allp if d in p['domain']]
    c=collections.Counter(tt for p in ps for tt in dict.fromkeys(p['techs']))
    nweb=sum(p['web'] for p in ps)
    s=(f"In Olivesoft's real project references (PFE internship projects and client projects published on the website), {d} projects typically use: "
       +', '.join(f"{a} ({b} projects)" for a,b in c.most_common(8))+". Projects: "+'; '.join(p['name'] for p in ps)+".")
    return dict(domain=d,project_count=len(ps),typical_technologies=[{'name':a,'projects':b} for a,b in c.most_common(8)],
                project_ids=[p['id'] for p in ps],document_text=s)
sds={x['domain']:x for x in t if x['doc_type']=='stack_by_domain'}
for d in ['HR','retail']:
    new=stack_entry(d); sds[d].update({k:new[k] for k in new})
new=stack_entry('luxury')
sid=max(int(x['id'].split('-')[1]) for x in t if x['doc_type']=='stack_by_domain')+1
t.append(dict(id=f'STACK-{sid:03d}',doc_type='stack_by_domain',**new))

json.dump(t,open('/mnt/user-data/outputs/tech_stacks.json','w'),indent=2,ensure_ascii=False)
