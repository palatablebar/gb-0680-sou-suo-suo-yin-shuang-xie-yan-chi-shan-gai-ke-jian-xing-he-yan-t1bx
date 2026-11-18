"""预算规则切换的书面裁决，供接口与日报引用。"""
from app.budgets import all_budgets, current_budget

RULING={
    "code":"KEEP_SEALED",
    "decided_at":"2026-11-18T12:00:00+00:00",
    "trigger":"预算阈值由 120s 收紧到 90s",
    "revoked_batches":[],
    "recomputed_batches":[],
    "policy":[
        "已复核的上午批次全部保留原 120s 口径，不作废、不追溯重算。",
        "待复核的旧预算批次同样不就地改写，避免同一批次出现两个结论。",
        "午间及以后新建批次默认按 90s 计算，并写入实际预算版本。",
        "历史批次以只读影子评估展示新预算结论，仅作对照，不改变封存结论与复核状态。",
        "同一输入重跑复用原批次：不新增批次，不覆盖封存结论和证据。",
    ],
    "attribution":"同一输入摘要下，新旧口径的通过结论或差异数变化一律归因于预算版本；输入变化才归因于文档。",
}


def transition():
    return {"ruling":RULING,"budgets":all_budgets(),"current":current_budget()}
