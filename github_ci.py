#!/usr/bin/env python3
"""Trigger and optionally wait for a GitHub Actions workflow_dispatch run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Callable
from urllib.parse import quote


TERMINAL_CONCLUSIONS = {
    "success",
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "neutral",
    "skipped",
    "stale",
    "startup_failure",
}


class GitHubCIError(RuntimeError):
    """A classified GitHub CLI failure."""

    def __init__(self, message: str, error_type: str = "github_error") -> None:
        super().__init__(message)
        self.error_type = error_type


def find_gh() -> str:
    configured = os.environ.get("UDA_GH_PATH")
    candidates = [
        configured,
        shutil.which("gh"),
        str(Path(sys.argv[0]).resolve().with_name("gh")),
        str(Path.home() / ".local/bin/gh"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise GitHubCIError(
        "GitHub CLI was not found; install gh or set UDA_GH_PATH",
        "missing_gh",
    )


def _classify_cli_error(stderr: str) -> str:
    lowered = stderr.lower()
    auth_markers = (
        "not logged into",
        "authentication",
        "bad credentials",
        "http 401",
        "requires authentication",
        "resource not accessible by integration",
    )
    return "authentication_error" if any(marker in lowered for marker in auth_markers) else "github_error"


def run_gh(gh: str, arguments: list[str], timeout: float = 60) -> str:
    try:
        completed = subprocess.run(
            [gh, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitHubCIError(f"GitHub CLI timed out: {' '.join(arguments)}", "github_timeout") from exc
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "GitHub CLI failed").strip()
        raise GitHubCIError(detail, _classify_cli_error(detail))
    return completed.stdout.strip()


def _json_gh(gh: str, arguments: list[str], timeout: float = 60) -> Any:
    output = run_gh(gh, arguments, timeout=timeout)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise GitHubCIError("GitHub CLI returned invalid JSON", "invalid_github_response") from exc


def _list_runs(gh: str, repo: str, workflow: str, ref: str) -> list[dict[str, Any]]:
    fields = "databaseId,url,status,conclusion,createdAt,headBranch,headSha,workflowName,event"
    value = _json_gh(
        gh,
        [
            "run",
            "list",
            "--repo",
            repo,
            "--workflow",
            workflow,
            "--branch",
            ref,
            "--event",
            "workflow_dispatch",
            "--limit",
            "30",
            "--json",
            fields,
        ],
    )
    if not isinstance(value, list):
        raise GitHubCIError("GitHub CLI returned an unexpected run list", "invalid_github_response")
    return value


def _run_result(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run.get("databaseId"),
        "run_url": run.get("url"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion") or None,
        "head_sha": run.get("headSha"),
        "created_at": run.get("createdAt"),
    }


def trigger_ci(
    repo: str,
    workflow: str,
    ref: str,
    *,
    wait: bool = False,
    discovery_timeout: float = 30,
    wait_timeout: float = 1800,
    poll_interval: float = 3,
    gh_path: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Dispatch a workflow and return a structured result.

    A successful dispatch sets ``accepted`` even if GitHub's eventually
    consistent run list does not reveal the new run before discovery_timeout.
    """
    if not repo or "/" not in repo or not workflow or not ref:
        return {
            "accepted": False,
            "error_type": "invalid_request",
            "error": "repo must be OWNER/REPO and workflow/ref must be non-empty",
        }

    result: dict[str, Any] = {
        "accepted": False,
        "repo": repo,
        "workflow": workflow,
        "ref": ref,
        "run_id": None,
        "run_url": None,
        "status": None,
        "conclusion": None,
    }
    try:
        gh = gh_path or find_gh()
        run_gh(gh, ["auth", "status", "--hostname", "github.com"])
        encoded_ref = quote(ref, safe="")
        head_sha = run_gh(
            gh,
            ["api", f"repos/{repo}/commits/{encoded_ref}", "--jq", ".sha"],
        )
        before_ids = {item.get("databaseId") for item in _list_runs(gh, repo, workflow, ref)}
        run_gh(
            gh,
            ["workflow", "run", workflow, "--repo", repo, "--ref", ref],
        )
        result["accepted"] = True
        result["requested_head_sha"] = head_sha

        deadline = monotonic() + max(0, discovery_timeout)
        discovered: dict[str, Any] | None = None
        while True:
            candidates = [
                item
                for item in _list_runs(gh, repo, workflow, ref)
                if item.get("databaseId") not in before_ids
                and item.get("headSha") == head_sha
            ]
            if candidates:
                discovered = candidates[0]
                break
            if monotonic() >= deadline:
                result["error_type"] = "run_discovery_timeout"
                result["error"] = "GitHub accepted the dispatch, but the new run was not discovered in time"
                return result
            sleep(poll_interval)

        result.update(_run_result(discovered))
        if not wait:
            return result

        run_id = str(result["run_id"])
        wait_deadline = monotonic() + max(0, wait_timeout)
        fields = "databaseId,url,status,conclusion,createdAt,headSha"
        while True:
            current = _json_gh(
                gh,
                ["run", "view", run_id, "--repo", repo, "--json", fields],
            )
            result.update(_run_result(current))
            conclusion = result.get("conclusion")
            if conclusion in TERMINAL_CONCLUSIONS or result.get("status") == "completed":
                return result
            if monotonic() >= wait_deadline:
                result["error_type"] = "wait_timeout"
                result["error"] = "The workflow run did not complete before wait_timeout"
                return result
            sleep(poll_interval)
    except GitHubCIError as exc:
        result["error_type"] = exc.error_type
        result["error"] = str(exc)
        return result


def _exit_code(result: dict[str, Any], waited: bool) -> int:
    if not result.get("accepted") or result.get("error_type"):
        return 1
    if waited and result.get("conclusion") != "success":
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repository as OWNER/REPO")
    parser.add_argument("--workflow", required=True, help="Workflow file name or ID")
    parser.add_argument("--ref", required=True, help="Branch or ref to dispatch")
    parser.add_argument("--wait", action="store_true", help="Poll until the run completes")
    parser.add_argument("--discovery-timeout", type=float, default=30)
    parser.add_argument("--wait-timeout", type=float, default=1800)
    parser.add_argument("--poll-interval", type=float, default=3)
    args = parser.parse_args()
    result = trigger_ci(
        args.repo,
        args.workflow,
        args.ref,
        wait=args.wait,
        discovery_timeout=args.discovery_timeout,
        wait_timeout=args.wait_timeout,
        poll_interval=args.poll_interval,
    )
    print(json.dumps(result, sort_keys=True))
    return _exit_code(result, args.wait)


if __name__ == "__main__":
    raise SystemExit(main())
