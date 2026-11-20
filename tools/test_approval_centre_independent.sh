#!/usr/bin/env bash
# Independently run UDA V2 Approval Centre regression tests, without Actions.
# Does not deploy, run manifest commands, modify registries or use production data.
set -euo pipefail

if [[ $# != 1 ]]; then
  echo "Usage: bash tools/test_approval_centre_independent.sh /path/to/NEW-private-output-dir" >&2
  exit 2
fi
dest="$1"
if [[ -e "$dest" || -L "$dest" ]]; then
  echo "Evidence output path already exists; refusing to overwrite" >&2
  exit 2
fi
repo="$(git rev-parse --show-toplevel)"
if [[ "$(git -C "$repo" branch --show-current)" != "feature/uda-v2-independent-validation" ]]; then
  echo "Run only on the independent UDA V2 review branch" >&2
  exit 2
fi
if [[ -n "$(git -C "$repo" status --porcelain)" ]]; then
  echo "Require a clean branch with committed review code" >&2
  exit 2
fi
if [[ ! -d "$(dirname "$dest")" ]]; then
  echo "Evidence output parent does not exist" >&2
  exit 2
fi
if [[ "$(realpath -m "$dest")" == "$repo/"* ]]; then
  echo "Evidence must be outside source checkout" >&2
  exit 2
fi
mkdir -m 700 -- "$dest"
dest="$(cd "$dest" && pwd -P)"
commit="$(git -C "$repo" rev-parse HEAD)"
printf '%s\n' "$commit" > "$dest/source-commit.txt"
python3 --version > "$dest/python-version.txt" 2>&1
cd "$repo"
# Tests must use tmp_path; no production deployment/host service permissions.
set +e
python3 -m pytest -q tests/test_approval_centre.py tests/test_dashboard.py \
  > "$dest/approval-and-dashboard.log" 2>&1
targeted=$?
python3 -m pytest -q > "$dest/full-uda-regression.log" 2>&1
full=$?
set -e
printf 'commit=%s\ntargeted_exit=%s\nfull_exit=%s\n' \
  "$commit" "$targeted" "$full" > "$dest/results.txt"
if [[ "$targeted" != 0 || "$full" != 0 ]]; then
  echo "Independent tests failed or could not start; see private evidence at $dest" >&2
  exit 1
fi
echo "Independent checks succeeded on $commit; evidence at $dest"
