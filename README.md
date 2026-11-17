# Shelflife

New requests get room to breathe. Keep the ones that matter.

Shelflife adds a shared retention policy to **Seerr + Jellyfin**, extending [Reclaimerr](https://github.com/jessielw/Reclaimerr). It is intended for a small, trusted household library.

- New Seerr requests default to **60 days from availability**, with an explanation and a longer/forever choice before submission.
- A requested TV season gets its window when the **complete season** is available. Other seasons are not enrolled by that request.
- Jellyfin descriptions show the date and how to keep the title. Leaving Soon collections highlight the final seven days.
- Any signed-in user can keep a title for longer or forever, immediately. There is no approval queue.
- On the **official Roku app**, Favorite means keep forever. Unfavoriting does **not** undo that keep. Favoriting an episode protects its season; favoriting a show covers present and future seasons.
- Browsers, including phone browsers, get a dedicated **Keep…** button. No Roku fork or custom app installation is required.
- Longer and permanent keeps always win. Old requests and the existing library are not automatically enrolled.

**Status: initial preview.** Automated tests cover the retention contract and browser integrations. Validate the notice and Favorite behavior on your physical Roku before turning on deletion. Preview is the default: it records proposed deadlines without changing files, descriptions or collections. Turning preview off gives available titles a fresh full viewing window.

## Run with Docker

Clone this repository and follow [installation and rollout](docs/shelflife/installation.md). The supplied [Compose example](deploy/compose.example.yaml) starts the application and a small Nginx gateway on localhost. It does not replace your existing media containers.

```sh
cp deploy/env.example deploy/.env
# Set MEDIA_NETWORK to the existing Docker network used by your media containers.
docker compose -p shelflife --env-file deploy/.env -f deploy/compose.example.yaml up -d --build
```

Open `http://localhost:8010`, complete setup, connect Jellyfin, Seerr, Sonarr and Radarr, then open **Library retention**. Use the internal service addresses for these connections, so they never loop back through the gateway.

Your existing HTTPS reverse proxy must route Seerr to gateway port `5056` and Jellyfin to gateway port `8097`. All clients, including Roku, need to use that Jellyfin address. The gateway records Favorites before forwarding them, including favorites removed before a periodic scan can observe them. Direct connections bypass that guarantee.

## Compatibility and limits

One main Jellyfin server, one enabled Seerr connection, and one application process are supported. Sonarr is required to verify complete seasons. Movies/seasons need stable TMDB identifiers and a completed Reclaimerr library sync. Missing identifiers, uncertain finale information, incomplete inventories, unavailable servers and active playback defer cleanup.

The Keep button supports Jellyfin Web and phone browsers. Native mobile clients may display the metadata notice and can use Favorite, but are not promised a custom button. Subpath installations are not supported. Existing TLS and access controls remain the reverse proxy's responsibility.

The gateway injects small scripts into stock web clients. Seerr/Jellyfin updates can change those interfaces; repeat the [acceptance checklist](docs/shelflife/testing.md) after updates. Their normal update channels remain unchanged. Client updates may require an integration fix.

## Development and contributions

See [CONTRIBUTING.md](CONTRIBUTING.md) for checks, [the product contract](docs/shelflife/product.md) for expected behavior, and [research](docs/shelflife/research.md) for the choice of foundation.

Python 3.11–3.13 and Node 26 are supported by the current build. Lockfiles are committed. CI runs backend tests, Python lint/types, frontend checks/build, browser acceptance tests and the container build on pull requests. Dependabot proposes updates; it does not merge them automatically.

## License and upstream

GPL-3.0; see [LICENSE.md](LICENSE.md). Reclaimerr's license, attribution and history are retained. Shelflife is an independent derivative, not an official Reclaimerr, Jellyfin or Seerr release. The initial base is Reclaimerr **0.6.12**, commit `76574445f45bf993d2388a31c8600f7bf46b73dc`.

The additions live primarily in `backend/shelflife`, with a migration, a retention page, a cleanup guard and the gateway. See [updating](docs/shelflife/updating.md) for maintaining the upstream relationship. Inherited documentation under `docs/` describes Reclaimerr's administration features; Shelflife instructions live under `docs/shelflife/`.
