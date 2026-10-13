import json
from pathlib import Path
import pytest
from one_agent.store import Store, encode
from one_agent.evidence import resolve
from one_agent.goals import evaluate, DISABLED
from one_agent.ingestion import load_goals, audit

PACK = Path(__file__).resolve().parents[1]
NOW = "2026-10-01T00:00:00Z"

def event(id="E1", dialect="d2", **overrides):
    row = {"event_id":id,"user_id":"U1","event":"app_open","received_at":"2026-09-30T23:00:00Z",
           "occurred_at":"2026-09-29T00:00:00Z","sent_at":"2026-09-30T22:00:00Z",
           "app_dialect":dialect,"properties":{}}
    row.update(overrides)
    return row

def profile(store, dialect="d1", **extra):
    row = {"user_id":"U1","updated_at":"2026-09-30T00:00:00Z","snapshot_at":"2026-09-30T00:00:00Z",
           "signup_at":"2026-09-29T00:00:00Z","subscription_status":"never","preferred_dialect":dialect,
           "notifications_opt_in":"true","whatsapp_opt_in":"false"}
    row.update(extra)
    store.viewer("U1")
    store.connection.execute("INSERT INTO profiles VALUES (?,?,?,?,?)",
        ("profiles:1","U1",row["updated_at"],row["snapshot_at"],encode(row)))

def rule(id):
    return next(g for g in load_goals(PACK)["goals"] if g["goal_id"]==id)

def test_duplicate_and_untrusted_timestamps(tmp_path):
    with Store(tmp_path/"memory.db") as s:
        assert s.add_event(event())
        assert not s.add_event(event())
        assert len(s.user_events("U1",NOW))==1
        assert s.user_events("U1",NOW)[0]["occurred_at"]=="2026-09-29T00:00:00Z"

def test_conflicting_dialect(tmp_path):
    with Store(tmp_path/"memory.db") as s:
        profile(s)
        s.add_event(event(properties={"deeplink":"ott://c/campaign/d3/title/T1"}))
        f = resolve(s,"U1",NOW)["app_dialect"]
        assert f.value=="d2"
        assert {c["kind"] for c in f.conflicts}=={"profile","deeplink"}

def test_missing_profile(tmp_path):
    with Store(tmp_path/"memory.db") as s:
        s.add_event(event())
        facts = resolve(s,"U1",NOW)
        assert facts["subscription_status"].status=="unknown"
        assert facts["notifications_opt_in"].status=="unknown"
        assert facts["app_dialect"].value=="d2"

def test_unknown_lifetime_eligibility(tmp_path):
    with Store(tmp_path/"memory.db") as s:
        profile(s)
        facts = resolve(s,"U1",NOW)
        assert evaluate(rule("G01"),facts,[],NOW).status=="unknown"
        assert evaluate(rule("G02"),facts,[],NOW).status=="unknown"
        assert evaluate(rule("G03"),facts,[],NOW).status=="eligible"

def test_observed_prior_event_disqualifies(tmp_path):
    with Store(tmp_path/"memory.db") as s:
        e = event(event="episode_completed")
        assert evaluate(rule("G02"),{},[e],NOW).status=="ineligible"

@pytest.mark.parametrize("gid",sorted(DISABLED))
def test_disabled_goals(gid):
    result = evaluate(rule(gid),{},[],NOW)
    assert result.disabled and result.status=="unknown"

def test_persistence(tmp_path):
    path = tmp_path/"memory.db"
    with Store(path) as s:
        with s.connection:
            profile(s)
            s.add_event(event())
        facts = resolve(s,"U1",NOW)
        s.save_facts("U1",NOW,facts)
        s.record_decision("D1","U1",NOW,{"action":"none","reason":"Phase 1"})
    with Store(path) as s:
        assert len(s.user_events("U1",NOW))==1
        assert resolve(s,"U1",NOW)["app_dialect"].value=="d2"
        assert s.connection.execute("SELECT COUNT(*) FROM facts").fetchone()[0]==6
        assert s.connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]==1

def test_optout_overrides_snapshot(tmp_path):
    with Store(tmp_path/"memory.db") as s:
        profile(s)
        s.add_event(event(event="notification_opt_out",properties={"channel":"push"}))
        assert resolve(s,"U1",NOW)["notifications_opt_in"].value is False

def test_receipt_order_wins_over_device_clock(tmp_path):
    with Store(tmp_path/"memory.db") as s:
        s.add_event(event(id="old",dialect="d1",received_at="2026-09-30T22:00:00Z",occurred_at=NOW))
        s.add_event(event(id="new",dialect="d4"))
        assert resolve(s,"U1",NOW)["app_dialect"].value=="d4"

def test_missing_pack_is_invalid(tmp_path):
    report = audit(tmp_path)
    assert not report["valid"] and "data/events.jsonl" in report["missing"]

def test_future_profile_not_visible(tmp_path):
    with Store(tmp_path/"memory.db") as s:
        profile(s,snapshot_at="2026-10-02T00:00:00Z")
        assert resolve(s,"U1",NOW)["signup_at"].status=="unknown"

def test_positive_stale_consent_uncertain(tmp_path):
    with Store(tmp_path/"memory.db") as s:
        profile(s)
        assert resolve(s,"U1",NOW)["notifications_opt_in"].status=="unknown"

def test_recent_return_window_excludes_trigger():
    current = event(received_at=NOW)
    result = evaluate(rule("G12"),{},[current],NOW,
                      history_start="2026-09-01T00:00:00Z",history_end=NOW)
    assert result.status=="eligible"

def test_goal_plan_atomicity_and_restart(tmp_path):
    import sqlite3
    path = tmp_path/"memory.db"
    with Store(path) as s:
        gid = s.commit_goal_plan("U1","G03","v1",NOW,"2026-10-03T00:00:00Z",{}, {})
        with pytest.raises(sqlite3.IntegrityError):
            s.commit_goal_plan("U1","G04","v1",NOW,"2026-10-03T00:00:00Z",{}, {})
        assert s.connection.execute("SELECT COUNT(*) FROM goals").fetchone()[0]==1
    with Store(path) as s:
        assert s.connection.execute("SELECT status FROM plans").fetchone()[0]=="active"
        s.close_goal(gid,"cancelled")
        assert s.connection.execute("SELECT status FROM plans").fetchone()[0]=="closed"

def test_differing_duplicate_payload_is_preserved(tmp_path):
    with Store(tmp_path/"memory.db") as s:
        s.add_event(event())
        assert not s.add_event(event(dialect="d5"))
        assert s.connection.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0]==1

def test_paid_history_conflicts_with_never_snapshot(tmp_path):
    with Store(tmp_path/"memory.db") as s:
        profile(s,updated_at="2026-09-30T23:30:00Z")
        s.add_event(event(event="purchase_completed",properties={"is_trial":False}))
        assert resolve(s,"U1",NOW)["subscription_status"].status=="unknown"

def test_window_with_incomplete_history_is_unknown():
    assert evaluate(rule("G12"),{},[],NOW).status=="unknown"

def test_subscription_expiry_does_not_invent_lapse(tmp_path):
    with Store(tmp_path/"memory.db") as s:
        profile(s,subscription_status="active",plan_ends_at="2026-09-30T12:00:00Z")
        assert resolve(s,"U1",NOW)["subscription_status"].status=="unknown"

def test_valid_future_entitlement(tmp_path):
    with Store(tmp_path/"memory.db") as s:
        profile(s,subscription_status="active",plan_ends_at="2026-10-30T00:00:00Z")
        facts = resolve(s,"U1",NOW)
        assert evaluate(rule("G08"),facts,[],NOW).status=="eligible"
        assert evaluate(rule("G04"),facts,[],NOW).status=="ineligible"

def test_equal_profile_versions_preserve_uncertainty(tmp_path):
    with Store(tmp_path/"memory.db") as s:
        profile(s)
        row = json.loads(s.connection.execute("SELECT payload FROM profiles").fetchone()[0])
        row["subscription_status"]="lapsed"
        s.connection.execute("INSERT INTO profiles VALUES (?,?,?,?,?)",
            ("profiles:2","U1",row["updated_at"],row["snapshot_at"],encode(row)))
        f = resolve(s,"U1",NOW)["subscription_status"]
        assert f.status=="unknown" and f.conflicts

def test_malformed_timestamp_is_rejected():
    from one_agent.ingestion import validate_record
    with pytest.raises(ValueError):
        validate_record("events",event(received_at=""))

def test_pack_import_is_idempotent_and_preserves_versions(tmp_path):
    import csv
    pack = tmp_path/"pack"
    for folder in ("data","config","replay"):
        (pack/folder).mkdir(parents=True)
    (pack/"data/events.jsonl").write_text(json.dumps(event())+"\n"+json.dumps(event())+"\n")
    with Store(tmp_path/"seed.db") as s:
        profile(s)
        row = json.loads(s.connection.execute("SELECT payload FROM profiles").fetchone()[0])
    with (pack/"data/profiles_snapshot.csv").open("w",newline="") as f:
        writer = csv.DictWriter(f,fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
        writer.writerow(row)
    for filename,fields,row in [
        ("catalogue.csv",["title_id","content_slug","dialect","content_type","available_from","available_until"],
         ["T1","S1","d2","show","2026-09-01T00:00:00Z",""]),
        ("episodes.csv",["episode_id","content_slug","season","episode","minutes"],["EP1","S1",1,1,10])]:
        with (pack/"data"/filename).open("w",newline="") as f:
            w = csv.writer(f); w.writerow(fields); w.writerow(row)
    trigger = event(deliver_at=NOW)
    (pack/"replay/triggers.jsonl").write_text(json.dumps(trigger)+"\n")
    (pack/"config/goals.json").write_text(json.dumps(load_goals(PACK)))
    db = tmp_path/"import.db"
    with Store(db) as s:
        assert s.import_pack(pack)["events_inserted"]==1
        assert s.import_pack(pack)["events_inserted"]==0
        assert s.connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]==2
        assert s.connection.execute("SELECT COUNT(*) FROM triggers").fetchone()[0]==1
        assert s.connection.execute("SELECT COUNT(*) FROM facts").fetchone()[0]==6
    with Store(db) as s:
        assert len(s.user_events("U1",NOW))==1
        assert s.connection.execute("SELECT COUNT(*) FROM goal_rules").fetchone()[0]==12
        (pack/"data/events.jsonl").write_text(json.dumps(event(id="different"))+"\n")
        with pytest.raises(ValueError,match="different pack"):
            s.import_pack(pack)
