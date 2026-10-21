"""Resolve repository visibility from GitHub metadata for UDA's web views."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

GITHUB_REPOSITORY_PATTERN = re.compile(r'^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?$')


def github_repository_slug(repo_path: str) -> str | None:
    """Return owner/name for a GitHub origin without exposing remote credentials."""
    try:
        remote = subprocess.run(
            ['git', '-C', str(Path(repo_path).expanduser()), 'remote', 'get-url', 'origin'],
            capture_output=True, text=True, timeout=2, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if remote.startswith('git@github.com:'):
        candidate = remote.removeprefix('git@github.com:')
    else:
        try:
            parts = urlsplit(remote)
        except ValueError:
            return None
        if parts.scheme not in {'https', 'http', 'ssh'} or (parts.hostname or '').lower() != 'github.com':
            return None
        candidate = parts.path.lstrip('/')
    match = GITHUB_REPOSITORY_PATTERN.fullmatch(candidate)
    return f"{match['owner']}/{match['repo']}" if match else None


def github_repository_visibility(repo_path: str) -> str | None:
    """Read GitHub visibility live; private repositories require an API token."""
    slug = github_repository_slug(repo_path)
    if not slug:
        return None
    headers = {
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'Universal-Deployment-Agent',
    }
    token = os.environ.get('UDA_GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    request = Request(f'https://api.github.com/repos/{slug}', headers=headers)
    try:
        with urlopen(request, timeout=3) as response:
            data = json.loads(response.read())
        visibility = data.get('visibility')
        return visibility if visibility in {'public', 'private'} else None
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        # Missing auth, rate limits, or transient GitHub outages must not break the portal.
        return None


def resolved_repo_visibility(entry: dict) -> str | None:
    """Prefer current GitHub metadata and retain the registry value as an offline fallback."""
    try:
        detected = github_repository_visibility(entry['repo_path'])
    except (KeyError, TypeError):
        detected = None
    return detected or (entry.get('repo_visibility') if entry.get('repo_visibility') in {'public', 'private'} else None)
