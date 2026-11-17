# Security

Shelflife handles media-server credentials and can delete media after activation. Keep it behind your existing authenticated HTTPS deployment. Administration requires Reclaimerr authentication; Jellyfin controls validate the actual account and visible item; the Seerr bridge uses the caller's session.

Report vulnerabilities privately through **Security → Report a vulnerability** in this repository. If unavailable, contact the owner through their published GitHub profile contact before sharing sensitive details. Never put keys, databases, media lists or private deployment files in issues.

Only the latest Shelflife release is maintained. The first release is a preview. Dependency update pull requests and CI help catch regressions; there is no security support SLA.

Back up the application data volume: permanent keeps live there. Restoring an older backup can lose newer keeps; restart in preview and reconcile before enabling cleanup. Do not expose an unconfigured setup wizard or the Docker daemon publicly.
