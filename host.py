"""Host the blog and keep its database synced with the private data repo.

Run with:  .venv/bin/python host.py

The data repo is cloned into instance/. It holds backup.db (a snapshot of the
live blog.db) and host.txt (which device is hosting right now). On start this
pulls the latest snapshot, while running it pushes a new one every few minutes
when something changed, and on stop it pushes a final one.

Only one device should host at a time. See "Hosting on more than one device"
in the README.
"""

import argparse
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
INSTANCE_DIR = BASE_DIR / "instance"
DATA_REPO = os.environ.get(
    "DATA_REPO", "https://github.com/SerotoninNow/paws-and-pointers-data.git"
)
BIND = os.environ.get("BIND", "127.0.0.1:8000")
SYNC_EVERY = int(os.environ.get("SYNC_EVERY", "300"))  # seconds
HOSTNAME = socket.gethostname()

# Commits in the data repo are made under this identity.
GIT_IDENTITY = [
    "-c", "user.name=paws-blog sync",
    "-c", "user.email=137849711+SerotoninNow@users.noreply.github.com",
]

# Only these files are synced. secret_key stays on each device, so visitors
# are logged out when the host changes but the key never leaves the machine.
DATA_GITIGNORE = "*\n!.gitignore\n!backup.db\n!host.txt\n"


def live_db():
    return INSTANCE_DIR / "blog.db"


def backup_db():
    return INSTANCE_DIR / "backup.db"


def host_file():
    return INSTANCE_DIR / "host.txt"


def log(message):
    print(f"[host] {message}", flush=True)


def git(*args, check=True):
    result = subprocess.run(
        ["git", *GIT_IDENTITY, *args],
        cwd=INSTANCE_DIR,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result


def snapshot():
    """Copy the live database to backup.db using SQLite's own backup, which is
    safe while the app is writing."""
    if not live_db().exists():
        return
    tmp = INSTANCE_DIR / "backup.db.tmp"
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(live_db())
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, backup_db())


def restore():
    """Replace the live database with the synced snapshot."""
    if not backup_db().exists():
        return
    tmp = INSTANCE_DIR / "blog.db.tmp"
    shutil.copyfile(backup_db(), tmp)
    os.replace(tmp, live_db())


def commit(message):
    git("add", "-A")
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return False
    git("commit", "-q", "-m", message)
    return True


def ahead_behind():
    out = git("rev-list", "--left-right", "--count", "HEAD...origin/main").stdout.split()
    return int(out[0]), int(out[1])


def push():
    result = git("push", "-q", "origin", "HEAD:main", check=False)
    if result.returncode != 0:
        log("PUSH FAILED, changes are saved on this device only for now:")
        log(result.stderr.strip() or "unknown error")
        return False
    return True


def current_host():
    """The device named in host.txt, or '' when nobody is hosting."""
    if not host_file().exists():
        return ""
    lines = host_file().read_text().splitlines()
    return lines[0].strip() if lines else ""


def prepare(args):
    """Bring instance/ up to date with the data repo. Exits if it is not safe
    to start hosting."""
    if not (INSTANCE_DIR / ".git").exists():
        if INSTANCE_DIR.exists() and any(INSTANCE_DIR.iterdir()):
            sys.exit(
                "instance/ has files in it but is not a clone of the data repo.\n"
                "Move it out of the way and run this again to clone a fresh copy."
            )
        log(f"cloning {DATA_REPO} into instance/")
        subprocess.run(["git", "clone", "-q", DATA_REPO, str(INSTANCE_DIR)], check=True)

    # Keep anything this device has that was never pushed (e.g. after a crash).
    snapshot()
    if commit(f"Unsynced changes from {HOSTNAME}"):
        log("found changes on this device that were never pushed")

    if git("fetch", "-q", "origin", check=False).returncode != 0:
        if not args.offline:
            sys.exit(
                "Can't reach GitHub, so the newest data can't be checked.\n"
                "Pass --offline to host with this device's copy anyway."
            )
        log("offline: hosting with this device's copy")
    else:
        ahead, behind = ahead_behind()
        if ahead and behind:
            if args.use_remote:
                keep = INSTANCE_DIR / f"conflict-{datetime.now():%Y%m%d-%H%M%S}.db"
                shutil.copyfile(backup_db(), keep)
                git("reset", "-q", "--hard", "origin/main")
                log(f"took GitHub's copy; this device's version is kept in {keep.name}")
            elif args.use_local:
                git("merge", "-q", "-s", "ours", "-m", f"Keep {HOSTNAME}'s copy", "origin/main")
                log("kept this device's copy; GitHub's version stays in the history")
            else:
                sys.exit(
                    "This device and GitHub both have changes the other doesn't.\n"
                    "They can't be merged, so pick one:\n"
                    "  --use-remote   take GitHub's copy (this device's is saved as instance/conflict-*.db)\n"
                    "  --use-local    keep this device's copy and overwrite GitHub's"
                )
        elif behind:
            git("merge", "-q", "--ff-only", "origin/main")
            log(f"pulled {behind} update(s) from GitHub")

    other = current_host()
    if other and other != HOSTNAME and not args.force:
        sys.exit(
            f"'{other}' is marked as hosting right now.\n"
            "Stop it there first. If it crashed or is definitely off, pass --force."
        )

    restore()
    host_file().write_text(f"{HOSTNAME}\nsince {datetime.now():%Y-%m-%d %H:%M}\n")
    commit(f"{HOSTNAME} started hosting")
    if git("rev-parse", "-q", "--verify", "origin/main", check=False).returncode != 0 or ahead_behind()[0]:
        push()


def sync():
    """Push a new snapshot if anything changed since the last one."""
    snapshot()
    commit(f"Sync from {HOSTNAME}")
    if ahead_behind()[0]:
        push()


def finish():
    snapshot()
    host_file().write_text("")
    commit(f"{HOSTNAME} stopped hosting")
    if ahead_behind()[0] and push():
        log("final snapshot pushed")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true",
                        help="host even if another device is marked as hosting")
    parser.add_argument("--offline", action="store_true",
                        help="host with this device's copy when GitHub is unreachable")
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--use-remote", action="store_true",
                        help="on a conflict, take GitHub's copy")
    choice.add_argument("--use-local", action="store_true",
                        help="on a conflict, keep this device's copy")
    args = parser.parse_args()

    prepare(args)

    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    env = dict(os.environ, SESSION_COOKIE_SECURE="1", TRUST_PROXY="1")
    # One worker: the app's rate limits are kept in that process's memory.
    server = subprocess.Popen(
        [sys.executable, "-m", "gunicorn", "--workers", "1", "--threads", "8",
         "--bind", BIND, "app:app"],
        cwd=BASE_DIR,
        env=env,
    )
    log(f"serving on {BIND}, syncing every {SYNC_EVERY}s")

    next_sync = time.monotonic() + SYNC_EVERY
    try:
        while not stopping and server.poll() is None:
            time.sleep(1)
            if time.monotonic() >= next_sync:
                next_sync = time.monotonic() + SYNC_EVERY
                try:
                    sync()
                except Exception as exc:  # keep serving if a sync fails
                    log(f"sync failed: {exc}")
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                server.kill()
        finish()
    return server.returncode or 0


if __name__ == "__main__":
    sys.exit(main())
