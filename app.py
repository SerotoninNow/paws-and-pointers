"""Paws & Pointers: a catboy-themed computer science blog.

Run with:  .venv/bin/python app.py
"""

import os
import re
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import markdown as md
from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

# ---------------------------------------------------------------- settings --
# Change these to make the blog yours.
SITE_NAME = "Paws & Pointers"
SITE_TAGLINE = "A catboy learning computer science"
AUTHOR_NAME = "Serowo"

BASE_DIR = Path(__file__).parent
INSTANCE_DIR = BASE_DIR / "instance"
DB_PATH = INSTANCE_DIR / "blog.db"

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 200
MAX_COMMENT_LEN = 2000
MAX_TITLE_LEN = 150
MAX_SUMMARY_LEN = 300
MAX_TAGS_LEN = 150

# Rate limits: name -> (max events, per this many seconds).
RATE_LIMITS = {
    "login": (8, 15 * 60),  # failed logins per IP address
    "register": (5, 60 * 60),  # new accounts per IP address
    "comment": (5, 60),  # comments per user
}

# Sent with every response. Scripts may only come from /static, so injected
# markup can't run code; nothing may frame the site (clickjacking).
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self';"
        " style-src-attr 'unsafe-inline'; img-src 'self' data: https:;"
        " object-src 'none'; base-uri 'self'; form-action 'self';"
        " frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
MAX_QUERY_LEN = 100

# Home page orderings: key -> (label, ORDER BY clause).
SORTS = {
    "newest": ("Newest first", "p.created_at DESC, p.id DESC"),
    "oldest": ("Oldest first", "p.created_at ASC, p.id ASC"),
    "liked": ("Most liked", "n_likes DESC, p.created_at DESC, p.id DESC"),
    "commented": ("Most commented", "n_comments DESC, p.created_at DESC, p.id DESC"),
}
DEFAULT_SORT = "newest"


def load_secret_key():
    """Use $SECRET_KEY if set, otherwise generate one and keep it on disk."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    INSTANCE_DIR.mkdir(exist_ok=True)
    key_file = INSTANCE_DIR / "secret_key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
        key_file.chmod(0o600)
    return key_file.read_text().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Set SESSION_COOKIE_SECURE=1 when serving over HTTPS.
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
    MAX_CONTENT_LENGTH=1024 * 1024,
)

# A hash to compare against when the username doesn't exist, so login takes
# the same time either way.
DUMMY_HASH = generate_password_hash(secrets.token_hex(16))


# ---------------------------------------------------------------- database --
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


WELCOME_POST = """\
This is a placeholder post so the blog isn't empty. Edit or delete it once
you're logged in as the admin (the first account registered).

## What I'll post here

Mostly notes on whatever I'm studying, plus write-ups of projects when I
finish one. Some of it will be wrong. Tell me in the comments if so.

## Markdown test

Code blocks are highlighted:

```python
def binary_search(items, target):
    lo, hi = 0, len(items) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if items[mid] == target:
            return mid
        if items[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
```

And tables:

| Structure   | Lookup   | Insert   |
|-------------|----------|----------|
| Array       | O(1)     | O(n)     |
| Hash map    | O(1)     | O(1)     |
| Binary tree | O(log n) | O(log n) |
"""


def init_db():
    INSTANCE_DIR.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript((BASE_DIR / "schema.sql").read_text())
    if db.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0:
        db.execute(
            "INSERT INTO posts (slug, title, summary, body_md, tags, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                "hello-world",
                "Hello, world! (=^･ω･^=)",
                "Placeholder first post, also a test that Markdown works.",
                WELCOME_POST,
                "meta, python",
                now_iso(),
            ),
        )
    db.commit()
    db.close()


# ---------------------------------------------------------------- security --
@app.after_request
def set_security_headers(response):
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if app.config["SESSION_COOKIE_SECURE"]:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


# Recent event times per (limit name, key). Kept in memory, so it resets on
# restart and is per-process if you run several workers.
_rate_events = defaultdict(deque)


def _recent_events(name, key):
    events = _rate_events[(name, key)]
    cutoff = time.monotonic() - RATE_LIMITS[name][1]
    while events and events[0] < cutoff:
        events.popleft()
    return events


def rate_limited(name, key):
    return len(_recent_events(name, key)) >= RATE_LIMITS[name][0]


def record_event(name, key):
    _recent_events(name, key).append(time.monotonic())
    if len(_rate_events) > 10_000:  # don't let the table grow without bound
        for k in [k for k, v in _rate_events.items() if not v]:
            del _rate_events[k]


def client_ip():
    return request.remote_addr or "unknown"


# ------------------------------------------------------------ auth helpers --
@app.before_request
def load_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        g.user = get_db().execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if g.user is None:
            session.clear()


@app.before_request
def csrf_protect():
    if request.method == "POST":
        expected = session.get("csrf_token", "")
        sent = request.form.get("csrf_token", "")
        if not expected or not secrets.compare_digest(expected, sent):
            abort(400)


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Log in first.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        if not g.user["is_admin"]:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def safe_next(target):
    """Only allow redirects back to paths on this site."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("index")


# -------------------------------------------------------- template helpers --
def render_markdown(text):
    html = md.markdown(
        text,
        extensions=["fenced_code", "codehilite", "tables", "sane_lists"],
        extension_configs={"codehilite": {"guess_lang": False}},
    )
    return Markup(html)


@app.template_filter("pretty_date")
def pretty_date(iso):
    if not iso:
        return ""
    dt = datetime.fromisoformat(iso)
    return f"{dt:%b} {dt.day}, {dt.year}"


@app.template_filter("reading_time")
def reading_time(text):
    return max(1, round(len(text.split()) / 200))


@app.template_filter("tag_list")
def tag_list(tags):
    return [t.strip() for t in tags.split(",") if t.strip()]


@app.template_filter("hue")
def hue(name):
    """A stable colour per username, for comment avatars."""
    return sum(ord(c) for c in name.lower()) * 37 % 360


@app.context_processor
def inject_globals():
    return {
        "site_name": SITE_NAME,
        "site_tagline": SITE_TAGLINE,
        "author_name": AUTHOR_NAME,
        "csrf_token": csrf_token,
        "year": datetime.now().year,
    }


def slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "post"
    return slug[:80]


def unique_slug(title, ignore_id=None):
    db = get_db()
    base = slugify(title)
    slug, n = base, 2
    while True:
        row = db.execute("SELECT id FROM posts WHERE slug = ?", (slug,)).fetchone()
        if row is None or row["id"] == ignore_id:
            return slug
        slug = f"{base}-{n}"
        n += 1


def get_post_or_404(slug):
    post = get_db().execute("SELECT * FROM posts WHERE slug = ?", (slug,)).fetchone()
    if post is None:
        abort(404)
    return post


# ------------------------------------------------------------------- pages --
def matches_search(post, terms):
    """True if every search term appears somewhere in the post."""
    haystack = " ".join(
        (post["title"], post["summary"], post["tags"], post["body_md"])
    ).casefold()
    return all(term in haystack for term in terms)


@app.route("/")
def index():
    tag = request.args.get("tag", "").strip().lower()
    query = " ".join(request.args.get("q", "").split())[:MAX_QUERY_LEN]
    sort = request.args.get("sort", DEFAULT_SORT)
    if sort not in SORTS:
        sort = DEFAULT_SORT
    # The ORDER BY is the only SQL built from a string, and it comes from the
    # fixed SORTS table above, never from the request. Everything else is
    # passed as ? parameters.
    posts = get_db().execute(
        "SELECT p.*,"
        " (SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id) AS n_comments,"
        " (SELECT COUNT(*) FROM likes l WHERE l.post_id = p.id) AS n_likes"
        f" FROM posts p ORDER BY {SORTS[sort][1]}"
    ).fetchall()

    # Every tag on the blog with its post count, for the filter bar.
    tag_counts = {}
    for p in posts:
        for t in {t.lower() for t in tag_list(p["tags"])}:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    all_tags = sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))

    if tag:
        posts = [p for p in posts if tag in [t.lower() for t in tag_list(p["tags"])]]
    if query:
        terms = query.casefold().split()
        posts = [p for p in posts if matches_search(p, terms)]
    return render_template(
        "index.html",
        posts=posts,
        tag=tag,
        query=query,
        all_tags=all_tags,
        sort=sort,
        sorts=SORTS,
        # Left out of links when it's the default, to keep URLs short.
        sort_param=sort if sort != DEFAULT_SORT else None,
    )


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/post/<slug>")
def post_detail(slug):
    post = get_post_or_404(slug)
    db = get_db()
    comments = db.execute(
        "SELECT c.*, u.username, u.is_admin FROM comments c"
        " JOIN users u ON u.id = c.user_id"
        " WHERE c.post_id = ? ORDER BY c.created_at, c.id",
        (post["id"],),
    ).fetchall()
    n_likes = db.execute(
        "SELECT COUNT(*) FROM likes WHERE post_id = ?", (post["id"],)
    ).fetchone()[0]
    liked = g.user is not None and db.execute(
        "SELECT 1 FROM likes WHERE post_id = ? AND user_id = ?", (post["id"], g.user["id"])
    ).fetchone() is not None
    return render_template(
        "post.html",
        post=post,
        n_likes=n_likes,
        liked=liked,
        body_html=render_markdown(post["body_md"]),
        comments=comments,
        max_comment_len=MAX_COMMENT_LEN,
    )


# ------------------------------------------------------------------- likes --
@app.post("/post/<slug>/like")
@login_required
def toggle_like(slug):
    """Like the post, or take the like back if this user already liked it."""
    post = get_post_or_404(slug)
    db = get_db()
    key = (post["id"], g.user["id"])
    removed = db.execute("DELETE FROM likes WHERE post_id = ? AND user_id = ?", key).rowcount
    if not removed:
        db.execute(
            "INSERT INTO likes (post_id, user_id, created_at) VALUES (?, ?, ?)",
            (*key, now_iso()),
        )
    db.commit()
    return redirect(url_for("post_detail", slug=slug) + "#like")


# ---------------------------------------------------------------- comments --
@app.post("/post/<slug>/comment")
@login_required
def add_comment(slug):
    post = get_post_or_404(slug)
    body = request.form.get("body", "").strip()
    if not body:
        flash("You can't post an empty comment.", "error")
    elif len(body) > MAX_COMMENT_LEN:
        flash(f"Comments are limited to {MAX_COMMENT_LEN} characters.", "error")
    elif rate_limited("comment", g.user["id"]):
        flash("You're commenting too fast. Wait a minute and try again.", "error")
    else:
        record_event("comment", g.user["id"])
        db = get_db()
        db.execute(
            "INSERT INTO comments (post_id, user_id, body, created_at) VALUES (?, ?, ?, ?)",
            (post["id"], g.user["id"], body, now_iso()),
        )
        db.commit()
        flash("Comment posted.", "ok")
    return redirect(url_for("post_detail", slug=slug) + "#comments")


@app.post("/comment/<int:comment_id>/delete")
@login_required
def delete_comment(comment_id):
    db = get_db()
    comment = db.execute(
        "SELECT c.*, p.slug FROM comments c JOIN posts p ON p.id = c.post_id WHERE c.id = ?",
        (comment_id,),
    ).fetchone()
    if comment is None:
        abort(404)
    if comment["user_id"] != g.user["id"] and not g.user["is_admin"]:
        abort(403)
    db.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    db.commit()
    flash("Comment deleted.", "ok")
    return redirect(url_for("post_detail", slug=comment["slug"]) + "#comments")


# -------------------------------------------------------------------- auth --
@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("index"))
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        db = get_db()
        error = None
        if not USERNAME_RE.match(username):
            error = "Usernames are 3 to 20 characters. Letters, numbers and underscores only."
        elif len(password) < MIN_PASSWORD_LEN:
            error = f"Passwords need at least {MIN_PASSWORD_LEN} characters."
        elif len(password) > MAX_PASSWORD_LEN:
            error = f"Passwords can be at most {MAX_PASSWORD_LEN} characters."
        elif password != confirm:
            error = "Those passwords don't match."
        elif db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            error = "That username is already taken."
        elif rate_limited("register", client_ip()):
            error = "Too many new accounts from this address. Try again later."

        if error is None:
            record_event("register", client_ip())
            # The very first account owns the blog.
            is_first = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            cur = db.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at)"
                " VALUES (?, ?, ?, ?)",
                (username, generate_password_hash(password), int(is_first), now_iso()),
            )
            db.commit()
            session.clear()
            session["user_id"] = cur.lastrowid
            flash(
                "Account created. You're the first user, so you're the admin."
                if is_first
                else f"Account created. Hi, {username}.",
                "ok",
            )
            return redirect(safe_next(request.args.get("next")))
        flash(error, "error")
    return render_template("register.html", username=username)


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")[:MAX_PASSWORD_LEN + 1]
        if rate_limited("login", client_ip()):
            flash("Too many failed logins. Wait a few minutes and try again.", "error")
            return render_template("login.html", username=username), 429
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        ok = check_password_hash(user["password_hash"] if user else DUMMY_HASH, password)
        if user and ok:
            _rate_events.pop(("login", client_ip()), None)
            session.clear()
            session["user_id"] = user["id"]
            flash(f"Logged in as {user['username']}.", "ok")
            return redirect(safe_next(request.args.get("next")))
        record_event("login", client_ip())
        flash("Wrong username or password.", "error")
    return render_template("login.html", username=username)


@app.post("/logout")
def logout():
    session.clear()
    flash("Logged out.", "ok")
    return redirect(url_for("index"))


# ------------------------------------------------------------ post editing --
def read_post_form():
    return {
        "title": request.form.get("title", "").strip()[:MAX_TITLE_LEN],
        "summary": request.form.get("summary", "").strip()[:MAX_SUMMARY_LEN],
        "tags": ", ".join(tag_list(request.form.get("tags", "")[:MAX_TAGS_LEN])),
        "body_md": request.form.get("body_md", "").strip(),
    }


@app.route("/new", methods=["GET", "POST"])
@admin_required
def new_post():
    form = {"title": "", "summary": "", "tags": "", "body_md": ""}
    if request.method == "POST":
        form = read_post_form()
        if not form["title"] or not form["body_md"]:
            flash("A post needs a title and some content.", "error")
        else:
            slug = unique_slug(form["title"])
            db = get_db()
            db.execute(
                "INSERT INTO posts (slug, title, summary, body_md, tags, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (slug, form["title"], form["summary"], form["body_md"], form["tags"], now_iso()),
            )
            db.commit()
            flash("Post published.", "ok")
            return redirect(url_for("post_detail", slug=slug))
    return render_template("editor.html", form=form, post=None)


@app.route("/post/<slug>/edit", methods=["GET", "POST"])
@admin_required
def edit_post(slug):
    post = get_post_or_404(slug)
    form = dict(post)
    if request.method == "POST":
        form = read_post_form()
        if not form["title"] or not form["body_md"]:
            flash("A post needs a title and some content.", "error")
        else:
            db = get_db()
            db.execute(
                "UPDATE posts SET title = ?, summary = ?, body_md = ?, tags = ?, updated_at = ?"
                " WHERE id = ?",
                (form["title"], form["summary"], form["body_md"], form["tags"], now_iso(), post["id"]),
            )
            db.commit()
            flash("Post updated.", "ok")
            return redirect(url_for("post_detail", slug=slug))
    return render_template("editor.html", form=form, post=post)


@app.post("/post/<slug>/delete")
@admin_required
def delete_post(slug):
    post = get_post_or_404(slug)
    db = get_db()
    db.execute("DELETE FROM posts WHERE id = ?", (post["id"],))
    db.commit()
    flash("Post deleted.", "ok")
    return redirect(url_for("index"))


# ------------------------------------------------------------------ errors --
ERRORS = {
    400: ("Bad request", "The form expired. Go back, refresh and try again."),
    403: ("Not allowed", "You don't have permission to do that."),
    404: ("Page not found", "Nothing here. The cat probably knocked it off the desk."),
}


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
def handle_error(err):
    title, message = ERRORS[err.code]
    return render_template("error.html", code=err.code, title=title, message=message), err.code


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
