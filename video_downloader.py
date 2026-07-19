#!/usr/bin/env python3
"""anydl — a universal, interactive video downloader.

Downloads video from ~any website. yt-dlp does the heavy lifting (1,700+ sites
plus a generic extractor that sniffs <video> tags / HLS / DASH manifests on
sites it doesn't explicitly know). For live streams and the handful of sites
yt-dlp can't reach, it falls back to streamlink.
"""
import os
import re
import shutil
import subprocess
import sys


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


def safe_filename(name):
    """Strip characters not allowed in file/folder names."""
    return re.sub(r'[\\/:*?"<>|]', "", name or "").strip() or "download"


def is_playlist(info):
    return info.get("_type") == "playlist"


def ask_fcp_mode():
    print("\nOptimize for Final Cut Pro / QuickTime? (H.264 + AAC, guaranteed compatibility)")
    while True:
        ans = input("FCP compatible output? [y/n]: ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("  Enter y or n.")


# ── Extraction ──────────────────────────────────────────────────────────────
# remote_components ejs:github is needed for current YouTube extraction; it is
# ignored (harmless) by every other extractor, so it's safe to pass globally.
_BASE_OPTS = {"quiet": True, "no_warnings": True, "remote_components": ["ejs:github"]}


def probe(url, yt_dlp):
    """Lightweight probe — flat for playlists — used to route the URL."""
    opts = dict(_BASE_OPTS, extract_flat="in_playlist")
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def get_full_info(url, yt_dlp):
    """Full extraction with the format list for a single video."""
    with yt_dlp.YoutubeDL(dict(_BASE_OPTS)) as ydl:
        return ydl.extract_info(url, download=False)


# ── Quality selection (site-agnostic) ─────────────────────────────────────────
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
    opts.append({"label": "best available", "kind": "best", "height": None,
                 "fps": 0, "format_id": None, "has_audio": True})
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


# ── Download drivers ──────────────────────────────────────────────────────────
def download_single(url, chosen, fcp_mode, yt_dlp, output_dir=None):
    fmt_spec = build_fmt_spec(chosen, fcp_mode)
    outtmpl = outtmpl_for(chosen, output_dir)
    mode_label = "FCP-compatible (H.264/AAC)" if fcp_mode else "original format"
    print(f"\nDownloading {chosen['label']} [{mode_label}]...\n")
    ydl_opts = build_ydl_opts(fmt_spec, outtmpl, fcp_mode)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


def download_playlist(url, info, fcp_mode, yt_dlp):
    playlist_title = info.get("title") or "playlist"
    entries = [e for e in (info.get("entries") or []) if e]
    if not entries:
        print("No videos found in playlist.")
        return

    print(f"\nPlaylist: {playlist_title}")
    print(f"Videos:   {len(entries)}\n")

    first_url = entries[0].get("url") or entries[0].get("webpage_url")
    print("Fetching formats from the first item to pick quality...")
    chosen = pick_option(get_full_info(first_url, yt_dlp))

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
                                      {"quiet": True, "no_warnings": True})
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            print("  ✓ Done")
        except Exception as e:
            print(f"  ✗ Failed: {e}")
            failed.append(video_title)

    print(f"\n{'─' * 50}")
    print(f"Downloaded: {len(entries) - len(failed)}/{len(entries)}")
    if failed:
        print(f"Failed ({len(failed)}):")
        for t in failed:
            print(f"  - {t}")
    print(f"Folder: ./{folder}/")


def handle_url(url, fcp_mode, yt_dlp):
    """Route one URL: playlist → live → normal yt-dlp → streamlink fallback."""
    from yt_dlp.utils import DownloadError

    print("\nFetching info...")
    try:
        info = probe(url, yt_dlp)
    except DownloadError as e:
        # yt-dlp couldn't even identify the URL → last-ditch streamlink attempt.
        print(f"  yt-dlp extraction failed: {e}")
        download_with_streamlink(url, url.rstrip("/").split("/")[-1] or "download",
                                 fcp_mode, reason="yt-dlp extraction failed")
        return

    if is_playlist(info):
        download_playlist(url, info, fcp_mode, yt_dlp)
        return

    # Single item — get full formats and check for a live stream.
    try:
        info = get_full_info(url, yt_dlp)
    except DownloadError as e:
        print(f"  yt-dlp extraction failed: {e}")
        download_with_streamlink(url, "download", fcp_mode,
                                 reason="yt-dlp extraction failed")
        return

    if info.get("is_live"):
        download_with_streamlink(url, info.get("title") or "live_stream",
                                 fcp_mode, reason="live stream")
        return

    chosen = pick_option(info)
    try:
        download_single(url, chosen, fcp_mode, yt_dlp)
        print("\nDone!")
    except DownloadError as e:
        print(f"  yt-dlp download failed: {e}")
        download_with_streamlink(url, info.get("title") or "download",
                                 fcp_mode, reason="yt-dlp download failed")


def main():
    yt_dlp = ensure_yt_dlp()

    print("anydl — universal video downloader")
    print("Enter video URLs from any site, one per line. Type 'done' when finished.")
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
        handle_url(url, fcp_mode, yt_dlp)

    if len(urls) > 1:
        print(f"\n{'═' * 50}")
        print(f"All {len(urls)} downloads complete.")


if __name__ == "__main__":
    main()
