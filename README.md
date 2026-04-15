# YouTube Downloader

Download any YouTube video in your chosen quality — fully interactive, no flags needed.

---

## Features

- **Quality picker** — lists all available resolutions (1080p, 720p, 480p, 60fps variants, etc.)
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

### Example session

```
Enter YouTube URL: https://www.youtube.com/watch?v=dQw4w9WgXcQ

Fetching available formats...

Title: Rick Astley - Never Gonna Give You Up
Duration: 3m 32s

Available qualities:
  [1] 1080p  .mp4  (video — audio merged automatically)
  [2] 720p   .mp4  (video — audio merged automatically)
  [3] 480p   .mp4  (video+audio)
  [4] 360p   .mp4  (video+audio)

Select quality [1-4]: 1

Downloading 1080p...

[download] Rick Astley - Never Gonna Give You Up [1080p].mp4
Done!
```

The file is saved in the current working directory as `Video Title [1080p].mp4`.

---

## FAQ

**Why do I need FFmpeg?**
High-quality streams (1080p and above) on YouTube are split into separate video and audio tracks. FFmpeg merges them into a single `.mp4`. Without it, only formats with built-in audio (typically 480p and below) will work.

**Where is the file saved?**
In the directory you run the script from.

**Does it support playlists?**
No — this tool downloads a single video. For playlists, use [yt-dlp](https://github.com/yt-dlp/yt-dlp) directly.

**Can I download private videos?**
No — only publicly accessible videos are supported.

---

## License

MIT License — see [LICENSE](LICENSE).

---

## Acknowledgements

Built on top of:
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — YouTube downloading engine
- [FFmpeg](https://ffmpeg.org/) — video/audio merging
