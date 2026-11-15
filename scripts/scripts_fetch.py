import json, urllib.request, urllib.parse, time, sys
from pathlib import Path
B="https://api.openalex.org/works"
SEL="id,display_name,publication_year,cited_by_count,is_retracted,referenced_works,abstract_inverted_index,primary_location"
calls=0
def get(params, name):
    global calls
    url=B+"?"+urllib.parse.urlencode(params, safe=":|,>")
    req=urllib.request.Request(url, headers={"User-Agent":"taintline-hackathon (+https://github.com/demir-sama)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rem=r.headers.get("x-ratelimit-remaining"); d=json.load(r)
    calls+=1
    json.dump(d, open(str(Path(__file__).resolve().parent.parent / f"data/raw/{name}.json"),"w"))
    print(name, len(d["results"]), "count", d["meta"]["count"], "remaining", rem, flush=True)
    return d["results"]
sid=lambda w: w["id"].rsplit("/",1)[1]
R=get({"filter":"is_retracted:true,publication_year:2020-2023,cited_by_count:>10,title_and_abstract.search:covid","per_page":200,"select":SEL}, "retracted")
rids=[sid(w) for w in R]
C1=[]
for i,chunk in enumerate([rids[:100], rids[100:200]]):
    if not chunk: continue
    C1+=get({"filter":"cites:"+"|".join(chunk),"sample":200,"seed":7,"per_page":200,"select":SEL}, f"c1_{i}")
c1ids=list(dict.fromkeys(sid(w) for w in C1 if not w.get("is_retracted")))
Q=[]
for i in range(3):
    chunk=c1ids[i*100:(i+1)*100]
    if not chunk: break
    Q+=get({"filter":"cites:"+"|".join(chunk)+",publication_year:2021-2024","sample":200,"seed":11,"per_page":200,"select":SEL}, f"q_{i}")
CTRL=get({"filter":"title_and_abstract.search:covid treatment,publication_year:2021-2024,is_retracted:false,type:article","sample":200,"seed":3,"per_page":200,"select":SEL}, "controls")
print("calls", calls)
