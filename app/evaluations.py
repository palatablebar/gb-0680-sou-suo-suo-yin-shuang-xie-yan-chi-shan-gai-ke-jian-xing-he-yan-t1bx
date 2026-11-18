"""把一次完整计算压缩为按预算版本冻结的评估快照。

快照只保存结论（门禁、对账状态、差异数、逐文档明细），不保存生成时刻，
因此同输入同预算重算得到完全相同的内容，便于封存与对照。
"""
from decimal import Decimal

from app.budgets import with_budget
from app.modules.m5_latency.rules import evaluate as stage5
from app.modules.m6_parity.rules import evaluate as stage6
from app.modules.m7_backfills.rules import evaluate as stage7


def recompute(payload,budget):
    """在不重读原始文件的前提下，用另一预算版本重算第 5–7 阶段。

    只替换结论阶段，登记、隔离与来源行保持原批次；批次号不变。
    """
    result={**payload,"stages":list(payload["stages"])}
    stages=result["stages"]
    params=with_budget(payload.get("parameters",{}),budget)
    quarantine=list(stages[3].get("cumulative_quarantine",[]))
    latency=stage5(stages[3]["rows"],{"parameters":params})
    latency["cumulative_quarantine"]=quarantine
    parity=stage6(latency["rows"],{"intake":stages[0]["metrics"],"quarantine":quarantine})
    parity["cumulative_quarantine"]=quarantine
    backfill=stage7(parity["rows"],{"reconcile":parity})
    backfill["cumulative_quarantine"]=quarantine
    result["stages"]=[stages[0],stages[1],stages[2],stages[3],latency,parity,backfill]
    result["parameters"]=params
    result["manifest"]={**payload["manifest"],"parameters":params,
                        "budget_version":budget["version"],"budget_seconds":budget["seconds"]}
    return result


def snapshot(result,budget):
    latency={row["doc_id"]:row for row in result["stages"][4]["rows"]}
    parity={row["doc_id"]:row for row in result["stages"][5]["rows"]}
    documents=[]
    for doc_id in sorted(set(latency)|set(parity)):
        gate=latency.get(doc_id,{})
        check=parity.get(doc_id,{})
        documents.append({
            "doc_id":doc_id,
            "gate":gate.get("gate"),
            "visibility_state":gate.get("visibility_state"),
            "status":check.get("status"),
            "difference":str(check.get("difference","0")),
            "expected":check.get("expected","0"),
            "reported":check.get("reported","0"),
            "delay_seconds":gate.get("delay_seconds"),
            "threshold_seconds":gate.get("threshold_seconds",budget["seconds"]),
        })
    lm=result["stages"][4]["metrics"]
    pm=result["stages"][5]["metrics"]
    return {
        "budget_version":budget["version"],
        "budget_seconds":budget["seconds"],
        "documents":documents,
        "metrics":{
            "documents":len(documents),
            "pass":lm["pass"],"delayed":lm["delayed"],"missing":lm["missing"],
            "waiting":lm["waiting"],"mismatch":lm["mismatch"],
            "differences":pm["differences"],
            "expected_total":pm["expected_total"],
            "reported_total":pm["reported_total"],
            "difference_sum":str(sum((Decimal(d["difference"]) for d in documents),Decimal(0))),
        },
        "seal_sha256":result["stages"][6]["metrics"]["sha256"],
    }


def conclusions(evaluation):
    """单文档的通过结论与差异数，供跨预算对照。"""
    return {row["doc_id"]: {"gate":row["gate"],
                            "gate_pass":row["gate"]=="通过",
                            "status":row["status"],
                            "difference":row["difference"]}
            for row in evaluation.get("documents",[])}


def compare(left,right):
    """逐文档对照两个预算版本下的通过结论与差异数。"""
    a=conclusions(left);b=conclusions(right)
    rows=[]
    for doc_id in sorted(set(a)|set(b)):
        old=a.get(doc_id);new=b.get(doc_id)
        rows.append({"doc_id":doc_id,"old":old,"new":new,
                     "gate_changed":(old or {}).get("gate_pass")!=(new or {}).get("gate_pass"),
                     "difference_changed":(old or {}).get("difference")!=(new or {}).get("difference"),
                     "changed":(old or {}).get("gate_pass")!=(new or {}).get("gate_pass")
                             or (old or {}).get("difference")!=(new or {}).get("difference")})
    return rows
