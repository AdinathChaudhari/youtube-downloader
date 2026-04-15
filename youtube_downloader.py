import os
import re
import subprocess
import sys


def ensure_yt_dlp():
    try:
        import yt_dlp
    except ImportError:
        print("Installing yt-dlp...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp"])
        import yt_dlp
    return yt_dlp


def safe_dirname(name):
    """Strip characters not allowed in folder names."""
    return re.sub(r'[\\/:*?"<>|]', "", name).strip()


def is_playlist(info):
    return info.get("_type") == "playlist"


def get_info(url, yt_dlp):
    ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist"}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info


def get_formats_for_video(url, yt_dlp):
    ydl_opts = {"quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info


def pick_format(info):
    formats = info.get("formats", [])

    seen = {}
    for f in formats:
        if not f.get("vcodec") or f["vcodec"] == "none":
            continue

        height = f.get("height")
        if not height:
            continue

        fps = f.get("fps") or 0
        ext = f.get("ext", "?")
        has_audio = f.get("acodec") and f["acodec"] != "none"
        label = f"{height}p"
        if fps and fps > 30:
            label += f" {int(fps)}fps"

        tbr = f.get("tbr") or 0
        if label not in seen or tbr > (seen[label].get("tbr") or 0):
            seen[label] = {
                "format_id": f["format_id"],
                "label": label,
                "ext": ext,
                "has_audio": has_audio,
                "tbr": tbr,
                "height": height,
                "fps": fps,
            }

    options = sorted(seen.values(), key=lambda x: x["height"], reverse=True)

    if not options:
        print("No video formats found.")
        sys.exit(1)

    title = info.get("title", "Unknown")
    duration = int(info.get("duration", 0) or 0)
    print(f"\nTitle: {title}")
    print(f"Duration: {duration // 60}m {duration % 60}s\n")
    print("Available qualities:")
    for i, opt in enumerate(options):
        audio_note = "(video+audio)" if opt["has_audio"] else "(video — audio merged automatically)"
        print(f"  [{i + 1}] {opt['label']}  .{opt['ext']}  {audio_note}")

    print()
    while True:
        choice = input(f"Select quality [1-{len(options)}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1]
        print(f"  Enter a number between 1 and {len(options)}.")


def build_fmt_spec(chosen):
    if chosen["has_audio"]:
        return chosen["format_id"]
    return f"{chosen['format_id']}+bestaudio"


def download_single(url, chosen, yt_dlp, output_dir=None):
    fmt_spec = build_fmt_spec(chosen)
    outtmpl = "%(title)s [%(height)sp].%(ext)s"
    if output_dir:
        outtmpl = os.path.join(output_dir, outtmpl)

    print(f"\nDownloading {chosen['label']}...\n")

    ydl_opts = {
        "format": fmt_spec,
        "merge_output_format": "mp4",
        "outtmpl": outtmpl,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


def pick_quality_label(sample_url, yt_dlp):
    """Fetch formats from the first video and let user pick a quality label."""
    print("\nFetching formats from first video to pick quality...")
    info = get_formats_for_video(sample_url, yt_dlp)
    return pick_format(info)


def download_playlist(url, yt_dlp):
    print("\nFetching playlist info...")
    info = get_info(url, yt_dlp)

    playlist_title = info.get("title") or "playlist"
    entries = info.get("entries") or []
    if not entries:
        print("No videos found in playlist.")
        sys.exit(1)

    print(f"\nPlaylist: {playlist_title}")
    print(f"Videos:   {len(entries)}\n")

    # Get first real video URL for quality selection
    first_url = entries[0].get("url") or entries[0].get("webpage_url")
    chosen = pick_quality_label(first_url, yt_dlp)

    folder_name = safe_dirname(playlist_title)
    os.makedirs(folder_name, exist_ok=True)
    print(f"\nSaving to folder: ./{folder_name}/\n")

    failed = []
    for i, entry in enumerate(entries, 1):
        video_url = entry.get("url") or entry.get("webpage_url")
        video_title = entry.get("title") or f"video_{i}"
        print(f"[{i}/{len(entries)}] {video_title}")
        try:
            fmt_spec = build_fmt_spec(chosen)
            ydl_opts = {
                "format": fmt_spec,
                "merge_output_format": "mp4",
                "outtmpl": os.path.join(folder_name, "%(title)s [%(height)sp].%(ext)s"),
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            print(f"  ✓ Done")
        except Exception as e:
            print(f"  ✗ Failed: {e}")
            failed.append(video_title)

    print(f"\n{'─' * 50}")
    print(f"Downloaded: {len(entries) - len(failed)}/{len(entries)}")
    if failed:
        print(f"Failed ({len(failed)}):")
        for t in failed:
            print(f"  - {t}")
    print(f"Folder: ./{folder_name}/")


def main():
    yt_dlp = ensure_yt_dlp()

    url = input("Enter YouTube URL (video or playlist): ").strip()
    if not url:
        print("No URL provided.")
        sys.exit(1)

    print("\nFetching info...")
    info = get_info(url, yt_dlp)

    if is_playlist(info):
        download_playlist(url, yt_dlp)
    else:
        info = get_formats_for_video(url, yt_dlp)
        chosen = pick_format(info)
        download_single(url, chosen, yt_dlp)
        print("\nDone!")


if __name__ == "__main__":
    main()
