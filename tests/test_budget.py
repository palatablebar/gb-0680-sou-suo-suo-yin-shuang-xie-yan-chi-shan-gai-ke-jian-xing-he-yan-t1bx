import csv,io
import pytest
from app import store
from app.config import COLUMNS
from app.errors import DomainError
from app.pipeline import calculate,execute,load_sample

def csv_bytes(delay_seconds):
    end=f"2026-11-16T10:{delay_seconds//60:02d}:{delay_seconds%60:02d}Z"
    rows=[
        ["1","d1","1","upsert","2026-11-16T10:00:00Z","-","source",'{"a":1}',"1",""],
        ["2","d1","1","upsert","2026-11-16T10:00:00Z",end,"index",'{"a":1}',"1",""],
    ]
    stream=io.StringIO(newline="");writer=csv.writer(stream);writer.writerow(COLUMNS)
    for row in rows: writer.writerow(row)
    return stream.getvalue().encode()

def test_default_budget_is_noon_90s():
    result=calculate(load_sample("dirty.csv"))
    assert result["manifest"]["budget_version"]=="budget-2026.11.18-noon"
    assert result["manifest"]["budget_seconds"]=="90"
    assert result["parameters"]["max_delay_seconds"]=="90"

def test_budget_change_keeps_run_id_and_batch_count():
    raw=csv_bytes(100)
    morning=calculate(raw,{"budget_version":"budget-2026.11.18-am"})
    noon=calculate(raw,{"budget_version":"budget-2026.11.18-noon"})
    assert morning["run_id"]==noon["run_id"]

def test_same_batch_only_one_sealed_conclusion():
    raw=csv_bytes(100)
    first=execute(raw,{"budget_version":"budget-2026.11.18-am"})
    second=execute(raw,{"budget_version":"budget-2026.11.18-noon"})
    assert first["run_id"]==second["run_id"]
    assert len(store.history())==1
    sealed=store.get(first["run_id"])
    assert sealed["manifest"]["budget_version"]=="budget-2026.11.18-am"
    assert sealed["executed_budget"]["seconds"]=="120"

def test_difference_comes_from_budget_not_document():
    raw=csv_bytes(100)
    morning=execute(raw,{"budget_version":"budget-2026.11.18-am"})
    store.review(morning["run_id"],1,"已复核")
    view=store.view(morning["run_id"])
    comparisons=view["comparison"]
    assert len(comparisons)==1
    item=comparisons[0]
    assert item["budget_version"]=="budget-2026.11.18-noon"
    assert item["old"]["gate"]=="通过" and item["new"]["gate"]=="延迟"
    assert item["old"]["difference"]=="0" and item["new"]["difference"]=="1"
    assert item["changed"] is True

def test_shadow_evaluation_does_not_change_sealed_decision():
    raw=csv_bytes(100)
    run=execute(raw,{"budget_version":"budget-2026.11.18-am"})
    store.review(run["run_id"],1,"已复核")
    before=store.get(run["run_id"])
    store.view(run["run_id"])
    store.daily()
    after=store.get(run["run_id"])
    assert after["decision"]==before["decision"]=="已复核"
    assert after["stages"][4]["metrics"]==before["stages"][4]["metrics"]

def test_ruling_revokes_nothing():
    report=store.daily()
    assert report["ruling"]["revoked_batches"]==[]
    assert report["ruling"]["recomputed_batches"]==[]

def test_daily_totals_split_by_budget_never_mixed():
    execute(csv_bytes(100),{"budget_version":"budget-2026.11.18-am"})
    execute(load_sample("clean.csv"),{"budget_version":"budget-2026.11.18-noon"})
    report=store.daily()
    assert report["single"] is True
    by_budget=report["totals_by_budget"]
    assert by_budget["budget-2026.11.18-am"]["batches"]==1
    assert by_budget["budget-2026.11.18-noon"]["batches"]==1
    assert sum(v["batches"] for v in by_budget.values())==report["counts"]["batches"]==2

def test_unknown_budget_rejected():
    with pytest.raises(DomainError) as error:
        calculate(load_sample("dirty.csv"),{"budget_version":"budget-x"})
    assert error.value.code=="BAD_BUDGET"

def test_conflicting_budget_and_seconds_rejected():
    with pytest.raises(DomainError) as error:
        calculate(load_sample("dirty.csv"),{"budget_version":"budget-2026.11.18-noon","max_delay_seconds":"120"})
    assert error.value.code=="BUDGET_MISMATCH"

def test_archive_records_actual_budget(client):
    p=client.post("/api/runs",json={"sample":"dirty.csv","parameters":{"budget_version":"budget-2026.11.18-am"}}).get_json()
    rows=list(csv.reader(io.StringIO(client.get("/api/runs/"+p["run_id"]+"/archive").data.decode("utf-8-sig"))))
    header=rows[0]
    assert header[3]=="kind" and header[4]=="budget_version" and header[5]=="budget_seconds"
    assert rows[1][4]=="budget-2026.11.18-am" and rows[1][5]=="120"

def test_daily_endpoint_has_single_report(client):
    client.post("/api/runs",json={"sample":"dirty.csv"})
    report=client.get("/api/daily").get_json()
    assert report["single"] is True and len(report["batches"])==1
    assert report["batches"][0]["sealed"]["budget_version"]=="budget-2026.11.18-noon"

def test_budget_rules_endpoint_lists_both_budgets(client):
    rules=client.get("/api/budget-rules").get_json()
    versions=[item["version"] for item in rules["budgets"]]
    assert versions==["budget-2026.11.18-am","budget-2026.11.18-noon"]
    assert rules["current"]["version"]=="budget-2026.11.18-noon"

def test_rerun_does_not_change_sealed_conclusion_after_review():
    raw=csv_bytes(100)
    run=execute(raw,{"budget_version":"budget-2026.11.18-am"})
    reviewed=store.review(run["run_id"],1,"已复核")
    again=execute(raw,{"budget_version":"budget-2026.11.18-noon"})
    assert again["run_id"]==reviewed["run_id"]
    assert again["decision"]=="已复核" and again["version"]==reviewed["version"]
    assert len(store.history())==1

def test_daily_report_is_stable_across_reruns():
    raw=csv_bytes(100)
    execute(raw)
    first=store.daily()
    execute(raw)
    second=store.daily()
    assert first["report_sha256"]==second["report_sha256"]
    assert len(second["batches"])==1

def test_sealed_conclusion_not_overwritten_by_new_budget_rerun():
    raw=csv_bytes(100)
    run=execute(raw,{"budget_version":"budget-2026.11.18-am"})
    execute(raw,{"budget_version":"budget-2026.11.18-noon"})
    stored=store.get(run["run_id"])
    assert stored["executed_budget"]["version"]=="budget-2026.11.18-am"
    assert stored["stages"][4]["rows"][0]["gate"]=="通过"
    report=store.daily()
    assert report["batches"][0]["sealed"]["metrics"]["differences"]==0
    assert report["batches"][0]["comparison"][0]["changed"] is True

def test_daily_is_read_only():
    run=execute(load_sample("dirty.csv"),{"budget_version":"budget-2026.11.18-am"})
    before=store.get(run["run_id"])
    store.daily();store.view(run["run_id"]);store.daily()
    after=store.get(run["run_id"])
    assert before["payload_sha"] if False else after["manifest"]["budget_version"]=="budget-2026.11.18-am"
    assert len(store.history())==1
    assert after["version"]==before["version"] and after["decision"]==before["decision"]

def test_shadow_evaluation_is_deterministic():
    run=execute(load_sample("dirty.csv"),{"budget_version":"budget-2026.11.18-am"})
    first=store.view(run["run_id"])["comparison"]
    second=store.view(run["run_id"])["comparison"]
    assert first==second

def test_module_preview_uses_frozen_budget_version():
    from app.modules.m5_latency.rules import evaluate as latency
    row={"source_at":"2026-11-16T10:00:00Z","visible_at":"2026-11-16T10:02:00Z","visibility_state":"CONSISTENT"}
    morning=latency([row],{"parameters":{"budget_version":"budget-2026.11.18-am"}})["rows"][0]
    noon=latency([row],{"parameters":{"budget_version":"budget-2026.11.18-noon"}})["rows"][0]
    assert morning["threshold_seconds"]=="120" and morning["gate"]=="通过"
    assert noon["threshold_seconds"]=="90" and noon["gate"]=="延迟"

def test_pages_and_daily_render(client):
    client.post("/api/runs",json={"sample":"dirty.csv"})
    assert client.get("/daily").status_code==200
    assert client.get("/").status_code==200
    assert client.get("/latency").status_code==200

def test_legacy_payload_defaults_to_morning_budget_but_stays_sealed():
    from app import store
    from app.pipeline import calculate
    result=calculate(load_sample("dirty.csv"),{"budget_version":"budget-2026.11.18-am"})
    legacy={"run_id":result["run_id"],"stages":result["stages"],
            "manifest":{k:result["manifest"][k] for k in ("input_sha256","rule_version","parameters","generated_at","elapsed_ms")},
            "parameters":{}}
    store.save(legacy["run_id"],legacy)
    store.review(legacy["run_id"],1,"已复核")
    view=store.view(legacy["run_id"])
    assert view["executed_budget"]["version"]=="budget-2026.11.18-am"
    assert view["executed_budget"]["seconds"]=="120"
    assert view["decision"]=="已复核"
    sealed=[e for e in view["evaluations"] if e["sealed"]]
    assert len(sealed)==1 and sealed[0]["budget_version"]=="budget-2026.11.18-am"
    assert {item["budget_version"] for item in view["comparison"]}=={"budget-2026.11.18-noon"}

def test_budget_sensitive_batches_listed_without_revoking():
    raw=csv_bytes(100)
    run=execute(raw,{"budget_version":"budget-2026.11.18-am"})
    store.review(run["run_id"],1,"已复核")
    report=store.daily()
    sensitive=report["budget_sensitive_batches"]
    assert len(sensitive)==1
    assert sensitive[0]["run_id"]==run["run_id"]
    assert sensitive[0]["documents"]==["d1"]
    assert report["ruling"]["revoked_batches"]==[]
    assert report["batches"][0]["decision"]=="已复核"

def test_legacy_batch_identity_reused_after_upgrade():
    """升级前用旧身份算法建的批次，重跑仍复用原批次。"""
    result=calculate(load_sample("dirty.csv"))
    legacy={"run_id":result["run_id"],"stages":result["stages"],
            "manifest":{k:result["manifest"][k] for k in ("input_sha256","rule_version","parameters","generated_at","elapsed_ms")},
            "parameters":{}}
    store.save(legacy["run_id"],legacy)
    store.review(legacy["run_id"],1,"已复核")
    again=execute(load_sample("dirty.csv"))
    assert again["reused"] is True
    assert again["run_id"]==legacy["run_id"]
    assert again["decision"]=="已复核"
    assert len(store.history())==1
