import argparse
from dataclasses import asdict
import json
import hashlib
from .ingestion import audit
from .store import Store
from .evidence import resolve
from .goals import evaluate_viewer

def main():
    parser = argparse.ArgumentParser(description="Local memory, planning, verification and simulated replay")
    sub = parser.add_subparsers(dest="command",required=True)
    validate = sub.add_parser("validate",help="Read-only pack validation; never opens a database")
    validate.add_argument("--pack",default=".")
    ingest = sub.add_parser("ingest",help="Import supplied data into local SQLite")
    ingest.add_argument("--pack",default=".")
    ingest.add_argument("--db",required=True)
    inspect = sub.add_parser("viewer",help="Resolve and persist a viewer's evidence and eligibility audit")
    inspect.add_argument("--db",required=True)
    inspect.add_argument("--user",required=True)
    inspect.add_argument("--as-of",required=True)
    planning = sub.add_parser("plan",help="Persist an unverified decision proposal; never publishes")
    planning.add_argument("--pack",default=".")
    planning.add_argument("--db",required=True)
    planning.add_argument("--user",required=True)
    planning.add_argument("--as-of",required=True)
    planning.add_argument("--request-id")
    planning.add_argument("--channel",choices=("auto","home_page","push","whatsapp","in_app_message","no_action"),default="auto")
    verification = sub.add_parser("verify",help="Verify a persisted proposal and reserve approval locally; never publishes")
    verification.add_argument("--pack",default=".")
    verification.add_argument("--db",required=True)
    verification.add_argument("--decision",required=True)
    verification.add_argument("--as-of",required=True)
    verification.add_argument("--max-model-calls",type=int,default=8)
    verification.add_argument("--max-tool-calls",type=int,default=20)
    verification.add_argument("--max-seconds",type=float,default=60)
    replay = sub.add_parser("replay",help="Run local durable replay; write simulated actions only")
    replay.add_argument("--pack",default=".")
    replay.add_argument("--db",default="sample_run/replay.sqlite3")
    replay.add_argument("--out",default="sample_run")
    replay.add_argument("--max-model-calls",type=int,default=8)
    replay.add_argument("--max-tool-calls",type=int,default=20)
    replay.add_argument("--max-seconds",type=float,default=60)
    replay.add_argument("--stale-seconds",type=float,default=86400)
    replay.add_argument("--store-read-timeout",type=float,default=.25)
    replay.add_argument("--channel",choices=("auto","home_page","push","whatsapp","in_app_message","no_action"),default="auto")
    for name in ("measure","pipeline"):
        command = sub.add_parser(name,help="Evaluate supplied outcomes" if name=="measure" else "Replay, simulate, measure and report locally")
        command.add_argument("--pack",default=".")
        command.add_argument("--db",default="sample_run/replay.sqlite3")
        command.add_argument("--out",default="sample_run")
        if name=="measure":
            command.add_argument("--sim")
            command.add_argument("--as-of")
    args = parser.parse_args()
    if args.command=="pipeline":
        from .pipeline import pipeline
        print(json.dumps(pipeline(args.pack,args.db,args.out),indent=2))
        return 0
    if args.command=="measure":
        from .pipeline import run_measurement
        summary,impact,validation=run_measurement(args.pack,args.db,args.out,args.sim,args.as_of)
        print(json.dumps(validation,indent=2))
        return 0
    if args.command=="replay":
        from .replay import run_replay
        print(json.dumps(run_replay(args.pack,args.db,args.out,max_model_calls=args.max_model_calls,max_tool_calls=args.max_tool_calls,max_seconds=args.max_seconds,stale_seconds=args.stale_seconds,store_read_timeout=args.store_read_timeout,channel=args.channel),indent=2))
        return 0
    if args.command=="validate":
        report = audit(args.pack)
        print(json.dumps(report,indent=2))
        return 0 if report["valid"] else 1
    with Store(args.db) as store:
        if args.command=="ingest":
            print(json.dumps(store.import_pack(args.pack),indent=2))
        elif args.command=="verify":
            from .verifier import verify_existing
            from .budget import Budget
            result = verify_existing(store,args.pack,args.decision,args.as_of,
                            budget=Budget(args.max_model_calls,args.max_tool_calls,args.max_seconds))
            print(json.dumps(result,indent=2))
        elif args.command=="plan":
            from .planner import plan
            print(json.dumps(plan(store,args.pack,args.user,args.as_of,channel=args.channel,
                                  request_id=args.request_id),indent=2))
        else:
            facts = resolve(store,args.user,args.as_of)
            store.save_facts(args.user,args.as_of,facts)
            payload = {"user_id":args.user,"as_of":args.as_of,
                "facts":{k:v.to_dict() for k,v in facts.items()},
                "eligibility":[asdict(e) for e in evaluate_viewer(store,args.user,args.as_of,facts)],
                "action":"none","reason":"Phase 1 evidence inspection; no goal commitment or publication"}
            identity = hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
            if not store.connection.execute("SELECT 1 FROM decisions WHERE decision_id=?",(identity,)).fetchone():
                store.record_decision(identity,args.user,args.as_of,payload)
            print(json.dumps(payload,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
