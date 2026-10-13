"""Deterministic proposals only. No publishing or model execution."""
from collections import Counter
from datetime import timedelta
from .schemas import IST, timestamp

def no_action(reason):
    return {"type":"NO_ACTION","status":"NO_ACTION","publishable":False,"reason":reason,"payload":None,"evidence":[]}

def available(title, at, withdrawn=()):
    now = timestamp(at)
    return (title["title_id"] not in set(withdrawn)
            and timestamp(title["available_from"]) <= now
            and (not title.get("available_until") or now < timestamp(title["available_until"])))

def proposals(goal, facts, catalogue, events, config, at, *, withdrawn=(), goal_started_at=None):
    """Return mutually exclusive options. Phase 3 must independently verify any chosen option."""
    dialect = facts.get("app_dialect")
    if not dialect or dialect.status != "known":
        return [no_action("Current app dialect is unknown")]
    titles = [t for t in catalogue if t["dialect"] == dialect.value and available(t,at,withdrawn)]
    if goal["goal_id"] == "G08":
        start = timestamp(goal_started_at or at).date()
        titles = [t for t in titles if 0 <= (start - timestamp(t["release_date"]+"T00:00:00Z").date()).days <= 30]
    # Stable ranking from observed viewer plays, followed by catalogue ID. Descriptions are never read.
    watched = Counter(e["properties"].get("title_id") for e in events if e["event"]=="play_started")
    titles.sort(key=lambda t: (-watched[t["title_id"]], t["title_id"]))
    unique, seen = [], set()
    for title in titles:
        if title["content_slug"] not in seen:
            unique.append(title)
            seen.add(title["content_slug"])
    if not unique:
        return [no_action("No available content in the current dialect satisfies this goal")]
    hero = unique[0]
    evidence = ["catalogue:"+t["title_id"] for t in unique]
    options = []
    def option(kind,payload,refs,reason):
        return {"type":kind,"status":"PROPOSED","publishable":False,
                "requires_independent_verification":True,"reason":reason,"payload":payload,"evidence":refs}
    page = config["home_page"]
    row_config = page["rows"]
    remaining = unique[1:]
    rows = []
    # Genre grouping does not assert unsupported global popularity or viewing causality.
    genres = sorted({g for t in remaining for g in t.get("genres","").split("|") if g})
    used = {hero["content_slug"]}
    for genre in genres:
        chosen = [t for t in remaining if genre in t.get("genres","").split("|") and t["content_slug"] not in used]
        chosen = chosen[:row_config["max_titles_per_row"]]
        if len(chosen) >= row_config["min_titles_per_row"] and len(rows) < row_config["max_rows"] and "genre" in row_config["row_types"]:
            rows.append({"row_type":"genre","genre":genre,"title_ids":[t["title_id"] for t in chosen]})
            used.update(t["content_slug"] for t in chosen)
    if page["hero"]["max_titles"] >= 1:
        ids = [hero["title_id"]] + [tid for row in rows for tid in row["title_ids"]]
        options.append(option("home_page",{"type":"home_page","proposed_at":at,"dialect":dialect.value,
            "hero_title_id":hero["title_id"],"rows":rows,"ttl_minutes":page["ttl_minutes"]},
            ["catalogue:"+tid for tid in ids]+["config/interventions.json:home_page"],
            "Available dialect-matched content; stable observed-play/ID ranking and genre rows"))
    local = timestamp(at).astimezone(IST)
    sent_today = [e for e in events if e["event"]=="message_delivered"
        and e["properties"].get("channel") in ("push","whatsapp")
        and timestamp(e["received_at"]).astimezone(IST).date()==local.date()]
    for kind in ("push","whatsapp"):
        rule = config[kind]
        consent = facts.get(rule["consent_field"])
        start,end = [tuple(map(int,s.split(":"))) for s in rule["quiet_hours_ist"]]
        minute = local.hour*60+local.minute
        start,end = start[0]*60+start[1], end[0]*60+end[1]
        quiet = (minute >= start or minute < end) if start > end else start <= minute < end
        reason = None
        if not consent or consent.status!="known" or consent.value is not True:
            reason = "Consent is not proven true"
        elif quiet:
            reason = "Proposed time is within IST quiet hours"
        elif sent_today:
            reason = "Observed push/WhatsApp delivery already uses the shared IST-day cap"
        if reason:
            options.append({"type":kind,"status":"BLOCKED","publishable":False,"reason":reason,
                            "payload":None,"evidence":list(consent.sources) if consent else []})
            continue
        payload = {"type":kind,"proposed_at":at,"send_at":at,"title_id":hero["title_id"]}
        if kind=="push":
            # Fixed copy makes no title, offer, price, urgency or deadline claims.
            payload.update(text={"title":"Pick something to watch","body":"Explore a title in your app dialect."},
                           deeplink=rule["deeplink_format"].replace("<title_id>",hero["title_id"]))
            copy = rule["copy"]
            if (len(payload["text"]["title"])>copy["title_max_chars"]
                or len(payload["text"]["body"])>copy["body_max_chars"]
                or any(p.lower() in " ".join(payload["text"].values()).lower() for p in copy["forbidden_phrases"])):
                options.append({"type":kind,"status":"BLOCKED","publishable":False,
                                "reason":"Copy constraints rejected the fixed template","payload":None,"evidence":[]})
                continue
        else:
            language = facts.get("app_language")
            template = next((t for t in rule["approved_templates"] if t["template_id"]=="wa_recommend_title_v1"),None)
            if not template or not language or language.status!="known" or language.value != template["language"]:
                options.append({"type":kind,"status":"BLOCKED","publishable":False,"reason":"No approved recommendation template in the known app language","payload":None,"evidence":[]})
                continue
            payload.update(template_id=template["template_id"],
                           variables={"title_name":hero["title"],"dialect_name":hero["dialect"]})
        options.append(option(kind,payload,["catalogue:"+hero["title_id"],*consent.sources,
            "config/interventions.json:"+kind],"Consent and time checks passed; delivery and final cap require verification"))
    shown = [e for e in events if e["event"]=="message_delivered"
             and e["properties"].get("channel")=="in_app_message"
             and timestamp(e["received_at"]).astimezone(IST).date()==local.date()]
    if len(shown) >= config["in_app_message"]["max_per_day"]:
        options.append({"type":"in_app_message","status":"BLOCKED","publishable":False,
                        "reason":"Observed in-app daily cap reached","payload":None,"evidence":[]})
    else:
        options.append(option("in_app_message",{"type":"in_app_message","proposed_at":at,
            "title_id":hero["title_id"],"text":{"title":"Explore your next title","body":"Choose a title to watch."},
            "deeplink":"ott://title/"+hero["title_id"]},
            ["catalogue:"+hero["title_id"],"config/interventions.json:in_app_message"],
            "Consent not required; queue for a later app open only after independent verification"))
    options.append(no_action("Abstention is always allowed"))
    return options
