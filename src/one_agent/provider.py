"""Local mock provider: outputs are untrusted and never become eligibility evidence."""
import copy
import json
from pathlib import Path
from typing import Protocol
from .budget import BudgetExceeded
from .ingestion import records

class ModelProvider(Protocol):
    def generate(self,trigger_event_id: str,context: dict,budget): ...

class ModelTimeout(TimeoutError):
    def __init__(self,seconds):
        self.seconds=seconds
        super().__init__(f"Injected timeout ({seconds} seconds); emulated without wall-clock sleep")

class MockProvider:
    def __init__(self,pack):
        self.faults={r["trigger_event_id"]:r for r in records(Path(pack)/"replay/model_faults.jsonl")}

    def generate(self,trigger_event_id,context,budget):
        def invoke():
            fault=self.faults.get(trigger_event_id)
            if fault:
                if fault["fault"]=="timeout":
                    raise ModelTimeout(fault["seconds"])
                return copy.deepcopy(fault["model_output"])
            return {"proposal":"NO_ACTION","reason":"Mock provider does not establish eligibility"}
        return budget.call("model","mock.generate",invoke)

def consult(provider,trigger_event_id,context,budget,fallback):
    raw=None
    try:
        raw=provider.generate(trigger_event_id,context,budget)
        parsed=json.loads(raw) if isinstance(raw,str) else raw
        if not isinstance(parsed,dict):
            raise ValueError("Model output must be an object")
        reason="Untrusted model advice discarded; deterministic proposal used"
    except BudgetExceeded as exc:
        return {"proposal":{"type":"NO_ACTION","reason":str(exc)},"model_output":raw,
                "source":"budget_abstention","trusted":False,"budget":budget.snapshot()}
    except (TimeoutError,ValueError,TypeError) as exc:
        reason=str(exc)
    return {"proposal":fallback(),"model_output":raw,"source":"deterministic_fallback",
            "reason":reason,"trusted":False,"budget":budget.snapshot()}
