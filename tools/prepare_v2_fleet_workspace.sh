#!/usr/bin/env bash
# Prepare a disposable Git-only workspace, never a production checkout.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo "Usage: bash tools/prepare_v2_fleet_workspace.sh /path/to/new-workspace" >&2
  exit 2
fi
target="$1"
case "$target" in
  /|/tmp|/home|*/deployment-agent|*/universal-deployment-agent|*/.config|*/.config/*)
    echo "Refusing unsafe workspace" >&2; exit 2 ;;
esac
if [[ -e "$target" ]]; then
  echo "Workspace must not exist; never overwrite checkout" >&2
  exit 2
fi
mkdir -m 700 -- "$target"
target="$(cd -- "$target" && pwd -P)"
repos=(
  general-search Notes XmasList flask_Motorbike-Cost-Tracker1
  mermaid-display-app mermaid_dashboard internet_pricing whisperdesk
  PackBridge querybridge wallpaper CatManager Allocraft GiftVault
  should-cost-intelligence-next AutoKeeper roundabout_designer CueCraft
  DAXBridge flowchain_studio
)
for name in "${repos[@]}"; do
  remote="$name"
  [[ "$name" == "internet_pricing" ]] && remote="Internet_pricing"
  git clone --no-checkout --single-branch --branch feature/uda-manifest-v2-review \
    "https://github.com/zageabb/${remote}.git" "$target/$name"
  git -C "$target/$name" fetch --no-tags origin \
    feature/uda-manifest-v1:refs/heads/feature/uda-manifest-v1
done
echo "Workspace prepared: $target"
