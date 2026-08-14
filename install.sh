#!/bin/sh
set -eu

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DATA_DIR=${XDG_DATA_HOME:-"$HOME/.local/share"}/deployment-agent
CONFIG_DIR=${XDG_CONFIG_HOME:-"$HOME/.config"}/deployment-agent
UNIT_DIR=${XDG_CONFIG_HOME:-"$HOME/.config"}/systemd/user

mkdir -p "$DATA_DIR" "$CONFIG_DIR" "$UNIT_DIR"
install -m 0755 "$SOURCE_DIR/deploy_agent.py" "$DATA_DIR/deploy_agent.py"
install -m 0755 "$SOURCE_DIR/dashboard.py" "$DATA_DIR/dashboard.py"
mkdir -p "$DATA_DIR/templates"
install -m 0644 "$SOURCE_DIR/templates/dashboard.html" "$DATA_DIR/templates/dashboard.html"
python3 -m venv "$DATA_DIR/venv"
"$DATA_DIR/venv/bin/pip" install -q -r "$SOURCE_DIR/requirements.txt"
install -m 0644 "$SOURCE_DIR/systemd/deployment-agent.service" "$UNIT_DIR/deployment-agent.service"
install -m 0644 "$SOURCE_DIR/systemd/deployment-agent.timer" "$UNIT_DIR/deployment-agent.timer"
install -m 0644 "$SOURCE_DIR/systemd/deployment-agent-dashboard.service" "$UNIT_DIR/deployment-agent-dashboard.service"
if [ ! -f "$CONFIG_DIR/config.json" ]; then
  install -m 0600 "$SOURCE_DIR/config.example.json" "$CONFIG_DIR/config.json"
  echo "Created $CONFIG_DIR/config.json; edit it before enabling the timer."
fi
systemctl --user daemon-reload
systemctl --user enable --now deployment-agent-dashboard.service
echo "Installed. Run a dry check before enabling:"
echo "$DATA_DIR/deploy_agent.py --config $CONFIG_DIR/config.json --dry-run"
echo "Then enable with: systemctl --user enable --now deployment-agent.timer"
echo "Dashboard: http://SERVER:5030 (username admin; password is dashboard_token in config.json)"
