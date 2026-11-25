"""Disposable end-to-end candidate receipt acceptance; no live destination."""
from pathlib import Path
import argparse
import json
import tempfile
from tools import uda_permanent_candidate_venv as prep
from tools import uda_candidate_admission as admission


def rehearse(stage):
    with tempfile.TemporaryDirectory(prefix="uda-receipt-lab-") as folder:
        lab = Path(folder)
        candidate = lab / "venv-v2"
        report = prep.prepare(stage.absolute(), candidate, lab)
        receipt = admission.seal(stage.absolute(), candidate, report)
        admission.verify(stage.absolute(), candidate, receipt)
        # Deliberate tamper after successful verification.
        marker = candidate / "unexpected-file"
        marker.write_bytes(b"fixture")
        marker.chmod(0o600)
        try:
            admission.verify(stage.absolute(), candidate, receipt)
        except ValueError as exc:
            if "changed" not in str(exc):
                raise
        else:
            raise RuntimeError("Candidate drift not refused")
        marker.unlink()
        admission.verify(stage.absolute(), candidate, receipt)
        return {"status": "PASS", "python": report["python"],
                "candidate_tree_sha256": receipt["tree_sha256"],
                "packages_sha256": receipt["packages_sha256"],
                "payload_count": len(receipt["payload"]),
                "receipt_verified": True, "tamper_refused": True,
                "restored_receipt_verified": True,
                "production_files_modified": False,
                "production_upgrade_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(rehearse(args.stage), indent=2))


if __name__ == "__main__":
    main()
