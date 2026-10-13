"""Eligibility only: no goal selection, interventions or outcome claims."""
import json
from datetime import timedelta
from .schemas import Eligibility, IST, timestamp

DISABLED = {"G06":"Recently lapsed has no defined interval",
            "G10":"Meaningful engagement has no measurable definition",
            "G11":"tv_app_open is not a supplied observable signal"}

def evaluate(goal, facts, events, as_of, *, history_start=None, history_end=None,
             catalogue=(), episodes=()):
    gid = goal["goal_id"]
    if gid in DISABLED:
        return Eligibility(gid,"unknown",DISABLED[gid],disabled=True)
    now = timestamp(as_of)
    events = [e for e in events if timestamp(e["received_at"]) <= now]
    rule = goal["eligibility"]
    checks = []
    evidence = []
    def add(status,reason):
        checks.append((status,reason))
    def covered(days):
        return bool(history_start and history_end and timestamp(history_start) <= now-timedelta(days=days)
                    and timestamp(history_end) >= now)
    if "signed_up_within_days" in rule:
        f = facts.get("signup_at")
        if not f or f.status=="unknown":
            add("unknown","Signup time is unknown")
        else:
            age = now-timestamp(f.value)
            add("eligible" if timedelta(0)<=age<=timedelta(days=rule["signed_up_within_days"]) else "ineligible",
                "Signup age checked against configured window using server evidence")
            evidence.extend(f.sources)
    if "requires_no_prior_event" in rule:
        matches = [e for e in events if e["event"]==rule["requires_no_prior_event"]]
        add("ineligible" if matches else "unknown",
            "Prior event observed" if matches else "Finite history cannot establish lifetime absence")
        evidence.extend("event:"+e["event_id"] for e in matches)
    if "subscription_status" in rule:
        f = facts.get("subscription_status")
        if not f or f.status=="unknown":
            add("unknown","Subscription status is uncertain")
        else:
            add("eligible" if f.value in rule["subscription_status"] else "ineligible","Configured subscription status checked")
            evidence.extend(f.sources)
    if gid == "G07":
        cat = {r["title_id"]:r for r in catalogue}
        groups = {}
        for e in events:
            title = cat.get(e["properties"].get("title_id"))
            if title and title["content_type"] in ("show","micro_drama"):
                groups.setdefault(title["content_slug"],[]).append(e)
        candidates = []
        for slug, history in groups.items():
            plays = [e for e in history if e["event"]=="play_started"]
            remaining = {r["episode_id"] for r in episodes if r["content_slug"]==slug} - {
                e["properties"].get("episode_id") for e in history if e["event"]=="episode_completed"}
            if plays and remaining and now-max(timestamp(e["received_at"]) for e in plays)>=timedelta(days=3):
                candidates.append(slug)
        # Unseen earlier completions and device-time ambiguity prevent proving unfinished state.
        add("unknown","Potential unfinished series: "+",".join(sorted(candidates)) if candidates else
            "No provable unfinished series; finite history cannot establish unwatched episodes")
    if gid in ("G09","G12"):
        kind = "play_started" if gid=="G09" else "app_open"
        window = [e for e in events if e["event"]==kind and
                  now-timedelta(days=14)<=timestamp(e["received_at"])<now]
        evidence.extend("event:"+e["event_id"] for e in window)
        count = len({timestamp(e["received_at"]).astimezone(IST).date() for e in window})
        violated = count>1 if gid=="G09" else bool(window)
        add("ineligible" if violated else "eligible" if covered(14) else "unknown",
            "Prior 14-day receipt-time window checked; eligibility requires complete coverage")
    if not checks:
        return Eligibility(gid,"unknown","Unsupported eligibility rule")
    status = "ineligible" if any(s=="ineligible" for s,_ in checks) else "unknown" if any(s=="unknown" for s,_ in checks) else "eligible"
    return Eligibility(gid,status,"; ".join(r for _,r in checks),tuple(sorted(set(evidence))))

def evaluate_viewer(store, user_id, as_of, facts):
    events = store.user_events(user_id,as_of)
    metadata = dict(store.connection.execute("SELECT key,value FROM metadata"))
    catalogue = [json.loads(r[0]) for r in store.connection.execute("SELECT payload FROM catalogue")]
    episodes = getattr(store,"episode_cache",None) or [json.loads(r[0]) for r in store.connection.execute("SELECT payload FROM episodes")]
    rules = store.connection.execute("SELECT payload FROM goal_rules WHERE version=(SELECT MAX(version) FROM goal_rules) ORDER BY goal_id")
    return [evaluate(json.loads(r[0]),facts,events,as_of,history_start=metadata.get("history_start"),
                     history_end=metadata.get("history_end"),catalogue=catalogue,episodes=episodes) for r in rules]
