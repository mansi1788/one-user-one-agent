import json
import hashlib
import sqlite3
from pathlib import Path

DDL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS viewers(user_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES viewers,
 event TEXT NOT NULL, received_at TEXT NOT NULL, occurred_at TEXT NOT NULL, sent_at TEXT NOT NULL,
 source TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_user_time ON events(user_id,received_at,event_id);
CREATE TABLE IF NOT EXISTS profiles(source_ref TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES viewers,
 updated_at TEXT NOT NULL, snapshot_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS profiles_user ON profiles(user_id,snapshot_at);
CREATE TABLE IF NOT EXISTS catalogue(title_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS episodes(episode_id TEXT PRIMARY KEY,content_slug TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS goal_rules(version TEXT,goal_id TEXT,payload TEXT NOT NULL,PRIMARY KEY(version,goal_id));
CREATE TABLE IF NOT EXISTS triggers(source_ref TEXT PRIMARY KEY,event_id TEXT NOT NULL,
 user_id TEXT NOT NULL REFERENCES viewers,deliver_at TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS facts(user_id TEXT REFERENCES viewers,name TEXT,as_of TEXT,payload TEXT NOT NULL,
 PRIMARY KEY(user_id,name,as_of));
CREATE TABLE IF NOT EXISTS conflicts(user_id TEXT REFERENCES viewers,name TEXT,as_of TEXT,payload TEXT NOT NULL,
 PRIMARY KEY(user_id,name,as_of,payload));
CREATE TABLE IF NOT EXISTS goals(id INTEGER PRIMARY KEY,user_id TEXT NOT NULL REFERENCES viewers,
 goal_id TEXT NOT NULL,rule_version TEXT NOT NULL,started_at TEXT NOT NULL,deadline TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('open','succeeded','failed','inconclusive','cancelled')),payload TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_goal ON goals(user_id) WHERE status='open';
CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY,user_id TEXT NOT NULL REFERENCES viewers,
 goal_instance_id INTEGER NOT NULL REFERENCES goals(id),status TEXT NOT NULL CHECK(status IN ('active','closed')),
 payload TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_plan ON plans(user_id) WHERE status='active';
CREATE TABLE IF NOT EXISTS decisions(decision_id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES viewers,
 trigger_event_id TEXT,decided_at TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approvals(
 approval_id TEXT PRIMARY KEY,decision_id TEXT NOT NULL UNIQUE REFERENCES decisions,
 user_id TEXT NOT NULL REFERENCES viewers,trigger_key TEXT NOT NULL,action_key TEXT NOT NULL UNIQUE,
 external_action_id TEXT UNIQUE,verified_at TEXT NOT NULL,expires_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('approved','revoked')),payload TEXT NOT NULL,
 UNIQUE(user_id,trigger_key));
CREATE TABLE IF NOT EXISTS message_reservations(
 reservation_id TEXT PRIMARY KEY,approval_id TEXT NOT NULL UNIQUE REFERENCES approvals,
 user_id TEXT NOT NULL REFERENCES viewers,ist_day TEXT NOT NULL,scope TEXT NOT NULL,
 slot INTEGER NOT NULL,status TEXT NOT NULL CHECK(status IN ('reserved','released')));
CREATE UNIQUE INDEX IF NOT EXISTS message_slot ON message_reservations(user_id,ist_day,scope,slot)
 WHERE status='reserved';
CREATE TABLE IF NOT EXISTS verifications(
 verification_id TEXT PRIMARY KEY,decision_id TEXT,user_id TEXT,verified_at TEXT NOT NULL,
 verdict TEXT NOT NULL CHECK(verdict IN ('APPROVED','REJECTED','ABSTAINED')),payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS call_audits(
 verification_id TEXT NOT NULL REFERENCES verifications,sequence INTEGER NOT NULL,payload TEXT NOT NULL,
 PRIMARY KEY(verification_id,sequence));

"""

def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)

class Store:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(DDL)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.connection.close()

    def viewer(self, user_id):
        self.connection.execute("INSERT OR IGNORE INTO viewers VALUES (?)", (user_id,))

    def add_event(self, row, source="data/events.jsonl"):
        from .schemas import timestamp
        self.viewer(row["user_id"])
        times = [timestamp(row[k]).isoformat() for k in ("received_at", "occurred_at", "sent_at")]
        cursor = self.connection.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?)",
            (row["event_id"], row["user_id"], row["event"], *times, source, encode(row)))
        if cursor.rowcount == 0:
            previous = self.connection.execute("SELECT payload FROM events WHERE event_id=?", (row["event_id"],)).fetchone()
            if json.loads(previous[0]) != row:
                self.connection.execute("INSERT OR IGNORE INTO conflicts VALUES (?,?,?,?)",
                    (row["user_id"], "event_id", times[0], encode({"event_id": row["event_id"],
                     "reason": "same event_id with differing payload", "incoming": row, "stored": json.loads(previous[0])})))
        return cursor.rowcount == 1

    def user_events(self, user_id, as_of):
        from .schemas import timestamp
        return [json.loads(r[0]) for r in self.connection.execute(
            "SELECT payload FROM events WHERE user_id=? AND received_at<=? ORDER BY received_at,event_id",
            (user_id, timestamp(as_of).isoformat()))]

    def user_profiles(self, user_id, as_of):
        from .schemas import timestamp
        rows = self.connection.execute("SELECT source_ref,payload FROM profiles WHERE user_id=?", (user_id,))
        return [(r[0], json.loads(r[1])) for r in rows
                if timestamp(json.loads(r[1])["snapshot_at"]) <= timestamp(as_of)
                and timestamp(json.loads(r[1])["updated_at"]) <= timestamp(as_of)]

    def save_facts(self, user_id, as_of, facts):
        with self.connection:
            self.viewer(user_id)
            for fact in facts.values():
                self.connection.execute("INSERT OR REPLACE INTO facts VALUES (?,?,?,?)",
                                        (user_id, fact.name, as_of, encode(fact.to_dict())))
                self.connection.execute("DELETE FROM conflicts WHERE user_id=? AND name=? AND as_of=?",
                                        (user_id, fact.name, as_of))
                for conflict in fact.conflicts:
                    self.connection.execute("INSERT OR IGNORE INTO conflicts VALUES (?,?,?,?)",
                                            (user_id, fact.name, as_of, encode(conflict)))

    def record_decision(self, decision_id, user_id, decided_at, payload, trigger_event_id=None):
        with self.connection:
            self.viewer(user_id)
            self.connection.execute("INSERT INTO decisions VALUES (?,?,?,?,?)",
                (decision_id,user_id,trigger_event_id,decided_at,encode(payload)))

    def import_pack(self, pack):
        from .ingestion import load, load_goals
        from .schemas import timestamp
        pack = Path(pack)
        counts = {}
        from .ingestion import PATHS
        digest = hashlib.sha256()
        for relative in sorted([*PATHS.values(), "config/goals.json"]):
            digest.update(relative.encode())
            digest.update((pack / relative).read_bytes())
        identity = digest.hexdigest()
        existing = self.connection.execute("SELECT value FROM metadata WHERE key='pack_identity'").fetchone()
        if existing and existing[0] != identity:
            raise ValueError("This database belongs to a different pack; use a fresh database")
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO metadata VALUES ('pack_identity',?)",(identity,))
            # Loading in server-receipt order makes duplicate resolution stable.
            rows = sorted(load(pack, "events"), key=lambda r: (timestamp(r["received_at"]), r["event_id"]))
            counts["events_inserted"] = sum(self.add_event(r) for r in rows)
            for kind, table in (("catalogue","catalogue"), ("episodes","episodes")):
                n = 0
                for row in load(pack, kind):
                    if kind == "catalogue":
                        self.connection.execute("INSERT OR REPLACE INTO catalogue VALUES (?,?)", (row["title_id"],encode(row)))
                    else:
                        self.connection.execute("INSERT OR REPLACE INTO episodes VALUES (?,?,?)",
                                                (row["episode_id"],row["content_slug"],encode(row)))
                    n += 1
                counts[kind] = n
            for kind in ("profiles", "triggers"):
                n = 0
                for number, row in enumerate(load(pack,kind),1):
                    self.viewer(row["user_id"])
                    ref = f"{kind}:{number}"
                    if kind == "profiles":
                        self.connection.execute("INSERT OR IGNORE INTO profiles VALUES (?,?,?,?,?)",
                            (ref,row["user_id"],row["updated_at"],row["snapshot_at"],encode(row)))
                    else:
                        self.connection.execute("INSERT OR IGNORE INTO triggers VALUES (?,?,?,?,?)",
                            (ref,row["event_id"],row["user_id"],row["deliver_at"],encode(row)))
                    n += 1
                counts[kind] = n
            config = load_goals(pack)
            for goal in config["goals"]:
                self.connection.execute("INSERT OR REPLACE INTO goal_rules VALUES (?,?,?)",
                                        (config["version"],goal["goal_id"],encode(goal)))
            if not rows:
                raise ValueError("Historical event file is empty")
            self.connection.execute("INSERT OR REPLACE INTO metadata VALUES ('history_start',?)",
                                    (min(r["received_at"] for r in rows),))
            self.connection.execute("INSERT OR REPLACE INTO metadata VALUES ('history_end',?)",
                                    (max(r["received_at"] for r in rows),))
        from .evidence import resolve
        as_of = max(timestamp(r["received_at"]) for r in rows).isoformat()
        user_ids = [r[0] for r in self.connection.execute("SELECT user_id FROM viewers")]
        for user_id in user_ids:
            self.save_facts(user_id,as_of,resolve(self,user_id,as_of))
        counts["viewers_materialized"] = len(user_ids)
        counts["facts_as_of"] = as_of
        return counts

    def commit_goal_plan(self, user_id, goal_id, rule_version, started_at, deadline, goal_payload, plan_payload):
        """Explicit state API only; Phase 1 does not select goals or execute plans."""
        from .schemas import timestamp
        if timestamp(deadline) <= timestamp(started_at):
            raise ValueError("Deadline must follow goal start")
        with self.connection:
            self.viewer(user_id)
            goal = self.connection.execute(
                "INSERT INTO goals(user_id,goal_id,rule_version,started_at,deadline,status,payload) VALUES (?,?,?,?,?,'open',?)",
                (user_id,goal_id,rule_version,started_at,deadline,encode(goal_payload)))
            self.connection.execute(
                "INSERT INTO plans(user_id,goal_instance_id,status,payload) VALUES (?,?,'active',?)",
                (user_id,goal.lastrowid,encode(plan_payload)))
        return goal.lastrowid

    def close_goal(self, goal_instance_id, status):
        if status not in ("succeeded","failed","inconclusive","cancelled"):
            raise ValueError("Invalid terminal goal status")
        with self.connection:
            self.connection.execute("UPDATE goals SET status=? WHERE id=? AND status='open'",(status,goal_instance_id))
            self.connection.execute("UPDATE plans SET status='closed' WHERE goal_instance_id=?",(goal_instance_id,))

    def active_goal_plan(self, user_id):
        row = self.connection.execute(
            "SELECT g.*,p.id AS plan_id,p.payload AS plan_payload FROM goals g "
            "JOIN plans p ON p.goal_instance_id=g.id AND p.status='active' "
            "WHERE g.user_id=? AND g.status='open'",(user_id,)).fetchone()
        return dict(row) if row else None

    def persist_planning(self, payload, expected_active):
        """Atomically preserve/replace one goal-plan pair and insert its proposed decision."""
        from .schemas import timestamp
        payload = json.loads(encode(payload))
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            previous = self.connection.execute("SELECT payload FROM decisions WHERE decision_id=?",
                                               (payload["decision_id"],)).fetchone()
            if previous:
                return json.loads(previous[0])
            current = self.active_goal_plan(payload["user_id"])
            if current != expected_active:
                raise RuntimeError("Viewer plan changed concurrently; retry planning against current state")
            transition = payload["plan_transition"]
            if current:
                prior_plan = json.loads(current["plan_payload"])
                if prior_plan.get("as_of") and timestamp(payload["as_of"]) < timestamp(prior_plan["as_of"]):
                    raise ValueError("Planning cannot move an active plan backwards in time")
            if current and transition in ("cancel","expire"):
                self.connection.execute("UPDATE plans SET status='closed' WHERE id=?",(current["plan_id"],))
                self.connection.execute("UPDATE goals SET status=? WHERE id=?",
                                        ("inconclusive" if transition=="expire" else "cancelled",current["id"]))
            goal = payload["goal"]
            if goal:
                if transition=="preserve":
                    self.connection.execute("UPDATE plans SET payload=? WHERE id=?",
                                            (encode(payload),current["plan_id"]))
                else:
                    self.viewer(payload["user_id"])
                    cursor = self.connection.execute(
                        "INSERT INTO goals(user_id,goal_id,rule_version,started_at,deadline,status,payload) "
                        "VALUES (?,?,?,?,?,'open',?)",
                        (payload["user_id"],goal["goal_id"],goal["rule_version"],goal["started_at"],
                         goal["deadline"],encode(goal)))
                    self.connection.execute(
                        "INSERT INTO plans(user_id,goal_instance_id,status,payload) VALUES (?,?,'active',?)",
                        (payload["user_id"],cursor.lastrowid,encode(payload)))
            self.viewer(payload["user_id"])
            self.connection.execute("INSERT INTO decisions VALUES (?,?,?,?,?)",
                (payload["decision_id"],payload["user_id"],payload.get("trigger_event_id"),payload["as_of"],encode(payload)))
        return payload
