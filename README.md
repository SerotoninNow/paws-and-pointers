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
- Data lives in `instance/blog.db`. Delete that file to start fresh.

## Make it yours

| What                          | Where                                  |
|-------------------------------|----------------------------------------|
| Site name, tagline, your name | top of `app.py`                        |
| About page text               | `templates/about.html`                 |
| Colours and fonts             | the `:root` block in `static/style.css`|
| Mascot                        | `static/catboy.svg`                    |

## Before putting it on the internet

`app.py` runs Flask's development server, which is meant for your own machine.
To host it publicly, run it behind a production server (e.g. `gunicorn app:app`)
with HTTPS, set `SESSION_COOKIE_SECURE=True`, and add login rate limiting.
