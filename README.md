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
- The home page has a search box (matches title, summary, tags and content;
  every word must appear) and a tag menu (the ☰ button). The two combine, e.g. `/?q=sort&tag=python`.
- Logged-in users can like a post (once each; clicking again takes it back).
  The home page can be sorted newest first, oldest first, most liked or most
  commented, via the Sort dropdown or `?sort=newest|oldest|liked|commented`.
- Data lives in `instance/blog.db`. Delete that file to start fresh.

## Make it yours

| What                          | Where                                  |
|-------------------------------|----------------------------------------|
| Site name, tagline, your name | top of `app.py`                        |
| About page text               | `templates/about.html`                 |
| Colours and fonts             | the `:root` block in `static/style.css`|
| Mascot                        | `static/catboy.svg`                    |

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
