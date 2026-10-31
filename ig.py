#!/usr/bin/env python3
"""Instagram manager CLI for agents. Stdlib only. Every command prints JSON.

Usage: python3 ig.py <command> [args]   (run `python3 ig.py -h` for the list)
"""
import argparse
import contextlib
import csv
import fcntl
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_VERSION = "v26.0"
GRAPH = f"https://graph.instagram.com/{API_VERSION}"
CREDS = Path(os.environ.get("IG_CREDENTIALS", "~/.config/ig-agent/credentials.json")).expanduser()
CSV_FIELDS = ["id", "publish_at", "type", "caption", "media", "status", "ig_media_id", "permalink", "error"]
TIME_FMT = "%Y-%m-%d %H:%M"  # local time of the machine running run-due
IMAGE_EXT = {".jpg", ".jpeg"}  # Instagram API accepts JPEG only
VIDEO_EXT = {".mp4", ".mov"}
REFRESH_AFTER_DAYS = 7  # long-lived tokens last 60 days; refresh early and often
STATUS_POLL_SECONDS = 10
STATUS_POLL_MAX = 60  # 10 minutes, enough for a reel download


class IGError(Exception):
    pass


def out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


# ---------- credentials + HTTP ----------

def load_creds():
    if not CREDS.exists():
        raise IGError(f"Not authenticated. Run: python3 ig.py auth  (expects token on stdin). Looked in {CREDS}")
    return json.loads(CREDS.read_text())


def save_creds(creds):
    CREDS.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = CREDS.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        f.write(json.dumps(creds, indent=2))  # created 0600, never readable by others
    tmp.replace(CREDS)


def http_json(method, url, token=None, params=None):
    params = {k: v for k, v in (params or {}).items() if v is not None}
    data = None
    if method in ("GET", "DELETE"):
        url += ("&" if "?" in url else "?") + urlencode(params) if params else ""
    else:
        data = urlencode(params).encode()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with urlopen(Request(url, data=data, method=method, headers=headers), timeout=60) as r:
            return json.load(r)
    except HTTPError as e:
        raise IGError(f"HTTP {e.code} on {method} {url.split('?')[0]}: {e.read().decode(errors='replace')}") from None
    except URLError as e:
        raise IGError(f"Network error on {method} {url.split('?')[0]}: {e.reason}") from None


def api(method, path, creds, **params):
    return http_json(method, f"{GRAPH}/{path}", creds["access_token"], params)


def maybe_refresh(creds, force=False):
    age_days = (time.time() - creds.get("refreshed_at", 0)) / 86400
    if not force and age_days < REFRESH_AFTER_DAYS:
        return creds
    r = http_json("GET", "https://graph.instagram.com/refresh_access_token",
                  params={"grant_type": "ig_refresh_token", "access_token": creds["access_token"]})
    new = {**creds, "access_token": r["access_token"], "refreshed_at": time.time(),
           "expires_at": time.time() + int(r.get("expires_in", 0))}
    save_creds(new)
    return new


# ---------- public URLs for local media ----------

def is_url(s):
    return s.startswith("https://") or s.startswith("http://")


def media_kind(path):
    ext = Path(path.split("?")[0]).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    raise IGError(f"Unsupported media '{path}'. Images must be .jpg/.jpeg, videos .mp4/.mov.")


def find_cloudflared():
    return shutil.which("cloudflared") or next(
        (p for p in ("/opt/homebrew/bin/cloudflared", "/usr/local/bin/cloudflared") if os.path.exists(p)), None)


def wait_reachable(url, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urlopen(Request(url, method="HEAD"), timeout=10) as r:
                if r.status == 200:
                    return
        except (HTTPError, URLError, TimeoutError, OSError):
            pass
        time.sleep(3)
    raise IGError(f"Tunnel URL never became reachable: {url}")


@contextlib.contextmanager
def tunnel(local_paths):
    """Serve ONLY the given files (copied to a temp dir) over a Cloudflare quick tunnel."""
    with tempfile.TemporaryDirectory() as d:
        names = {}
        for p in local_paths:
            name = f"{uuid.uuid4().hex}{Path(p).suffix.lower()}"
            shutil.copy(p, Path(d) / name)
            names[p] = name
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=d))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        proc = subprocess.Popen([find_cloudflared(), "tunnel", "--no-autoupdate", "--url",
                                 f"http://127.0.0.1:{server.server_address[1]}"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            base, deadline = None, time.time() + 60
            while not base and time.time() < deadline:
                line = proc.stderr.readline()
                if not line and proc.poll() is not None:
                    break
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                base = m and m.group(0)
            if not base:
                raise IGError("cloudflared did not return a tunnel URL")
            threading.Thread(target=proc.stderr.read, daemon=True).start()  # drain so it never blocks
            urls = {p: f"{base}/{n}" for p, n in names.items()}
            for u in urls.values():
                wait_reachable(u)
            yield urls
        finally:
            proc.terminate()
            server.shutdown()


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def litterbox(path):
    # ponytail: third-party temp host with 1h expiry and no SLA; install cloudflared for the reliable path
    r = subprocess.run(["curl", "-sS", "--fail", "-F", "reqtype=fileupload", "-F", "time=1h",
                        "-F", f"fileToUpload=@{path}", "https://litterbox.catbox.moe/resources/internals/api.php"],
                       capture_output=True, text=True, timeout=300)
    url = r.stdout.strip()
    if r.returncode != 0 or not is_url(url):
        raise IGError(f"Litterbox upload failed: {r.stderr or r.stdout}")
    return url


@contextlib.contextmanager
def public_urls(items):
    local = [i for i in items if not is_url(i)]
    for p in local:
        if not Path(p).is_file():
            raise IGError(f"Media file not found: {p}")
    if not local:
        yield {i: i for i in items}
    elif find_cloudflared():
        with tunnel(local) as urls:
            yield {i: urls.get(i, i) for i in items}
    else:
        yield {i: (i if is_url(i) else litterbox(i)) for i in items}


# ---------- publishing ----------

def wait_finished(creds, container_id):
    for _ in range(STATUS_POLL_MAX):
        r = api("GET", container_id, creds, fields="status_code,status")
        code = r.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise IGError(f"Container {container_id} {code}: {r.get('status')}")
        time.sleep(STATUS_POLL_SECONDS)
    raise IGError(f"Container {container_id} not ready after {STATUS_POLL_SECONDS * STATUS_POLL_MAX}s")


def media_params(kind, url):
    return {"image_url": url} if kind == "image" else {"video_url": url}


def build_containers(creds, post_type, media, caption, urls):
    """Create containers; return the id to publish."""
    uid = creds["user_id"]
    kinds = [media_kind(m) for m in media]
    if post_type == "carousel":
        if not 2 <= len(media) <= 20:
            raise IGError("Carousel needs 2 to 20 media items")
        children = []
        for m, k in zip(media, kinds):
            extra = {"media_type": "VIDEO"} if k == "video" else {}
            c = api("POST", f"{uid}/media", creds, is_carousel_item="true", **media_params(k, urls[m]), **extra)
            wait_finished(creds, c["id"])
            children.append(c["id"])
        return api("POST", f"{uid}/media", creds, media_type="CAROUSEL",
                   children=",".join(children), caption=caption)["id"]
    if len(media) != 1:
        raise IGError(f"'{post_type}' takes exactly one media item")
    k, url = kinds[0], urls[media[0]]
    if post_type == "image":
        if k != "image":
            raise IGError("type=image needs a .jpg/.jpeg")
        return api("POST", f"{uid}/media", creds, image_url=url, caption=caption)["id"]
    if post_type == "reel":
        if k != "video":
            raise IGError("type=reel needs a .mp4/.mov")
        return api("POST", f"{uid}/media", creds, media_type="REELS", video_url=url, caption=caption)["id"]
    if post_type == "story":
        return api("POST", f"{uid}/media", creds, media_type="STORIES", **media_params(k, url))["id"]
    raise IGError(f"Unknown type '{post_type}'. Use image, carousel, reel, story.")


def publish(creds, post_type, media, caption):
    for m in media:
        media_kind(m)  # fail fast before opening a tunnel
    with public_urls(media) as urls:
        cid = build_containers(creds, post_type, media, caption or None, urls)
        wait_finished(creds, cid)  # URLs must stay live until FINISHED
        mid = api("POST", f"{creds['user_id']}/media_publish", creds, creation_id=cid)["id"]
    permalink = api("GET", mid, creds, fields="permalink").get("permalink", "")
    return {"ig_media_id": mid, "permalink": permalink}


def split_media(s):
    return [m.strip() for m in s.split("|") if m.strip()]


# ---------- calendar CSV ----------

def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [{k: (r.get(k) or "").strip() if k != "caption" else (r.get(k) or "") for k in CSV_FIELDS} for r in rows]


def write_rows(path, rows):
    tmp = f"{path}.tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def due_rows(rows, now):
    """Indexes of rows with status=scheduled whose publish_at has passed."""
    due = []
    for i, r in enumerate(rows):
        if r["status"] != "scheduled":
            continue
        try:
            when = datetime.strptime(r["publish_at"], TIME_FMT)
        except ValueError:
            continue  # reported by `validate`
        if when <= now:
            due.append(i)
    return due


def validate_rows(rows, base_dir):
    problems = []
    for r in rows:
        rid = r["id"] or "?"
        try:
            datetime.strptime(r["publish_at"], TIME_FMT)
        except ValueError:
            problems.append(f"{rid}: publish_at '{r['publish_at']}' must be YYYY-MM-DD HH:MM")
        if r["type"] not in ("image", "carousel", "reel", "story"):
            problems.append(f"{rid}: type '{r['type']}' must be image|carousel|reel|story")
        if r["status"] not in ("draft", "scheduled", "posted", "failed"):
            problems.append(f"{rid}: status '{r['status']}' must be draft|scheduled|posted|failed")
        if len(r["caption"]) > 2200:
            problems.append(f"{rid}: caption over 2200 chars")
        for m in split_media(r["media"]):
            try:
                media_kind(m)
            except IGError as e:
                problems.append(f"{rid}: {e}")
            if not is_url(m) and not (base_dir / m).is_file():
                problems.append(f"{rid}: media file not found: {m}")
    return problems


@contextlib.contextmanager
def csv_lock(path):
    with open(f"{path}.lock", "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise IGError("Another run-due is already running on this CSV") from None
        yield


def run_due(csv_path, dry_run=False):
    base = Path(csv_path).resolve().parent
    with csv_lock(csv_path):
        rows = read_rows(csv_path)
        due = due_rows(rows, datetime.now())
        if dry_run:
            return {"due": [rows[i]["id"] for i in due]}
        if not due:
            return {"posted": [], "failed": []}
        creds = maybe_refresh(load_creds())
        posted, failed = [], []
        for i in due:
            r = rows[i]
            media = [m if is_url(m) else str(base / m) for m in split_media(r["media"])]
            try:
                res = publish(creds, r["type"], media, r["caption"])
                rows[i] = {**r, "status": "posted", "error": "", **res}
                posted.append(r["id"])
            except IGError as e:
                rows[i] = {**r, "status": "failed", "error": str(e)[:500]}
                failed.append({"id": r["id"], "error": str(e)})
            # ponytail: write after each post; a crash between publish and this write could repost one row
            write_rows(csv_path, rows)
        return {"posted": posted, "failed": failed}


def render_calendar(rows, title="Content calendar"):
    rows = sorted(rows, key=lambda r: r["publish_at"])
    by_day = {}
    for r in rows:
        by_day.setdefault(r["publish_at"][:10] or "undated", []).append(r)
    e = html.escape
    days = []
    for day, items in by_day.items():
        cards = []
        for r in items:
            media = split_media(r["media"])
            thumb = next((m for m in media if Path(m.split("?")[0]).suffix.lower() in IMAGE_EXT), "")
            img = f'<img src="{e(thumb)}" alt="" loading="lazy">' if thumb else ""
            link = f' <a href="{e(r["permalink"])}">view</a>' if r["permalink"] else ""
            err = f'<p class="err">{e(r["error"])}</p>' if r["error"] else ""
            cards.append(
                f'<article class="card s-{e(r["status"])}">{img}<div><p class="meta">{e(r["publish_at"][11:])} · '
                f'{e(r["type"])} · <b>{e(r["status"])}</b>{link}</p><p class="cap">{e(r["caption"])}</p>{err}</div></article>')
        days.append(f'<section><h2>{e(day)}</h2>{"".join(cards)}</section>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title><style>
:root{{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--card:#fff;--line:#e7e5e4}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0c0a09;--fg:#f5f5f4;--muted:#a8a29e;--card:#1c1917;--line:#292524}}}}
body{{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:760px;margin:auto}} h1{{font-size:22px}} h2{{font-size:14px;color:var(--muted);margin:28px 0 8px}}
.card{{display:flex;gap:12px;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--muted);
border-radius:8px;padding:12px;margin-bottom:8px}} .card img{{width:72px;height:72px;object-fit:cover;border-radius:4px}}
.meta{{margin:0;color:var(--muted);font-size:13px}} .cap{{margin:4px 0 0;white-space:pre-wrap}} .err{{color:#dc2626;margin:4px 0 0}}
.s-scheduled{{border-left-color:#2563eb}} .s-posted{{border-left-color:#16a34a}} .s-failed{{border-left-color:#dc2626}}
</style></head><body><main><h1>{e(title)}</h1>{"".join(days) or "<p>No posts yet.</p>"}</main></body></html>"""


# ---------- commands ----------

def cmd_auth(a):
    token = (os.environ.get("IG_TOKEN") or sys.stdin.read()).strip()
    if not token:
        raise IGError("Pass the token on stdin or in IG_TOKEN")
    me = http_json("GET", f"{GRAPH}/me", token, {"fields": "user_id,username,account_type"})
    creds = {"access_token": token, "user_id": me["user_id"], "username": me.get("username"),
             "account_type": me.get("account_type"), "refreshed_at": 0}
    try:
        creds = maybe_refresh(creds, force=True)  # converts the clock to a fresh 60 days
    except IGError as e:
        creds["refresh_note"] = f"Refresh failed (fine for brand-new tokens, retried later): {e}"
        save_creds(creds)
    out({k: v for k, v in creds.items() if k != "access_token"})


def cmd_whoami(a):
    c = load_creds()
    out(api("GET", "me", c, fields="user_id,username,name,account_type,biography,website,"
                                   "profile_picture_url,followers_count,follows_count,media_count"))


def cmd_refresh(a):
    c = maybe_refresh(load_creds(), force=True)
    out({"ok": True, "expires_at": datetime.fromtimestamp(c["expires_at"]).isoformat()})


def cmd_post(a):
    out(publish(maybe_refresh(load_creds()), a.type, split_media(a.media), a.caption))


def cmd_run_due(a):
    out(run_due(a.csv, a.dry_run))


def cmd_validate(a):
    problems = validate_rows(read_rows(a.csv), Path(a.csv).resolve().parent)
    out({"ok": not problems, "problems": problems})
    if problems:
        sys.exit(1)


def cmd_calendar(a):
    Path(a.out).write_text(render_calendar(read_rows(a.csv)), encoding="utf-8")
    out({"written": str(Path(a.out).resolve())})


def cmd_media(a):
    c = load_creds()
    out(api("GET", f"{c['user_id']}/media", c, limit=a.limit,
            fields="id,caption,media_type,timestamp,permalink,comments_count,like_count"))


def cmd_comments(a):
    c = load_creds()
    out(api("GET", f"{a.media_id}/comments", c, limit=a.limit,
            fields="id,text,username,timestamp,hidden,replies{id,text,username,timestamp}"))


def cmd_reply(a):
    out(api("POST", f"{a.comment_id}/replies", load_creds(), message=a.message))


def cmd_hide(a):
    out(api("POST", a.comment_id, load_creds(), hide="false" if a.unhide else "true"))


def cmd_delete_comment(a):
    out(api("DELETE", a.comment_id, load_creds()))


def cmd_limit(a):
    c = load_creds()
    out(api("GET", f"{c['user_id']}/content_publishing_limit", c, fields="config,quota_usage"))


def main(argv=None):
    p = argparse.ArgumentParser(prog="ig.py", description="Instagram manager for agents. Prints JSON.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth", help="Save a token read from stdin or IG_TOKEN").set_defaults(fn=cmd_auth)
    sub.add_parser("whoami", help="Show the connected account").set_defaults(fn=cmd_whoami)
    sub.add_parser("refresh", help="Refresh the 60-day token now").set_defaults(fn=cmd_refresh)
    sub.add_parser("limit", help="Show publishing quota usage").set_defaults(fn=cmd_limit)

    s = sub.add_parser("post", help="Publish now")
    s.add_argument("--type", required=True, choices=["image", "carousel", "reel", "story"])
    s.add_argument("--media", required=True, help="Paths or URLs, separated by |")
    s.add_argument("--caption", default="")
    s.set_defaults(fn=cmd_post)

    for name, fn, h in (("run-due", cmd_run_due, "Publish scheduled rows that are due"),
                        ("validate", cmd_validate, "Check the CSV for problems"),
                        ("calendar", cmd_calendar, "Render the CSV to an HTML calendar")):
        s = sub.add_parser(name, help=h)
        s.add_argument("--csv", default="content.csv")
        if name == "run-due":
            s.add_argument("--dry-run", action="store_true")
        if name == "calendar":
            s.add_argument("--out", default="calendar.html")
        s.set_defaults(fn=fn)

    s = sub.add_parser("media", help="List recent posts")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(fn=cmd_media)
    s = sub.add_parser("comments", help="List comments on a post")
    s.add_argument("media_id")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(fn=cmd_comments)
    s = sub.add_parser("reply", help="Reply to a comment")
    s.add_argument("comment_id")
    s.add_argument("message")
    s.set_defaults(fn=cmd_reply)
    s = sub.add_parser("hide", help="Hide (or --unhide) a comment")
    s.add_argument("comment_id")
    s.add_argument("--unhide", action="store_true")
    s.set_defaults(fn=cmd_hide)
    s = sub.add_parser("delete-comment", help="Delete a comment")
    s.add_argument("comment_id")
    s.set_defaults(fn=cmd_delete_comment)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except IGError as e:
        out({"error": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    main()
