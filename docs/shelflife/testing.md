# Testing

CI runs the complete inherited pytest suite plus Shelflife policy/database/HTTP tests, Python lint/types, Svelte checks/build, Chromium acceptance tests and a Docker image build. Tests never talk to production media servers.

```sh
uv run pytest tests/test_shelflife_policy.py tests/test_shelflife_retention.py tests/test_shelflife_routes.py
cd frontend
npx playwright test
```

Browser fixtures cover fetch/XHR submissions, default/forever choices, cancellation, Jellyfin success/failure handling, and an ordinary user's phone layout.

## Integration acceptance

Repeat after gateway, Seerr, Jellyfin or Roku updates:

- Both gateway ports respond and `nginx -t` succeeds. Scripts load without weakening CSP.
- The user's own Seerr session creates the request; no administrator key reaches the browser.
- Dates and instructions appear for a requested movie and season on the physical Roku and in Jellyfin Web.
- Favorite then immediately unfavorite on Roku, restart Shelflife, and verify the permanent keep persists.
- Another user can keep/extend; a shorter choice never reduces an existing keep.
- In an isolated library with disposable files, verify expiry through Arr, exact season scope, request reconciliation and playback deferral. Never accelerate production deadlines to test this.
- An unavailable upstream defers cleanup. Normal playback, seeking and websocket updates work through the gateway.

Physical Roku rendering and real Arr deletion are manual acceptance checks; browser fixtures do not prove them. Keep production deletion paused until they pass.
