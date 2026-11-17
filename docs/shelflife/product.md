# Product contract

Shelflife makes temporary retention visible and lets a small, trusted group decide what stays. It extends Reclaimerr and keeps the official Roku app.

## Request and availability

Every new Seerr browser request presents the 60-day default before submission, with 180 days, one year, custom days (60–36500), and forever. Seerr's existing request permissions and approval behavior still apply. Keeps never need administrator approval.

Only requests created after activation are enrolled. Movies start their window when first observed available in Jellyfin. A TV request enrolls only explicitly requested seasons. A season starts when Sonarr reports all known episodes downloaded and aired, there is affirmative finale evidence, and Jellyfin contains those episodes. Uncertain seasons wait. First observation may give extra time; it never backdates the window.

## Keeping

Any authenticated member can choose more time or forever. A timed keep guarantees at least that many days from the action; request-time choices start from availability. Longer/permanent decisions always win. The requester cannot undo another member's keep.

Roku Favorite makes a permanent keep. Unfavoriting leaves it intact. Movie favorites protect the movie; episode/season favorites protect the season; show favorites protect all present and future seasons. The same behavior applies to other clients using the gateway.

Browsers have a dedicated Keep control. Whole-show timed keeps cover currently enrolled seasons and requests made while that keep is active. Forever covers future seasons without expiration.

## Visibility and cleanup

Jellyfin descriptions start with the date and Roku instructions. Shows summarize requested-season deadlines. The original synopsis is preserved. Leaving Soon collections highlight the final seven days. Clients may cache descriptions; refresh detail pages after changes.

At the deadline, Reclaimerr removes the exact movie or requested season and unmonitors it in Arr. Active playback and unverifiable observations defer cleanup. Keeps are rechecked before cleanup. A season request must never authorize whole-series deletion.

Preview records windows/keeps without changing files, descriptions or collections. Activation grants available temporary titles a fresh full window. Pause stops deletion while continuing keeps and notices. The existing library is not automatically enrolled.

Reliable Favorite capture requires all clients to use the gateway; Seerr requests must use its request bridge. Direct connections bypass that guarantee, though polling can capture favorites left in place. Physical Roku validation is a release acceptance step.
