from app.modules.m5_latency.rules import evaluate
from app.errors import DomainError
import pytest
def doc(visible="2026-11-16T10:02:00Z",state="CONSISTENT"):return {"source_at":"2026-11-16T10:00:00Z","visible_at":visible,"visibility_state":state}
def test_real_missing_count(result): assert result["stages"][4]["metrics"]["missing"]==1
def test_real_delayed_count(result): assert result["stages"][4]["metrics"]["delayed"]==1
def test_threshold_equal_pass():
    "TRAP-23 边界等值通过（显式使用 120s 预算）"
    assert evaluate([doc()],{"parameters":{"max_delay_seconds":"120"}})["rows"][0]["gate"]=="通过"

def test_module_preview_follows_current_budget():
    "模块直算不得默认另一个口径"
    assert evaluate([doc()],{})["rows"][0]["threshold_seconds"]=="90"
    assert evaluate([doc()],{})["rows"][0]["gate"]=="延迟"
def test_over_threshold_delayed(): assert evaluate([doc("2026-11-16T10:02:01Z")],{})["rows"][0]["gate"]=="延迟"
def test_missing_within_budget_waiting(): assert evaluate([doc(None,"MISSING_INDEX")],{"parameters":{"as_of":"2026-11-16T10:01:00Z"}})["rows"][0]["gate"]=="等待"
def test_mismatch_not_mislabeled_delay(): assert evaluate([doc("2026-11-16T10:05:00Z","STALE_INDEX")],{})["rows"][0]["gate"]=="内容差异"
def test_negative_threshold_rejected():
    with pytest.raises(DomainError):evaluate([],{"parameters":{"max_delay_seconds":"-1"}})
