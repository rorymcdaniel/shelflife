# Domain glossary

| Term | Meaning |
| --- | --- |
| Retention entry | Durable movie/season policy identified by TMDB ID and season number; survives rescans. |
| Enrollment | Attaching a confirmed new Seerr request after activation. An unsent choice is not enrollment. |
| Availability | First verified observation that a movie or complete requested season is watchable in Jellyfin. |
| Keep | Immediately accepted, monotonic extension or permanent retention decision. |
| Permanent keep | No expiry; removing Favorite does not revoke it. |
| Whole-show keep | Keep-only umbrella across seasons; never a whole-series deletion target. |
| Preview | Records windows/keeps without changing files, descriptions or collections. |
| Pause | Stops cleanup while continuing keeps and notices. |
| Deletion candidate | Transient Reclaimerr work record, not the source of truth for keeps. |
| Gateway | Same-origin proxy adding controls and recording request/Favorite choices before forwarding. |
