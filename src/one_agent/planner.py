"""Local deterministic goal selection and intervention planning."""
import hashlib
import json
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from .evidence import resolve
from .goals import evaluate_viewer, evaluate
from .ingestion import load_goals, records
from .interventions import proposals, no_action
from .schemas import timestamp
from .store import encode

# Implementation priority, not a claim of measured uplift: onboarding, conversion, return, habit, discovery.
PRIORITY = ("G01","G02","G03","G04","G05","G07","G12","G09","G08")
CHANNELS = ("auto","home_page","push","whatsapp","in_app_message","no_action")

def arm_for(pack,user_id):
    matches = [r["arm"] for r in records(Path(pack)/"replay/arms.csv") if r["user_id"]==user_id]
    return matches[0] if len(matches)==1 and matches[0] in ("agent","holdout") else "unknown"

def plan(store, pack, user_id, as_of, *, channel="auto", request_id=None, trigger_event_id=None):
    if channel not in CHANNELS:
        raise ValueError("Unsupported channel")
    at = timestamp(as_of).isoformat()
    pack = Path(pack)
    config = load_goals(pack)
    if getattr(store,"replay_mode",False):
        from .runtime import effective_goals
        config = effective_goals(store,pack)
    with (pack/"config/interventions.json").open(encoding="utf-8") as f:
        intervention_config = json.load(f)
    policy = (pack/"config/messaging_policy.md").read_text(encoding="utf-8")
    arm = arm_for(pack,user_id)
    rules = {g["goal_id"]:g for g in config["goals"]}
    persisted_rules = {r["goal_id"]:json.loads(r["payload"]) for r in store.connection.execute(
        "SELECT goal_id,payload FROM goal_rules WHERE version=?",(config["version"],))}
    if persisted_rules != rules:
        raise ValueError("Persisted goal rules differ from supplied config; ingest this pack first")
    stored_version = store.connection.execute("SELECT MAX(version) FROM goal_rules").fetchone()[0]
    if stored_version != config["version"]:
        raise ValueError("Supplied config is not the latest persisted goal rule version")
    facts = resolve(store,user_id,at)
    store.save_facts(user_id,at,facts)
    # Read back the persisted fact snapshot used by this decision.
    fact_audit = {r["name"]:json.loads(r["payload"]) for r in store.connection.execute(
        "SELECT name,payload FROM facts WHERE user_id=? AND as_of=?",(user_id,at))}
    for f in fact_audit.values():
        f["age_seconds"] = max(0,(timestamp(at)-timestamp(f["observed_at"])).total_seconds()) if f["observed_at"] else None
    events = store.user_events(user_id,at)
    conflicts = [json.loads(r["payload"]) for r in store.connection.execute(
        "SELECT as_of,payload FROM conflicts WHERE user_id=? ORDER BY as_of,name,payload",(user_id,))
        if timestamp(r["as_of"]) <= timestamp(at)]
    catalogue = [json.loads(r[0]) for r in store.connection.execute("SELECT payload FROM catalogue ORDER BY title_id")]
    # Inspect only withdrawals already known at this as-of time; do not execute or replay controls.
    controls = [r for r in (getattr(store,"applied_controls",None) if getattr(store,"replay_mode",False) else records(pack/"replay/control_events.jsonl"))
                if r["type"]=="title_withdrawn" and timestamp(r["at"])<=timestamp(at)]
    withdrawn = sorted({r["title_id"] for r in controls})
    eligibility = evaluate_viewer(store,user_id,at,facts)
    evidence_snapshot = {"user_id":user_id,"as_of":at,"request_id":request_id,"channel":channel,
        "facts":fact_audit,"history":events,"conflicts":conflicts,"catalogue":catalogue,
        "goals":config,"interventions":intervention_config,"policy":policy,"arm":arm,"withdrawn":controls,
        "eligibility":[asdict(e) for e in eligibility]}
    identity = "P-"+hashlib.sha256(encode(evidence_snapshot).encode()).hexdigest()
    previous = store.connection.execute("SELECT payload FROM decisions WHERE decision_id=?",(identity,)).fetchone()
    if previous:
        return json.loads(previous[0])
    active = store.active_goal_plan(user_id)
    if active and timestamp(at)<timestamp(active["started_at"]):
        raise ValueError("Cannot revise a goal using an earlier planning time; use a separate database for historical inspection")
    by_id = {e.goal_id:e for e in eligibility}
    continuation = None
    chosen, reason, transition = None, "", "none"
    if arm != "agent":
        reason = "Randomized holdout: no agent intervention" if arm=="holdout" else "Missing or ambiguous arm assignment"
        transition = "cancel" if active else "none"
    elif active:
        result = by_id.get(active["goal_id"])
        # A signup acquisition window is evaluated at commitment, not reset every visit.
        if active["goal_id"]=="G03" and result and result.status=="ineligible":
            acquisition = evaluate(rules["G03"],facts,events,active["started_at"])
            if acquisition.status=="eligible":
                result = acquisition
                continuation = asdict(acquisition)
        if timestamp(active["deadline"]) <= timestamp(at):
            reason,transition = "Goal deadline elapsed; outcome remains inconclusive in Phase 2","expire"
        elif not result or result.disabled or result.status=="ineligible":
            reason,transition = "New evidence invalidates the existing goal eligibility","cancel"
        else:
            chosen,transition = rules[active["goal_id"]],"preserve"
            reason = "Preserve active goal and original deadline" if result.status=="eligible" else "Preserve active goal but pause interventions while eligibility is unknown"
    if arm=="agent" and chosen is None:
        chosen = next((rules[g] for g in PRIORITY if g in by_id and by_id[g].status=="eligible"
                       and not by_id[g].disabled and rules[g]["success"].get("event")),None)
        if chosen:
            reason += ("; " if reason else "")+"Select first supported measurable goal in documented deterministic priority"
        elif not reason:
            reason = "No measurable goal has proven eligibility"
    started_at = active["started_at"] if transition=="preserve" else at
    deadline = active["deadline"] if transition=="preserve" else (
        (timestamp(at)+timedelta(hours=chosen["success"]["window_hours"])).isoformat() if chosen else None)
    goal = None
    if chosen:
        goal = {"goal_id":chosen["goal_id"],"name":chosen["name"],"rule_version":config["version"],
            "started_at":started_at,"deadline":deadline,"success":chosen["success"],
            "evidence":[*by_id[chosen["goal_id"]].evidence,"config/goals.json:"+chosen["goal_id"]],
            "selection_reason":reason}
    effective_status = continuation["status"] if continuation else (by_id[chosen["goal_id"]].status if chosen else None)
    if arm!="agent" or not goal:
        options = [no_action(reason)]
    elif effective_status!="eligible":
        options = [no_action("Existing goal retained; current eligibility is unknown")]
    else:
        options = proposals(chosen,facts,catalogue,events,intervention_config,at,
                            withdrawn=withdrawn,goal_started_at=started_at)
    if channel=="no_action":
        selected = no_action("Caller explicitly requested abstention")
    elif channel=="auto":
        selected = next((p for p in options if p["status"]=="PROPOSED"), options[0])
    else:
        selected = next((p for p in options if p["type"]==channel and p["status"]=="PROPOSED"),None)
        if selected is None:
            blocked = next((p["reason"] for p in options if p["type"]==channel),options[0]["reason"])
            selected = no_action(blocked)
    if selected["status"]=="BLOCKED":
        selected = no_action(selected["reason"])
    confidence = {"level":"evidence_supported" if goal and effective_status=="eligible" else "insufficient",
        "reason":"Eligibility follows cited pack rules; latest received settings choose dialect. This is not a calibrated probability or predicted treatment effect.",
        "limitations":["Facts may be stale; delivery is not assumed","Lifetime history remains incomplete",
                       "Independent verification has not run"]}
    payload = {"decision_id":identity,"user_id":user_id,"as_of":at,"arm":arm,
        "status":"PROPOSED" if selected["status"]=="PROPOSED" else "NO_ACTION",
        "published":False,"goal":goal,"selection_reason":reason,
        "eligibility":[asdict(e) for e in eligibility],"facts":fact_audit,"conflicts":conflicts,
        "dialect":fact_audit["app_dialect"],"proposal":selected,"alternatives":options,
        "evidence":sorted(set((goal["evidence"] if goal else [])+selected["evidence"]+
            ["replay/arms.csv:"+user_id,"config/messaging_policy.md"]+
            ["replay/control_events.jsonl:title_withdrawn:"+r["title_id"] for r in controls])),
        "assumptions":["Receipt-time chronology is used; device clocks are untrusted",
                       "Stable priority is an engineering policy, not measured uplift",
                       "Availability and policy must be checked again before any publication"],
        "confidence":confidence,"plan_transition":transition,"continuation_eligibility":continuation,
        "no_action_reason":selected["reason"] if selected["type"]=="NO_ACTION" else None}
    if trigger_event_id is not None:
        payload["trigger_event_id"] = trigger_event_id
    return store.persist_planning(payload,active)
