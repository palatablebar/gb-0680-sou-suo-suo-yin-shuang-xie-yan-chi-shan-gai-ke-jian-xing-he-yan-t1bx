import sqlite3,json,hashlib
from app.config import DATA_DIR
from app.errors import DomainError
from app.budgets import budget_of,budget_meta,all_budgets,current_budget
from app.evaluations import compare
from app.rulings import RULING

def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"records.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    return db

def save(run_id,payload):
    # 批次身份不含预算；已存在批次原样保留，重跑不得改写封存结论。
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,payload) VALUES (?,?)",(run_id,json.dumps(payload,ensure_ascii=False)))
    return get(run_id)

def find_existing(input_sha256,identity,rule_version):
    """按输入摘要 + 非预算参数 + 规则版本定位既有批次。

    这样即使旧批次当时把预算写成 120 秒、新请求写 90 秒或只写预算版本，
    同一批输入仍复用原批次，不会因预算表达方式不同而新增批次。
    """
    from app.budgets import identity_params
    with connect() as db:
        rows=db.execute("SELECT id,payload FROM runs ORDER BY rowid").fetchall()
    for run_id,raw in rows:
        try: payload=json.loads(raw)
        except ValueError: continue
        meta=payload.get("manifest",{})
        if meta.get("input_sha256")!=input_sha256: continue
        if meta.get("rule_version")!=rule_version: continue
        if identity_params(payload.get("parameters"))!=identity: continue
        return run_id
    return None

def get(run_id):
    with connect() as db: row=db.execute("SELECT payload,version,decision FROM runs WHERE id=?",(run_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","批次不存在",404)
    return {**json.loads(row[0]),"version":row[1],"decision":row[2]}

def latest():
    with connect() as db: row=db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    return get(row[0]) if row else None

def history():
    with connect() as db:
        records=[(i,json.loads(p),v,d) for i,p,v,d in db.execute("SELECT id,payload,version,decision FROM runs ORDER BY rowid DESC")]
    out=[]
    for run_id,payload,version,decision in records:
        budget=budget_of(payload.get("parameters"))
        out.append({"run_id":run_id,"version":version,"decision":decision,
                    "budget_version":budget["version"],"budget_seconds":budget["seconds"],
                    "input_sha256":payload.get("manifest",{}).get("input_sha256")})
    return out

def review(run_id,version,decision):
    if decision not in {"已复核","退回复核"}: raise DomainError("BAD_DECISION","复核状态无效")
    with connect() as db:
        cursor=db.execute("UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?",(decision,run_id,version))
        if cursor.rowcount!=1:
            if not db.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone(): raise DomainError("NOT_FOUND","批次不存在",404)
            raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
    return get(run_id)


def _evaluations(payload):
    from app.pipeline import evaluations_for
    return evaluations_for(payload)

def view(run_id):
    """单批次视图：封存结论与实际预算版本，附带跨预算只读对照。"""
    payload=get(run_id)
    evaluations=_evaluations(payload)
    executed=budget_of(payload.get("parameters"))
    sealed=next((e for e in evaluations if e["budget_version"]==executed["version"]),None)
    others=[e for e in evaluations if e["budget_version"]!=executed["version"]]
    rows=[]
    if sealed is not None:
        for other in others:
            for item in compare(sealed,other):
                rows.append({"budget_version":other["budget_version"],"label":other["label"],**item})
    return {**payload,"executed_budget":budget_meta(executed),"evaluations":evaluations,
            "comparison":rows,"attribution":"同输入摘要下结论变化归因于预算版本"}

def _zero():
    return {"batches":0,"documents":0,"pass":0,"differences":0,"difference_sum":0.0}

def daily():
    """唯一日报：每个批次只有一份结论，合计按实际预算版本分栏。

    不把 120s 与 90s 的批次混进同一个合计，也不为历史批次另造结论；
    跨预算对照逐文档列出，输入摘要相同则差异只能归因预算版本。
    """
    with connect() as db:
        records=[(i,json.loads(p),v,d) for i,p,v,d in db.execute("SELECT id,payload,version,decision FROM runs ORDER BY rowid")]
    batches=[];totals={item["version"]:_zero() for item in all_budgets()}
    divergent=0;affected=[]
    for run_id,payload,version,decision in records:
        executed=budget_of(payload.get("parameters"))
        evaluations=_evaluations(payload)
        sealed=next((e for e in evaluations if e["budget_version"]==executed["version"]),None)
        if sealed is None: continue
        comparisons=[]
        for other in evaluations:
            if other["budget_version"]==executed["version"]: continue
            for item in compare(sealed,other):
                comparisons.append({"budget_version":other["budget_version"],"label":other["label"],**item})
        changed=sum(1 for item in comparisons if item["changed"])
        divergent+=changed
        bucket=totals.setdefault(executed["version"],_zero())
        bucket["batches"]+=1;bucket["documents"]+=sealed["metrics"]["documents"]
        bucket["pass"]+=sealed["metrics"]["pass"];bucket["differences"]+=sealed["metrics"]["differences"]
        bucket["difference_sum"]=round(bucket["difference_sum"]+float(sealed["metrics"]["difference_sum"]),6)
        batches.append({
            "run_id":run_id,"version":version,"decision":decision,
            "input_sha256":payload.get("manifest",{}).get("input_sha256"),
            "rule_version":payload.get("manifest",{}).get("rule_version"),
            "budget":budget_meta(executed),
            "sealed":{k:sealed[k] for k in ("budget_version","budget_seconds","metrics","documents")},
            "comparison":comparisons,"changed_documents":changed,
        })
        if changed:
            # 预算敏感批次：只登记为待人工复核，不作废、不追溯重算。
            affected.append({"run_id":run_id,"decision":decision,
                             "sealed_budget_version":executed["version"],
                             "changed_documents":changed,
                             "documents":[item["doc_id"] for item in comparisons if item["changed"]],
                             "action":"保留封存结论，人工判断是否补充复核"})
    report={"single":True,"basis":"每批次按创建时实际预算版本封存，日报只列一份结论；合计按预算版本分栏",
            "current_budget":budget_meta(current_budget()),
            "budgets":[budget_meta(item) for item in all_budgets()],
            "ruling":RULING,"batches":batches,
            "budget_sensitive_batches":affected,
            "totals_by_budget":{k:v for k,v in totals.items() if v["batches"]},
            "counts":{"batches":len(batches),
                      "documents":sum(v["documents"] for v in totals.values()),
                      "divergent_documents":divergent,
                      "divergence_attribution":"BUDGET" if divergent else "NONE"}}
    # 日报身份只由批次封存内容决定：同库重跑不会产生第二份日报。
    canonical=json.dumps({"batches":batches,"ruling":RULING["code"]},sort_keys=True,ensure_ascii=False)
    report["report_sha256"]=hashlib.sha256(canonical.encode()).hexdigest()
    return report
