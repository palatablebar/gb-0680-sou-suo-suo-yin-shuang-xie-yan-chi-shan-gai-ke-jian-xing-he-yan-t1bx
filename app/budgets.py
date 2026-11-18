"""预算规则登记与裁决。

预算不是普通参数：每次阈值调整必须登记为新版本。批次创建时冻结实际
预算版本，之后任何重跑、重算都只能追加对照评估，不得改写已封存结论。

裁决（2026-11-18 午间收紧）：
- 上午按 120s 计算并已复核的批次：全部保留、不作废、不追溯重算。
- 待复核的旧预算批次：同样不就地改写；新预算只作为只读对照评估。
- 午间及以后新建批次：默认按 90s 计算。
- “作废重算”的历史批次集合为空；差异按预算版本逐文档对照。
"""
from app.errors import DomainError
from app.values import number

BUDGETS=[
    {"version":"budget-2026.11.18-am","label":"上午 120s","seconds":"120",
     "effective_from":"2026-11-18T00:00:00+00:00","superseded":True},
    {"version":"budget-2026.11.18-noon","label":"午间 90s","seconds":"90",
     "effective_from":"2026-11-18T12:00:00+00:00","superseded":False},
]
_BY_VERSION={item["version"]:item for item in BUDGETS}
# 预算字段不参与批次身份：同一批输入换预算只追加对照评估，不新增批次。
BUDGET_KEYS={"budget_version","max_delay_seconds"}


def all_budgets():
    return list(BUDGETS)


def current_budget():
    return BUDGETS[-1]


def get_budget(version):
    item=_BY_VERSION.get(version)
    if item is None: raise DomainError("BAD_BUDGET","预算版本未登记")
    return item


def budget_for_seconds(value):
    target=number(value)
    for item in reversed(BUDGETS):
        if number(item["seconds"])==target: return item
    raise DomainError("BAD_BUDGET","预算阈值未登记，请先登记预算版本")


def resolve_budget(params):
    """由请求参数解析预算版本，绝不允许隐式混用两个口径。"""
    params=params or {}
    version=params.get("budget_version")
    explicit=params.get("max_delay_seconds")
    if version is not None:
        item=get_budget(version)
        if explicit is not None and number(explicit)!=number(item["seconds"]):
            raise DomainError("BUDGET_MISMATCH","阈值与预算版本不一致")
        return item
    if explicit is not None:
        return budget_for_seconds(explicit)
    return current_budget()


def budget_of(params):
    """读取已冻结参数中的预算版本。

    未登记秒数按历史批次处理：合成一个 legacy 口径，保证封存结论可展示，
    但不会被当作当前预算。
    """
    params=params or {}
    version=params.get("budget_version")
    if version in _BY_VERSION: return _BY_VERSION[version]
    seconds=params.get("max_delay_seconds")
    if seconds is not None:
        try: return budget_for_seconds(seconds)
        except DomainError:
            value=number(seconds)
            return {"version":f"budget-legacy-{value}s","label":f"历史未登记 {value}s",
                    "seconds":str(value),"effective_from":None,"superseded":True}
    return BUDGETS[0]


def with_budget(params,budget):
    effective=dict(params or {})
    effective["budget_version"]=budget["version"]
    effective["max_delay_seconds"]=budget["seconds"]
    return effective


def identity_params(params):
    """批次身份只取非预算参数；预算变化不得产生新批次。"""
    return {k:v for k,v in (params or {}).items() if k not in BUDGET_KEYS}


def budget_meta(budget):
    return {"version":budget["version"],"label":budget["label"],
            "seconds":budget["seconds"],"effective_from":budget["effective_from"],
            "superseded":bool(budget["superseded"])}
