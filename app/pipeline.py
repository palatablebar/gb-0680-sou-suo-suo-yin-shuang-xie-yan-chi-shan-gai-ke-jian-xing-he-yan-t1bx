import time
from app.config import ROOT,MODULES
from app.errors import DomainError
from app.values import scalar
from app.budgets import resolve_budget,with_budget,budget_meta,all_budgets,budget_of,identity_params
from app.evaluations import recompute,snapshot
from app.manifest import digest,manifest
from app import store
from app.modules.m1_streams.rules import evaluate as stage1
from app.modules.m2_schema.rules import evaluate as stage2
from app.modules.m3_versions.rules import evaluate as stage3
from app.modules.m4_visibility.rules import evaluate as stage4
from app.modules.m5_latency.rules import evaluate as stage5
from app.modules.m6_parity.rules import evaluate as stage6
from app.modules.m7_backfills.rules import evaluate as stage7
STAGES=[stage1,stage2,stage3,stage4,stage5,stage6,stage7]
def load_sample(name):
    if name not in {"dirty.csv","clean.csv","legacy.csv"}: raise DomainError("BAD_SAMPLE","样例不存在",404)
    return (ROOT/"sample_data"/name).read_bytes()
def calculate(raw,params=None,stop=6):
    params=params or {};budget=resolve_budget(params);effective=with_budget(params,budget)
    started=time.monotonic();context={"parameters":effective,"raw":raw,"quarantine":[]};stages=[];rows=[]
    for index,stage in enumerate(STAGES[:stop+1]):
        result=stage(raw if index==0 else rows,context)
        result=scalar(result);rows=result["rows"]
        context["quarantine"].extend(result.get("quarantine",[]))
        if index==0: context["intake"]=result["metrics"]
        result["cumulative_quarantine"]=list(context["quarantine"])
        context[MODULES[index][0]]=result
        stages.append(result)
    result={"run_id":digest(raw,effective)[:20],"stages":stages,"manifest":manifest(raw,effective,started,budget),"parameters":effective,"executed_budget":budget_meta(budget)}
    if stop>=6:
        result["evaluations"]={budget["version"]:snapshot(result,budget)}
        for other in all_budgets():
            if other["version"]==budget["version"]: continue
            result["evaluations"][other["version"]]=snapshot(recompute(result,other),other)
    return result
def execute(raw,params=None):
    result=calculate(raw,params)
    identity=identity_params(result["parameters"])
    existing=store.find_existing(result["manifest"]["input_sha256"],identity,result["manifest"]["rule_version"])
    run_id=existing or result["run_id"]
    if existing:
        # 旧批次 id 可能用旧身份算法产生；复用原 id，不新增批次。
        result["run_id"]=existing
    else: store.save(run_id,result)
    view=store.view(run_id)
    # 明确告诉调用方：这是复用批次，请求预算与封存预算可能不同。
    view["reused"]=bool(existing)
    view["requested_budget"]=result["executed_budget"]
    return view
def stage_preview(index,payload):
    if "rows" in payload and index>0:
        if not isinstance(payload["rows"],list) or any(not isinstance(row,dict) for row in payload["rows"]): raise DomainError("BAD_ROWS","记录需要对象列表")
        if not isinstance(payload.get("context",{}),dict): raise DomainError("BAD_CONTEXT","上下文需要对象")
        return scalar(STAGES[index](payload["rows"],payload.get("context",{"parameters":{},"quarantine":[]})))
    raw=payload.get("csv")
    raw=raw.encode() if isinstance(raw,str) else load_sample(payload.get("sample","dirty.csv"))
    return calculate(raw,payload.get("parameters",{}),index)["stages"][-1]


def evaluations_for(payload):
    """返回批次在各预算版本下的评估视图。

    批次自带的快照是封存口径（sealed=True）；对尚未包含的已登记预算
    按需只读重算，sealed=False，绝不写回批次。
    """
    stored=dict(payload.get("evaluations") or {})
    executed=budget_of(payload.get("parameters"))
    if executed["version"] not in stored and len(payload.get("stages",[]))>=7:
        stored[executed["version"]]=snapshot(payload,executed)
    registered={item["version"]:item for item in all_budgets()}
    out=[]
    for version,evaluation in stored.items():
        budget=registered.get(version) or {"label":f"历史 {evaluation.get('budget_seconds')}s","superseded":True}
        out.append({**evaluation,"label":budget["label"],
                    "sealed":version==executed["version"],
                    "superseded":bool(budget["superseded"])})
    for budget in all_budgets():
        if budget["version"] in stored: continue
        if len(payload.get("stages",[]))<7: continue
        out.append({**snapshot(recompute(payload,budget),budget),
                    "label":budget["label"],"sealed":budget["version"]==executed["version"],
                    "superseded":bool(budget["superseded"])})
    return out
