# UDA deployment reporting — development specification

## Objective
Show what is actually deployed for each application and publish verified production
deployments to **that application's own GitHub repository** using the GitHub
Deployments API. The UDA dashboard remains the central inventory. No source
commits or GitHub Actions execution are required.

## Safety first
- **Read-only by default**: `python deployment_reporting.py --config /path/to/registry.json`
  prints an inventory; it never updates or restarts services.
- Do not infer a running build solely from the checkout HEAD, `main`, or a
  running systemd service. An application-specific `deployed_sha_file` is required.
- Missing attestation = `unverified`; dirty checkout = `dirty`;
  attestation different from checkout = `mismatch`. These states cannot publish.
- If a deployed commit is verified but behind the configured origin tracking
  branch, display `behind_remote`, not a false deployment failure.
- The remote SHA reflects the **last locally fetched** `origin/<branch>`; the
  dashboard does not fetch GitHub at page load.
- For the UDA checkout currently using local modifications, reporting must
  remain unverified/dirty until a controlled clean release is deployed.
- Do not put tokens, private settings, backups or server environments in Git.

## Registry fields (optional per application)
```json
{
  "name": "example",
  "repo_path": "/srv/apps/example",
  "branch": "main",
  "deployed_sha_file": "/var/lib/uda/builds/example.sha",
  "github_environment": "production",
  "github_reporting_enabled": false
}
```
`deployed_sha_file` must be written atomically by the deployment procedure **only
after** the release is started and passes its health verification. It must contain
the full 40-character lowercase hexadecimal commit SHA for the running artifact.
A file created by simply reading the current checkout is not valid evidence.

## Publishing to GitHub
Opt in using `github_reporting_enabled: true` and a protected service
environment variable `UDA_GITHUB_DEPLOYMENT_TOKEN`, granting **Deployments:
write** on the selected application repositories. Then explicitly run:

```sh
python3 deployment_reporting.py --config /path/to/registry.json --publish
```

This creates a GitHub deployment for a verified commit, then publishes a
successful deployment status. A failed API request must be investigated;
GitHub publication does not change the deployment itself.

Do not schedule automatic publication yet. Before enabling that increment,
implement durable idempotency, a publishing history and policy for runtime
health transitions. Limit publishing to successful release events rather than
every monitoring poll.

## Acceptance plan before Ubuntu synchronisation
1. Unit tests for clean, dirty, mismatched and unverified checkouts.
2. Validate GitHub repository origin parsing; reject non-GitHub hosts.
3. Mock the Deployments API; verify ref/URL and reject invalid credentials
   and unverified runtime identity.
4. Run the full UDA regression suite and capture logs against the exact SHA.
5. Review archive/restore failure paths and reconcile partial state safely.
6. Merge the fully tested branch only when required checks are green.
7. Preserve the private Ubuntu backup, reconcile the dirty server checkout
   and deploy once, during a controlled maintenance window.
8. Verify the running artifact SHA through an independent runtime marker or
   immutable artifact manifest; don't create it from a dirty Git checkout.
9. Enable publishing on UDA first, then progressively on other applications.
10. Confirm each app's own GitHub Deployments tab shows the verified release.

## Future increments
- Durable publication state, retries and webhook delivery
- Current health/degraded/stopped states distinct from deployment success
- GitHub latest release/remote-SHA refresh and reconciliation
- Deployment audit and export API for ForgeBridge and desktop clients
- Signed release manifests and per-application release identity
