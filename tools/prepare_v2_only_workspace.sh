#!/usr/bin/env bash
# Opt-in preparation only. Creates NEW disposable Git checkouts; never deploys.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo "Usage: bash tools/prepare_v2_only_workspace.sh /path/to/NEW-empty-workspace" >&2
  exit 2
fi
target="$1"
case "$target" in
  ""|/|/tmp|/home|/home/*/|*/deployment-agent|*/universal-deployment-agent|*/.config|*/.config/*)
    echo "Refusing unsafe workspace path" >&2; exit 2 ;;
esac
if [[ -e "$target" || -L "$target" ]]; then
  echo "Refusing existing workspace: do not overwrite or mix with live checkouts" >&2
  exit 2
fi
parent="$(dirname -- "$target")"
if [[ ! -d "$parent" || -L "$parent" ]]; then
  echo "Workspace parent must be an existing real directory" >&2; exit 2
fi
mkdir -m 700 -- "$target"
target="$(cd -- "$target" && pwd -P)"
repos=(
  tender_designer lucky-lab-slot-statistics Bank_of_mum context-studio
  research-core SideCar NetworkBridge Sheetbridge LedgerOne
  bottle_factory_game should-cost-intelligence
)
for name in "${repos[@]}"; do
  echo "Fetching immutable source for ${name} (review branch only)"
  git clone --no-checkout --single-branch --branch feature/uda-v2-review \
    "https://github.com/zageabb/${name}.git" "${target}/${name}"
done
echo "Prepared 11 V2-only read-only source worktrees: ${target}"
echo "This command fetched source only; it did not execute manifest commands."
