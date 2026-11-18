import csv,io,json
def build_archive(run):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["run_id","input_sha256","rule_version","kind","budget_version","budget_seconds","source_lines","reason","evidence"])
    meta=run["manifest"]
    budget=run.get("executed_budget") or meta.get("budget") or {}
    for row in run["stages"][-1]["rows"]:
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"accepted",budget.get("version",""),budget.get("seconds",""),json.dumps(row.get("_sources",[])),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    for row in run["stages"][-1].get("cumulative_quarantine",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"quarantine",budget.get("version",""),budget.get("seconds",""),json.dumps(row.get("_sources",[])),row.get("reason",""),json.dumps(row,ensure_ascii=False)])
    return "﻿"+stream.getvalue()
