# dssmove-blog — Claude Code project rules

These rules apply to any Claude Code session working inside this folder. Read them in full before making changes. They sit alongside (not instead of) `~/.claude/CLAUDE.md`.

## What this repo is

Static blog for **DSS Move** (dssmove.com) — short posts about the UC / Housing Benefit rental market, market notes, and product updates. Audience: landlords, agents, and renters using the directory.

The repo is **private**. Anything published here may eventually be made public, but treat the working tree as private by default.

## Stack

- **Pure Python static-site generator.** Zero runtime dependencies — stdlib only.
- Entry point: `scripts/build.py`.
- Posts live as Markdown with YAML-ish frontmatter in `posts/`.
- Templates in `templates/` (`base.html`, `post.html`, `index.html`) use `{{ name }}` placeholders.
- Static assets in `static/`.
- Build output lands in `site/` (git-ignored).

## Commands

| What | Command |
|------|---------|
| Validate everything | `python3 scripts/build.py --check` |
| Validate + check external URLs | `python3 scripts/build.py --check --check-external` |
| Build the site | `python3 scripts/build.py` |
| Clean build | `rm -rf site/ && python3 scripts/build.py` |

`--check` validates: required folders/templates exist; every post has full frontmatter; lists are within size bounds; FAQ items are `question?|answer`; `official_link` is https + recognised host suffix (`gov.uk`, `parliament.uk`, `citizensadvice.org.uk`, `shelter.org.uk`, `turn2us.org.uk`, `housingombudsman.org.uk`, `ons.gov.uk`); body word count is 300–550; no `<img>` / `![]()` has an empty alt; internal links resolve to a real post or static asset; slugs are unique. It does **not** hit the network unless you pass `--check-external` (which also HEADs the `official_link`).

**Always run `python3 scripts/build.py --check` before committing.** CI may later enforce this — keep main green.

## Authoring a post

1. Create `posts/YYYY-MM-DD-slug.md`.
2. **Full frontmatter** (all required — `--check` enforces it):

   ```
   ---
   title: Your headline here
   date: 2026-05-20
   slug: your-headline-here
   summary: One-sentence meta description under 200 chars.
   callout: One-sentence note that appears in a highlighted aside.
   official_link: https://www.gov.uk/some-page
   keywords:
     - first keyword
     - second keyword
     - (8 to 15 total)
   tags:
     - first tag
     - second tag
     - third tag
   key_points:
     - First key point (exactly 3 required)
     - Second key point
     - Third key point
   faq:
     - Question one ends with a question mark?|Answer one as a single sentence.
     - Question two ends with a question mark?|Answer two as a single sentence.
   ---
   ```

   - **Lists** use YAML-style block syntax: `key:` on its own line, then indented `  - item` lines.
   - **FAQ** items are `question?|answer` — pipe-separated, question must end with `?`.
   - **official_link** must be https and host must end with one of: `gov.uk`, `parliament.uk`, `citizensadvice.org.uk`, `shelter.org.uk`, `turn2us.org.uk`, `housingombudsman.org.uk`, `ons.gov.uk`.
3. **Body word count: 300–550.** Strict. Counted on the Markdown body only (not frontmatter).
4. Body is Markdown. Supported: ATX headings (`#` through `######`), paragraphs, `**bold**`, `*italic*`, `` `inline code` ``, fenced code blocks (```` ``` ````), unordered lists (`- item`), ordered lists (`1. item`), links `[text](url)`, images `![alt](url)`, horizontal rules (`---`).
5. **Every image must have non-empty alt text.**
6. **Internal links** (paths starting with `/`) must point to a slug that exists in `posts/` or a file in `static/`.
7. Run `--check`, then `build`, then open `site/<slug>/index.html` in a browser to eyeball.

## Editorial brief

Posts follow the DSS Move voice:
- **Audience:** people on UC / Housing Benefit looking for a place to rent.
- **Reading age ~9.** Plain UK English. Short sentences (12–18 words). Avoid jargon; if you must use an acronym, spell it out first (`Universal Credit (UC)`).
- **Numbers as digits.** £ before amount (`£950`, not `950 GBP`). ISO dates (`2026-05-20`).
- **One topic per post.** Pick the angle most useful to a reader, not the most newsworthy headline.
- **Never invent figures.** Every number/date/rule must trace to an official source — GOV.UK, DWP, House of Commons Library, Turn2us, Citizens Advice, Shelter. Cite the source via `official_link`.
- **No advice that needs a lawyer or adviser** — point to Citizens Advice / Shelter instead.

## What NOT to do

- **Never commit secrets.** No `.env`, `.pem`, `.key`, `credentials.json`, service-account JSONs, or API tokens. `.gitignore` blocks the common patterns but you are the last line of defence — eyeball `git status` before staging.
- **Never add a runtime dependency** without explicit approval. The build runs on stdlib Python 3.9+. If you think you need PyYAML / markdown / jinja2 — stop and ask first.
- **Never touch live deployment** from this repo. There is no CI/CD wired up at the scaffold stage. Do not add GitHub Actions that push to a live host without explicit approval.
- **Never push directly to `main`.** Work on a branch, open a PR. `main` should be branch-protected (see `SECURITY.md`).
- **Never bypass `--check`** by skipping pre-commit hooks (`--no-verify`) or by removing failing validations. Fix the underlying issue.

## Style

- Prose: plain UK English, second person ("you"), short sentences. Numbers as digits. £ before amount (`£950`, not `950 GBP`).
- Headings: sentence case ("How DSS Move works", not "How DSS Move Works").
- Filenames: kebab-case, dated (`2026-05-20-welcome.md`).

## Memory of standing user rules

The user is Arsh (arshellahi). Global rules in `~/.claude/CLAUDE.md` apply, particularly:
- GDrive deliverables go in `My Drive/Claude Research Projects/<matching subfolder>/`. This repo lives **locally**, so the rule doesn't apply to source — but any exported PDFs or marketing assets generated for distribution should still follow it.
- Today's date semantics live in the global rules; convert relative dates ("next Thursday") to absolute ISO dates when writing them down.
