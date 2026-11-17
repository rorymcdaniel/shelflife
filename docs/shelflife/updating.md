# Updating

Initial upstream: Reclaimerr 0.6.12, commit `76574445f45bf993d2388a31c8600f7bf46b73dc`. Keep the `upstream` remote pointing to `https://github.com/jessielw/Reclaimerr.git`.

For a release, fetch tags, create an update branch, merge the release tag and run CI. Review migration ancestry: concurrent upstream/Shelflife heads require an Alembic merge revision. Test on a database copy and preserve the keep ledger; never replace the running database with an empty one.

```sh
git fetch upstream --tags
git switch -c update/reclaimerr-VERSION
git merge VERSION
# Review, resolve conflicts, run CONTRIBUTING.md checks, then open a PR.
```

Back up data before upgrading, rebuild/recreate the containers and repeat acceptance checks with cleanup paused. Seerr, Jellyfin and official Roku apps retain their normal upstream update channels; Shelflife ships no replacement clients.

Dependabot proposes weekly dependency, Docker and Action updates to `main`. Required checks gate merging. Upstream application releases are not automatically merged: a successful build cannot validate Roku rendering or a changed request form. The project maintainer owns that compatibility work.
