import subprocess

import github_ci


def test_trigger_discovers_queued_run(monkeypatch):
    calls = []
    before = [{"databaseId": 10, "headSha": "old"}]
    after = [{
        "databaseId": 11,
        "url": "https://github.com/o/r/actions/runs/11",
        "status": "queued",
        "conclusion": "",
        "createdAt": "2026-10-05T12:00:00Z",
        "headSha": "abc",
    }]
    lists = iter([before, after])

    monkeypatch.setattr(github_ci, "run_gh", lambda gh, args, timeout=60: calls.append(args) or ("abc" if args[0] == "api" else ""))
    monkeypatch.setattr(github_ci, "_list_runs", lambda *args: next(lists))

    result = github_ci.trigger_ci("o/r", "ci.yml", "main", gh_path="gh", sleep=lambda _: None)

    assert result == {
        "accepted": True,
        "repo": "o/r",
        "workflow": "ci.yml",
        "ref": "main",
        "run_id": 11,
        "run_url": "https://github.com/o/r/actions/runs/11",
        "status": "queued",
        "conclusion": None,
        "requested_head_sha": "abc",
        "head_sha": "abc",
        "created_at": "2026-10-05T12:00:00Z",
    }
    assert ["workflow", "run", "ci.yml", "--repo", "o/r", "--ref", "main"] in calls


def test_wait_returns_failure(monkeypatch):
    lists = iter([[], [{"databaseId": 22, "headSha": "abc", "status": "queued"}]])
    views = iter([
        {"databaseId": 22, "url": "u", "status": "in_progress", "conclusion": "", "headSha": "abc"},
        {"databaseId": 22, "url": "u", "status": "completed", "conclusion": "failure", "headSha": "abc"},
    ])

    monkeypatch.setattr(github_ci, "run_gh", lambda gh, args, timeout=60: "abc" if args[0] == "api" else "")
    monkeypatch.setattr(github_ci, "_list_runs", lambda *args: next(lists))
    monkeypatch.setattr(github_ci, "_json_gh", lambda *args, **kwargs: next(views))

    result = github_ci.trigger_ci("o/r", "ci.yml", "main", wait=True, gh_path="gh", sleep=lambda _: None)
    assert result["accepted"] is True
    assert result["status"] == "completed"
    assert result["conclusion"] == "failure"
    assert github_ci._exit_code(result, waited=True) == 1


def test_authentication_error_is_classified(monkeypatch):
    error = github_ci.GitHubCIError("not logged into github.com", "authentication_error")
    monkeypatch.setattr(github_ci, "run_gh", lambda *args, **kwargs: (_ for _ in ()).throw(error))
    result = github_ci.trigger_ci("o/r", "ci.yml", "main", gh_path="gh")
    assert result["accepted"] is False
    assert result["error_type"] == "authentication_error"


def test_run_gh_does_not_use_shell(monkeypatch):
    calls = []
    completed = subprocess.CompletedProcess(["gh"], 0, stdout="ok\n", stderr="")
    monkeypatch.setattr(github_ci.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)) or completed)
    assert github_ci.run_gh("gh", ["auth", "status"]) == "ok"
    assert calls[0][0][0] == ["gh", "auth", "status"]
    assert "shell" not in calls[0][1]


def test_invalid_request_does_not_call_github(monkeypatch):
    monkeypatch.setattr(github_ci, "run_gh", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")))
    result = github_ci.trigger_ci("missing-owner", "ci.yml", "main", gh_path="gh")
    assert result["accepted"] is False
    assert result["error_type"] == "invalid_request"
