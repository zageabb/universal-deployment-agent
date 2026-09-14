# Ubuntu server port inventory

Verified **14 September 2026** on **192.168.1.249** using `ss -ltnp`,
`systemctl --user show/cat`, Docker published-port mappings, Git remotes and
HTTP checks. This is the observed deployment, not a list of development defaults.
Port assignments can change; repeat these checks before deploying another app.

## Active applications

All listed application URLs returned HTTP 200 during verification, except the
authenticated deployment dashboard, which returned HTTP 401 as expected.

| GitHub repository | Host TCP ports | Source checkout | User systemd units / runtime |
|---|---|---|---|
| [Bank_of_mum](https://github.com/zageabb/Bank_of_mum) | Web: **5080**, API: **5082** | `/home/zageabb/flask/Bank_of_mum` | `bank-of-mum-api.service`, `bank-of-mum-web.service` |
| [Flask_Question](https://github.com/zageabb/Flask_Question) | Application: **5081** | `/home/zageabb/flask/Flask_Question` | `migrated-flask@Flask_Question.service` |
| [Heart](https://github.com/zageabb/Heart) | Application: **5062** | `/home/zageabb/flask/Heart` | `migrated-flask@Heart.service` |
| [Internet_pricing](https://github.com/zageabb/Internet_pricing) | Application: **5054** | `/home/zageabb/ollama-chat/internet-pricing` | `ollama-chat-internet-pricing.service` |
| [Notes](https://github.com/zageabb/Notes) | Application: **5063** | `/home/zageabb/flask/Notes` | `migrated-flask@Notes.service` |
| [SCM_Agent](https://github.com/zageabb/SCM_Agent) | Application: **5073** | `/home/zageabb/flask/SCM_Agent` | `migrated-static@SCM_Agent.service` |
| [ScreenDesign](https://github.com/zageabb/ScreenDesign) | Application: **5064** | `/home/zageabb/flask/ScreenDesign` | `migrated-flask@ScreenDesign.service` |
| [XmasList](https://github.com/zageabb/XmasList) | Application: **5065** | `/home/zageabb/flask/XmasList` | `migrated-flask@XmasList.service` |
| [camper-power-studio](https://github.com/zageabb/camper-power-studio) | Web: **5077**, API: **8001** | `/home/zageabb/apps/camper-power-studio` | `camper-power-studio.service` |
| [context-lab](https://github.com/zageabb/context-lab) | Application: **5051** | `/home/zageabb/ollama-chat/context-lab` | `ollama-chat-context-lab.service` |
| [context-studio](https://github.com/zageabb/context-studio) | Web: **5075**, API: **8074** | `/home/zageabb/ollama-chat/context-studio` | `context-studio-backend.service`, `context-studio-frontend.service` |
| [flask_MarginTrans](https://github.com/zageabb/flask_MarginTrans) | Application: **5066** | `/home/zageabb/flask/flask_MarginTrans` | `migrated-flask@flask_MarginTrans.service` |
| [flask_Motorbike-Cost-Tracker1](https://github.com/zageabb/flask_Motorbike-Cost-Tracker1) | Application: **5067** | `/home/zageabb/flask/flask_Motorbike-Cost-Tracker1` | `migrated-flask@flask_Motorbike-Cost-Tracker1.service` |
| [flask_SpreadSheet](https://github.com/zageabb/flask_SpreadSheet) | Application: **5068** | `/home/zageabb/flask/flask_SpreadSheet` | `migrated-flask@flask_SpreadSheet.service` |
| [general-search](https://github.com/zageabb/general-search) | Application: **5053** | `/home/zageabb/ollama-chat/general-search` | `ollama-chat-general-search.service` |
| [lucky-lab-slot-statistics](https://github.com/zageabb/lucky-lab-slot-statistics) | Application: **5020** | `/home/zageabb/slot-statistics-lab` | `lucky-lab` Docker container |
| [markdown-migration-studio](https://github.com/zageabb/markdown-migration-studio) | Application: **5074** | `/home/zageabb/flask/Template_Changer` | `migrated-flask@Template_Changer.service` |
| [mermaid_dashboard](https://github.com/zageabb/mermaid_dashboard) | Application: **5071** | `/home/zageabb/flask/mermaid_dashboard` | `migrated-flask@mermaid_dashboard.service` |
| [mermaid_final](https://github.com/zageabb/mermaid_final) | Application: **5070** | `/home/zageabb/mermaid/mermaid_final` | `migrated-flask@mermaid-display-app.service` |
| [reflex_AgentDemo](https://github.com/zageabb/reflex_AgentDemo) | Application: **5072** | `/home/zageabb/flask/reflex_AgentDemo` | `migrated-flask@reflex_AgentDemo.service` |
| [should-cost-intelligence](https://github.com/zageabb/should-cost-intelligence) | Application: **5076** | `/home/zageabb/ollama-chat/should-cost-intelligence` | `ollama-chat-should-cost-intelligence.service` |
| [should-cost-price-estimator](https://github.com/zageabb/should-cost-price-estimator) | Application: **5055** | `/home/zageabb/ollama-chat/should-cost-price-estimator` | `ollama-chat-price-estimator.service` |
| [system-knowledge-designer](https://github.com/zageabb/system-knowledge-designer) | Application: **5015** | `/home/zageabb/ollama-chat/system-knowledge-designer` | `ollama-chat-system-knowledge-designer.service` |
| [tender_designer](https://github.com/zageabb/tender_designer) | Application: **5050** | `/home/zageabb/ollama-chat/Tender_Designer` | `ollama-chat-tender-designer.service` |
| [universal-deployment-agent](https://github.com/zageabb/universal-deployment-agent) | Authenticated dashboard: **5030**, Application Home: **5048** | `/home/zageabb/ollama-chat/universal-deployment-agent` | `deployment-agent-dashboard.service`, `deployment-agent-home.service` |

The `mermaid-display-app` registry entry is an alias for the live service on
**5070**. Its systemd override runs **mermaid_final** from
`/home/zageabb/mermaid/mermaid_final`, not the older checkout under `~/flask`.
Check `systemctl --user cat migrated-flask@mermaid-display-app.service` before
updating that application.

Application Home runs from the installed deployment-agent runtime at
`/home/zageabb/.local/share/deployment-agent`; its source repository is
`~/ollama-chat/universal-deployment-agent`.

## Other application and infrastructure listeners

These listeners are present on the server but do not map to an identified
owned application repository. Host ports are distinct from container ports.

| Service | Host TCP port | Container port / observation |
|---|---:|---|
| Flask form app | 5069 | User unit `migrated-flask@flask_form_app.service`; HTTP 200; checkout `~/flask/flask_form_app` has no Git remote |
| Ollama Web-Search Agent | 8000 | Container `ollama-agent`, 8000 → 8000; Compose directory `~/ollama-stack` has no Git remote |
| Open WebUI | 3000 | Container `open-webui`, 3000 → 8080 |
| Ollama | 11434 | Container `ollama-old`, 11434 → 11434; the separate `ollama` container has no host-published port |
| Ollama authentication proxy | 8080 | Container `ollama-auth-proxy`, 8080 → 8080 |
| SearXNG | 8081 | Container `searxng`, 8081 → 8080 |
| Mermaid Live Editor | 9000 | Container `mermaid-live`, 9000 → 8080; upstream repository is `mermaid-js/mermaid-live-editor` |
| Jupyter | 10000 | Container `nostalgic_booth`, 10000 → 8888 |
| PostgreSQL | 5432 | Container `postgres_db`, 5432 → 5432 |
| pgAdmin | 5049 | Container `pgadmin_web`, 5049 → 80 |
| SSH | 22 | Host service |
| VNC listeners | 5900–5903 | Bound to 127.0.0.1 only |
| CUPS | 631 | Bound to loopback only |

DNS listeners also use port 53 on `127.0.0.53` and `192.168.122.1`; these are
host infrastructure rather than application web ports.

## Checkouts without a verified live application port

| Repository | Observed status |
|---|---|
| [flask_chat](https://github.com/zageabb/flask_chat) | User service inactive; configured port 5000 has no listener |
| [PUXAI](https://github.com/zageabb/PUXAI) | Checkout exists; development default 8787 has no listener |
| [Pricing_Analysis_Lab](https://github.com/zageabb/Pricing_Analysis_Lab) | Checkout exists; development default 5052 has no listener |
| [Motorbike-Cost-Tracker1](https://github.com/zageabb/Motorbike-Cost-Tracker1) | Older Reflex checkout is not serving the live Flask replacement, which uses 5067 |
| [mermaid-display-app](https://github.com/zageabb/mermaid-display-app) | Registry/service name retained, but live source is mermaid_final on 5070 |
| [research-core](https://github.com/zageabb/research-core) | Shared Python library; no standalone HTTP service registered |

## Avoid the known port mix-ups

- Bank of Mum: web **5080**, API **5082**. Port 8000 is a different application.
- Context Studio: web **5075**, API **8074**. Its example Docker ports differ.
- Camper Power Studio: web **5077**, API **8001**. Port 5075 is Context Studio.
- Internet Pricing: **5054**. General Search uses **5053**.
- Application Home: **5048**. Port 5049 is pgAdmin.
- Mermaid application: **5070**, with source in mermaid_final. Mermaid Live Editor is **9000**.

## Repeat the audit

```bash
ss -ltnp
systemctl --user list-units --type=service --state=running
systemctl --user cat bank-of-mum-api bank-of-mum-web
docker ps --format '{{.Names}} | {{.Ports}}'
curl -fsS http://127.0.0.1:5082/api/health
curl -fsS http://127.0.0.1:8074/api/health
curl -fsS http://127.0.0.1:8001/health
```

Inspect each service's effective `WorkingDirectory`, including drop-in overrides,
and compare its Git remote before publishing changes. The deployment registry's
`health_url` may point to an API port rather than the browser-facing frontend.
Do not publish local environment files or authentication tokens with this inventory.
