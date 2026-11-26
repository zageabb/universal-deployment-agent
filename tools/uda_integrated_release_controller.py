"""Integrated release orchestration, with injected operational gates.

No CLI and no default live adapter. Caller must supply independently verified
maintenance approval, backup and quiescence checks. A failed recovery remains
in review; it never reports successful rollback solely from journal state.
"""
from tools import uda_production_payload_transaction as payload
from tools import uda_production_service_isolation as services
from tools.uda_controlled_activation import State, UNITS
from tools.uda_production_release_plan import verify_unchanged


def original(record):
    return {u: State(**s) for u,s in record["plan"]["contract"]["original_states"].items()}


def require(check, message):
    if check is not True:
        raise ValueError(message)


def recover(session, stage, runtime, adapter, gates):
    record = session.load()
    if record["phase"] in {"accepted", "aborted", "rolled_back", "prepared"}:
        raise ValueError("Transaction is not recoverable")
    require(gates.authorized(record["plan"]), "Recovery authorization missing")
    if record["phase"] != "recovering":
        session.advance("recovering")
    try:
        # Never restore files while a deployment or web writer remains active.
        require(gates.reisolate(adapter, original(record)), "Recovery isolation failed")
        require(gates.quiescent(), "Recovery writers still active")
        require(gates.verify_preserved(record["plan"]), "Preserved payload drift")
        payload.restore_environment(session, runtime)
        payload.restore_files(session, stage, runtime)
        if "original_environment" in record:
            from tools.uda_production_integrity_gates import verify_environment
            verify_environment(runtime / "venv", record["original_environment"])
        require(gates.verify_original_environment(runtime), "Original environment not verified")
        require(gates.verify_preserved(record["plan"]), "Preserved payload drift")
        services.restore(adapter, original(record), gates.probe_restored)
        session.advance("rolled_back")
    except Exception:
        session.advance("review")
        raise


def execute(session, stage, runtime, adapter, gates, plan):
    require(gates.authorized(plan), "Maintenance authorization missing")
    verify_unchanged(plan, gates.current_plan())
    require(gates.verify_preserved(plan), "Preserved payload drift")
    session.begin(plan)
    try:
        services.isolate(adapter, session)
        require(gates.quiescent(), "Writers still active")
        require(gates.fresh_backup(plan), "Fresh backup not verified")
        require(gates.verify_original_environment(runtime), "Original environment not verified")
        require(gates.verify_preserved(plan), "Preserved payload drift")
        from tools.uda_production_integrity_gates import environment
        record = session.load()
        record["original_environment"] = environment(runtime / "venv")
        session.save(record)
        payload.apply(session, stage, runtime)
        payload.switch(session, runtime)
        require(gates.verify_preserved(plan), "Preserved payload drift")
        services.restore(adapter, original(session.load()), gates.probe_candidate)
        session.advance("accepted")
        return "accepted"
    except Exception:
        if session.load()["phase"] == "prepared":
            session.advance("aborted")
            raise
        recover(session, stage, runtime, adapter, gates)
        return "rolled_back"
