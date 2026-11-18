import hashlib,json,time
from datetime import datetime,timezone
from app.budgets import identity_params,budget_meta
from app.config import RULE_VERSION
def digest(raw,params=None):
    return hashlib.sha256(raw+json.dumps(identity_params(params),sort_keys=True,ensure_ascii=False).encode()+RULE_VERSION.encode()).hexdigest()
def manifest(raw,params,started,budget):
    return {"input_sha256":hashlib.sha256(raw).hexdigest(),"rule_version":RULE_VERSION,"parameters":params,"budget":budget_meta(budget),"budget_version":budget["version"],"budget_seconds":budget["seconds"],"generated_at":datetime.now(timezone.utc).isoformat(),"elapsed_ms":round((time.monotonic()-started)*1000,2)}
