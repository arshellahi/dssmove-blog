#!/usr/bin/env python3
"""DSS Move blog static site builder.

Usage:
    python3 scripts/build.py              # build site/ from posts, templates, static
    python3 scripts/build.py --check      # validate only (exit non-zero on failure)
    python3 scripts/build.py --check --check-external
                                          # also HEAD external URLs (slow, networked)
    python3 scripts/build.py --clean      # rm -rf site/ before building

Zero runtime dependencies. Python 3.9+ stdlib only.
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date as date_cls
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = ROOT / "posts"
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"
SITE_DIR = ROOT / "site"

# Frontmatter schema -----------------------------------------------------------
REQUIRED_SCALAR = ("title", "date", "slug", "summary", "callout", "official_link")
REQUIRED_LIST = {
    # field name -> (min items, max items)
    "keywords": (8, 15),
    "tags": (3, 5),
    "key_points": (3, 3),
    "faq": (2, 2),
}
ALL_REQUIRED = REQUIRED_SCALAR + tuple(REQUIRED_LIST)

OFFICIAL_HOST_SUFFIXES = (
    "gov.uk",
    "parliament.uk",
    "citizensadvice.org.uk",
    "shelter.org.uk",
    "turn2us.org.uk",
    "housingombudsman.org.uk",
    "ons.gov.uk",
)

REQUIRED_DIRS = (POSTS_DIR, TEMPLATES_DIR, STATIC_DIR)
REQUIRED_TEMPLATES = ("base.html", "post.html", "index.html")

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LIST_ITEM_RE = re.compile(r"^\s+-\s+(.+?)\s*$")

FENCE_RE = re.compile(r"^```(\S*)\s*$")
ATX_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
HR_RE = re.compile(r"^-{3,}\s*$")
UL_RE = re.compile(r"^[-*]\s+(.*)$")
OL_RE = re.compile(r"^(\d+)\.\s+(.*)$")
IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)")
LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
CODE_RE = re.compile(r"`([^`\n]+)`")
PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Post:
    path: Path
    meta: dict  # str -> str | list[str]
    body_md: str
    body_html: str = ""
    images: list = field(default_factory=list)
    links: list = field(default_factory=list)

    @property
    def slug(self) -> str:
        return self.meta["slug"]

    @property
    def title(self) -> str:
        return self.meta["title"]

    @property
    def date(self) -> str:
        return self.meta["date"]

    @property
    def summary(self) -> str:
        return self.meta["summary"]


@dataclass
class Issue:
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


# ---------------------------------------------------------------------------
# Frontmatter parser (YAML-ish subset: flat scalars + block lists)
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str, source: str):
    issues: list = []
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        issues.append(Issue(source, "missing leading '---' frontmatter fence"))
        return {}, text, issues
    end = text.find("\n---\n", 4)
    if end == -1:
        end = text.find("\n---\r\n", 4)
    if end == -1:
        issues.append(Issue(source, "missing closing '---' frontmatter fence"))
        return {}, text, issues
    block = text[4:end]
    body = text[end + 5:]

    meta: dict = {}
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line.startswith(" ") or line.startswith("\t"):
            issues.append(Issue(source, f"unexpected indented line (no parent key open): {raw!r}"))
            i += 1
            continue
        if ":" not in line:
            issues.append(Issue(source, f"frontmatter line missing colon: {raw!r}"))
            i += 1
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
                value = value[1:-1]
            if key in meta:
                issues.append(Issue(source, f"duplicate frontmatter key {key!r}"))
            meta[key] = value
            i += 1
        else:
            # list field: collect indented "- item" lines
            items: list = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    i += 1
                    continue
                m = LIST_ITEM_RE.match(nxt)
                if not m:
                    break
                items.append(m.group(1).strip())
                i += 1
            if key in meta:
                issues.append(Issue(source, f"duplicate frontmatter key {key!r}"))
            meta[key] = items
    return meta, body, issues


# ---------------------------------------------------------------------------
# Frontmatter validation
# ---------------------------------------------------------------------------

def validate_frontmatter(meta: dict, source: str) -> list:
    issues: list = []

    for key in ALL_REQUIRED:
        if key not in meta:
            issues.append(Issue(source, f"missing required frontmatter key {key!r}"))

    for key in REQUIRED_SCALAR:
        if key not in meta:
            continue
        value = meta[key]
        if not isinstance(value, str):
            issues.append(Issue(source, f"{key!r} must be a scalar, got list"))
            continue
        if not value.strip():
            issues.append(Issue(source, f"empty value for frontmatter key {key!r}"))

    for key, (lo, hi) in REQUIRED_LIST.items():
        if key not in meta:
            continue
        value = meta[key]
        if not isinstance(value, list):
            issues.append(Issue(source, f"{key!r} must be a list (use 'key:' then '  - item' lines)"))
            continue
        n = len(value)
        if n < lo or n > hi:
            issues.append(Issue(source,
                f"{key!r} must have {lo}–{hi} items (got {n})"))
        for j, item in enumerate(value):
            if not isinstance(item, str) or not item.strip():
                issues.append(Issue(source, f"{key!r} item {j+1} is empty"))

    if isinstance(meta.get("slug"), str) and meta["slug"] and not SLUG_RE.match(meta["slug"]):
        issues.append(Issue(source, f"slug {meta['slug']!r} must be lowercase kebab-case"))
    if isinstance(meta.get("date"), str) and meta["date"]:
        if not ISO_DATE_RE.match(meta["date"]):
            issues.append(Issue(source, f"date {meta['date']!r} must be ISO YYYY-MM-DD"))
        else:
            try:
                date_cls.fromisoformat(meta["date"])
            except ValueError:
                issues.append(Issue(source, f"date {meta['date']!r} is not a real calendar date"))

    # FAQ items must be "question?|answer"
    if isinstance(meta.get("faq"), list):
        for j, item in enumerate(meta["faq"]):
            if not isinstance(item, str):
                continue
            if "|" not in item:
                issues.append(Issue(source, f"faq item {j+1} must be 'question?|answer'"))
                continue
            q, _, a = item.partition("|")
            q = q.strip()
            a = a.strip()
            if not q.endswith("?"):
                issues.append(Issue(source, f"faq item {j+1} question must end with '?'"))
            if not a:
                issues.append(Issue(source, f"faq item {j+1} answer is empty"))

    # official_link must be https + recognised host suffix
    link = meta.get("official_link")
    if isinstance(link, str) and link.strip():
        parsed = urllib.parse.urlparse(link)
        if parsed.scheme != "https":
            issues.append(Issue(source, f"official_link {link!r} must use https"))
        host = (parsed.hostname or "").lower()
        if not any(host == suf or host.endswith("." + suf) for suf in OFFICIAL_HOST_SUFFIXES):
            issues.append(Issue(source,
                f"official_link host {host!r} not in allowlist "
                f"({', '.join(OFFICIAL_HOST_SUFFIXES)})"))

    # summary length sanity (meta description)
    summary = meta.get("summary")
    if isinstance(summary, str) and summary.strip():
        if len(summary) > 200:
            issues.append(Issue(source,
                f"summary is {len(summary)} chars; keep under 200 for meta description"))

    return issues


# ---------------------------------------------------------------------------
# Markdown → HTML (minimal subset, line-based)
# ---------------------------------------------------------------------------

def _esc(s: str) -> str:
    return html.escape(s, quote=False)


def render_inline(text: str, post_images: list, post_links: list) -> str:
    placeholders: list = []

    def stash(html_chunk: str) -> str:
        token = f"\x00P{len(placeholders)}\x00"
        placeholders.append(html_chunk)
        return token

    def img_sub(m):
        alt, src = m.group(1), m.group(2)
        title = m.group(3) or ""
        post_images.append((alt, src))
        title_attr = f' title="{_esc(title)}"' if title else ""
        return stash(f'<img src="{_esc(src)}" alt="{_esc(alt)}"{title_attr}>')

    def link_sub(m):
        label, href = m.group(1), m.group(2)
        title = m.group(3) or ""
        post_links.append((label, href))
        title_attr = f' title="{_esc(title)}"' if title else ""
        rel = ' rel="noopener noreferrer"' if href.startswith(("http://", "https://")) else ""
        target = ' target="_blank"' if href.startswith(("http://", "https://")) else ""
        return stash(f'<a href="{_esc(href)}"{title_attr}{rel}{target}>{_esc(label)}</a>')

    def code_sub(m):
        return stash(f"<code>{_esc(m.group(1))}</code>")

    text = IMG_RE.sub(img_sub, text)
    text = LINK_RE.sub(link_sub, text)
    text = CODE_RE.sub(code_sub, text)
    text = _esc(text)
    text = BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", text)
    text = ITALIC_RE.sub(lambda m: f"<em>{m.group(1)}</em>", text)
    for i, chunk in enumerate(placeholders):
        text = text.replace(f"\x00P{i}\x00", chunk)
    return text


def render_markdown(md: str):
    images: list = []
    links: list = []
    out: list = []
    lines = md.splitlines()
    i = 0
    para: list = []
    ul: list = []
    ol: list = []

    def flush_para():
        if para:
            out.append("<p>" + render_inline(" ".join(para).strip(), images, links) + "</p>")
            para.clear()

    def flush_ul():
        if ul:
            out.append("<ul>")
            for item in ul:
                out.append("  <li>" + render_inline(item, images, links) + "</li>")
            out.append("</ul>")
            ul.clear()

    def flush_ol():
        if ol:
            out.append("<ol>")
            for item in ol:
                out.append("  <li>" + render_inline(item, images, links) + "</li>")
            out.append("</ol>")
            ol.clear()

    def flush_all():
        flush_para()
        flush_ul()
        flush_ol()

    while i < len(lines):
        line = lines[i]
        fence = FENCE_RE.match(line)
        if fence:
            flush_all()
            lang = fence.group(1)
            buf: list = []
            i += 1
            while i < len(lines) and not FENCE_RE.match(lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1
            class_attr = f' class="language-{_esc(lang)}"' if lang else ""
            out.append(f"<pre><code{class_attr}>{_esc(chr(10).join(buf))}</code></pre>")
            continue

        if not line.strip():
            flush_all()
            i += 1
            continue

        if HR_RE.match(line):
            flush_all()
            out.append("<hr>")
            i += 1
            continue

        atx = ATX_RE.match(line)
        if atx:
            flush_all()
            level = len(atx.group(1))
            content = render_inline(atx.group(2), images, links)
            out.append(f"<h{level}>{content}</h{level}>")
            i += 1
            continue

        ul_m = UL_RE.match(line)
        if ul_m:
            flush_para()
            flush_ol()
            ul.append(ul_m.group(1))
            i += 1
            continue

        ol_m = OL_RE.match(line)
        if ol_m:
            flush_para()
            flush_ul()
            ol.append(ol_m.group(2))
            i += 1
            continue

        flush_ul()
        flush_ol()
        para.append(line.strip())
        i += 1

    flush_all()
    return "\n".join(out), images, links


# ---------------------------------------------------------------------------
# Loading + cross-post checks
# ---------------------------------------------------------------------------

def discover_posts():
    posts: list = []
    issues: list = []
    if not POSTS_DIR.exists():
        return posts, issues
    for path in sorted(POSTS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        source = str(path.relative_to(ROOT))
        meta, body, fm_issues = parse_frontmatter(text, source)
        issues.extend(fm_issues)
        issues.extend(validate_frontmatter(meta, source))
        if not meta:
            continue
        try:
            body_html, images, links = render_markdown(body)
        except Exception as exc:
            issues.append(Issue(source, f"markdown render failed: {exc!r}"))
            continue
        post = Post(path=path, meta=meta, body_md=body, body_html=body_html,
                    images=images, links=links)
        # Body word count (post body only, not frontmatter)
        words = len(re.findall(r"\b\w+\b", body))
        if words < 300 or words > 550:
            issues.append(Issue(source,
                f"body word count {words} outside required 300–550 range"))
        posts.append(post)
    return posts, issues


def check_layout():
    issues: list = []
    for d in REQUIRED_DIRS:
        if not d.is_dir():
            issues.append(Issue(str(d.relative_to(ROOT)), "required directory missing"))
    for t in REQUIRED_TEMPLATES:
        p = TEMPLATES_DIR / t
        if not p.is_file():
            issues.append(Issue(f"templates/{t}", "required template missing"))
    return issues


def check_image_alts(posts):
    issues: list = []
    for post in posts:
        for alt, src in post.images:
            if not alt.strip():
                issues.append(Issue(str(post.path.relative_to(ROOT)),
                                    f"image {src!r} has empty alt text"))
    return issues


def check_unique_slugs(posts):
    issues: list = []
    seen: dict = {}
    for post in posts:
        if not post.meta.get("slug"):
            continue
        if post.slug in seen:
            issues.append(Issue(str(post.path.relative_to(ROOT)),
                                f"slug {post.slug!r} already used by {seen[post.slug]}"))
        else:
            seen[post.slug] = str(post.path.relative_to(ROOT))
    return issues


def check_internal_links(posts):
    issues: list = []
    slugs = {p.slug for p in posts if p.meta.get("slug")}
    static_files = {
        str(p.relative_to(STATIC_DIR)) for p in STATIC_DIR.rglob("*") if p.is_file()
    } if STATIC_DIR.is_dir() else set()
    for post in posts:
        for label, href in post.links + [(alt, src) for alt, src in post.images]:
            if href.startswith(("http://", "https://", "mailto:", "tel:", "#")):
                continue
            target = href.lstrip("/")
            if target.startswith("posts/"):
                slug = target[len("posts/"):].rstrip("/")
                if slug.endswith("/index.html"):
                    slug = slug[:-len("/index.html")]
                if slug not in slugs:
                    issues.append(Issue(str(post.path.relative_to(ROOT)),
                                        f"internal link {href!r} → unknown post slug {slug!r}"))
                continue
            if target.startswith("static/"):
                rel = target[len("static/"):]
                if rel not in static_files:
                    issues.append(Issue(str(post.path.relative_to(ROOT)),
                                        f"internal link {href!r} → missing static file {rel!r}"))
                continue
            slug = target.rstrip("/")
            if slug.endswith("/index.html"):
                slug = slug[:-len("/index.html")]
            if slug and slug in slugs:
                continue
            issues.append(Issue(str(post.path.relative_to(ROOT)),
                                f"internal link {href!r} could not be resolved "
                                f"(expected /posts/<slug>/ or /static/<file>)"))
    return issues


def check_external_links(posts):
    issues: list = []
    seen: set = set()
    targets: list = []
    for post in posts:
        # Include official_link in the external HEAD check
        link = post.meta.get("official_link")
        if isinstance(link, str) and link.startswith(("http://", "https://")):
            targets.append((post, "official_link", link))
        for _label, href in post.links + [(a, s) for a, s in post.images]:
            if href.startswith(("http://", "https://")):
                targets.append((post, "body link", href))

    for post, kind, href in targets:
        if href in seen:
            continue
        seen.add(href)
        req = urllib.request.Request(href, method="HEAD",
                                     headers={"User-Agent": "dssmove-blog-link-check/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status >= 400:
                    issues.append(Issue(str(post.path.relative_to(ROOT)),
                                        f"{kind} {href!r} returned HTTP {resp.status}"))
        except urllib.error.HTTPError as exc:
            if exc.code == 405:
                try:
                    req2 = urllib.request.Request(href, method="GET",
                                                  headers={"User-Agent": "dssmove-blog-link-check/1.0"})
                    with urllib.request.urlopen(req2, timeout=10) as resp:
                        if resp.status >= 400:
                            issues.append(Issue(str(post.path.relative_to(ROOT)),
                                                f"{kind} {href!r} returned HTTP {resp.status}"))
                except Exception as exc2:
                    issues.append(Issue(str(post.path.relative_to(ROOT)),
                                        f"{kind} {href!r} failed: {exc2!r}"))
            else:
                issues.append(Issue(str(post.path.relative_to(ROOT)),
                                    f"{kind} {href!r} returned HTTP {exc.code}"))
        except Exception as exc:
            issues.append(Issue(str(post.path.relative_to(ROOT)),
                                f"{kind} {href!r} failed: {exc!r}"))
    return issues


# ---------------------------------------------------------------------------
# Rendering structured frontmatter into HTML fragments
# ---------------------------------------------------------------------------

def render_key_points(items) -> str:
    return "\n".join(f"      <li>{_esc(p)}</li>" for p in items)


def render_callout(text: str) -> str:
    return f"<p>{_esc(text)}</p>"


def render_faq(items) -> str:
    parts: list = []
    for item in items:
        q, _, a = item.partition("|")
        q = q.strip()
        a = a.strip()
        parts.append(
            "    <details>\n"
            f"      <summary>{_esc(q)}</summary>\n"
            f"      <p>{_esc(a)}</p>\n"
            "    </details>"
        )
    return "\n".join(parts)


def render_tags(items) -> str:
    return " ".join(f'<span class="tag">{_esc(t)}</span>' for t in items)


def render_template(tpl: str, ctx: dict) -> str:
    return PLACEHOLDER_RE.sub(lambda m: ctx.get(m.group(1), ""), tpl)


def write_site(posts):
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True)

    base = (TEMPLATES_DIR / "base.html").read_text(encoding="utf-8")
    post_tpl = (TEMPLATES_DIR / "post.html").read_text(encoding="utf-8")
    index_tpl = (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")

    sorted_posts = sorted(posts, key=lambda p: p.date, reverse=True)

    for post in sorted_posts:
        inner = render_template(post_tpl, {
            "title": _esc(post.title),
            "date": _esc(post.date),
            "summary": _esc(post.summary),
            "body": post.body_html,
            "slug": _esc(post.slug),
            "key_points": render_key_points(post.meta.get("key_points", [])),
            "callout": render_callout(post.meta.get("callout", "")),
            "faq": render_faq(post.meta.get("faq", [])),
            "tags": render_tags(post.meta.get("tags", [])),
            "official_link": _esc(post.meta.get("official_link", "")),
        })
        page = render_template(base, {
            "page_title": _esc(f"{post.title} — DSS Move blog"),
            "summary": _esc(post.summary),
            "content": inner,
            "site_title": "DSS Move blog",
        })
        out_dir = SITE_DIR / post.slug
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(page, encoding="utf-8")

    items_html = "\n".join(
        f'  <li><time datetime="{_esc(p.date)}">{_esc(p.date)}</time> '
        f'<a href="/{_esc(p.slug)}/">{_esc(p.title)}</a> — '
        f'{_esc(p.summary)}</li>'
        for p in sorted_posts
    )
    inner = render_template(index_tpl, {
        "items": items_html,
        "site_title": "DSS Move blog",
    })
    page = render_template(base, {
        "page_title": "DSS Move blog",
        "summary": "Notes on the UC / Housing Benefit rental market.",
        "content": inner,
        "site_title": "DSS Move blog",
    })
    (SITE_DIR / "index.html").write_text(page, encoding="utf-8")

    if STATIC_DIR.is_dir():
        dest = SITE_DIR / "static"
        shutil.copytree(STATIC_DIR, dest)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run_checks(check_external: bool) -> int:
    issues: list = []
    issues.extend(check_layout())
    posts, post_issues = discover_posts()
    issues.extend(post_issues)
    issues.extend(check_image_alts(posts))
    issues.extend(check_unique_slugs(posts))
    issues.extend(check_internal_links(posts))
    if check_external:
        n_ext = sum(
            1 for p in posts
            for _, h in p.links + [(a, s) for a, s in p.images]
            if h.startswith(("http://", "https://"))
        ) + sum(
            1 for p in posts
            if isinstance(p.meta.get("official_link"), str)
            and p.meta["official_link"].startswith(("http://", "https://"))
        )
        print(f"Checking {n_ext} external URL(s)...")
        issues.extend(check_external_links(posts))

    if issues:
        print(f"FAIL — {len(issues)} issue(s):", file=sys.stderr)
        for issue in issues:
            print(f"  {issue}", file=sys.stderr)
        return 1
    print(f"OK — {len(posts)} post(s), layout valid, frontmatter valid, "
          f"image alts present, slugs unique, internal links resolve"
          + (", external links reachable" if check_external else ""))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="DSS Move blog builder")
    parser.add_argument("--check", action="store_true",
                        help="validate only; do not write site/")
    parser.add_argument("--check-external", action="store_true",
                        help="with --check, also HEAD external URLs (networked, slow)")
    parser.add_argument("--clean", action="store_true",
                        help="remove site/ before building")
    args = parser.parse_args(argv)

    if args.check:
        return run_checks(args.check_external)

    if args.clean and SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)

    rc = run_checks(check_external=False)
    if rc != 0:
        print("Build aborted: --check failed. Fix issues above before building.", file=sys.stderr)
        return rc

    posts, _ = discover_posts()
    write_site(posts)
    print(f"Built {len(posts)} post(s) into {SITE_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
