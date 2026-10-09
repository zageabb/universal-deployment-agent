# UDA subpath compatibility: application migration standard

Status: migration standard established 2026-10-09; individual application implementations **not implied complete**.

## Scope and discovery

**Hard scope restriction (user decision 2026-10-09): change ONLY applications currently listed in the live UDA application registry.** Do not modify any unlisted GitHub repository, even if it is a web application, deployed independently, or mentioned in historical notes. An entry need not yet have `proxy_enabled=true` to be in scope, but changes should only be made when the entry is confirmed in the live registry. Obtain the live registry/inventory first; the source-controlled `config.example.json` is illustrative and `UBUNTU_PORTS.md` is a historical snapshot, **not authoritative membership evidence**. Do not mechanically change CLI utilities, extensions, libraries, prototypes or inactive services unless specifically listed as a UDA application and its hosted runtime needs adjustment. Capture deployed service, URL, slug, port, framework, existing auth, health route, and owner. GitHub repositories and UDA entries are not necessarily 1:1.

Public origin: `https://tanyaanne.ddns.net`; canonical app URL: `/apps/<slug>/`. Treat origin and slug as deployment configuration, not hardcoded application constants. Preserve ordinary root-hosted local access.

## Proxy contract and boundary

- Ensure requests dispatched under `/apps/<slug>/` are routed consistently: choose **strip-prefix plus forwarded prefix** OR **retain-prefix with native base path** per service. Do not apply both prefix transformations.
- Normalize `/apps/<slug>` to `/apps/<slug>/` with a redirect preserving query strings.
- Set forward metadata from **Caddy itself**, overwriting untrusted client-supplied `Forwarded`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Forwarded-Prefix`, and any identity headers. Trust only known ingress proxy hops (not blanket trust of arbitrary callers).
- UDA's proxy authentication/authorization check is the **ingress boundary**. Bind app backends to loopback or a private container network, and prevent direct remote bypass. Do not treat a health endpoint as proof of user authorization.
- Decide cookie boundaries deliberately. Each app uses a unique cookie name and a narrow app `Path=/apps/<slug>/` where supported; UDA portal auth remains independent. Distinct names alone do not guarantee isolation. Audit app-specific logout and cookie clear paths. If backend receives stripped path, explicitly configure cookie Path for public prefix.
- Avoid spoofed or accidental identity propagation. Apps with their own auth should keep enforcing it unless the UDA integration is explicitly designed and tested as single-sign-on. Protect mutating endpoints against CSRF as appropriate.

## Framework implementation patterns

### Flask/Werkzeug
- Use `ProxyFix(..., x_proto=1, x_host=1, x_prefix=1)` only for deployments **behind one trusted ingress hop**, adjusting counts to actual topology.
- Ensure `SCRIPT_NAME`/URL generation reflects the public prefix in request context. Generate routes and static assets with `url_for`, including redirects.
- Set app-specific `SESSION_COOKIE_NAME`, secure/HTTP-only/same-site settings, and cookie Path appropriate to the public prefix. Avoid assuming `ProxyFix` configures the cookie Path.
- Keep development root hosting functional, and test both modes.

### FastAPI/Starlette/ASGI
- Do **not** copy Flask `ProxyFix`. Configure ASGI `root_path` consistently with Caddy's strip-prefix behaviour and trusted proxy hosts/headers.
- Verify generated OpenAPI/docs, redirects, API routes, static mounts, and WebSocket routes under the public path.
- Set CORS/CSRF/session cookie settings with same-origin access in mind.

### React/Vite/Vue/SPAs
- Configure build asset base and SPA router basename from the selected public prefix; support env/build-time configuration.
- Relative fetch URL resolution must be verified on nested routes: `fetch("api/items")` is **not automatically safe** at `/apps/slug/settings/page`. Prefer a single configured base/API URL helper.
- Check history-mode fallback only within the app prefix, dynamic imports, CSS `url(...)`, manifests, icons, service worker scope, WebSockets, EventSource and deep-link refresh.
- Don't place bearer tokens in publicly readable build configuration.

### Other runtimes
- Explicitly audit Streamlit, Gradio, Node/Express, Next.js, and web server/static sites for their own supported base-path options, socket/stream endpoints and redirects. No generic Python middleware applies to all stacks.
- Chrome/browser extensions (for example TabVault) require a separate assessment; UDA publication is not a reason to rewrite extension URLs.

## Contract tests (required per app)

1. Root-mode local launch still works where supported.
2. Canonical public route + trailing-slash redirect work through **real Caddy/UDA**.
3. CSS, fonts, images, script chunks, favicon, PWA/static manifest load at the prefixed URL.
4. Navigation, deep links, refresh, 404/error pages, redirects, OAuth callback if any, and all `Location` headers stay within the app route.
5. GET/POST/forms, API calls, query strings, cookies, CSRF and logout behave correctly without affecting the UDA portal or sibling apps.
6. WebSocket, SSE, streaming, large uploads/downloads work where used; match proxy body-size/timeout limits.
7. Unauthorized and unauthenticated requests cannot reach app data; bypass attempts using direct backend port, forged proxy headers, encoded paths, traversal-like paths and cross-app cookies are rejected.
8. Health route is safe and reachable by the **intended internal monitor** without accidental public bypass.
9. App CI passes and UDA proxy configuration validates. Record live acceptance separately.

## Deployment recipe

1. Inventory UDA live registry, treating it as the exclusive allowlist; mark `compatible`, `requires work`, `not applicable`, or `not assessed`.
2. Prioritize CatManager regression baseline **only if it is listed in the live UDA registry**, then other listed browser apps in risk order. Do not infer membership from GitHub or the historical port inventory.
3. For each app: read AGENTS.md and DEVELOPMENT.md, add an app-specific `OPS-UDA-SUBPATH` task, implement matching framework changes, tests and CI, then canary enable its UDA route. Do not enable all public routes simultaneously.
4. Update UDA registry `proxy_enabled`, `proxy_slug`, `allowed_groups`, `app_url` **after** compatibility and authorization testing. Keep local `app_url` host/port specific to the real service. Never commit production server config, secrets, or credentials.
5. Record migration status, changes, commit, CI run and human acceptance in the registry/onboarding log.

## Known starting points

- **CatManager**: repository DEVELOPMENT.md records OPS-050 Flask prefix + unique cookie implementation. Still requires live end-to-end UDA/Caddy validation including cookie paths and sibling-app interactions.
- **SideCar**: documented FastAPI + React architecture. Requires ASGI root_path, SPA asset/router base, WebSocket/API and file upload testing; not a Flask middleware conversion.
- **TabVault**: browser extension; assess only any separately hosted service, not extension packaging.
- All other apps: status **not assessed** until actual code and live UDA inventory reviewed.

## Important corrections to generic advice

- `SESSION_COOKIE_NAME` uniqueness is useful but incomplete; explicit cookie Path and secure flags matter.
- A relative `fetch("api/items")` resolves against the *current document URL*, not a guaranteed application root.
- `ProxyFix` can be unsafe if proxy headers are not filtered and direct access remains possible.
- A successful `/health` response does not demonstrate that the authentication guard is correct.
