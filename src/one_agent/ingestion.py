"""Read-only, streaming source loaders and pack audit."""
import csv
import hashlib
import json
from pathlib import Path
from .schemas import timestamp

REQUIRED = {
    "data/events.jsonl", "data/profiles_snapshot.csv", "data/catalogue.csv",
    "data/episodes.csv", "config/goals.json", "config/interventions.json",
    "config/pricing.json", "config/messaging_policy.md",
    "pilot/pilot_assignment.csv", "pilot/pilot_outcomes.csv",
    "pilot/pilot_summary_report.md", "replay/triggers.jsonl",
    "replay/live_events.jsonl", "replay/control_events.jsonl",
    "replay/model_faults.jsonl", "replay/arms.csv", "simulator/simulate_outcomes.py",
}
FIELDS = {
    "events": {"event_id", "user_id", "event", "received_at", "occurred_at", "sent_at", "properties"},
    "profiles": {"user_id", "updated_at", "snapshot_at", "subscription_status", "preferred_dialect",
                 "notifications_opt_in", "whatsapp_opt_in", "signup_at"},
    "catalogue": {"title_id", "content_slug", "dialect", "content_type", "available_from", "available_until"},
    "episodes": {"episode_id", "content_slug", "season", "episode", "minutes"},
    "triggers": {"event_id", "user_id", "event", "received_at", "occurred_at", "sent_at", "deliver_at", "properties"},
}
PATHS = {"events": "data/events.jsonl", "profiles": "data/profiles_snapshot.csv",
         "catalogue": "data/catalogue.csv", "episodes": "data/episodes.csv",
         "triggers": "replay/triggers.jsonl"}

def records(path):
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        if path.suffix == ".csv":
            yield from csv.DictReader(handle)
        else:
            for line in handle:
                if line.strip():
                    yield json.loads(line)

def validate_record(kind, row):
    missing = FIELDS[kind] - row.keys()
    if missing:
        raise ValueError(f"{kind}: missing fields {sorted(missing)}")
    key = {"events": "event_id", "triggers": "event_id", "profiles": "user_id",
           "catalogue": "title_id", "episodes": "episode_id"}[kind]
    if not row[key]:
        raise ValueError(f"{kind}: empty {key}")
    required_times = {"events": ("received_at","occurred_at","sent_at"),
                      "triggers": ("received_at","occurred_at","sent_at","deliver_at"),
                      "profiles": ("updated_at","snapshot_at"),"catalogue": ("available_from",),
                      "episodes": ()}[kind]
    for name in required_times:
        timestamp(row[name])
    if kind in ("events","triggers") and (not row["user_id"] or not row["event"]):
        raise ValueError("Event user and event type must be nonempty")
    for name in ("received_at", "occurred_at", "sent_at", "deliver_at", "updated_at",
                 "snapshot_at", "signup_at", "available_from", "available_until"):
        if row.get(name):
            timestamp(row[name])
    if kind in ("events", "triggers") and not isinstance(row["properties"], dict):
        raise ValueError("properties must be an object")
    if kind == "profiles":
        for field in ("notifications_opt_in", "whatsapp_opt_in"):
            if row[field] not in ("true", "false", ""):
                raise ValueError(f"Invalid {field}")
        if row["subscription_status"] not in ("never", "active", "trial_active", "lapsed", ""):
            raise ValueError("Invalid subscription_status")
    if kind == "episodes":
        for field in ("season", "episode", "minutes"):
            if float(row[field]) <= 0:
                raise ValueError(f"Invalid {field}")

def load(pack, kind):
    for number, row in enumerate(records(Path(pack) / PATHS[kind]), 1):
        try:
            validate_record(kind, row)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"{PATHS[kind]} record {number}: {exc}") from exc
        yield row

def load_goals(pack):
    with (Path(pack) / "config/goals.json").open(encoding="utf-8") as handle:
        config = json.load(handle)
    seen = set()
    for goal in config["goals"]:
        if goal["goal_id"] in seen or not isinstance(goal["eligibility"], dict):
            raise ValueError("Duplicate or invalid goal")
        seen.add(goal["goal_id"])
        if goal["success"]["window_hours"] <= 0:
            raise ValueError("Invalid goal window")
    return config

def audit(pack):
    pack = Path(pack)
    missing = sorted(p for p in REQUIRED if not (pack / p).is_file())
    report = {"missing": missing, "files": {}, "errors": [], "warnings": []}
    for relative in sorted(REQUIRED - set(missing)):
        path = pack / relative
        report["files"][relative] = {"bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    loaded = {}
    for kind, relative in PATHS.items():
        if relative in missing:
            continue
        try:
            rows = list(load(pack, kind))
            loaded[kind] = rows
            report["files"][relative]["records"] = len(rows)
        except (ValueError, KeyError, TypeError) as exc:
            report["errors"].append(str(exc))
    if "config/goals.json" not in missing:
        try:
            report["goals"] = len(load_goals(pack)["goals"])
        except (ValueError, KeyError, TypeError) as exc:
            report["errors"].append(str(exc))
    events = loaded.get("events", [])
    profiles = loaded.get("profiles", [])
    report["duplicate_event_records"] = len(events) - len({e["event_id"] for e in events})
    report["extra_profile_versions"] = len(profiles) - len({p["user_id"] for p in profiles})
    titles = {r["title_id"] for r in loaded.get("catalogue", [])}
    slugs = {r["content_slug"] for r in loaded.get("catalogue", [])}
    episode_ids = {r["episode_id"] for r in loaded.get("episodes", [])}
    report["unknown_title_references"] = sum(
        bool(e["properties"].get("title_id")) and e["properties"]["title_id"] not in titles for e in events)
    report["unknown_episode_references"] = sum(
        bool(e["properties"].get("episode_id")) and e["properties"]["episode_id"] not in episode_ids for e in events)
    report["orphan_episode_rows"] = sum(r["content_slug"] not in slugs for r in loaded.get("episodes", []))
    report["trigger_users_without_profile"] = len(
        {r["user_id"] for r in loaded.get("triggers", [])} - {r["user_id"] for r in profiles})
    report["warnings"] = ["Device timestamps are untrusted; finite history does not prove lifetime absence.",
                          "G06, G10 and G11 are disabled pending definitions/signals."]
    report["valid"] = not missing and not report["errors"]
    return report
