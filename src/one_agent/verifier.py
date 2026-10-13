"""Independent safety checks and local approvals. No publisher exists here."""
import hashlib
import json
import sqlite3
import uuid
from datetime import timedelta
from pathlib import Path
from .budget import Budget, BudgetExceeded
from .evidence import resolve
from .goals import evaluate
from .ingestion import load_goals, records
from .schemas import IST, timestamp
from .store import encode

FIXED_COPY = {
    "push":{"title":"Pick something to watch","body":"Explore a title in your app dialect."},
    "in_app_message":{"title":"Explore your next title","body":"Choose a title to watch."},
}

def _authorities(pack, at, store=None):
    pack=Path(pack)
    def read(name):
        return json.loads((pack/name).read_text(encoding="utf-8"))
    policy=(pack/"config/messaging_policy.md").read_text(encoding="utf-8")
    from .runtime import effective_goals
    return {"goals":effective_goals(store,pack) if getattr(store,"replay_mode",False) else load_goals(pack),"interventions":read("config/interventions.json"),
        "pricing":read("config/pricing.json"),"policy":policy,
        "arms":list(records(pack/"replay/arms.csv")),
        "controls":[r for r in (store.applied_controls if getattr(store,"replay_mode",False) else records(pack/"replay/control_events.jsonl")) if timestamp(r["at"])<=timestamp(at)]}

def _context(store,user,at,decision_id):
    return {"facts":resolve(store,user,at),"events":store.user_events(user,at),
        "profiles":store.user_profiles(user,at),"active":store.active_goal_plan(user),
        "catalogue":{r["title_id"]:json.loads(r["payload"]) for r in store.connection.execute("SELECT * FROM catalogue")},
        "episodes":getattr(store,"episode_cache",None) or [json.loads(r[0]) for r in store.connection.execute("SELECT payload FROM episodes")],
        "rules":{(r["version"],r["goal_id"]):json.loads(r["payload"]) for r in store.connection.execute("SELECT * FROM goal_rules")},
        "metadata":dict(store.connection.execute("SELECT key,value FROM metadata")),
        "triggers":[json.loads(r[0]) for r in store.connection.execute("SELECT payload FROM triggers WHERE user_id=?",(user,))],
        "decision":store.connection.execute("SELECT * FROM decisions WHERE decision_id=?",(decision_id,)).fetchone()}

def _consent(context,field,channel):
    optouts=[e for e in context["events"] if e["event"]=="notification_opt_out" and e["properties"].get("channel")==channel]
    if optouts:
        return False,["event:"+e["event_id"] for e in optouts],"Observed opt-out overrides snapshot"
    versions=[(ref,p) for ref,p in context["profiles"] if p.get(field) in ("true","false")]
    if not versions:
        return False,[],"No authoritative consent record"
    latest=max(timestamp(p["updated_at"]) for _,p in versions)
    versions=[(ref,p) for ref,p in versions if timestamp(p["updated_at"])==latest]
    return (all(p[field]=="true" for _,p in versions),[ref for ref,_ in versions],
            "Latest supplied consent field, checked independently of planner facts")

def verify(store,pack,decision,as_of,*,budget=None):
    """A transaction protects authoritative SQLite reads, duplicate checks and reservations."""
    budget=budget or Budget()
    checks=[]
    user=decision.get("user_id") if isinstance(decision,dict) else None
    did=decision.get("decision_id") if isinstance(decision,dict) else None
    vid="V-"+uuid.uuid4().hex
    at=timestamp(as_of).isoformat()
    action=None
    approval_id=None
    def check(name,passed,reason,evidence=(),unknown=False):
        checks.append({"name":name,"status":"PASSED" if passed else "UNKNOWN" if unknown else "FAILED",
                       "reason":reason,"evidence":list(evidence)})
        return passed
    def bad():
        return any(c["status"]!="PASSED" for c in checks)
    try:
        authority=budget.call("tool","load_authoritative_config_and_policy",_authorities,pack,at,store)
        with store.connection:
            store.connection.execute("BEGIN IMMEDIATE")
            context=budget.call("tool","read_authoritative_viewer_and_catalogue",_context,store,user,at,did)
            registered=context["decision"]
            check("decision_identity",bool(registered and registered["user_id"]==user),
                  "Decision must belong to this viewer in SQLite",["decisions:"+str(did)])
            option=decision.get("proposal",{})
            kind=option.get("type")
            action=option.get("payload")
            matches=[r["arm"] for r in authority["arms"] if r["user_id"]==user]
            agent=len(matches)==1 and matches[0]=="agent"
            check("holdout",kind=="NO_ACTION" or agent,
                  "Only a uniquely assigned agent-arm viewer can receive approval",
                  ["replay/arms.csv:"+str(user),"config/messaging_policy.md:5"])
            if kind=="NO_ACTION":
                check("no_action",action is None,
                      "Randomized holdout: no action may be approved" if matches==["holdout"] else "Explicit abstention contains no publishable action",
                      ["replay/arms.csv:"+str(user),"config/messaging_policy.md:5"])
            else:
                _validate(context,authority,decision,kind,action,at,check)
            # Claim verification/persistence budget before any approval or reservation is inserted.
            budget.charge("tool","commit_verification_and_reservation")
            verdict="REJECTED" if any(c["status"]=="FAILED" for c in checks) else (
                "ABSTAINED" if bad() or kind=="NO_ACTION" else "APPROVED")
            if verdict=="APPROVED":
                proposed=timestamp(action["proposed_at"])
                send=timestamp(action.get("send_at",at))
                effective=max(timestamp(at),send)
                active=context["active"]
                expires=min(timestamp(active["deadline"]),proposed+timedelta(minutes=authority["interventions"]["home_page"]["ttl_minutes"])) if kind=="home_page" else timestamp(active["deadline"])
                if action.get("expires_at"):
                    expires=min(expires,timestamp(action["expires_at"]))
                action_key=hashlib.sha256(encode({"user":user,"type":kind,"action":action}).encode()).hexdigest()
                trigger=registered["trigger_event_id"] or "inspection:"+did
                old=store.connection.execute("SELECT * FROM approvals WHERE decision_id=? OR action_key=? OR (user_id=? AND trigger_key=?)",
                    (did,action_key,user,trigger)).fetchall()
                external=decision.get("action_id")
                if external:
                    old+=store.connection.execute("SELECT * FROM approvals WHERE external_action_id=?",(external,)).fetchall()
                same=next((r for r in old if r["decision_id"]==did and r["action_key"]==action_key and r["status"]=="approved"),None)
                if old and not (same and all(r["approval_id"]==same["approval_id"] for r in old)):
                    check("duplicate_action",False,"Decision, trigger or action already has a different or revoked approval",
                          ["approvals:"+r["approval_id"] for r in old])
                    verdict="REJECTED"
                    # Report cap violations independently, even when action deduplication also fails.
                    scope="outbound" if kind in ("push","whatsapp") else "in_app" if kind=="in_app_message" else None
                    if scope:
                        day=effective.astimezone(IST).date().isoformat()
                        limit=1 if scope=="outbound" else authority["interventions"]["in_app_message"]["max_per_day"]
                        channels=("push","whatsapp") if scope=="outbound" else ("in_app_message",)
                        delivered=[e for e in context["events"] if e["event"]=="message_delivered"
                            and e["properties"].get("channel") in channels
                            and timestamp(e["received_at"]).astimezone(IST).date().isoformat()==day]
                        reserved=store.connection.execute(
                            "SELECT approval_id FROM message_reservations WHERE user_id=? AND ist_day=? AND scope=? AND status='reserved'",
                            (user,day,scope)).fetchall()
                        check("frequency_cap",len(delivered)+len(reserved)<limit,
                              "IST-day cap includes observed deliveries and durable reservations",
                              ["event:"+e["event_id"] for e in delivered]+["approvals:"+r[0] for r in reserved])
                elif same:
                    approval_id=same["approval_id"]
                    check("idempotency",True,"Existing approval reused; no new reservation",["approvals:"+approval_id])
                else:
                    scope="outbound" if kind in ("push","whatsapp") else "in_app" if kind=="in_app_message" else None
                    day=effective.astimezone(IST).date().isoformat()
                    limit=1 if scope=="outbound" else authority["interventions"]["in_app_message"]["max_per_day"]
                    delivered=[e for e in context["events"] if e["event"]=="message_delivered"
                        and e["properties"].get("channel") in (("push","whatsapp") if scope=="outbound" else ("in_app_message",))
                        and timestamp(e["received_at"]).astimezone(IST).date().isoformat()==day] if scope else []
                    reserved=store.connection.execute("SELECT slot,approval_id FROM message_reservations WHERE user_id=? AND ist_day=? AND scope=? AND status='reserved'",
                                                     (user,day,scope)).fetchall() if scope else []
                    if scope and len(delivered)+len(reserved)>=limit:
                        check("frequency_cap",False,"IST-day cap consumed by observed delivery or durable reservation",
                              ["event:"+e["event_id"] for e in delivered]+["approvals:"+r["approval_id"] for r in reserved])
                        verdict="REJECTED"
                    else:
                        approval_id="A-"+action_key
                        approved={"action":action,"published":False,"publishable":False,
                                  "requires_reverification_before_publication":True,
                                  "not_before":effective.isoformat(),"expires_at":expires.isoformat()}
                        store.connection.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,'approved',?)",
                            (approval_id,did,user,trigger,action_key,external,at,expires.isoformat(),encode(approved)))
                        if scope:
                            occupied={r["slot"] for r in reserved}
                            slot=next(n for n in range(limit) if n not in occupied)
                            store.connection.execute("INSERT INTO message_reservations VALUES (?,?,?,?,?,?,'reserved')",
                                ("R-"+action_key,approval_id,user,day,scope,slot))
                        check("reservation",True,"Local approval recorded; no action published",["approvals:"+approval_id])
            if verdict!="APPROVED" and did:
                existing=store.connection.execute("SELECT approval_id FROM approvals WHERE decision_id=? AND status='approved'",(did,)).fetchall()
                for row in existing:
                    store.connection.execute("UPDATE approvals SET status='revoked' WHERE approval_id=?",(row[0],))
                    if not getattr(store,"is_published",lambda _:False)(row[0]):
                        store.connection.execute("UPDATE message_reservations SET status='released' WHERE approval_id=?",(row[0],))
            result=_report(vid,did,user,at,verdict,checks,approval_id,budget)
            _record(store,result)
            return result
    except (BudgetExceeded,sqlite3.Error,OSError,ValueError,TypeError,KeyError,AttributeError,StopIteration) as exc:
        check("safe_failure",False,f"{type(exc).__name__}: {exc}",unknown=isinstance(exc,(BudgetExceeded,sqlite3.Error,OSError)))
        verdict="REJECTED" if any(c["status"]=="FAILED" for c in checks) else "ABSTAINED"
        result=_report(vid,did,user,at,verdict,checks,None,budget)
        # Audit-only recovery is not an action/tool retry. Never reserve on a failed verification.
        try:
            with store.connection:
                _record(store,result)
        except sqlite3.Error:
            result["audit_persisted"]=False
        return result

def _report(vid,did,user,at,verdict,checks,approval,budget):
    return {"verification_id":vid,"decision_id":did,"user_id":user,"verified_at":at,"verdict":verdict,
        "approval_id":approval,"published":False,"publishable":False,"checks":checks,
        "reasons":([c["reason"] for c in checks if c["status"]!="PASSED"] or
                   ([c["reason"] for c in checks if c["name"]=="no_action"] if verdict=="ABSTAINED" else [])),
        "evidence":sorted({ref for c in checks for ref in c["evidence"]}),"budget":budget.snapshot()}

def _record(store,result):
    store.connection.execute("INSERT INTO verifications VALUES (?,?,?,?,?,?)",
        (result["verification_id"],result["decision_id"],result["user_id"],result["verified_at"],
         result["verdict"],encode(result)))
    for n,entry in enumerate(result["budget"]["calls"]):
        store.connection.execute("INSERT INTO call_audits VALUES (?,?,?)",(result["verification_id"],n,encode(entry)))

def _validate(context,authority,decision,kind,action,at,check):
    config=authority["interventions"]
    if not check("action_schema",kind in ("home_page","push","whatsapp","in_app_message") and isinstance(action,dict),
                 "Action must have a supported channel and object payload",["config/interventions.json"]):
        return
    check("channel",action.get("type")==kind,"Envelope and payload channel must agree")
    allowed={"type","proposed_at","expires_at","language"}
    allowed |= {"dialect","hero_title_id","rows","ttl_minutes"} if kind=="home_page" else {"send_at","title_id","text","deeplink","template_id","variables"}
    check("fields",not (action.keys()-allowed),"Unknown action fields cannot bypass the publishing contract")
    goal=decision.get("goal") or {}
    active=context["active"]
    gid=goal.get("goal_id")
    rule=next((r for r in authority["goals"]["goals"] if r["goal_id"]==gid),None)
    version=authority["goals"]["version"]
    valid_goal=bool(active and rule and active["goal_id"]==gid and goal.get("rule_version")==active["rule_version"]==version)
    check("active_goal",valid_goal,"Goal ID and rule version must match the open SQLite goal",["goals:"+str(gid)])
    if not valid_goal:
        return
    check("latest_rule_version",max((v for v,g in context["rules"]),default=None)==version,
          "Actual config must be the latest persisted rule version")
    check("goal_rule",context["rules"].get((version,gid))==rule,"SQLite rules must match actual config",["config/goals.json:"+gid])
    started=timestamp(active["started_at"])
    deadline=timestamp(active["deadline"])
    check("goal_window",timestamp(goal["started_at"])==started and timestamp(goal["deadline"])==deadline
          and deadline==started+timedelta(hours=rule["success"]["window_hours"]) and started<=timestamp(at)<deadline,
          "Original goal window must match config and remain open")
    success=rule["success"]
    for control in authority["controls"]:
        if control["type"]=="goal_rule_corrected" and control["goal_id"]==gid:
            success={**success,**control["new_success"]}
    check("success_signal",goal.get("success")==success,"Success definition must include every known correction",
          ["config/goals.json:"+gid,"replay/control_events.jsonl"])
    now=timestamp(at)
    proposed=timestamp(action["proposed_at"])
    send=timestamp(action.get("send_at",at))
    if decision.get("trigger_event_id") and send==timestamp(decision["as_of"]):
        send=timestamp(at)  # Immediate dispatch; proposal identity stays immutable.
    check("schedule",timestamp(decision["as_of"])<=proposed<=now and send>=now and send<deadline,
          "No backdated send, future page proposal, or scheduling outside goal window")
    if kind=="home_page":
        check("page_expiration",proposed+timedelta(minutes=config[kind]["ttl_minutes"])>now
              and action.get("ttl_minutes")==config[kind]["ttl_minutes"],"Home page must be unexpired and use configured TTL")
    if action.get("expires_at"):
        check("expiration",now<timestamp(action["expires_at"])<=deadline and send<timestamp(action["expires_at"]),
              "Explicit expiration must be after action time and within goal deadline")
    evaluation=evaluate(rule,context["facts"],context["events"],at,
        history_start=context["metadata"].get("history_start"),history_end=context["metadata"].get("history_end"),
        catalogue=context["catalogue"].values(),episodes=context["episodes"])
    if gid=="G03" and evaluation.status=="ineligible":
        evaluation=evaluate(rule,context["facts"],context["events"],active["started_at"])
    check("eligibility",not evaluation.disabled and evaluation.status=="eligible",evaluation.reason,evaluation.evidence,
          unknown=evaluation.status=="unknown")
    facts=context["facts"]
    dialect=facts["app_dialect"]
    language=facts["app_language"]
    check("current_dialect",dialect.status=="known" and (kind!="home_page" or action.get("dialect")==dialect.value),
          "Use authoritative latest received app dialect",dialect.sources)
    check("current_language",language.status=="known" and (not action.get("language") or action["language"]==language.value),
          "Language must agree with latest received settings",language.sources,unknown=language.status=="unknown")
    ids=[]
    if kind=="home_page":
        rows=action.get("rows")
        check("hero",isinstance(action.get("hero_title_id"),str) and config[kind]["hero"]["max_titles"]>=1,
              "Exactly one scalar hero ID is supported")
        ids=[action.get("hero_title_id")]
        if not check("rows",isinstance(rows,list) and len(rows)<=config[kind]["rows"]["max_rows"],"Row count must fit configuration"):
            rows=[]
        for index,row in enumerate(rows):
            rule_rows=config[kind]["rows"]
            okay=isinstance(row,dict) and row.get("row_type") in rule_rows["row_types"] and isinstance(row.get("title_ids"),list)
            check(f"row_{index}_schema",okay,"Row must use configured type and title-ID list")
            if okay:
                check(f"row_{index}_size",rule_rows["min_titles_per_row"]<=len(row["title_ids"])<=rule_rows["max_titles_per_row"],
                      "Row title count must fit configured bounds")
                ids.extend(row["title_ids"])
    else:
        ids=[action.get("title_id")]
    titles=[context["catalogue"].get(t) for t in ids if isinstance(t,str)]
    check("catalogue_identity",bool(ids) and len(titles)==len(ids) and all(titles),"Every content reference must exist in SQLite",
          ["catalogue:"+str(t) for t in ids])
    valid=[t for t in titles if t]
    withdrawn={r["title_id"] for r in authority["controls"] if r["type"]=="title_withdrawn"}
    action_time=send if kind in ("push","whatsapp","in_app_message") else now
    for title in valid:
        ref=["catalogue:"+title["title_id"]]
        check("title_dialect:"+title["title_id"],title["dialect"]==dialect.value,"Title must match current app dialect",ref)
        check("title_language:"+title["title_id"],title.get("language")==language.value,"Title variant must match current app language",ref)
        check("availability:"+title["title_id"],title["title_id"] not in withdrawn and timestamp(title["available_from"])<=action_time
            and (not title.get("available_until") or action_time<timestamp(title["available_until"])),
            "Title must be available and not withdrawn at proposed action time",ref+["replay/control_events.jsonl"])
        if gid=="G08":
            days=(started.date()-timestamp(title["release_date"]+"T00:00:00Z").date()).days
            check("recent_release:"+title["title_id"],0<=days<=30,"G08 title must satisfy release interval",ref)
    check("content_slug_deduplication",len({t["content_slug"] for t in valid})==len(ids),
          "Same content_slug cannot appear twice in an action")
    registered=context["decision"]
    if registered and registered["trigger_event_id"]:
        check("trigger_identity",decision.get("trigger_event_id",registered["trigger_event_id"])==registered["trigger_event_id"],
              "Trigger identity must match SQLite decision")
        trigger_rows=context.get("triggers",[])
        match=next((r for r in trigger_rows if r["event_id"]==registered["trigger_event_id"] and r["user_id"]==decision["user_id"]),None)
        check("trigger",bool(match and timestamp(match["deliver_at"])<=now),"Trigger must be known and belong to viewer")
        if match:
            age=(now-timestamp(match["deliver_at"])).total_seconds()
            check("latency",age<=60,"Verification must fit 60-second decision budget; over 300 seconds is a failure",
                  ["trigger:"+match["event_id"]])
    if kind in ("push","whatsapp"):
        okay,refs,reason=_consent(context,config[kind]["consent_field"],kind)
        check("consent",okay,reason,refs+["config/messaging_policy.md:1"])
        local=send.astimezone(IST)
        minute=local.hour*60+local.minute
        start,end=[int(s[:2])*60+int(s[3:]) for s in config[kind]["quiet_hours_ist"]]
        quiet=(minute>=start or minute<end) if start>end else start<=minute<end
        check("quiet_hours",not quiet,"No outbound messages between 22:00 and 08:00 IST",["config/messaging_policy.md:2"])
    if kind in ("push","in_app_message"):
        text=action.get("text")
        check("honest_copy",text==FIXED_COPY[kind],"Only independently substantiated fixed copy is supported; arbitrary claims are rejected",
              ["config/messaging_policy.md:4"])
        if kind=="push" and isinstance(text,dict):
            copy=config[kind]["copy"]
            check("copy_limits",all(isinstance(text.get(k),str) and len(text[k])<=copy[k+"_max_chars"] for k in ("title","body")),
                  "Push title/body lengths must fit configuration")
            check("forbidden_copy",not any(p.casefold() in encode(text).casefold() for p in copy["forbidden_phrases"]),
                  "Forbidden urgency and guarantee phrases are rejected")
        expected=config["push"]["deeplink_format"].replace("<title_id>",str(action.get("title_id")))
        check("deeplink",action.get("deeplink")==expected,"Deeplink must reference exactly the proposed title")
    if kind=="whatsapp":
        template=next((t for t in config[kind]["approved_templates"] if t["template_id"]==action.get("template_id")),None)
        check("approved_template",bool(template),"WhatsApp template must be approved",["config/interventions.json:whatsapp"])
        if template:
            check("template_language",template["language"]==language.value,"WhatsApp template language must match settings")
            expected={"title_name":valid[0]["title"],"dialect_name":valid[0]["dialect"]} if valid else {}
            check("template_variables",template["template_id"]=="wa_recommend_title_v1"
                  and set(template["variables"])==set(expected) and action.get("variables")==expected,
                  "Variables must come from authoritative catalogue; new-episode and ending-trial claims require unsupported freshness evidence")
        check("template_only",not action.get("text") and not action.get("deeplink"),"WhatsApp accepts approved template variables only")

def verify_existing(store,pack,decision_id,as_of,*,budget=None):
    """CLI entry point that counts retrieval of the persisted proposal."""
    budget=budget or Budget()
    try:
        row=budget.call("tool","load_persisted_proposal",
            lambda:store.connection.execute("SELECT payload FROM decisions WHERE decision_id=?",(decision_id,)).fetchone())
        if row is None:
            raise ValueError("Decision is not present in SQLite")
        return verify(store,pack,json.loads(row[0]),as_of,budget=budget)
    except (BudgetExceeded,ValueError,sqlite3.Error) as exc:
        checks=[{"name":"proposal_retrieval","status":"UNKNOWN" if isinstance(exc,(BudgetExceeded,sqlite3.Error)) else "FAILED",
                 "reason":str(exc),"evidence":["decisions:"+decision_id]}]
        result=_report("V-"+uuid.uuid4().hex,decision_id,None,timestamp(as_of).isoformat(),
                       "REJECTED" if isinstance(exc,ValueError) else "ABSTAINED",checks,None,budget)
        try:
            with store.connection:
                _record(store,result)
        except sqlite3.Error:
            result["audit_persisted"]=False
        return result
