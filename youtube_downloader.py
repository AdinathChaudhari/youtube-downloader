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


def get_formats(url, yt_dlp):
    ydl_opts = {"quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info


def pick_format(info):
    formats = info.get("formats", [])

    # Collect formats that have both video and audio, or video-only (we'll merge with best audio)
    # Group by resolution for display
    seen = {}
    for f in formats:
        if not f.get("vcodec") or f["vcodec"] == "none":
            continue  # skip audio-only

        height = f.get("height")
        if not height:
            continue

        fps = f.get("fps") or 0
        ext = f.get("ext", "?")
        has_audio = f.get("acodec") and f["acodec"] != "none"
        label = f"{height}p"
        if fps and fps > 30:
            label += f" {int(fps)}fps"

        # Keep the best (highest tbr) format per resolution label
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

    print(f"\nTitle: {info.get('title', 'Unknown')}")
    print(f"Duration: {int(info.get('duration', 0) or 0) // 60}m {int(info.get('duration', 0) or 0) % 60}s\n")
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


def download(url, chosen, yt_dlp):
    fmt_id = chosen["format_id"]

    if chosen["has_audio"]:
        # Format already has audio
        fmt_spec = fmt_id
    else:
        # Merge with best available audio
        fmt_spec = f"{fmt_id}+bestaudio"

    print(f"\nDownloading {chosen['label']}...\n")

    ydl_opts = {
        "format": fmt_spec,
        "merge_output_format": "mp4",
        "outtmpl": "%(title)s [%(height)sp].%(ext)s",
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    print("\nDone!")


def main():
    yt_dlp = ensure_yt_dlp()

    url = input("Enter YouTube URL: ").strip()
    if not url:
        print("No URL provided.")
        sys.exit(1)

    print("\nFetching available formats...")
    info = get_formats(url, yt_dlp)
    chosen = pick_format(info)
    download(url, chosen, yt_dlp)


if __name__ == "__main__":
    main()
