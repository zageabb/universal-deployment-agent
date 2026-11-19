"""V2-003 out-of-band, review-only approval attestation for a unit bundle.

An independent operator authority signs the exact reviewed *bundle digest*,
source commit, target application, operator, action and one-use nonce. The
verifier never authorizes host writes: permission is always 'review_only'.

There is no signing endpoint or environment-derived signer in UDA. The
trusted authority must manage the key outside Git, the web dashboard and
repository checkout. Approval receipts are single-use in the private review
store and must not be used by any privileged activation worker.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time

from onboarding import OnboardingError

SHA = re.compile(r"^[0-9a-f]{64}$")
SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")
APP = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
OPERATOR = re.compile(r"^[A-Za-z0-9_.@-]{2,128}$")
NONCE = re.compile(r"^[0-9a-f]{32}$")
VERSION = 1
MAX_AGE = 900
MAX_TOKEN = 2048


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _private_store(root: Path) -> Path:
    if not isinstance(root, Path) or not root.is_absolute() or root.is_symlink():
        raise OnboardingError("Approval receipt store must be an absolute real directory")
    if not root.is_dir() or root.stat().st_mode & 0o077:
        raise OnboardingError("Approval receipt store must exist and be private")
    return root


def _digest_bundle(bundle: dict) -> tuple[str, str, str]:
    if not isinstance(bundle, dict) or bundle.get("deployment_allowed") is not False:
        raise OnboardingError("Only review-only unit bundles may be attested")
    if bundle.get("approval_required") is not True or bundle.get("status") != "review_only":
        raise OnboardingError("Unit bundle is not an approved review artifact")
    app, commit, digest = (bundle.get("application"), bundle.get("commit_sha"),
                           bundle.get("bundle_sha256"))
    if (not isinstance(app, str) or not APP.fullmatch(app) or
            not isinstance(commit, str) or not SOURCE_SHA.fullmatch(commit) or
            not isinstance(digest, str) or not SHA.fullmatch(digest)):
        raise OnboardingError("Invalid unit bundle identity")
    unit_hashes = bundle.get("unit_hashes")
    unit_texts = bundle.get("units")
    order = bundle.get("order")
    if (not isinstance(unit_texts, dict) or not unit_texts or
            not isinstance(unit_hashes, dict) or set(unit_texts) != set(unit_hashes) or
            not isinstance(order, list) or set(order) != set(unit_texts) or
            len(order) != len(unit_texts)):
        raise OnboardingError("Invalid unit bundle contents")
    for unit, content in unit_texts.items():
        if (not isinstance(content, str) or
                hashlib.sha256(content.encode()).hexdigest() != unit_hashes[unit]):
            raise OnboardingError("Unit bundle text differs from attested hash")
    evidence = {"application": app, "commit_sha": commit, "order": order,
                "unit_hashes": unit_hashes}
    runtime_hashes = bundle.get("runtime_hashes")
    if runtime_hashes is not None:
        if (not isinstance(runtime_hashes, dict) or not runtime_hashes or
                not set(runtime_hashes).issubset(unit_texts) or
                any(not isinstance(v, str) or not SHA.fullmatch(v)
                    for v in runtime_hashes.values())):
            raise OnboardingError("Invalid reviewed runtime provenance")
        evidence["runtime_hashes"] = runtime_hashes
    actual = hashlib.sha256(_canonical(evidence)).hexdigest()
    if not hmac.compare_digest(actual, digest):
        raise OnboardingError("Unit bundle evidence digest mismatch")
    return app, commit, digest


def issue_review_attestation(bundle: dict, *, operator: str,
                             signing_key: bytes, now: int | None = None,
                             nonce: str | None = None) -> str:
    """For an independent trusted operator authority, never dashboard code."""
    app, commit, digest = _digest_bundle(bundle)
    if not isinstance(operator, str) or not OPERATOR.fullmatch(operator):
        raise OnboardingError("Invalid authenticated reviewer identity")
    if not isinstance(signing_key, bytes) or len(signing_key) < 32:
        raise OnboardingError("Review signing key must be at least 32 bytes")
    issued = int(time.time()) if now is None else now
    if type(issued) is not int or issued <= 0:
        raise OnboardingError("Invalid signing time")
    nonce = secrets.token_hex(16) if nonce is None else nonce
    if not isinstance(nonce, str) or not NONCE.fullmatch(nonce):
        raise OnboardingError("Invalid approval nonce")
    payload = {"version": VERSION, "action": "review_unit_bundle",
               "operator": operator, "application": app, "commit_sha": commit,
               "bundle_sha256": digest, "issued_at": issued,
               "expires_at": issued + MAX_AGE, "nonce": nonce}
    raw = _canonical(payload)
    signature = hmac.new(signing_key, raw, hashlib.sha256).hexdigest()
    token = raw.hex() + "." + signature
    if len(token) > MAX_TOKEN:
        raise OnboardingError("Approval attestation too large")
    return token


def review_attestation(bundle: dict, token: str, *, operator: str,
                       signing_key: bytes, receipt_store: Path,
                       now: int | None = None) -> dict:
    """Consume one review attestation exactly once, without installation."""
    app, commit, digest = _digest_bundle(bundle)
    if not isinstance(token, str) or len(token) > MAX_TOKEN or token.count(".") != 1:
        raise OnboardingError("Invalid approval token")
    encoded, supplied = token.split(".")
    if not re.fullmatch(r"[0-9a-f]+", encoded) or not SHA.fullmatch(supplied):
        raise OnboardingError("Malformed approval token")
    if not isinstance(signing_key, bytes) or len(signing_key) < 32:
        raise OnboardingError("Missing trusted review verification key")
    try:
        raw = bytes.fromhex(encoded)
        payload = json.loads(raw)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise OnboardingError("Unparseable approval payload") from exc
    if not isinstance(payload, dict) or _canonical(payload) != raw:
        raise OnboardingError("Non-canonical review approval token")
    expected_keys = {"version", "action", "operator", "application", "commit_sha",
                     "bundle_sha256", "issued_at", "expires_at", "nonce"}
    if set(payload) != expected_keys or payload.get("version") != VERSION or (
            payload.get("action") != "review_unit_bundle"):
        raise OnboardingError("Unexpected approval permission or payload")
    expected = hmac.new(signing_key, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise OnboardingError("Review approval signature mismatch")
    timestamp = int(time.time()) if now is None else now
    if (type(timestamp) is not int or type(payload.get("issued_at")) is not int or
            type(payload.get("expires_at")) is not int or
            payload["issued_at"] > timestamp + 30 or
            payload["expires_at"] <= timestamp or
            payload["expires_at"] - payload["issued_at"] != MAX_AGE):
        raise OnboardingError("Expired or invalid review approval")
    if (not isinstance(operator, str) or not OPERATOR.fullmatch(operator) or
            payload["operator"] != operator or payload["application"] != app or
            payload["commit_sha"] != commit or payload["bundle_sha256"] != digest or
            not isinstance(payload["nonce"], str) or not NONCE.fullmatch(payload["nonce"])):
        raise OnboardingError("Approval scope differs from reviewed bundle/operator")
    root = _private_store(receipt_store)
    target = root / ("review-" + payload["nonce"] + ".json")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(target, flags, 0o600)
    except FileExistsError as exc:
        raise OnboardingError("Review approval token has already been consumed") from exc
    try:
        with os.fdopen(fd, "w") as receipt:
            json.dump({"nonce": payload["nonce"], "operator": operator,
                       "application": app, "bundle_sha256": digest,
                       "permission": "review_only"}, receipt, sort_keys=True)
            receipt.write("\n")
            receipt.flush()
            os.fsync(receipt.fileno())
        dfd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except Exception:
        # A failed receipt may have been partly persisted. Never issue a
        # second use; manual investigation is required.
        raise
    return {"application": app, "commit_sha": commit,
            "bundle_sha256": digest, "operator": operator,
            "review_accepted": True, "permission": "review_only",
            "can_install": False, "can_start_service": False,
            "can_recover": False}
