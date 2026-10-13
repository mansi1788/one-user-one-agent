"""Conservative, fact-specific resolution using only evidence available as of a time."""
from urllib.parse import urlsplit
from .schemas import Fact, timestamp

def resolve(store, user_id, as_of):
    events = store.user_events(user_id, as_of)
    profiles = store.user_profiles(user_id, as_of)
    profiles.sort(key=lambda item: (timestamp(item[1]["updated_at"]), item[0]))
    facts = {}

    def profile_fact(name, field):
        candidates = [(ref,p) for ref,p in profiles if p.get(field) not in ("",None)]
        if not candidates:
            return Fact(name,None,"unknown",reason="No usable profile evidence")
        latest_time = candidates[-1][1]["updated_at"]
        latest = [(ref,p) for ref,p in candidates if timestamp(p["updated_at"]) == timestamp(latest_time)]
        values = {p[field] for _,p in latest}
        conflicts = tuple({"source":ref,"value":p[field],"updated_at":p["updated_at"]}
                          for ref,p in candidates if p[field] != latest[-1][1][field])
        if len(values) != 1:
            return Fact(name,None,"unknown",tuple(ref for ref,_ in latest),latest_time,
                        "Equally current profile versions disagree",conflicts)
        ref,p = latest[-1]
        return Fact(name,p[field],"known",(ref,),p["updated_at"],"Latest available profile version",conflicts)

    for name,field in (("signup_at","signup_at"),("subscription_status","subscription_status"),
                       ("notifications_opt_in","notifications_opt_in"),("whatsapp_opt_in","whatsapp_opt_in")):
        facts[name] = profile_fact(name,field)
    signups = [e for e in events if e["event"] == "signup_completed"]
    if signups:
        e = signups[0]
        old = facts["signup_at"]
        conflicts = old.conflicts + (({"source":old.sources,"value":old.value},) if old.value and timestamp(old.value) != timestamp(e["received_at"]) else ())
        facts["signup_at"] = Fact("signup_at",e["received_at"],"known",("event:"+e["event_id"],),
                                  e["received_at"],"Server receipt of signup; device time untrusted",conflicts)
    languages = [e for e in events if e.get("app_language")]
    if languages:
        e = languages[-1]
        values = {r["app_language"] for r in languages if timestamp(r["received_at"]) == timestamp(e["received_at"])}
        facts["app_language"] = Fact("app_language",e["app_language"] if len(values)==1 else None,
            "known" if len(values)==1 else "unknown",("event:"+e["event_id"],),e["received_at"],
            "Latest received app language setting")
    else:
        facts["app_language"] = Fact("app_language",None,"unknown",reason="No app language setting observed")
    dialect_profile = profile_fact("app_dialect","preferred_dialect")
    settings = [e for e in events if e.get("app_dialect")]
    if settings:
        latest = settings[-1]
        value = latest["app_dialect"]
        conflicts = list(dialect_profile.conflicts)
        if dialect_profile.value and dialect_profile.value != value:
            conflicts.append({"source":dialect_profile.sources,"value":dialect_profile.value,"kind":"profile"})
        for e in events:
            link = e["properties"].get("deeplink","")
            parts = urlsplit(link).path.split("/")
            # ott://c/<campaign>/<dialect>/title/<title_id>
            if urlsplit(link).netloc == "c" and len(parts) >= 5 and parts[3] == "title":
                if parts[2] != value:
                    conflicts.append({"source":"event:"+e["event_id"],"value":parts[2],"kind":"deeplink"})
        same_time = {e["app_dialect"] for e in settings if timestamp(e["received_at"]) == timestamp(latest["received_at"])}
        facts["app_dialect"] = Fact("app_dialect",value if len(same_time)==1 else None,
            "known" if len(same_time)==1 else "unknown",("event:"+latest["event_id"],),
            latest["received_at"],"App settings win over profile and campaign; receipt order, not device time",
            tuple(conflicts))
    else:
        facts["app_dialect"] = Fact("app_dialect",None,"unknown",dialect_profile.sources,
            dialect_profile.observed_at,"Profile preference does not establish current app settings",
            dialect_profile.conflicts)

    for name,channel in (("notifications_opt_in","push"),("whatsapp_opt_in","whatsapp")):
        base = facts[name]
        optouts = [e for e in events if e["event"]=="notification_opt_out" and e["properties"].get("channel")==channel]
        if optouts:
            e = optouts[-1]
            facts[name] = Fact(name,False,"known",("event:"+e["event_id"],),e["received_at"],
                "Observed opt-out; no documented event reinstates consent",
                base.conflicts + (({"source":base.sources,"value":base.value},) if base.value=="true" else ()))
        elif base.status == "known":
            # A stale positive snapshot is evidence, not proof of current consent.
            facts[name] = Fact(name,False if base.value=="false" else None,
                "known" if base.value=="false" else "unknown",base.sources,base.observed_at,
                "Negative snapshot is restrictive; positive snapshot requires current verification",base.conflicts)

    base = facts["subscription_status"]
    changes = [e for e in events if e["event"] in ("purchase_completed","subscription_renewed","subscription_lapsed")]
    newer = [e for e in changes if base.observed_at is None or timestamp(e["received_at"]) >= timestamp(base.observed_at)]
    if newer:
        e = newer[-1]
        if e["event"]=="subscription_lapsed":
            value = "lapsed"
        elif e["event"]=="subscription_renewed":
            value = "active"
        else:
            trial = e["properties"].get("is_trial")
            value = "trial_active" if trial is True else "active" if trial is False else None
        facts["subscription_status"] = Fact("subscription_status",value,"known" if value else "unknown",
            ("event:"+e["event_id"],),e["received_at"],"Latest received subscription transition; no invented expiry",
            base.conflicts + (({"source":base.sources,"value":base.value},) if base.value and base.value!=value else ()))
    elif base.status=="known":
        # A never-paid snapshot is a supplied lifetime assertion; positive entitlement may expire.
        if base.value in ("active","trial_active"):
            matching = next((p for ref,p in reversed(profiles) if ref in base.sources),{})
            end = matching.get("plan_ends_at")
            if not end or timestamp(end) <= timestamp(as_of):
                facts["subscription_status"] = Fact(base.name,None,"unknown",base.sources,base.observed_at,
                    "Snapshot entitlement has no future-valid end; expiry does not prove lapse",base.conflicts)
    paid = [e for e in changes if e["event"]=="subscription_renewed" or
            (e["event"]=="purchase_completed" and e["properties"].get("is_trial") is False)]
    if paid and facts["subscription_status"].value=="never":
        f = facts["subscription_status"]
        facts["subscription_status"] = Fact(f.name,None,"unknown",f.sources+("event:"+paid[-1]["event_id"],),
            f.observed_at,"Never-paid snapshot contradicts observed paid history",
            f.conflicts+({"source":"event:"+paid[-1]["event_id"],"value":"paid before"},))
    return facts
