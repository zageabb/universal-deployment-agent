"""Operational orchestration, with mandatory independent V1 writer protection.

No executable CLI. Caller supplies trusted independent writer and external
application data guards, actual probes and a locked persistent journal.
"""
from pathlib import Path
from contextlib import contextmanager
from tools.uda_v1_writer_protection import hold
from deploy_agent import load_config, maintenance_lock
from tools import uda_production_payload_transaction as payload
from tools import uda_production_service_isolation as services
from tools import uda_application_backup_creation as application
from tools import uda_operational_backup_gate as backup
from tools import uda_production_integrity_gates as integrity
from tools import uda_maintenance_protection as permission
from tools.uda_maintenance_evidence import approval
from tools.uda_integrated_release_controller import original, require
from tools.uda_production_release_plan import verify_unchanged, inspect
from tools.uda_controlled_activation import TIMERS, WEB, validate


def reisolate(adapter, states):
    services.review(adapter.snapshot(), states)
    for unit in TIMERS:
        if adapter.snapshot()[unit].active != "inactive":
            adapter.change("stop", unit)
    services.drain(adapter, states)
    for unit in reversed(WEB):
        if adapter.snapshot()[unit].active != "inactive":
            adapter.change("stop", unit)
    integrity.units_idle(adapter, states)


class Controller:
    def __init__(self, session, stage, home, adapter, writer_guard,
                 external_data_guard, probe_candidate, probe_restored, *, process_review):
        self.session, self.stage, self.home, self.adapter = session, stage, home, adapter
        self.writer_guard, self.external_data_guard = writer_guard, external_data_guard
        self.probe_candidate, self.probe_restored = probe_candidate, probe_restored
        self.process_review = process_review
        self.legacy_guard = None
        self.runtime = home / ".local/share/deployment-agent"
        self.config = home / ".config/deployment-agent/config.json"

    def guard(self):
        integrity.units_idle(self.adapter, original(self.session.load()))
        require(self.writer_guard(), "Independent writer exclusion missing")
        if self.legacy_guard is None:
            raise ValueError("Legacy protection not held")
        require(self.legacy_guard(), "Legacy protection lost")
        require(self.external_data_guard(), "External application protection missing")
        return True

    @contextmanager
    def protected(self):
        # Acquire V2 first, matching the V2 worker lock order.
        with maintenance_lock(load_config(self.config), exclusive=True):
            with hold(self.home, self.writer_guard, self.process_review) as guard:
                self.legacy_guard = guard
                try:
                    yield
                finally:
                    self.legacy_guard = None

    def application_guard(self, plan, excluded):
        require(self.external_data_guard(), "External application protection missing")
        return application.verify_bound(self.session, self.home, plan, excluded)

    def execute(self, plan, evidence, uda_archive, application_archive):
        s = self.session
        approval(plan, evidence)
        verify_unchanged(plan, inspect(self.stage, candidate_receipt=plan["contract"]["venv"]["receipt"]))
        integrity.preserved(plan, self.home)
        require(self.writer_guard(), "Independent writer exclusion missing")
        s.begin(plan)
        try:
            permission.bind(s, evidence)
            permission.authorize(s)
            services.isolate(self.adapter, s)
            states = original(s.load())
            with self.protected():
                self.guard()
                application.create(s, self.adapter, states, self.home, application_archive, self.guard)
                backup.prepare(s, self.adapter, states, self.home, uda_archive, evidence,
                               self.guard, self.application_guard)
                backup.verify_before_apply(s, self.adapter, states, self.home,
                                           self.guard, self.application_guard)
                integrity.preserved(plan, self.home)
                record = s.load()
                record["original_environment"] = integrity.environment(self.runtime / "venv")
                s.save(record)
                def boundary(_):
                    permission.authorize(s)
                    self.guard()
                boundary(None)
                payload.apply(s, self.stage, self.runtime, interrupt=boundary)
                payload.switch(s, self.runtime, interrupt=boundary)
                boundary(None)
                integrity.preserved(plan, self.home)
            permission.authorize(s)
            require(self.writer_guard(), "Independent writer exclusion missing")
            services.restore(self.adapter, states, self.probe_candidate)
            permission.authorize(s)
            s.advance("accepted")
            return "accepted"
        except Exception:
            if s.load()["phase"] == "prepared":
                s.advance("aborted")
                raise
            self.recover()
            return "rolled_back"

    def recover(self):
        s = self.session
        record = s.load()
        permission.authorize(s, recovery=True)
        if record["phase"] != "recovering":
            s.advance("recovering")
        try:
            states = original(record)
            reisolate(self.adapter, states)
            with self.protected():
                self.guard()
                integrity.preserved(record["plan"], self.home)
                payload.restore_environment(s, self.runtime)
                payload.restore_files(s, self.stage, self.runtime)
                if "original_environment" in record:
                    integrity.verify_environment(self.runtime / "venv", record["original_environment"])
                integrity.preserved(record["plan"], self.home)
                self.guard()
            require(self.writer_guard(), "Independent writer exclusion missing")
            services.restore(self.adapter, states, self.probe_restored)
            s.advance("rolled_back")
        except Exception:
            s.advance("review")
            raise
