#!/usr/bin/env python3
"""Publish the day's codex.comics post to the feed Underglow reads (latest.json, on GitHub Pages).

    python3 publish.py post.png [more.png ...] [--title TEXT] [--link URL] [--date YYYY-MM-DD]
    python3 publish.py --clear

It copies the post's images into days/<date>/, rewrites latest.json, drops days older than --keep,
then commits and pushes (--no-push stops after the commit). Everything here is public, so each image
loses its metadata (Exif, XMP, Photoshop, text) on the way in, and one in another colour space, such as
Display P3, is converted to sRGB (that part needs Pillow; without it, a note says so). It needs only
Python 3 and git, with push access to this repo.
"""
import argparse
import datetime
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import zlib

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = "https://ricky-zombie.github.io/underglow-daily/latest.json"
MAX_BYTES = 8 * 1024 * 1024  # the game's own limits
MIN_SIDE, MAX_SIDE = 16, 4096
JPEG_FRAMES = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
JPEG_METADATA = {0xE1, 0xED, 0xFE}  # APP1 (Exif, XMP), APP13 (Photoshop, IPTC), comments
PNG_METADATA = {b"tEXt", b"zTXt", b"iTXt", b"tIME", b"eXIf"}


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


def exif_orientation(segment):
    """The Orientation tag of an APP1 Exif segment; 1 (upright) if it has none."""
    t = segment[10:]  # after the marker, the length and "Exif\0\0"
    try:
        e = {b"II": "<", b"MM": ">"}[t[:2]]
        ifd = struct.unpack(e + "I", t[4:8])[0]
        for k in range(struct.unpack(e + "H", t[ifd:ifd + 2])[0]):
            p = ifd + 2 + 12 * k
            if struct.unpack(e + "H", t[p:p + 2])[0] == 0x0112:
                return struct.unpack(e + "H", t[p + 8:p + 10])[0]
    except (KeyError, struct.error):
        pass
    return 1


def strip_jpeg(data):
    """The JPEG without its metadata segments, its colour profile (None if it has none), and its
    Exif orientation."""
    keep, icc, orientation, i = [data[:2]], b"", 1, 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker == 0xDA:  # the image data, kept as it is from here on
            break
        end = i + 2 if marker == 0x01 or 0xD0 <= marker <= 0xD7 else i + 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
        seg = data[i:end]
        if marker == 0xE1 and seg[4:10] == b"Exif\0\0":
            orientation = exif_orientation(seg)
        if marker == 0xE2 and seg[4:16] == b"ICC_PROFILE\0":
            icc += seg[18:]  # after its name and the part's number and count
        if marker not in JPEG_METADATA:
            keep.append(seg)
        i = end
    return b"".join(keep) + data[i:], icc or None, orientation


def strip_png(data):
    """The PNG without its text, time and Exif chunks, and its colour profile (None if it has none)."""
    keep, icc, i = [data[:8]], None, 8
    while i + 12 <= len(data):
        n = struct.unpack(">I", data[i:i + 4])[0]
        kind = data[i + 4:i + 8]
        if kind == b"iCCP":
            body = data[i + 8:i + 8 + n]
            icc = zlib.decompress(body[body.index(b"\0") + 2:])
        if kind not in PNG_METADATA:
            keep.append(data[i:i + 12 + n])
        i += 12 + n
        if kind == b"IEND":
            break
    return b"".join(keep), icc


def to_srgb(data, kind, icc):
    """The image converted to sRGB, untagged and without metadata; None without Pillow."""
    try:
        from PIL import Image, ImageCms
    except ImportError:
        return None
    try:
        im = Image.open(io.BytesIO(data))
        mode = "RGBA" if "A" in im.getbands() or "transparency" in im.info else "RGB"
        im = ImageCms.profileToProfile(im.convert(mode), ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                       ImageCms.createProfile("sRGB"), outputMode=mode)
        out = io.BytesIO()
        if kind == "png":
            im.save(out, "PNG", optimize=True)
        else:
            im.convert("RGB").save(out, "JPEG", quality=95, subsampling=0)
        return out.getvalue()
    except Exception as e:  # an odd profile: keep the image as it was
        print(f"note: couldn't convert it to sRGB ({e})")
        return None


def clean(path, data, kind):
    """The image as it goes public: without its metadata, and in sRGB where it can be converted."""
    if kind == "jpg":
        data, icc, orientation = strip_jpeg(data)
        if orientation != 1:
            sys.exit(f"{path}: its Exif turns it (orientation {orientation}); save it upright and publish again")
    else:
        data, icc = strip_png(data)
    if icc is None or b"sRGB" in icc or "sRGB".encode("utf-16-be") in icc:
        return data
    converted = to_srgb(data, kind, icc)
    if converted is None:
        print(f"note: {path} isn't sRGB, and without Pillow it can't be converted: the game shows it a little duller")
        return data
    print(f"{path}: converted to sRGB")
    return converted


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
        data = clean(path, data, kind)
        if len(data) > MAX_BYTES:
            sys.exit(f"{path}: {len(data) / 1e6:.1f} MB once converted; the limit is 8 MB")
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
