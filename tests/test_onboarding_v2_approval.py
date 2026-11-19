"""Offline out-of-band review attestations: no real deployment workers."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import pytest
import yaml

from onboarding import OnboardingError
from onboarding_release import prepare_release
from onboarding_v2_unit_renderer import render_reviewed_units
from onboarding_v2_approval import issue_review_attestation, review_attestation

SHA="a"*40
KEY=b"independent-review-authority-32bytes-test-only"


def fixture(tmp_path):
    staging=tmp_path/"staging";staging.mkdir()
    source=staging/("tender-designer-"+SHA[:12]);source.mkdir()
    (source/"app.py").write_text("pass\n")
    (source/"mailbox_daemon.py").write_text("pass\n")
    releases=tmp_path/"releases";releases.mkdir()
    release=prepare_release({"application":"tender-designer","repository":"zageabb/tender_designer",
        "commit_sha":SHA,"staged_path":str(source)},staging,releases)
    doc=yaml.safe_load((Path(__file__).resolve().parents[1]/"examples/uda-v2-multi-service.yaml").read_text())
    mapping={"web":"tender-web.service","mailbox":"tender-mailbox.service"}
    commands={"web":("/usr/bin/python3","app.py"),"mailbox":("/usr/bin/python3","mailbox_daemon.py")}
    env={}
    for name in mapping:
        f=tmp_path/(name+".env");f.write_text("SECRET_PLACEHOLDER=private\n");f.chmod(0o600);env[name]=f
    for service in doc["services"]:
        service["systemd_unit"]=mapping[service["name"]]
        service["entrypoint"]=list(commands[service["name"]])
    bundle=render_reviewed_units(doc,release_path=Path(release["release_path"]),
        source_commit_sha=SHA,environment_files=env,
        approved_entrypoints=commands,expected_units=mapping)
    store=tmp_path/"receipts";store.mkdir(mode=0o700)
    return bundle,store


def issue(bundle, *, operator="reviewer@example.com", now=10000, key=KEY, nonce=None):
    return issue_review_attestation(bundle,operator=operator,signing_key=key,now=now,nonce=nonce)


def consume(bundle,token,store,*,operator="reviewer@example.com",now=10001,key=KEY):
    return review_attestation(bundle,token,operator=operator,signing_key=key,
                              receipt_store=store,now=now)


def test_verified_bundle_requires_separate_attestation_and_cannot_install(tmp_path):
    bundle,store=fixture(tmp_path)
    token=issue(bundle)
    result=consume(bundle,token,store)
    assert result["review_accepted"] is True
    assert result["permission"]=="review_only"
    assert result["can_install"] is False
    assert result["can_start_service"] is False
    assert result["can_recover"] is False
    assert len(list(store.glob("review-*.json")))==1


def test_replay_rejected_with_atomic_one_use_receipt(tmp_path):
    bundle,store=fixture(tmp_path);token=issue(bundle)
    consume(bundle,token,store)
    with pytest.raises(OnboardingError,match="already been consumed"):
        consume(bundle,token,store)


@pytest.mark.parametrize("wrong",["operator","key","expired","future","tamper"])
def test_mismatched_or_expired_attestation_rejected(tmp_path,wrong):
    bundle,store=fixture(tmp_path);token=issue(bundle)
    if wrong=="operator":
        call={"operator":"other@example.com"}
    elif wrong=="key":
        call={"key":b"completely-different-independent-review-key"}
    elif wrong=="expired":
        call={"now":10901}
    elif wrong=="future":
        call={"now":9000}
    else:
        call={};token=token[:-1]+("0" if token[-1]!="0" else "1")
    with pytest.raises(OnboardingError):
        consume(bundle,token,store,**call)
    assert not list(store.iterdir())


def test_exact_bundle_digest_rejects_changed_unit_text(tmp_path):
    bundle,store=fixture(tmp_path);token=issue(bundle)
    changed=deepcopy(bundle)
    changed["units"]["tender-web.service"]+="\nEnvironment=INJECTED=1\n"
    with pytest.raises(OnboardingError,match="differs"):
        consume(changed,token,store)
    assert not list(store.iterdir())


def test_bundle_hash_rejects_changed_source_and_order(tmp_path):
    bundle,store=fixture(tmp_path)
    token=issue(bundle)
    changed=deepcopy(bundle);changed["commit_sha"]="b"*40
    with pytest.raises(OnboardingError,match="digest"):
        consume(changed,token,store)
    changed=deepcopy(bundle);changed["order"].reverse()
    with pytest.raises(OnboardingError,match="digest"):
        consume(changed,token,store)
    assert not list(store.iterdir())


def test_signed_token_cannot_claim_install_permission(tmp_path):
    bundle,store=fixture(tmp_path)
    token=issue(bundle)
    left,right=token.split(".")
    data=bytes.fromhex(left).decode().replace("review_unit_bundle","install_unit_bundle")
    forged=data.encode().hex()+"."+right
    with pytest.raises(OnboardingError,match="permission"):
        consume(bundle,forged,store)


def test_rejects_public_store_and_symbolic_link(tmp_path):
    bundle,store=fixture(tmp_path);token=issue(bundle)
    store.chmod(0o755)
    with pytest.raises(OnboardingError,match="private"):
        consume(bundle,token,store)
    store.chmod(0o700)
    link=tmp_path/"linked"
    link.symlink_to(store,target_is_directory=True)
    with pytest.raises(OnboardingError,match="absolute real"):
        consume(bundle,token,link)


def test_review_receipt_does_not_include_commands_or_secrets(tmp_path):
    bundle,store=fixture(tmp_path)
    consume(bundle,issue(bundle),store)
    value=next(store.iterdir()).read_text()
    assert "ExecStart" not in value
    assert "SECRET_PLACEHOLDER" not in value
    assert "/usr/bin/python3" not in value


def test_no_manifest_field_can_authorize_review(tmp_path):
    bundle,store=fixture(tmp_path)
    changed=deepcopy(bundle)
    changed["deployment_allowed"]=True
    with pytest.raises(OnboardingError,match="review-only"):
        issue(changed)
    changed=deepcopy(bundle)
    changed["approval_required"]=False
    with pytest.raises(OnboardingError,match="review artifact"):
        issue(changed)


def test_review_token_does_not_grant_service_action(tmp_path):
    bundle,store=fixture(tmp_path)
    token=issue(bundle)
    verified=consume(bundle,token,store)
    assert set(verified)=={"application","commit_sha","bundle_sha256",
                            "operator","review_accepted","permission",
                            "can_install","can_start_service","can_recover"}
    assert not any(v is True for k,v in verified.items() if k.startswith("can_"))
