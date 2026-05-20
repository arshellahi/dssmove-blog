# Security policy — dssmove-blog

Read this **before** running any command that touches the network, secrets, or shared infrastructure.

## Reporting a vulnerability

Email **arsh@arshellahi.com** with the subject line `[dssmove-blog security]`. Do not open a public issue. Expect an acknowledgement within 48h.

## Scope

In scope:
- This repository (`dssmove-blog`) — source, build script, templates.
- Anything published from this repo onto a public host once deployment is wired up.

Out of scope (at the scaffold stage):
- dssmove.com main site and database — separate project.
- Calculator project under `~/Documents/Claude/Projects/Dssmove/` — separate folder.
- Any third-party service this blog might later embed (analytics, comments).

## Secrets policy

**Nothing secret enters this repo. Ever.** Even briefly. Even on a feature branch.

Blocked by `.gitignore`:
- `.env`, `.env.*` (except `.env.example`)
- `*.pem`, `*.key`, `*.crt`, `*.p12`, `*.pfx`
- `credentials*`, `secrets*`, `*.secret`
- `service-account*.json`, `gha-secrets*`

If you discover a secret has been committed:
1. **Rotate the secret immediately** at its source (revoke the API key, regenerate the cert, etc.) — `git rm` is not enough; assume the secret is leaked the moment it reaches GitHub.
2. Tell Arsh.
3. Then clean up history (`git filter-repo` or BFG, force-push to a new branch, never to `main`).

## Branch protection (manual, configure on GitHub)

`main` must be protected:
- Require a pull request before merging — at least 1 review.
- Require status checks (`build.py --check`) once CI is wired up.
- Block force-pushes.
- Block direct pushes to `main`.
- Block deletion of `main`.

## GitHub repo settings (manual)

After the initial push, enable in **Settings → Code security & analysis**:
- **Secret scanning** — on.
- **Push protection** — on (blocks pushes that include detected secrets).
- **Dependabot alerts** — on.
- **Dependabot security updates** — on.

These are free for private repos under most plans and catch the common mistakes.

## Deployment

There is **no automated deployment** at the scaffold stage. Do not add a GitHub Action that pushes to a live host (S3, Netlify, Cloudflare Pages, anything) without explicit approval from Arsh first. The threat model: a bad merge to `main` should not be able to defac dssmove.com or replace a published post without human review.

When deployment is added later, it must:
- Run from a protected branch only.
- Use short-lived deploy credentials (OIDC where possible, not long-lived tokens).
- Be reversible — keep the previous build artefact for at least one release.

## Build-time policy

`scripts/build.py` reads from `posts/`, `templates/`, `static/` and writes to `site/`. It does **not**:
- Make any network request unless `--check-external` is passed.
- Execute code embedded in posts.
- Read anything outside the repo.

If you change `build.py` to do any of the above, update this file in the same commit and call it out in the PR.

## Dependencies

Zero runtime dependencies today. The build runs on Python 3.9+ stdlib only.

If a dependency is added later it must:
- Be pinned to an exact version.
- Be reviewed for last-published date, weekly downloads, and maintainer count.
- Be added to Dependabot's watch list.

## Acknowledged limitations

- This is a single-maintainer hobby-scale repo. There is no SLA. The above policies describe the target state, not a guarantee.
- The Markdown subset in `build.py` is hand-rolled. It has not been audited against an HTML-injection test suite. Do not paste untrusted Markdown into `posts/` — author content only.
