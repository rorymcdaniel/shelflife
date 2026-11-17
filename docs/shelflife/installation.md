# Installation and rollout

Copy `deploy/env.example` to `deploy/.env`, set the existing media network and internal service addresses, then start the [Compose example](../../deploy/compose.example.yaml). Compose often prefixes network names; check `docker network ls`.

```sh
docker compose -p shelflife --env-file deploy/.env -f deploy/compose.example.yaml up -d --build
```

1. Open `http://localhost:8010` and complete setup with a strong administrator password. Connect Jellyfin as the main server, exactly one Seerr, and relevant Sonarr/Radarr services. Use their original internal Docker addresses, never gateway addresses. Enable Jellyfin sign-in for household dashboard users.
2. Run a full library sync and check inventories. Do not create separate age/deletion rules for the same policy. Shelflife owns enrollment/deadlines and reuses Reclaimerr's deletion engine.
3. Open **Library retention → Manage library retention**, enter public Seerr/Jellyfin origins and your time zone, and enable preview. Its activation timestamp excludes older requests.
4. Route your existing HTTPS proxy's Seerr destination to `127.0.0.1:5056`, Jellyfin to `127.0.0.1:8097`. Keep public hostnames, TLS, access controls and websocket/streaming support. A containerized proxy on the media network can use `shelflife-gateway:8080`/`:8081` instead.
5. Check the request prompt and cancel it. Submit a disposable test request and verify enrollment. Check browser Keep. On Roku, favorite then immediately unfavorite a test title: its keep must remain permanent. Roku must use the gateway address, including on the LAN; direct port `8096` bypasses capture.
6. To validate descriptions, turn preview off **with cleanup paused**. Available titles receive a fresh full window. Check dates and Favorite instructions on the physical Roku, browser and phone. Confirm playback. Unpause only after the [acceptance checks](testing.md) pass.

For a public admin hostname, set `SHELFLIFE_PUBLIC_URL` to its HTTPS origin and `COOKIE_SECURE=true`, then recreate the container. Do not expose the unconfigured setup wizard. Configure trusted proxy settings per inherited Reclaimerr docs if using forwarded authentication. Keep gateway/application ports on localhost unless protected by a private network/firewall.

## Backups and rollback

Back up `shelflife_shelflife-data` before upgrades. It contains credentials and permanent keeps: never commit it. To roll back routing, pause Shelflife and point the proxy at the original ports. Stop its containers using the same Compose command with `stop`. Avoid `down -v`, which destroys the ledger.

Metadata notices remain after rollback. They are a prefixed overview paragraph with the synopsis below a blank line; refresh metadata or remove the prefix when uninstalling. An old database backup may lack newer keeps: reconcile in preview before activating it.

## Troubleshooting

- **No prompt/button:** confirm the gateway page contains `/shelflife/assets/` scripts and reload cached assets. CSP must permit same-origin scripts; do not disable it globally.
- **Missing intent error:** the request reached the bridge without the integration. Fix script loading rather than bypassing the safeguard.
- **No dates:** check activation cutoff, full inventory sync, TMDB IDs and complete-season evidence. Checks run every minute; see deferred errors on Library retention.
- **No deletion:** preview, pause, playback, uncertainty and keeps intentionally prevent cleanup.
- **Keep failure:** the Jellyfin account must be enabled and able to see that item. Unsupported media types retain their ordinary Favorite behavior.
