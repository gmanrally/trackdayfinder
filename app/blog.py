"""Native blog + a WordPress-REST facade for seo-studio.

Replaces the WordPress stack that used to serve trackdayfinder.co.uk/blog —
the whole PHP/wp-admin attack surface is gone. Two halves:

1. Public pages: /blog and /blog/{slug}/ rendered in the site's own style,
   straight from the BlogPost table.
2. A minimal WordPress REST v2 facade under /blog/wp-json/wp/v2/ speaking
   exactly the subset seo-studio's WordPressClient uses (Basic-auth app
   password, posts CRUD, media upload/search, RankMath meta fields, and
   /pages as internal-link targets — which we answer with the site's real
   product pages). seo-studio therefore needs zero changes: point it at
   https://trackdayfinder.co.uk/blog with BLOG_USER / BLOG_APP_PASSWORD.

Old WP permalinks (/blog/{slug}/) are preserved so nothing indexed breaks.
"""
from __future__ import annotations

import base64
import hmac
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from sqlmodel import select
from .models import BlogPost, BlogMedia, session as db_session, _DATA_DIR

router = APIRouter()

MEDIA_DIR = _DATA_DIR / "blog_media"

BLOG_USER = os.environ.get("BLOG_USER", "seo-studio").strip()
BLOG_APP_PASSWORD = (os.environ.get("BLOG_APP_PASSWORD", "") or "").replace(" ", "").strip()

# Internal-link targets we expose as WP "pages": the product surface the
# blog should be funnelling readers into. Fixed ids so seo-studio can
# reference them stably; meta writes against them are accepted and ignored.
SITE_PAGES = [
    (100001, "UK & European trackday list", "/"),
    (100002, "Trackday map", "/map"),
    (100003, "Trackday calendar", "/calendar"),
    (100004, "Trackday spaces for sale", "/spaces"),
    (100005, "Email alerts for trackdays", "/alerts"),
]


def _host() -> str:
    from .main import CANONICAL_HOST
    return CANONICAL_HOST


def _slugify(s: str) -> str:
    from .main import slugify
    return slugify(s)


# ---------- auth ----------

def _require_auth(request: Request) -> None:
    """WP-style Basic auth with the app password. The facade is disabled
    entirely (404) until BLOG_APP_PASSWORD is configured."""
    if not BLOG_APP_PASSWORD:
        raise HTTPException(status_code=404)
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        user, _, pwd = base64.b64decode(header.split(None, 1)[1]).decode().partition(":")
    except Exception:
        raise HTTPException(status_code=401, detail="Bad authorization header")
    if not (hmac.compare_digest(user, BLOG_USER)
            and hmac.compare_digest(pwd.replace(" ", ""), BLOG_APP_PASSWORD)):
        raise HTTPException(status_code=401, detail="Bad credentials")


# ---------- helpers ----------

def _strip_tags(html: str, limit: int = 200) -> str:
    txt = re.sub(r"<[^>]+>", " ", html or "")
    txt = re.sub(r"\s+", " ", txt).strip()
    return (txt[: limit - 1] + "…") if len(txt) > limit else txt


def _media_url(m: BlogMedia) -> str:
    return f"{_host()}/blog/media/{m.filename}"


def _post_json(p: BlogPost) -> dict:
    d = p.published_at or p.created_at
    return {
        "id": p.id,
        "slug": p.slug,
        "status": p.status,
        "type": "post",
        "link": f"{_host()}/blog/{p.slug}/",
        "date_gmt": d.strftime("%Y-%m-%dT%H:%M:%S"),
        "title": {"rendered": p.title, "raw": p.title},
        "content": {"rendered": p.content, "raw": p.content},
        "excerpt": {"rendered": _strip_tags(p.content, 200)},
        "featured_media": p.featured_media_id or 0,
        "meta": {
            "rank_math_title": p.seo_title or "",
            "rank_math_description": p.seo_description or "",
            "rank_math_focus_keyword": p.focus_keyword or "",
        },
    }


def _media_json(m: BlogMedia) -> dict:
    return {
        "id": m.id,
        "source_url": _media_url(m),
        "alt_text": m.alt_text or "",
        "title": {"rendered": m.title or m.filename},
        "media_type": "image",
    }


def _unique_slug(s, want: str) -> str:
    base = want or "post"
    slug, n = base, 2
    while s.exec(select(BlogPost).where(BlogPost.slug == slug)).first() is not None:
        slug = f"{base}-{n}"
        n += 1
    return slug


def _apply_meta(p: BlogPost, meta: dict) -> None:
    if "rank_math_title" in meta:
        p.seo_title = meta["rank_math_title"] or None
    if "rank_math_description" in meta:
        p.seo_description = meta["rank_math_description"] or None
    if "rank_math_focus_keyword" in meta:
        p.focus_keyword = meta["rank_math_focus_keyword"] or None


# ---------- public pages ----------

@router.get("/blog", response_class=HTMLResponse)
@router.get("/blog/", response_class=HTMLResponse, include_in_schema=False)
async def blog_index(request: Request):
    from .main import templates
    from datetime import date as _date
    with db_session() as s:
        posts = s.exec(select(BlogPost).where(BlogPost.status == "publish")
                       .order_by(BlogPost.published_at.desc())).all()
        media = {m.id: m for m in s.exec(select(BlogMedia)).all()}
    items = [{
        "post": p,
        "excerpt": _strip_tags(p.content, 180),
        "image": _media_url(media[p.featured_media_id]) if p.featured_media_id in media else None,
    } for p in posts]
    return templates.TemplateResponse(request, "blog/index.html", {
        "items": items, "now_year": _date.today().year,
    })


@router.get("/blog/{slug}", response_class=HTMLResponse)
@router.get("/blog/{slug}/", response_class=HTMLResponse, include_in_schema=False)
async def blog_post(request: Request, slug: str):
    from .main import templates
    from datetime import date as _date
    with db_session() as s:
        p = s.exec(select(BlogPost).where(BlogPost.slug == slug,
                                          BlogPost.status == "publish")).first()
        media = None
        if p and p.featured_media_id:
            media = s.exec(select(BlogMedia).where(BlogMedia.id == p.featured_media_id)).first()
    if p is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "blog/post.html", {
        "p": p,
        "meta_title": p.seo_title or p.title,
        "meta_description": p.seo_description or _strip_tags(p.content, 158),
        "hero": _media_url(media) if media else None,
        "now_year": _date.today().year,
    })


@router.get("/blog/media/{filename}")
async def blog_media(filename: str):
    name = Path(filename).name          # traversal guard
    path = MEDIA_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path)


# ---------- WordPress REST v2 facade ----------

WP = "/blog/wp-json/wp/v2"


@router.get(WP + "/users/me")
async def wp_me(request: Request):
    _require_auth(request)
    return {"id": 1, "name": BLOG_USER, "slug": BLOG_USER}


@router.get(WP + "/posts")
async def wp_list_posts(request: Request, slug: Optional[str] = None,
                        status: str = "publish", page: int = 1, per_page: int = 10,
                        search: Optional[str] = None):
    _require_auth(request)
    per_page = max(1, min(int(per_page or 10), 100))
    with db_session() as s:
        q = select(BlogPost)
        if slug:
            q = q.where(BlogPost.slug == slug)
        elif status and status != "any":
            q = q.where(BlogPost.status == status)
        posts = s.exec(q.order_by(BlogPost.published_at.desc(),
                                  BlogPost.created_at.desc())).all()
    if search:
        low = search.lower()
        posts = [p for p in posts if low in p.title.lower() or low in p.content.lower()]
    start = (max(1, int(page or 1)) - 1) * per_page
    return [_post_json(p) for p in posts[start:start + per_page]]


@router.post(WP + "/posts")
async def wp_create_post(request: Request):
    _require_auth(request)
    body = await request.json()
    title = (body.get("title") or "").strip() or "Untitled"
    with db_session() as s:
        p = BlogPost(
            slug=_unique_slug(s, _slugify(title)),
            title=title,
            content=body.get("content") or "",
            status="publish" if body.get("status") == "publish" else "draft",
            featured_media_id=body.get("featured_media") or None,
        )
        _apply_meta(p, body.get("meta") or {})
        if p.status == "publish":
            p.published_at = datetime.utcnow()
        s.add(p)
        s.commit()
        s.refresh(p)
        return JSONResponse(_post_json(p), status_code=201)


@router.get(WP + "/posts/{post_id}")
async def wp_get_post(request: Request, post_id: int):
    _require_auth(request)
    with db_session() as s:
        p = s.exec(select(BlogPost).where(BlogPost.id == post_id)).first()
    if p is None:
        raise HTTPException(status_code=404)
    return _post_json(p)


@router.post(WP + "/posts/{post_id}")
async def wp_update_post(request: Request, post_id: int):
    _require_auth(request)
    body = await request.json()
    with db_session() as s:
        p = s.exec(select(BlogPost).where(BlogPost.id == post_id)).first()
        if p is None:
            raise HTTPException(status_code=404)
        if "title" in body:
            p.title = (body["title"] or "").strip() or p.title
        if "content" in body:
            p.content = body["content"] or ""
        if "featured_media" in body:
            p.featured_media_id = body["featured_media"] or None
        if "status" in body:
            new = "publish" if body["status"] == "publish" else "draft"
            if new == "publish" and p.status != "publish":
                p.published_at = p.published_at or datetime.utcnow()
            p.status = new
        _apply_meta(p, body.get("meta") or {})
        p.updated_at = datetime.utcnow()
        s.add(p)
        s.commit()
        s.refresh(p)
        return _post_json(p)


@router.delete(WP + "/posts/{post_id}")
async def wp_delete_post(request: Request, post_id: int, force: str = "false"):
    _require_auth(request)
    with db_session() as s:
        p = s.exec(select(BlogPost).where(BlogPost.id == post_id)).first()
        if p is None:
            raise HTTPException(status_code=404)
        if force.lower() == "true":
            s.delete(p)
        else:
            p.status = "draft"          # our "trash": unpublished, recoverable
            s.add(p)
        s.commit()
    return {"deleted": True}


@router.get(WP + "/pages")
async def wp_pages(request: Request, search: Optional[str] = None,
                   per_page: int = 8):
    _require_auth(request)
    host = _host()
    out = [{"id": pid, "slug": link.strip("/") or "home",
            "title": {"rendered": title}, "link": host + link}
           for pid, title, link in SITE_PAGES]
    if search:
        low = search.lower()
        preferred = [p for p in out if low in p["title"]["rendered"].lower()]
        out = preferred or out
    return out[: max(1, min(int(per_page or 8), 50))]


@router.post(WP + "/pages/{page_id}")
async def wp_page_meta(request: Request, page_id: int):
    _require_auth(request)   # accepted, ignored — our pages have their own SEO
    return {"id": page_id}


@router.get(WP + "/media")
async def wp_list_media(request: Request, search: Optional[str] = None,
                        per_page: int = 8):
    _require_auth(request)
    with db_session() as s:
        media = s.exec(select(BlogMedia).order_by(BlogMedia.created_at.desc())).all()
    if search:
        low = search.lower()
        media = [m for m in media
                 if low in (m.title or "").lower() or low in (m.alt_text or "").lower()
                 or low in m.filename.lower()]
    return [_media_json(m) for m in media[: max(1, min(int(per_page or 8), 100))]]


@router.get(WP + "/media/{media_id}")
async def wp_get_media(request: Request, media_id: int):
    _require_auth(request)
    with db_session() as s:
        m = s.exec(select(BlogMedia).where(BlogMedia.id == media_id)).first()
    if m is None:
        raise HTTPException(status_code=404)
    return _media_json(m)


@router.post(WP + "/media")
async def wp_upload_media(request: Request):
    _require_auth(request)
    disp = request.headers.get("content-disposition", "")
    m = re.search(r'filename="([^"]+)"', disp)
    raw_name = Path(m.group(1)).name if m else "upload.bin"
    stem = _slugify(Path(raw_name).stem) or "file"
    ext = Path(raw_name).suffix.lower()[:8]
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    name, n = f"{stem}{ext}", 2
    while (MEDIA_DIR / name).exists():
        name = f"{stem}-{n}{ext}"
        n += 1
    (MEDIA_DIR / name).write_bytes(data)
    with db_session() as s:
        row = BlogMedia(filename=name, title=Path(raw_name).stem)
        s.add(row)
        s.commit()
        s.refresh(row)
        return JSONResponse(_media_json(row), status_code=201)


@router.post(WP + "/media/{media_id}")
async def wp_update_media(request: Request, media_id: int):
    _require_auth(request)
    body = await request.json()
    with db_session() as s:
        m = s.exec(select(BlogMedia).where(BlogMedia.id == media_id)).first()
        if m is None:
            raise HTTPException(status_code=404)
        if "alt_text" in body:
            m.alt_text = body["alt_text"] or ""
        if "title" in body:
            m.title = body["title"] or m.title
        s.add(m)
        s.commit()
        s.refresh(m)
        return _media_json(m)


# ---------- one-off WordPress import ----------

def import_wordpress(base_url: str) -> int:
    """Pull published posts (+ images) from a live WordPress at base_url into
    the native blog. Idempotent by slug. Run BEFORE the nginx cutover, while
    the old WP still answers on its public REST API."""
    base = base_url.rstrip("/") + "/wp-json/wp/v2"
    imported = 0
    with httpx.Client(timeout=30.0, follow_redirects=True) as c:
        page = 1
        while True:
            r = c.get(f"{base}/posts", params={
                "per_page": 50, "page": page, "status": "publish",
                "_fields": "id,slug,date_gmt,title,content,featured_media"})
            if r.status_code >= 400:
                break
            batch = r.json()
            if not batch:
                break
            for wp in batch:
                slug = wp["slug"]
                with db_session() as s:
                    if s.exec(select(BlogPost).where(BlogPost.slug == slug)).first():
                        continue
                content = (wp.get("content") or {}).get("rendered", "")
                # Localise images: anything under the old WP uploads dir gets
                # downloaded into our media store so WP can be switched off.
                content, first_media_id = _localise_images(c, base_url, content)
                feat_id = None
                fm = wp.get("featured_media")
                if fm:
                    try:
                        mr = c.get(f"{base}/media/{fm}",
                                   params={"_fields": "source_url,alt_text"})
                        if mr.status_code < 400 and mr.json().get("source_url"):
                            feat_id = _download_media(
                                c, mr.json()["source_url"],
                                alt=mr.json().get("alt_text", ""))
                    except httpx.HTTPError:
                        pass
                if feat_id is None:
                    feat_id = first_media_id
                title = ((wp.get("title") or {}).get("rendered", "") or slug)
                title = re.sub(r"&#\d+;|&[a-z]+;", lambda m2: {
                    "&amp;": "&", "&#8211;": "–", "&#8217;": "'", "&#8216;": "'",
                    "&#8220;": '"', "&#8221;": '"'}.get(m2.group(0), ""), title)
                dt = None
                try:
                    dt = datetime.fromisoformat(wp.get("date_gmt", ""))
                except ValueError:
                    pass
                with db_session() as s:
                    s.add(BlogPost(slug=slug, title=title, content=content,
                                   status="publish", featured_media_id=feat_id,
                                   published_at=dt or datetime.utcnow()))
                    s.commit()
                imported += 1
            page += 1
    return imported


def _download_media(c: httpx.Client, url: str, alt: str = "") -> Optional[int]:
    try:
        r = c.get(url)
        if r.status_code >= 400 or not r.content:
            return None
    except httpx.HTTPError:
        return None
    raw_name = Path(url.split("?")[0]).name or "image.jpg"
    stem = _slugify(Path(raw_name).stem) or "image"
    ext = Path(raw_name).suffix.lower()[:8] or ".jpg"
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    with db_session() as s:
        existing = s.exec(select(BlogMedia).where(
            BlogMedia.filename == f"{stem}{ext}")).first()
        if existing:
            return existing.id
    name, n = f"{stem}{ext}", 2
    while (MEDIA_DIR / name).exists():
        name = f"{stem}-{n}{ext}"
        n += 1
    (MEDIA_DIR / name).write_bytes(r.content)
    with db_session() as s:
        row = BlogMedia(filename=name, alt_text=alt or "", title=stem)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id


def _localise_images(c: httpx.Client, wp_base: str, content: str):
    """Rewrite <img> URLs under the old WP uploads dir to our media store,
    downloading each file once. Returns (content, first_media_id)."""
    first_id: Optional[int] = None
    pattern = re.compile(re.escape(wp_base.rstrip("/")) + r"/wp-content/uploads/[^\s\"'>]+")
    urls = sorted(set(pattern.findall(content or "")))
    for url in urls:
        mid = _download_media(c, url)
        if mid is None:
            continue
        if first_id is None:
            first_id = mid
        with db_session() as s:
            m = s.exec(select(BlogMedia).where(BlogMedia.id == mid)).first()
        content = content.replace(url, f"/blog/media/{m.filename}")
    return content, first_id
