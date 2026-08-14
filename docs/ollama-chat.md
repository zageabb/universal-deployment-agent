# Ollama Chat reference deployment

The repository includes the live reference configuration used under `/home/zageabb/ollama-chat`.

## Registered applications

| Application | Service | Port | Deployment state |
|---|---|---:|---|
| Tender Designer | `ollama-chat-tender-designer.service` | 5050 | Automatic |
| Context Lab | `ollama-chat-context-lab.service` | 5051 | Automatic |
| Flask Chat | `ollama-chat-flask-chat.service` | 5000 | Monitor-only; stopped |
| General Search | `ollama-chat-general-search.service` | 5053 | Automatic |
| Price Estimator | `ollama-chat-price-estimator.service` | 5055 | Automatic |
| System Knowledge Designer | `ollama-chat-system-knowledge-designer.service` | 5015 | Automatic |

The authoritative host registry is `~/.config/deployment-agent/config.json`. The checked-in file under `examples/ollama-chat` is a reviewed reference and contains no credentials.

## Root launchers

The following executable files live directly under `/home/zageabb/ollama-chat`:

```text
tender_start
context_lab_start
flask_chat_start
general_search_start
price_estimator_start
system_knowledge_designer_start
deployment_agent_start
```

Each application launcher delegates to its systemd user service. This prevents the duplicate background processes that can occur with repeated `nohup` commands.

Legacy launcher names may remain as compatibility wrappers, including `start`, `context_lab`, `general_search`, `price_start`, and `system_start`.

## Server-managed state

Application credentials are stored in mode-600 files beneath:

```text
~/.config/ollama-chat/
```

Preserved startup scripts, deployment backups, and pre-migration logs are stored beneath:

```text
~/ollama-chat/server-state/
```

Price Estimator persistent data remains in its ignored `instance` directory and settings files. Those assets are not modified by Git deployment.

## Current exception

Flask Chat is registered and has a standardized launcher and service definition, but remains stopped and monitor-only because it was not running when the deployment agent was installed and its checkout still contains local state.

## Verification

```bash
systemctl --user list-timers deployment-agent.timer
systemctl --user status deployment-agent.service
~/.local/share/deployment-agent/deploy_agent.py \
  --config ~/.config/deployment-agent/config.json \
  --dry-run
```

The expected result is `current` for all prepared automatic applications and `monitored_dirty` for Flask Chat until it is prepared.
