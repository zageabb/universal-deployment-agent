"""Bounded, read-only GitHub API source staging for private UDA repositories.

No Git process or repository code is run; no credentials are written to disk.
This small-repository path rejects submodules, symlinks, unusual modes and
oversized snapshots. Larger sources will require a separate vetted transport.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from onboarding import OnboardingError, repository_name

SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_FILES = 1000
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 12 * 1024 * 1024


def _api_json(repository: str, endpoint: str, token: str) -> dict:
    url = f"https://api.github.com/repos/{repository}/{endpoint}"
    request = Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urlopen(request, timeout=20) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise OnboardingError("Source API response exceeds configured maximum")
        value = json.loads(data)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise OnboardingError("Could not retrieve GitHub source snapshot") from exc
    if not isinstance(value, dict):
        raise OnboardingError("Unexpected GitHub source response")
    return value


def _safe_relative_path(value: str) -> Path:
    if not isinstance(value, str) or len(value) > 512 or "\x00" in value or "\\" in value:
        raise OnboardingError("Unsafe repository path")
    raw = PurePosixPath(value)
    if (raw.is_absolute() or not raw.parts or
            any(piece in ("", ".", "..", ".git") for piece in value.split("/"))):
        raise OnboardingError("Unsafe repository path")
    if str(raw) != value:
        raise OnboardingError("Non-canonical repository path")
    return Path(*raw.parts)


def stage_private_snapshot(plan: dict, staging_root: Path, token: str,
                           *, api=_api_json) -> dict:
    """Stage exact commit via Git trees/blobs; never invoke Git or execute code."""
    if not token:
        raise OnboardingError("GitHub read token is required")
    repository = plan.get("repository")
    if not isinstance(repository, str):
        raise OnboardingError("Missing repository")
    repository_name(f"https://github.com/{repository}")
    commit_sha = plan.get("commit_sha")
    name = plan.get("application")
    if not isinstance(commit_sha, str) or not SHA.fullmatch(commit_sha):
        raise OnboardingError("Invalid pinned commit")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", name):
        raise OnboardingError("Invalid application name")
    if staging_root.expanduser().is_symlink():
        raise OnboardingError("Staging directory may not be a symlink")
    root = staging_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise OnboardingError("Staging root is missing")
    destination = root / f"{name}-{commit_sha[:12]}"
    if destination.exists() or destination.is_symlink():
        raise OnboardingError("Destination already exists")
    commit = api(repository, f"git/commits/{commit_sha}", token)
    tree_sha = commit.get("tree", {}).get("sha")
    if not isinstance(tree_sha, str) or not SHA.fullmatch(tree_sha):
        raise OnboardingError("Invalid Git tree response")
    listing = api(repository, f"git/trees/{tree_sha}?recursive=1", token)
    if listing.get("truncated") is not False:
        raise OnboardingError("Incomplete Git tree refused")
    entries = listing.get("tree")
    if not isinstance(entries, list):
        raise OnboardingError("Missing Git tree entries")
    blobs = []
    size = 0
    paths = set()
    for row in entries:
        if not isinstance(row, dict) or row.get("type") not in {"tree", "blob"}:
            raise OnboardingError("Unsupported Git tree entry")
        path = _safe_relative_path(row.get("path"))
        if row.get("type") == "tree":
            if row.get("mode") != "040000":
                raise OnboardingError("Unsupported directory mode")
            continue
        if row.get("mode") not in {"100644", "100755"}:
            raise OnboardingError("Links and submodules require manual review")
        if path.as_posix() in paths:
            raise OnboardingError("Duplicate snapshot path")
        paths.add(path.as_posix())
        blob_sha = row.get("sha")
        length = row.get("size")
        if (not isinstance(blob_sha, str) or not SHA.fullmatch(blob_sha) or
                type(length) is not int or not 0 <= length <= MAX_FILE_BYTES):
            raise OnboardingError("Invalid blob size or SHA")
        size += length
        blobs.append((path, blob_sha, length))
        if len(blobs) > MAX_FILES or size > MAX_TOTAL_BYTES:
            raise OnboardingError("Snapshot exceeds source limits")
    if not blobs:
        raise OnboardingError("No application files in snapshot")
    # A temp sibling avoids partial staging destinations after failures.
    scratch = Path(tempfile.mkdtemp(prefix=".private-source-", dir=root))
    try:
        for path, blob_sha, length in blobs:
            response = api(repository, f"git/blobs/{blob_sha}", token)
            if response.get("encoding") != "base64":
                raise OnboardingError("Unsupported Git blob encoding")
            encoded = response.get("content")
            if not isinstance(encoded, str) or len(encoded) > (MAX_FILE_BYTES * 4 // 3 + 16_384):
                raise OnboardingError("Oversized encoded blob")
            try:
                contents = base64.b64decode("".join(encoded.split()), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise OnboardingError("Malformed Git blob data") from exc
            if len(contents) != length:
                raise OnboardingError("Git blob size mismatch")
            # Git's blob hash covers the 'blob <length>\\0' header as well.
            git_blob = b"blob " + str(length).encode() + b"\x00" + contents
            if hashlib.sha1(git_blob).hexdigest() != blob_sha:
                raise OnboardingError("Git blob integrity mismatch")
            target = scratch / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
            target.chmod(0o600)
        os.replace(scratch, destination)
    except Exception:
        if scratch.exists():
            shutil.rmtree(scratch)
        raise
    return {"repository": repository, "application": name,
            "commit_sha": commit_sha, "staged_path": str(destination),
            "status": "staged_only", "source": "github_api",
            "service_created": False, "registry_modified": False}
