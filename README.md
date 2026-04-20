# YouTube Downloader

Download any YouTube video in your chosen quality — fully interactive, no flags needed.

---

## Features

- **Single video or full playlist** — paste either URL and it handles both
- **Quality picker** — lists all available resolutions (2160p/4K, 1080p, 720p, 480p, 60fps variants, etc.)
- **FCP / QuickTime compatible mode** — forces H.264 + AAC so files open natively in Final Cut Pro and QuickTime Player
- **Playlist folder** — each playlist downloads into its own named folder, one file per video
- **Auto audio merge** — if the chosen quality is video-only, best audio is merged automatically
- **MP4 output** — always saves as a clean `.mp4`
- **Auto-installs yt-dlp** — no manual setup needed beyond Python
- **Zero config** — just run it and follow the prompts

---

## Requirements

### System
- **Python** 3.8+
- **FFmpeg** (required for merging video + audio streams)

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Windows — download from https://ffmpeg.org/download.html
```

### Python packages

```bash
pip install yt-dlp
```

> `yt-dlp` is auto-installed on first run if missing.

---

## Installation

```bash
git clone https://github.com/AdinathChaudhari/youtube-downloader.git
cd youtube-downloader
```

No additional setup needed.

---

## Usage

```bash
python youtube_downloader.py
```

You'll be asked two questions before anything downloads:

1. **URL** — paste a single video or playlist link
2. **FCP compatible output?** — `y` for Final Cut Pro / QuickTime, `n` for original format

### Single video

```
Enter YouTube URL (video or playlist): https://www.youtube.com/watch?v=dQw4w9WgXcQ
FCP compatible output? [y/n]: y

Fetching info...

Title: Rick Astley - Never Gonna Give You Up
Duration: 3m 32s

Available qualities:
  [1] 2160p  .mp4  (video — audio merged automatically)
  [2] 1080p  .mp4  (video — audio merged automatically)
  [3] 720p   .mp4  (video — audio merged automatically)
  [4] 480p   .mp4  (video+audio)
  [5] 360p   .mp4  (video+audio)

Select quality [1-5]: 2

Downloading 1080p [FCP-compatible (H.264/AAC)]...

Done!
```

The file is saved in the current directory as `Video Title [1080p].mp4`.

### Playlist

```
Enter YouTube URL (video or playlist): https://www.youtube.com/playlist?list=PLxxxxxxx
FCP compatible output? [y/n]: n

Fetching info...

Playlist: My Favourite Songs
Videos:   12

Fetching formats from first video to pick quality...

Title: Song One
Duration: 3m 45s

Available qualities:
  [1] 1080p  .mp4  (video — audio merged automatically)
  [2] 720p   .mp4  (video+audio)
  [3] 480p   .mp4  (video+audio)

Select quality [1-3]: 2

Saving to folder: ./My Favourite Songs/  [original format]

[1/12] Song One
  ✓ Done
[2/12] Song Two
  ✓ Done
...
──────────────────────────────────────────────────
Downloaded: 12/12
Folder: ./My Favourite Songs/
```

Each video is saved as a separate file inside a folder named after the playlist.

---

## FCP / QuickTime Compatibility

YouTube's highest-quality streams use **VP9** or **AV1** video with **Opus** audio — codecs that QuickTime Player and Final Cut Pro do not natively support. Even though the container is `.mp4`, the video may refuse to open or play back incorrectly.

When you answer **`y`** to the FCP prompt:

| | Original mode | FCP mode |
|---|---|---|
| Video codec | VP9 / AV1 (YouTube default) | H.264 (AVC) |
| Audio codec | Opus / WebM | AAC |
| Container | best available | MP4 |

FCP mode selects the best available H.264 stream at your chosen resolution and re-encodes the audio to AAC via FFmpeg. This adds a small processing step but guarantees the file opens without issues in Final Cut Pro, QuickTime Player, and iMovie.

---

## FAQ

**Why do I need FFmpeg?**
High-quality streams (1080p, 1440p, 2160p/4K) on YouTube are split into separate video and audio tracks. FFmpeg merges them into a single file. Without it, only formats with built-in audio (typically 480p and below) will work.

**Where is the file saved?**
In the directory you run the script from.

**Does it support playlists?**
Yes — paste a playlist URL and it downloads every video into a named folder. Quality and FCP mode are picked once and applied to all videos.

**Can I download private videos?**
No — only publicly accessible videos are supported.

**What if no H.264 stream exists at my chosen resolution?**
FCP mode falls back to the best available H.264 stream at or below your chosen height. Audio is always re-encoded to AAC regardless.

---

## License

MIT License — see [LICENSE](LICENSE).

---

## Acknowledgements

Built on top of:
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — YouTube downloading engine
- [FFmpeg](https://ffmpeg.org/) — video/audio merging
