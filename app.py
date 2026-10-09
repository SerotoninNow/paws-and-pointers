"""Paws & Pointers: a catboy-themed computer science blog.

Run with:  .venv/bin/python app.py
"""

import os
import re
import secrets
import sqlite3
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
MAX_COMMENT_LEN = 2000


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
@app.route("/")
def index():
    tag = request.args.get("tag", "").strip().lower()
    posts = get_db().execute(
        "SELECT p.*, (SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id) AS n_comments"
        " FROM posts p ORDER BY p.created_at DESC, p.id DESC"
    ).fetchall()
    if tag:
        posts = [p for p in posts if tag in [t.lower() for t in tag_list(p["tags"])]]
    return render_template("index.html", posts=posts, tag=tag)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/post/<slug>")
def post_detail(slug):
    post = get_post_or_404(slug)
    comments = get_db().execute(
        "SELECT c.*, u.username, u.is_admin FROM comments c"
        " JOIN users u ON u.id = c.user_id"
        " WHERE c.post_id = ? ORDER BY c.created_at, c.id",
        (post["id"],),
    ).fetchall()
    return render_template(
        "post.html",
        post=post,
        body_html=render_markdown(post["body_md"]),
        comments=comments,
        max_comment_len=MAX_COMMENT_LEN,
    )


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
    else:
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
        elif password != confirm:
            error = "Those passwords don't match."
        elif db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            error = "That username is already taken."

        if error is None:
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
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        ok = check_password_hash(user["password_hash"] if user else DUMMY_HASH, password)
        if user and ok:
            session.clear()
            session["user_id"] = user["id"]
            flash(f"Logged in as {user['username']}.", "ok")
            return redirect(safe_next(request.args.get("next")))
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
        "title": request.form.get("title", "").strip(),
        "summary": request.form.get("summary", "").strip(),
        "tags": ", ".join(tag_list(request.form.get("tags", ""))),
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
