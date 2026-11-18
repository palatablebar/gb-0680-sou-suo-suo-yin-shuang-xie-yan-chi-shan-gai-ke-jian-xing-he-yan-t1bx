from flask import render_template
from app.config import MODULES,TITLE,SHORT
from app.pipeline import execute,load_sample
from app import store
COLUMNSETS=[['event_id', 'doc_id', 'version', 'op', 'side', 'source_time', 'visible_time'], ['event_id', 'doc_id', 'version', 'op', 'side', 'source_at', 'visible_at'], ['doc_id', 'side', 'version', 'op', 'tombstone', 'superseded_versions'], ['doc_id', 'source_version', 'index_version', 'source_op', 'index_op', 'visibility_state', 'document_equal'], ['doc_id', 'visibility_state', 'delay_seconds', 'threshold_seconds', 'gate', 'visible_at'], ['doc_id', 'visibility_state', 'gate', 'delay_seconds', 'expected', 'reported', 'status'], ['doc_id', 'source_version', 'index_version', 'gate', 'status']]
LABELS={'event_id': '事件号', 'doc_id': '文档号', 'version': '版本', 'op': '操作', 'side': '数据端', 'source_time': '源时刻', 'visible_time': '可见时刻', 'source_at': '源 UTC', 'visible_at': '可见 UTC', 'tombstone': '墓碑', 'superseded_versions': '已替代版本', 'source_version': '源版本', 'index_version': '索引版本', 'source_op': '源操作', 'index_op': '索引操作', 'visibility_state': '可见性结论', 'document_equal': '内容一致', 'delay_seconds': '延迟 / s', 'threshold_seconds': '预算 / s', 'gate': '门禁', 'expected': '应通过', 'reported': '实通过', 'status': '对账', 'accepted': '采纳行', 'deletes': '删除事件', 'states': '最终状态数', 'tombstones': '墓碑数', 'conflict_rows': '内容冲突行', 'documents': '文档数', 'consistent': '一致文档', 'missing': '缺失数', 'pass': '通过数', 'delayed': '延迟数', 'waiting': '等待数', 'mismatch': '内容差异', 'records': '清单数', 'source_lines': '源行数', 'sha256': '摘要', 'ready': '可回补', 'differences': '差异数', 'accepted_inputs': '采纳来源行', 'quarantine_inputs': '隔离来源行', 'output_records': '结果记录', 'input': '输入行', 'excluded': '排除行', 'balanced': '行数平衡', 'expected_total': '预期合计', 'reported_total': '申报合计', 'blank': '空行', 'repeated_headers': '分段表头', 'encoding': '编码', 'duplicate': '重复行', 'quarantine': '隔离行', 'accepted': '采纳行', 'budget_seconds': '实际预算 / s', 'budget_version': '预算版本', 'difference_sum': '差异合计', 'divergent_documents': '口径变化文档'}

def register_pages(app):
    def page(index):
        latest=store.latest() or execute(load_sample("dirty.csv"))
        run=store.view(latest["run_id"])
        stage=run["stages"][index]
        rules=store.daily()
        return render_template(f"m{index+1}.html",title=TITLE,short=SHORT,modules=MODULES,index=index,run=run,stage=stage,rows=stage["rows"],columns=COLUMNSETS[index][:12],history=store.history(),labels=LABELS,budget_rules=rules["budgets"],report={"current_budget":rules["current_budget"],"counts":rules["counts"]})
    def daily():
        rules=store.daily()
        latest=store.latest()
        return render_template("daily.html",title=TITLE,short=SHORT,modules=MODULES,index=None,report=rules,labels=LABELS,run=store.view(latest["run_id"]) if latest else None,budget_rules=rules["budgets"])
    app.add_url_rule("/",view_func=lambda:page(4))
    app.add_url_rule("/daily",endpoint="daily_report",view_func=daily)
    for index,(slug,name) in enumerate(MODULES):
        app.add_url_rule("/"+slug,endpoint="page_"+slug,view_func=lambda index=index:page(index))
