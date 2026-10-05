#!/usr/bin/env python3
"""Publish the day's codex.comics post to the feed Underglow reads (latest.json, on GitHub Pages).

    python3 publish.py post.png [more.png ...] [--title TEXT] [--link URL] [--date YYYY-MM-DD]
    python3 publish.py --clear

It copies the post's images into days/<date>/, rewrites latest.json, drops days older than --keep,
then commits and pushes (--no-push stops after the commit). It needs only Python 3 and git, with push
access to this repo.
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = "https://ricky-zombie.github.io/underglow-daily/latest.json"
MAX_BYTES = 8 * 1024 * 1024  # the game's own limits
MIN_SIDE, MAX_SIDE = 16, 4096
JPEG_FRAMES = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def kind_and_size(data):
    """("png" or "jpg", width, height) from the file's header, or None for anything else."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        return "png", w, h
    if data[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                return None
            marker = data[i + 1]
            if marker == 0xFF:
                i += 1
            elif marker == 0x01 or 0xD0 <= marker <= 0xD8:
                i += 2
            elif marker in JPEG_FRAMES:
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "jpg", w, h
            else:
                i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None


def git(*args, capture=False):
    r = subprocess.run(["git", "-C", ROOT, *args], check=True, text=True,
                       stdout=subprocess.PIPE if capture else None)
    return r.stdout if capture else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("images", nargs="*", help="the post's images in order (PNG or JPEG); the game shows the first")
    ap.add_argument("--title", default="", help="the post's title")
    ap.add_argument("--link", default="", help="the post on Instagram (an https address)")
    ap.add_argument("--date", default=datetime.date.today().isoformat(), help="YYYY-MM-DD (default: today)")
    ap.add_argument("--keep", type=int, default=14, help="days of images kept on the site (default 14)")
    ap.add_argument("--clear", action="store_true", help="take the comic down: the game shows its stock ad")
    ap.add_argument("--no-push", action="store_true", help="commit, but don't push")
    a = ap.parse_args()
    if a.clear == bool(a.images):
        ap.error("give the post's images, or --clear")
    try:
        day = datetime.date.fromisoformat(a.date)
    except ValueError:
        ap.error(f"--date {a.date!r} isn't YYYY-MM-DD")
    if a.link and not a.link.startswith("https://"):
        ap.error("--link must be an https address")
    if len(a.title) > 200:
        ap.error("--title is over 200 characters")

    # Every image is read and checked before the repo is touched.
    posts = []
    for path in a.images:
        with open(path, "rb") as f:
            data = f.read()
        found = kind_and_size(data)
        if not found:
            sys.exit(f"{path}: not a PNG or JPEG")
        kind, w, h = found
        if len(data) > MAX_BYTES:
            sys.exit(f"{path}: {len(data) / 1e6:.1f} MB; the limit is 8 MB")
        if not (MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE):
            sys.exit(f"{path}: {w} x {h} px; each side must be {MIN_SIDE} to {MAX_SIDE}")
        posts.append((data, kind))

    git("pull", "--ff-only", "--quiet")
    date = day.isoformat()
    days = os.path.join(ROOT, "days")
    names = []
    if posts:
        # A second run for the same day replaces it. Each name carries a hash of the image, so a
        # corrected image is a new address and the game fetches it.
        folder = os.path.join(days, date)
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder)
        for n, (data, kind) in enumerate(posts, 1):
            name = f"{n:02d}-{hashlib.sha256(data).hexdigest()[:12]}.{kind}"
            with open(os.path.join(folder, name), "wb") as f:
                f.write(data)
            names.append(f"days/{date}/{name}")
    feed = {"version": 1, "date": date, "title": a.title, "link": a.link, "images": names}
    with open(os.path.join(ROOT, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(feed, f, indent=2, ensure_ascii=False)
        f.write("\n")
    # Only recent days stay on the site; git's history keeps the rest.
    cutoff = day - datetime.timedelta(days=a.keep)
    for d in sorted(os.listdir(days)):
        try:
            old = datetime.date.fromisoformat(d) < cutoff
        except ValueError:
            continue
        if old:
            shutil.rmtree(os.path.join(days, d))

    git("add", "-A", "--", "latest.json", "days")
    if git("status", "--porcelain", "--", "latest.json", "days", capture=True).strip():
        message = f"{date}: no comic" if a.clear else (f"{date}: {a.title}" if a.title else date)
        git("commit", "--quiet", "-m", message)
    else:
        print("Nothing new: that's what the feed has already.")
    if not a.no_push:
        git("push", "--quiet")
    what = "no comic (the game shows its stock ad)" if a.clear else f"{len(names)} image(s), the first on the bus stop"
    print(f"{date}: {what}.\n{SITE}\nPages takes a minute or two; the game reads it as play starts and every 3 hours.")


if __name__ == "__main__":
    main()
