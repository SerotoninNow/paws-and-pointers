# Paws & Pointers

A catboy-themed blog about learning computer science. Flask + SQLite, with
accounts, comments, Markdown posts and syntax-highlighted code.

## Run it

```bash
.venv/bin/python app.py
```

Then open http://127.0.0.1:5000.

Setting it up on another machine:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## How it works

- **The first account you register is the admin.** Only the admin can write,
  edit and delete posts (a "+ New post" link appears in the header).
- Everyone else can sign up to comment. People can delete their own comments;
  the admin can delete any.
- Posts are written in Markdown. Use fenced blocks (```` ```python ````) for
  highlighted code.
- Images in posts: in the editor, paste or drop an image (or use "Add image")
  and it appears in the text at the cursor, with text boxes above and below
  it. Add as many as you like. Drag an image's bottom-right corner or type a
  width to resize it. A post is still stored as Markdown: each image is a line
  like `![a cat](/media/12){ width=400 }`. Images are shrunk to at most 1600px
  wide, re-encoded as WebP and stored in the database. Only the admin can
  upload.
- The home page has a search box (matches title, summary, tags and content;
  every word must appear) and a tag menu (the ☰ button). The two combine, e.g. `/?q=sort&tag=python`.
- Logged-in users can like a post (once each; clicking again takes it back).
  The home page can be sorted newest first, oldest first, most liked or most
  commented, via the Sort dropdown or `?sort=newest|oldest|liked|commented`.
- Every account has a profile at `/user/<username>` and a settings page
  (click your name in the header) for a display name, pronouns, a bio and a
  profile picture. Pictures are shown as a circle; the uploader chooses which
  part to keep or to show the whole picture uncropped. Animated GIFs are
  allowed and play only while hovered. Pictures are shrunk to 256px,
  re-encoded as WebP and stored in the database, so they sync along with
  everything else.
- Moderation: the admin can delete any single comment, and from a person's
  profile can delete all their comments or the whole account (which removes
  its comments, likes and picture too). The "Accounts" link in the header
  lists every account. A deleted account's username can be registered again.
- Data lives in `instance/blog.db`. Delete that file to start fresh.

## Make it yours

| What                          | Where                                  |
|-------------------------------|----------------------------------------|
| Site name, tagline, your name | top of `app.py`                        |
| About page text               | `templates/about.html`                 |
| Colours and fonts             | the `:root` block in `static/style.css`|
| Mascot (placeholder for now)  | `static/catboy.svg`                    |
| Logo and browser-tab icon     | `static/favicon.svg`                   |

## Hosting on more than one device

`host.py` runs the site with gunicorn on `127.0.0.1:8000` and keeps the
database synced with a private GitHub repo (`paws-and-pointers-data`), so
different devices can take turns hosting the same blog.

```bash
.venv/bin/python host.py
```

- On start it pulls the newest snapshot. While running it pushes a new one
  every 5 minutes if something changed. On stop (Ctrl+C) it pushes a last one.
- **One device at a time.** The data repo records who is hosting, and a second
  device refuses to start until the first has stopped. If the first one
  crashed or is definitely off, start with `--force`.
- If two devices both end up with changes the other doesn't have, they can't
  be merged. Start with `--use-remote` to take GitHub's copy (this device's is
  kept as `instance/conflict-*.db`) or `--use-local` to keep this device's.
- `instance/secret_key` is not synced, so visitors are logged out when the
  host changes.

Setting up a new device: log in with `gh auth login`, clone this repo, create
the virtualenv as above, then run `host.py`. It clones the data repo into
`instance/` by itself. Point Tailscale at it with
`tailscale funnel --bg 8000`.

## Security

- **SQL injection:** every query passes values as `?` parameters. The one
  piece of SQL built from a string (the sort order) comes from a fixed list.
- **XSS:** templates escape everything by default, and a Content-Security-Policy
  header only allows scripts from `/static`, so injected markup can't run code.
- **CSRF:** every form carries a per-session token that is checked on POST.
- **Clickjacking and sniffing:** `X-Frame-Options`, `frame-ancestors 'none'`
  and `X-Content-Type-Options: nosniff` are sent with every response.
- **Brute force and spam:** 8 failed logins per 15 minutes and 5 new accounts
  per hour per IP address; 5 comments per minute per user. Counters are kept
  in memory, so they reset when the app restarts.
- **Passwords** are stored as salted hashes, never in plain text.
- **Uploads:** profile pictures are decoded and re-encoded on the server, so
  only pixels are kept (no metadata, no files disguised as images). Uploads
  are capped at 8 MB, animations at 120 frames and 1 MB once shrunk, and
  profile saves at 10 per minute per user.
- **Impersonation:** a display name can't match another account's username or
  display name, and the username is always shown beside it.

Posts are trusted: Markdown may contain raw HTML, and only the admin can write
them. Don't paste Markdown from people you don't trust.

## Before putting it on the internet

`app.py` runs Flask's development server, which is meant for your own machine.
To host it publicly:

- Run it behind a production server (e.g. `gunicorn app:app`) with HTTPS.
- Set `SESSION_COOKIE_SECURE=1` in the environment. This also turns on HSTS.
- Register your admin account before sharing the link: the first account
  registered becomes the admin.
- Behind a reverse proxy, every visitor appears to come from the proxy's
  address, so the per-IP limits are shared. Configure Werkzeug's `ProxyFix`
  for your proxy to fix that.
