# UDA application migration scope — 2026-10-09

Source: live-registry inventory supplied by application owner. **Exactly 36 enabled entries; this is the exclusive migration allowlist.** No other repositories/applications may be changed as part of DEV-003.

| UDA group | Registered application | Launcher | Public proxy status | Migration assessment |
|---|---|---|---|---|
| Infrastructure | Application Home | Hidden | Not stated | Review UDA portal internals; avoid self-proxy recursion |
| Infrastructure | Universal Deployment Agent | Hidden | Not stated | Review management surface; avoid exposing dashboard without explicit policy |
| TAIJU | General Search | Visible | Not published | UDA subpath implementation on draft PR [#3](https://github.com/zageabb/general-search/pull/3); test/CI/live verification pending |
| TAIJU | Internet Pricing | Visible | Not published | UDA subpath branch and draft PR [#4](https://github.com/zageabb/Internet_pricing/pull/4); CI/live verification pending |
| TAIJU | PackBridge | Visible | Not published | Needs assessment |
| TAIJU | Price Estimator | Visible | Not published | Needs assessment |
| TAIJU | Research Core | No launcher URL | Not published | Check for HTTP browser surface; may be not applicable |
| TAIJU | Should Cost Intelligence | Visible | Not published | Needs assessment |
| TAIJU – Development | Context Lab | Visible | Not published | Needs assessment |
| TAIJU – Development | Context Studio | Visible | Not published | Needs assessment; separate web/API |
| TAIJU – Development | Markdown Migration Studio | Visible | Not published | Needs assessment |
| TAIJU – Development | Mermaid Dashboard | Visible | Not published | Needs assessment |
| TAIJU – Development | Mermaid Display App | Visible | Not published | Needs assessment; alias/service mapping |
| TAIJU – Development | Notes | Visible | Not published | Needs assessment |
| TAIJU – Development | QueryBridge | Visible | Not published | Needs assessment |
| TAIJU – Development | System Knowledge Designer | Visible | Not published | Needs assessment |
| TAIJU – Development | WhisperDesk | Visible | Not published | Needs assessment |
| Personal | Bank of Mum | Visible | Not published | Needs assessment; separate web/API |
| Personal | Camper Power Studio | Visible | Not published | Needs assessment; separate web/API |
| Personal | Heart | Visible | Not published | Needs assessment |
| Personal | LedgerOne | Visible | Not published | Needs assessment |
| Personal | Lucky Lab | Visible | Not published | Needs assessment |
| Personal | Motorbike Cost Tracker | Visible | Not published | Needs assessment; verify active repo alias |
| Personal | Sidecar | Visible | Not published | Needs assessment; FastAPI + React, WebSocket/files |
| Personal | Tender Designer | Visible | Not published | Needs assessment |
| Personal | Wallpaper Animation Studio | Visible | Not published | Needs assessment |
| Development | Flask Chat | Visible | Not published | Needs assessment |
| Development | Flask Form App | Visible | Not published | Needs assessment; verify repo mapping |
| Development | Flask Question | Visible | Not published | Needs assessment |
| Development | Flask Spreadsheet | Visible | Not published | Needs assessment |
| Development | Reflex Agent Demo | Visible | Not published | Needs assessment |
| Development | SCM Agent | Visible | Not published | Needs assessment |
| Development | Screen Design | Visible | Not published | Needs assessment |
| Development | Xmas List | Visible | Not published | Needs assessment |
| HE Development | Margin Trans | Visible | Not published | Needs assessment |
| TAIJU WEB Access | CatManager | Visible | **Published** | Existing code claims prefix compatibility; regression + live test required |

Counts by group: Infrastructure 2, TAIJU 6, TAIJU – Development 9, Personal 9, Development 8, HE Development 1, TAIJU WEB Access 1. **Total: 36**, **enabled: 36**, **launcher-visible: 33**, **launcher-hidden: 2**, **no launcher URL: 1**, **currently publicly proxied: 1**.

## Rules

1. Only rows above can lead to application source changes. If a UDA display name differs from the repository name, verify the current *live* entry's `repo_path` / running service and Git remote first.
2. UDA membership does **not** mean a change is required: audit and classify `compatible`, `needs changes`, `not applicable`, or `blocked`. Research Core might be non-web; infrastructure must not be exposed casually.
3. Do not set `proxy_enabled=true` for the remaining 35 entries as a byproduct of source compatibility. Publication, group entitlements and real-world access tests are separate tasks.
4. Preserve the original app groups unless the owner expressly requests changes. No bulk permission or group migration.
5. Work per application: investigate framework, write scoped implementation tasks to its DEVELOPMENT.md if available, preserve AGENTS.md workflow, modify/test only as needed, report evidence and status back here.
6. The inventory establishes *membership*, not current ports, slugs, code frameworks, or app safety; use running registry metadata to establish those details before edits.
