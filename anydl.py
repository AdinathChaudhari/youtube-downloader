#!/usr/bin/env python3
"""anydl — a universal, interactive downloader.

Downloads from ~any URL by routing each one to the right engine:

  * video sites / playlists / embedded media → yt-dlp (1,700+ extractors + generic)
  * live streams / yt-dlp failures            → streamlink
  * direct files over HTTP(S) (any file type) → aria2c (multi-connection) or stdlib
  * FTP                                        → aria2c or stdlib urllib
  * torrents / magnet links                    → aria2c (BitTorrent)

aria2c is optional: if it's on PATH it's used for direct/FTP/torrent downloads
(faster, resumable, and the only way to do torrents/magnets); if it isn't, a
pure-stdlib downloader handles HTTP/FTP files and torrents print an install hint.

Usage:  python anydl.py
        (then paste URLs one per line, type 'done', and answer the FCP prompt)

The router + multi-engine design is inspired by ghost-downloader-3
(https://github.com/xiaoyouchr/ghost-downloader-3).
"""
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, unquote


BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Extensions we treat as "a file to download" (vs. a web page to extract from).
KNOWN_FILE_EXTS = {
    # video
    ".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".ts", ".m4v", ".mpg",
    ".mpeg", ".wmv", ".3gp",
    # audio
    ".mp3", ".m4a", ".aac", ".flac", ".wav", ".opus", ".ogg", ".wma",
    # archives / disk images / installers
    ".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".bz2", ".dmg", ".pkg",
    ".iso", ".deb", ".rpm", ".apk", ".msi", ".exe",
    # docs / images / data
    ".pdf", ".epub", ".mobi", ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".bmp", ".svg", ".tiff", ".srt", ".vtt", ".ass", ".json", ".csv", ".txt",
    ".xml",
}

# Container exts worth a lossless remux to .mp4 for Final Cut Pro (if codecs allow).
FCP_REMUX_EXTS = {".mkv", ".ts", ".flv", ".avi", ".wmv", ".m4v", ".webm"}


def ensure_yt_dlp():
    try:
        import yt_dlp
    except ImportError:
        print("Installing yt-dlp...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp>=2026.3.17"])
        import yt_dlp
    return yt_dlp


def ensure_streamlink():
    """Return a command prefix that invokes streamlink, installing it if needed."""
    exe = shutil.which("streamlink")
    if exe:
        return [exe]
    try:
        import streamlink  # noqa: F401
        return [sys.executable, "-m", "streamlink"]
    except ImportError:
        print("Installing streamlink (for live / unsupported streams)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "streamlink"])
        return [sys.executable, "-m", "streamlink"]


def find_aria2c():
    return shutil.which("aria2c")


def safe_filename(name):
    """Strip characters not allowed in file/folder names."""
    return re.sub(r'[\\/:*?"<>|]', "", name or "").strip() or "download"


def unique_path(path):
    """Return path, or 'name (1).ext' etc. if it already exists."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


def is_playlist(info):
    return info.get("_type") == "playlist"


def ask_fcp_mode():
    print("\nOptimize video for Final Cut Pro / QuickTime? (H.264 + AAC, guaranteed compatibility)")
    print("(Only affects video; direct files / torrents / FTP are downloaded as-is.)")
    while True:
        ans = input("FCP compatible output? [y/n]: ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("  Enter y or n.")


# ── yt-dlp extraction ─────────────────────────────────────────────────────────
# remote_components ejs:github is needed for current YouTube extraction; it is
# ignored (harmless) by every other extractor, so it's safe to pass globally.
_BASE_OPTS = {"quiet": True, "no_warnings": True, "remote_components": ["ejs:github"]}


# ── Browser-cookie support (paywalled / bot-checked sites like YouTube) ─────────
# Cookies are used only as a *retry* when a site demands sign-in, so the common
# case pays no cost and no keychain prompt. When a block does hit, we ask ONCE
# which browser you're logged in on (auto-detecting by disk path can't tell which
# browser holds the login) and reuse that choice for the rest of the session.
BROWSERS = ["safari", "chrome", "firefox", "edge", "brave", "opera"]
_COOKIE_BROWSER = False  # False = not yet asked, None = declined, str = chosen browser


def _needs_cookies(err):
    """True if a yt-dlp error is a sign-in / bot-check that cookies could fix."""
    s = str(err).lower()
    return ("sign in to confirm" in s or "not a bot" in s
            or "confirm you" in s or "sign in to view" in s)


def choose_cookie_browser():
    """Ask once which browser to read cookies from; cache the answer for the run."""
    global _COOKIE_BROWSER
    if _COOKIE_BROWSER is not False:
        return _COOKIE_BROWSER
    print("\n  This site wants a sign-in cookie. Which browser are you logged into "
          "it on?")
    for i, b in enumerate(BROWSERS, 1):
        print(f"    {i}. {b.capitalize()}")
    print("    0. None / skip")
    while True:
        ans = input("  Browser [0-6]: ").strip()
        if ans in ("0", ""):
            _COOKIE_BROWSER = None
            return None
        if ans.isdigit() and 1 <= int(ans) <= len(BROWSERS):
            _COOKIE_BROWSER = BROWSERS[int(ans) - 1]
            return _COOKIE_BROWSER
        print("  Enter a number 0-6.")


def cookie_opts():
    """yt-dlp opts to read cookies from the chosen browser, or {} if declined."""
    b = choose_cookie_browser()
    return {"cookiesfrombrowser": (b, None, None, None)} if b else {}


def _extract(fn, seed=None):
    """Run an extraction fn(extra_opts), retrying once with browser cookies on a
    sign-in / bot-check. Returns (info, cookie_extra_that_worked) or None on failure.

    `seed` reuses cookies already known to work for this URL so we don't re-detect
    (or re-prompt the keychain) on every subsequent extraction of the same video.
    """
    from yt_dlp.utils import DownloadError
    base = dict(seed or {})
    try:
        return fn(base), base
    except DownloadError as e:
        # Not a cookie issue, or we already retried with cookies → give up.
        if not _needs_cookies(e) or base:
            print(f"  yt-dlp couldn't extract media: {str(e)[:200]}")
            return None
        ck = cookie_opts()
        if not ck:
            print(f"  yt-dlp couldn't extract media: {str(e)[:200]}")
            print("  Skipped cookies — this URL needs a sign-in to download.")
            return None
        print(f"  Retrying with {_COOKIE_BROWSER} cookies "
              "(your keychain may prompt)...")
        try:
            return fn(ck), ck
        except DownloadError as e2:
            print(f"  yt-dlp still couldn't extract media: {str(e2)[:200]}")
            return None


def probe(url, yt_dlp, extra=None):
    """Lightweight yt-dlp probe — flat for playlists — used to route the URL."""
    opts = dict(_BASE_OPTS, extract_flat="in_playlist")
    if extra:
        opts.update(extra)
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def get_full_info(url, yt_dlp, extra=None):
    """Full extraction with the format list for a single video."""
    opts = dict(_BASE_OPTS)
    if extra:
        opts.update(extra)
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


_KNOWN_IES = None


def known_extractor(url, yt_dlp):
    """True if a *specific* (non-generic) yt-dlp extractor claims this URL.

    Lets us route known video sites straight to yt-dlp without an HTTP probe,
    and avoids misrouting a known URL whose path happens to end in a file ext.
    """
    global _KNOWN_IES
    if _KNOWN_IES is None:
        from yt_dlp.extractor import gen_extractor_classes
        _KNOWN_IES = [ie for ie in gen_extractor_classes()
                      if "generic" not in ie.IE_NAME.lower()
                      and "commonmistakes" not in ie.IE_NAME.lower()]
    try:
        return any(ie.suitable(url) for ie in _KNOWN_IES)
    except Exception:
        return False


# ── Quality selection (site-agnostic) ─────────────────────────────────────────
# The never-a-dead-end option: hand format choice back to yt-dlp per video.
BEST_OPTION = {"label": "best available", "kind": "best", "height": None,
               "fps": 0, "format_id": None, "has_audio": True}


def build_quality_options(info):
    """Return selectable quality options (best first) for any site.

    Each option: {label, kind, height, fps, format_id}.
      kind == "height"  → group video streams by resolution (YouTube-style)
      kind == "format"  → a specific format_id (sites without height metadata)
      kind == "best"    → let yt-dlp pick the best available stream
    """
    formats = info.get("formats") or []

    # Tier 1: streams that carry a real pixel height → group by resolution.
    by_label = {}
    for f in formats:
        if not f.get("vcodec") or f.get("vcodec") == "none":
            continue
        height = f.get("height")
        if not height:
            continue
        fps = f.get("fps") or 0
        label = f"{height}p" + (f" {int(fps)}fps" if fps > 30 else "")
        tbr = f.get("tbr") or 0
        if label not in by_label or tbr > (by_label[label].get("tbr") or 0):
            by_label[label] = {
                "label": label, "kind": "height", "height": height, "fps": fps,
                "ext": f.get("ext", "?"),
                "has_audio": bool(f.get("acodec") and f["acodec"] != "none"),
                "tbr": tbr,
            }
    if by_label:
        return sorted(by_label.values(), key=lambda x: x["height"], reverse=True)

    # Tier 2: video streams without height metadata → offer them by note/bitrate.
    opts = []
    for f in formats:
        if f.get("vcodec") == "none" and f.get("acodec") == "none":
            continue
        if f.get("vcodec") == "none":  # audio-only, skip in the video picker
            continue
        note = f.get("format_note") or f.get("resolution") or f.get("format") or f.get("format_id")
        tbr = f.get("tbr") or 0
        label = str(note)
        if f.get("ext"):
            label += f"  .{f['ext']}"
        opts.append({
            "label": label, "kind": "format", "height": f.get("height"), "fps": f.get("fps") or 0,
            "format_id": f.get("format_id"),
            "has_audio": bool(f.get("acodec") and f["acodec"] != "none"),
            "tbr": tbr,
        })
    # De-dupe by label, keep highest bitrate, sort best first.
    dedup = {}
    for o in opts:
        if o["label"] not in dedup or o["tbr"] > dedup[o["label"]]["tbr"]:
            dedup[o["label"]] = o
    opts = sorted(dedup.values(), key=lambda x: x["tbr"], reverse=True)

    # Tier 3 / fallback: always offer "best available" so nothing is a dead end.
    opts.append(dict(BEST_OPTION))
    return opts


def pick_option(info):
    options = build_quality_options(info)

    title = info.get("title", "Unknown")
    duration = int(info.get("duration") or 0)
    print(f"\nTitle: {title}")
    if duration:
        print(f"Duration: {duration // 60}m {duration % 60}s")

    # Single obvious choice (e.g. a direct MP4, or only "best") → don't nag.
    if len(options) == 1:
        print(f"Quality: {options[0]['label']}")
        return options[0]

    print("\nAvailable qualities:")
    for i, opt in enumerate(options):
        if opt["kind"] == "best":
            note = "(auto-selects the best video+audio)"
        elif opt.get("has_audio"):
            note = "(video+audio)"
        else:
            note = "(video — audio merged automatically)"
        print(f"  [{i + 1}] {opt['label']}  {note}")

    print()
    while True:
        choice = input(f"Select quality [1-{len(options)}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1]
        print(f"  Enter a number between 1 and {len(options)}.")


def build_fmt_spec(chosen, fcp_mode):
    kind = chosen.get("kind", "best")

    if kind == "height":
        h = chosen["height"]
        fps = chosen.get("fps") or 0
        fps_filter = f"[fps<={int(fps)}]" if fps > 30 else ""
        if fcp_mode:
            return (
                f"bestvideo[vcodec^=avc][height={h}]{fps_filter}+bestaudio[acodec=mp4a]"
                f"/bestvideo[vcodec^=avc][height<={h}]+bestaudio[acodec=mp4a]"
                f"/bestvideo[vcodec^=avc][height<={h}]+bestaudio"
            )
        # Height-based selectors so one pick works across a whole playlist,
        # not just the video whose formats were sampled.
        return (
            f"bestvideo[height={h}]{fps_filter}+bestaudio"
            f"/bestvideo[height<={h}]+bestaudio"
            f"/best[height<={h}]/best"
        )

    if kind == "format" and chosen.get("format_id"):
        fid = chosen["format_id"]
        # Try the exact stream (+ audio if it's video-only), then degrade to best.
        base = f"{fid}+bestaudio/{fid}/best"
        if fcp_mode:
            return "bestvideo[vcodec^=avc]+bestaudio[acodec=mp4a]/best[vcodec^=avc]/" + base
        return base

    # kind == "best" (or anything unexpected) → best available.
    if fcp_mode:
        return ("bestvideo[vcodec^=avc]+bestaudio[acodec=mp4a]"
                "/best[vcodec^=avc]/bestvideo+bestaudio/best")
    return "bestvideo+bestaudio/best"


def build_ydl_opts(fmt_spec, outtmpl, fcp_mode, extra=None):
    opts = dict(_BASE_OPTS)
    opts.update({"format": fmt_spec, "outtmpl": outtmpl, "noplaylist": True})
    # Probe options were quiet; a foreground single download should show progress.
    opts["quiet"] = False
    opts["no_warnings"] = False
    if fcp_mode:
        opts["merge_output_format"] = "mp4"
        opts["postprocessor_args"] = ["-c:a", "aac"]
    if extra:
        opts.update(extra)
    return opts


def outtmpl_for(chosen, output_dir=None):
    # Only tag the filename with resolution when the site actually reports one.
    if chosen.get("kind") == "height":
        name = "%(title).200s [%(height)sp].%(ext)s"
    else:
        name = "%(title).200s.%(ext)s"
    return os.path.join(output_dir, name) if output_dir else name


# ── streamlink fallback (live / yt-dlp can't handle) ──────────────────────────
def download_with_streamlink(url, title, fcp_mode, output_dir=None, reason="live/unsupported"):
    cmd = ensure_streamlink()
    out_ts = safe_filename(title) + ".ts"
    if output_dir:
        out_ts = os.path.join(output_dir, out_ts)

    print(f"\nyt-dlp can't grab this directly ({reason}); using streamlink...")
    print("  For a live stream, press Ctrl-C to stop recording.\n")
    rc = subprocess.call(cmd + [url, "best", "-o", out_ts, "--force"])
    if rc != 0 or not os.path.exists(out_ts):
        print("  ✗ streamlink could not download this URL.")
        return False

    if fcp_mode and shutil.which("ffmpeg"):
        out_mp4 = out_ts[:-3] + ".mp4"
        # Container remux to .mp4 for FCP/QuickTime; stream copy keeps it fast.
        rc = subprocess.call(["ffmpeg", "-y", "-i", out_ts, "-c", "copy", out_mp4],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if rc == 0 and os.path.exists(out_mp4):
            os.remove(out_ts)
            print(f"  ✓ Saved (remuxed to .mp4): {out_mp4}")
            return True
    print(f"  ✓ Saved: {out_ts}")
    return True


# ── yt-dlp download drivers ────────────────────────────────────────────────────
def download_single(url, chosen, fcp_mode, yt_dlp, output_dir=None, extra=None):
    fmt_spec = build_fmt_spec(chosen, fcp_mode)
    outtmpl = outtmpl_for(chosen, output_dir)
    mode_label = "FCP-compatible (H.264/AAC)" if fcp_mode else "original format"
    print(f"\nDownloading {chosen['label']} [{mode_label}]...\n")
    ydl_opts = build_ydl_opts(fmt_spec, outtmpl, fcp_mode, extra)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


FORMAT_SAMPLE_LIMIT = 5


def sample_playlist_formats(entries, yt_dlp, cookie_extra=None):
    """Full-extract the first *usable* playlist entry, for the quality picker.

    Long playlists routinely open with a dead item (copyright block, deleted,
    private, region-locked). Sampling only entries[0] let one such item abort the
    whole run, so walk down the list until one extracts. Returns
    (info, cookie_extra) or None if the first FORMAT_SAMPLE_LIMIT are all dead.
    """
    tried = 0
    for entry in entries:
        item_url = entry.get("url") or entry.get("webpage_url")
        if not item_url:
            continue
        got = _extract(lambda extra: get_full_info(item_url, yt_dlp, extra),
                       seed=cookie_extra)
        if got is not None:
            return got
        tried += 1
        if tried >= FORMAT_SAMPLE_LIMIT:
            break
        print("  That item is unavailable — sampling the next one...")
    return None


FAILED_MANIFEST = "failed.txt"


def write_failed_manifest(folder, playlist_title, failed, total):
    """Write ./<folder>/failed.txt listing everything the playlist run couldn't get.

    Dual-purpose on purpose: every comment line starts with '#', so the file reads
    fine to a human *and* `grep -v '^#' failed.txt` yields a bare URL list you can
    paste straight back into anydl for a retry. On a long playlist the console tally
    scrolls away; this is the copy that survives.

    Never raises — a manifest problem must not fail a run that already downloaded.
    """
    path = os.path.join(folder, FAILED_MANIFEST)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"# anydl — failed items from \"{playlist_title}\"\n")
            fh.write(f"# {len(failed)} of {total} failed · {stamp}\n")
            fh.write("# '#' lines are comments; the bare lines are URLs.\n")
            fh.write("# Retry with:  grep -v '^#' failed.txt\n")
            for idx, title, item_url, reason in failed:
                fh.write(f"\n# [{idx}/{total}] {title}\n")
                # Reason is a yt-dlp error — keep it one line so the file stays scannable.
                fh.write(f"#     {' '.join(str(reason).split())[:300]}\n")
                fh.write(f"{item_url or '# (no URL in playlist entry)'}\n")
        return path
    except OSError as e:
        print(f"  note: couldn't write {FAILED_MANIFEST}: {e}")
        return None


def download_playlist(url, info, fcp_mode, yt_dlp, cookie_extra=None):
    playlist_title = info.get("title") or "playlist"
    entries = [e for e in (info.get("entries") or []) if e]
    if not entries:
        print("No videos found in playlist.")
        return

    print(f"\nPlaylist: {playlist_title}")
    print(f"Videos:   {len(entries)}\n")

    print("Fetching formats from the first available item to pick quality...")
    sampled = sample_playlist_formats(entries, yt_dlp, cookie_extra)
    if sampled is None:
        print(f"\n  Couldn't read formats from the first {FORMAT_SAMPLE_LIMIT} "
              "items — using 'best available' for the whole playlist.")
        chosen = dict(BEST_OPTION)
    else:
        sample_info, cookie_extra = sampled
        chosen = pick_option(sample_info)

    folder = safe_filename(playlist_title)
    os.makedirs(folder, exist_ok=True)
    mode_label = "FCP-compatible (H.264/AAC)" if fcp_mode else "original format"
    print(f"\nSaving to folder: ./{folder}/  [{mode_label}]\n")

    failed = []
    for i, entry in enumerate(entries, 1):
        video_url = entry.get("url") or entry.get("webpage_url")
        video_title = entry.get("title") or f"video_{i}"
        print(f"[{i}/{len(entries)}] {video_title}")
        try:
            fmt_spec = build_fmt_spec(chosen, fcp_mode)
            outtmpl = outtmpl_for(chosen, folder)
            ydl_opts = build_ydl_opts(fmt_spec, outtmpl, fcp_mode,
                                      dict(cookie_extra or {},
                                           quiet=True, no_warnings=True))
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            print("  ✓ Done")
        except Exception as e:
            print(f"  ✗ Failed: {str(e)[:200]}")
            failed.append((i, video_title, video_url, e))

    print(f"\n{'─' * 50}")
    print(f"Downloaded: {len(entries) - len(failed)}/{len(entries)}")
    if failed:
        print(f"Failed ({len(failed)}):")
        for _, t, _, _ in failed:
            print(f"  - {t}")
        manifest = write_failed_manifest(folder, playlist_title, failed, len(entries))
        if manifest:
            print(f"Failed list: ./{manifest}")
    print(f"Folder: ./{folder}/")


# ── HTTP(S) probe + classification ─────────────────────────────────────────────
def _origin(url):
    s = urlsplit(url)
    return f"{s.scheme}://{s.netloc}/" if s.scheme and s.netloc else None


def probe_url(url):
    """One ranged GET (browser headers). Returns (final_url, headers, body) or None.

    A ranged GET (never HEAD) is used because HEAD is frequently rejected or
    unsigned on presigned CDN URLs (GitHub releases, S3/GCS). Retries once with a
    Referer if the first attempt is refused.
    """
    for extra in ({}, {"Referer": _origin(url) or ""}):
        headers = dict(BROWSER_HEADERS, Range="bytes=0-8191")
        headers.update({k: v for k, v in extra.items() if v})
        try:
            resp = urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=30)
        except urllib.error.HTTPError:
            continue          # try the Referer variant, then give up
        except Exception:
            return None
        try:
            body = resp.read(8192)
            final = resp.geturl()
            hdrs = resp.headers
            resp.close()
            return (final, hdrs, body)
        except Exception:
            return None
    return None


def classify(final_url, headers, body):
    """Decide MANIFEST / FILE / PAGE. Priority: body sniff > disposition > type > ext."""
    ct = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
    cd = (headers.get("Content-Disposition") or "").lower()
    path = urlsplit(final_url).path.lower()
    b = body.lstrip(b"\xef\xbb\xbf \t\r\n")

    # 1. Body sniff wins (misreported content-types are common).
    if b.startswith(b"#EXTM3U"):
        return "MANIFEST"
    if b"<MPD" in b[:2048]:
        return "MANIFEST"
    # 2. Manifest by extension / content-type.
    if path.endswith((".m3u8", ".m3u", ".mpd")) or ct in {
            "application/vnd.apple.mpegurl", "application/x-mpegurl",
            "audio/mpegurl", "audio/x-mpegurl", "application/dash+xml"}:
        return "MANIFEST"
    # 3. "Content-Disposition: attachment" → the server wants us to save it.
    if "attachment" in cd:
        return "FILE"
    # 4. Explicit HTML (by type or body) → a web page to extract from.
    head = b[:256].lower()
    if ct in {"text/html", "application/xhtml+xml"} or head.startswith(
            (b"<!doctype", b"<html", b"<head")):
        return "PAGE"
    # 5. Binary/media content-types → a file.
    if ct.startswith(("video/", "audio/", "image/")) or ct in {
            "application/octet-stream", "application/zip", "application/pdf",
            "application/x-7z-compressed", "application/gzip",
            "application/x-tar", "application/x-rar-compressed",
            "application/x-bittorrent"}:
        return "FILE"
    # 6. Known file extension.
    if os.path.splitext(path)[1] in KNOWN_FILE_EXTS:
        return "FILE"
    return "PAGE"


def derive_filename(url, headers):
    cd = headers.get("Content-Disposition") or ""
    m = (re.search(r"filename\*\s*=\s*(?:UTF-8'')?([^;\r\n]+)", cd, re.I)
         or re.search(r'filename\s*=\s*"?([^";\r\n]+)"?', cd, re.I))
    if m:
        return safe_filename(unquote(m.group(1).strip().strip('"')))
    name = unquote(os.path.basename(urlsplit(url).path))
    return safe_filename(name)


def _looks_like_html_file(path, limit=65536):
    """True if a small downloaded file is actually an HTML (error) page."""
    try:
        if os.path.getsize(path) > limit:
            return False
        with open(path, "rb") as f:
            head = f.read(256).lstrip().lower()
        return head.startswith((b"<!doctype", b"<html", b"<head"))
    except OSError:
        return False


# ── aria2c + stdlib download engines ───────────────────────────────────────────
_ARIA2_BASE = ["--console-log-level=warn", "--summary-interval=0",
               "--file-allocation=none", "--max-tries=3", "--retry-wait=2",
               "--connect-timeout=15", "--timeout=30"]


def download_via_aria2(url, output_dir, mode, filename=None, referer=None):
    aria = find_aria2c()
    if not aria:
        return False
    args = [aria] + list(_ARIA2_BASE) + ["-d", output_dir or "."]
    if mode == "http":
        args += ["-c", "--always-resume=false", "-x", "8", "-s", "8",
                 "--min-split-size=1M", "--auto-file-renaming=false",
                 "--allow-overwrite=false", "--user-agent", BROWSER_HEADERS["User-Agent"]]
        if referer:
            args += ["--referer", referer]
        if filename:
            args += ["-o", filename]
    elif mode == "ftp":
        args += ["-c", "-x", "4", "-s", "4", "--ftp-pasv=true"]
        if filename:
            args += ["-o", filename]
    elif mode == "torrent":
        args += ["--seed-time=0", "--bt-stop-timeout=600",
                 "--follow-torrent=mem", "--bt-save-metadata=false"]
    args.append(url)
    return subprocess.call(args) == 0


def _download_urllib_to(url, target, referer=None, expect_media=True):
    """Stream a URL to <target> via .part, then atomic rename. urllib handles ftp://."""
    headers = dict(BROWSER_HEADERS)
    if referer:
        headers["Referer"] = referer
    try:
        resp = urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=60)
    except urllib.error.HTTPError as e:
        print(f"  ✗ HTTP {e.code} {e.reason}")
        return None
    except Exception as e:
        print(f"  ✗ Download failed: {e}")
        return None

    with resp:
        total = int(resp.headers.get("Content-Length") or 0)
        encoded = bool(resp.headers.get("Content-Encoding"))
        first = resp.read(1 << 16)
        if expect_media and first[:256].lstrip().lower().startswith(
                (b"<!doctype", b"<html", b"<head")):
            print("  ✗ Server returned an HTML page, not a file.")
            return None
        part = target + ".part"
        name = os.path.basename(target)
        print(f"\nDownloading {name}" + (f" ({total / 1e6:.1f} MB)" if total else "") + "...")
        done = 0
        with open(part, "wb") as f:
            f.write(first)
            done += len(first)
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done * 100 // total:3d}%  "
                          f"{done / 1e6:.1f}/{total / 1e6:.1f} MB", end="", flush=True)
        if total:
            print()

    if total and not encoded and done != total:
        print(f"  ✗ Incomplete ({done}/{total} bytes); kept {part}")
        return None
    os.replace(part, target)
    print(f"  ✓ Saved: {target}")
    return target


def download_direct(url, filename, output_dir=None, referer=None, expect_media=True):
    """Download a direct HTTP(S) file via aria2c (if present) else stdlib. Returns path/None."""
    outdir = output_dir or "."
    target = unique_path(os.path.join(outdir, safe_filename(filename)))
    name = os.path.basename(target)
    if find_aria2c():
        if download_via_aria2(url, outdir, "http", filename=name, referer=referer):
            if os.path.exists(target):
                if expect_media and _looks_like_html_file(target):
                    os.remove(target)
                    print("  ✗ Got an HTML page, not a file.")
                    return None
                print(f"  ✓ Saved: {target}")
                return target
        print("  aria2c didn't produce the file; falling back to built-in downloader...")
    return _download_urllib_to(url, target, referer=referer, expect_media=expect_media)


def download_ftp(url, output_dir=None):
    if find_aria2c():
        name = derive_filename(url, {})
        if download_via_aria2(url, output_dir, "ftp", filename=name):
            print("  ✓ Done")
            return True
        print("  aria2c FTP failed; trying built-in...")
    name = derive_filename(url, {})
    target = unique_path(os.path.join(output_dir or ".", name))
    return _download_urllib_to(url, target, expect_media=False) is not None


def download_torrent(url, output_dir=None):
    if not find_aria2c():
        print("\nThis is a torrent/magnet link — it needs aria2 to download:")
        print("  macOS:  brew install aria2")
        print("  Linux:  sudo apt install aria2   (or your package manager)")
        return False
    print("\nDownloading torrent/magnet via aria2c (Ctrl-C to abort)...\n")
    ok = download_via_aria2(url, output_dir, "torrent")
    print("  ✓ Done" if ok else "  ✗ Torrent download failed or timed out.")
    return ok


def maybe_fcp_remux(path):
    """Losslessly remux a video file to .mp4 for FCP — only if codecs already fit."""
    if os.path.splitext(path)[1].lower() not in FCP_REMUX_EXTS:
        return
    if not (shutil.which("ffprobe") and shutil.which("ffmpeg")):
        return

    def codec(stream):
        try:
            out = subprocess.check_output(
                ["ffprobe", "-v", "error", "-select_streams", stream,
                 "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1", path],
                text=True).strip().splitlines()
            return out[0].strip() if out else ""
        except Exception:
            return ""

    vcodec, acodec = codec("v:0"), codec("a:0")
    if vcodec in ("h264", "hevc") and acodec in ("aac", ""):
        mp4 = unique_path(os.path.splitext(path)[0] + ".mp4")
        rc = subprocess.call(["ffmpeg", "-y", "-i", path, "-c", "copy", mp4],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if rc == 0 and os.path.exists(mp4):
            os.remove(path)
            print(f"  ✓ Remuxed to FCP-friendly .mp4: {mp4}")
    else:
        print(f"  note: codecs {vcodec or '?'}/{acodec or '?'} — left as-is; "
              "FCP import may need a transcode.")


# ── The router ──────────────────────────────────────────────────────────────
def yt_dlp_flow(url, fcp_mode, yt_dlp, allow_streamlink=True):
    """Existing video path: playlist → live → single video, with streamlink fallback.
    Returns True on success, False if yt-dlp couldn't handle it."""
    from yt_dlp.utils import DownloadError

    print("\nFetching info...")
    probed = _extract(lambda extra: probe(url, yt_dlp, extra))
    if probed is None:
        return False
    info, cookie_extra = probed

    if is_playlist(info):
        download_playlist(url, info, fcp_mode, yt_dlp, cookie_extra)
        return True

    # Reuse any cookies that already worked so we don't re-detect / re-prompt.
    full = _extract(lambda extra: get_full_info(url, yt_dlp, extra), seed=cookie_extra)
    if full is None:
        return False
    info, cookie_extra = full

    if info.get("is_live"):
        if allow_streamlink:
            return download_with_streamlink(url, info.get("title") or "live_stream",
                                            fcp_mode, reason="live stream")
        return False

    chosen = pick_option(info)
    try:
        download_single(url, chosen, fcp_mode, yt_dlp, extra=cookie_extra)
        print("\nDone!")
        return True
    except DownloadError as e:
        print(f"  yt-dlp download failed: {str(e)[:200]}")
        if allow_streamlink:
            return download_with_streamlink(url, info.get("title") or "download",
                                            fcp_mode, reason="yt-dlp download failed")
        return False


def handle_url(url, fcp_mode, yt_dlp):
    """Route one URL to the right engine."""
    scheme = urlsplit(url).scheme.lower()

    # 1. Torrent / magnet.
    if scheme == "magnet" or urlsplit(url).path.lower().endswith(".torrent") \
            or (not scheme and url.lower().endswith(".torrent")):
        download_torrent(url)
        return

    # 2. FTP and unsupported / unsafe schemes.
    if scheme == "ftp":
        download_ftp(url)
        return
    if scheme in ("ftps", "sftp"):
        print(f"\n{scheme}:// isn't supported by aria2/urllib. Skipping.")
        return
    if scheme in ("data", "file", "about", "javascript"):
        print(f"\n{scheme}: URLs aren't downloadable here. Skipping.")
        return
    if scheme not in ("http", "https"):
        print(f"\nUnsupported URL scheme '{scheme}'. Skipping.")
        return

    # 3a. A specific yt-dlp extractor claims it → straight to the video path.
    if known_extractor(url, yt_dlp):
        yt_dlp_flow(url, fcp_mode, yt_dlp)
        return

    # 3b. Probe once, then classify.
    probed = probe_url(url)
    if probed is None:
        # Couldn't probe → UNKNOWN: yt-dlp, then a guarded direct attempt, then streamlink.
        if yt_dlp_flow(url, fcp_mode, yt_dlp, allow_streamlink=False):
            return
        print("  Trying a direct download...")
        saved = download_direct(url, derive_filename(url, {}), referer=_origin(url))
        if saved:
            if fcp_mode:
                maybe_fcp_remux(saved)
            return
        download_with_streamlink(url, derive_filename(url, {}) or "download",
                                 fcp_mode, reason="all extractors failed")
        return

    final_url, headers, body = probed
    kind = classify(final_url, headers, body)

    if kind == "MANIFEST":
        yt_dlp_flow(url, fcp_mode, yt_dlp)
    elif kind == "FILE":
        filename = derive_filename(final_url, headers)
        print(f"\nDetected direct file: {filename}")
        saved = download_direct(final_url, filename, referer=_origin(url))
        if saved and fcp_mode:
            maybe_fcp_remux(saved)
    else:  # PAGE — never direct-download (it would save the HTML page).
        if not yt_dlp_flow(url, fcp_mode, yt_dlp, allow_streamlink=True):
            print("  ✗ Couldn't find any downloadable media at this URL.")


def main():
    yt_dlp = ensure_yt_dlp()

    print("anydl — universal downloader")
    print("Paste URLs from any site (videos, playlists, live streams, direct files,")
    print("FTP, torrents/magnets), one per line. Type 'done' when finished.")
    urls = []
    while True:
        line = input(f"URL {len(urls) + 1} (or 'done'): ").strip()
        if line.lower() in ("done", "d", ""):
            if not urls:
                print("No URLs provided.")
                sys.exit(1)
            break
        urls.append(line)

    print(f"\n{len(urls)} URL(s) queued.")
    fcp_mode = ask_fcp_mode()

    for i, url in enumerate(urls, 1):
        if len(urls) > 1:
            print(f"\n{'═' * 50}")
            print(f"Item {i}/{len(urls)}: {url}")
        try:
            handle_url(url, fcp_mode, yt_dlp)
        except KeyboardInterrupt:
            # Skip just this item; keep the queue going.
            print("\n  ⏹  Skipped (Ctrl-C).")
            continue
        except Exception as e:
            # Same rule for an unexpected engine error: one bad URL must not
            # take the rest of the queue down with it.
            print(f"\n  ✗ Skipped — unexpected error: {str(e)[:200]}")
            continue

    if len(urls) > 1:
        print(f"\n{'═' * 50}")
        print("All downloads complete.")


if __name__ == "__main__":
    main()
