# anydl — Universal Video Downloader

Download video from **almost any website** in your chosen quality — fully interactive, no flags needed.

Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp) (1,700+ supported sites plus a generic
extractor that finds embedded `<video>` / HLS / DASH streams on sites it doesn't explicitly know),
with a [streamlink](https://streamlink.github.io/) fallback for **live streams** and the odd site
yt-dlp can't reach.

> Formerly "YouTube Downloader" — YouTube still works exactly as before; it's now just one of
> hundreds of supported sites.

---

## Features

- **Works on almost any site** — YouTube, Vimeo, Twitter/X, TikTok, Reddit, Twitch VODs, news
  sites, direct `.mp4`/HLS links, and ~1,700 more via yt-dlp; unknown sites are attempted through
  yt-dlp's generic extractor
- **Live-stream capture** — live URLs and yt-dlp-unsupported sites automatically fall back to
  streamlink (auto-installed on first use)
- **Multiple URLs** — queue as many videos/playlists as you want, then download them all at once
- **Single video or full playlist** — paste either and it handles both
- **Robust quality picker** — groups streams by resolution when the site reports one, lists
  formats by bitrate when it doesn't, and always offers a "best available" option so no site is a
  dead end
- **FCP / QuickTime compatible mode** — forces H.264 + AAC + `.mp4` for native playback in Final
  Cut Pro / QuickTime (streamlink captures are remuxed to `.mp4` too)
- **Playlist folder** — each playlist downloads into its own named folder, one file per video
- **Auto audio merge** — video-only picks are merged with the best audio automatically
- **Auto-installs its dependencies** — `yt-dlp` (and `streamlink` when first needed) install
  themselves; no manual setup beyond Python + FFmpeg
- **Zero config** — just run it and follow the prompts

---

## Requirements

### System
- **Python** 3.8+
- **FFmpeg** (required for merging video + audio streams and for FCP remuxing)

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Windows — download from https://ffmpeg.org/download.html
```

### Python packages

```bash
pip install yt-dlp        # streamlink is installed on demand, only if a live/unsupported URL needs it
```

> `yt-dlp` (and `streamlink`, when first required) are auto-installed on first run if missing.

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
python video_downloader.py
```

You'll be prompted to enter URLs one at a time, then answer one question before anything downloads:

1. **URLs** — paste video and/or playlist links from any site, one per line; type `done` when finished
2. **FCP compatible output?** — `y` for Final Cut Pro / QuickTime, `n` for original format

### Single video (any site)

```
anydl — universal video downloader
Enter video URLs from any site, one per line. Type 'done' when finished.
URL 1 (or 'done'): https://vimeo.com/76979871
URL 2 (or 'done'): done

1 URL(s) queued.
FCP compatible output? [y/n]: y

Fetching info...

Title: The Mountain
Duration: 3m 25s

Available qualities:
  [1] 1080p  (video — audio merged automatically)
  [2] 720p   (video+audio)
  [3] 540p   (video+audio)
  [4] best available  (auto-selects the best video+audio)

Select quality [1-4]: 1

Downloading 1080p [FCP-compatible (H.264/AAC)]...

Done!
```

The file is saved in the current directory. Sites that report a resolution get a
`Title [1080p].ext` filename; others are saved as `Title.ext`.

### Live stream / unsupported site

```
URL 1 (or 'done'): https://www.twitch.tv/somechannel
...
Fetching info...

yt-dlp can't grab this directly (live stream); using streamlink...
  For a live stream, press Ctrl-C to stop recording.

  ✓ Saved (remuxed to .mp4): somechannel.mp4
```

### Playlist

```
Playlist: My Favourite Songs
Videos:   12

Fetching formats from the first item to pick quality...
...
Saving to folder: ./My Favourite Songs/  [original format]

[1/12] Song One
  ✓ Done
...
──────────────────────────────────────────────────
Downloaded: 12/12
Folder: ./My Favourite Songs/
```

Each video is saved as a separate file inside a folder named after the playlist. You can mix
single videos and playlists from different sites in the same queue.

---

## How it decides what to use

For each URL, in order:

1. **Playlist?** → downloads every entry into a named folder (quality picked once, applied to all).
2. **Live stream?** (`is_live`) → captured with **streamlink** (`best` quality).
3. **Normal video** → downloaded with **yt-dlp** at your chosen quality.
4. **yt-dlp can't extract or download it?** → last-ditch **streamlink** attempt on the raw URL.

---

## FCP / QuickTime Compatibility

Many high-quality streams use **VP9** or **AV1** video with **Opus** audio — codecs that QuickTime
Player and Final Cut Pro don't natively support. Answer **`y`** to the FCP prompt to force a
compatible file:

| | Normal mode (`n`) | FCP mode (`y`) |
|---|---|---|
| Video codec | AV1 / VP9 (best quality) | H.264 (AVC) |
| Audio codec | Opus (best quality) | AAC (re-encoded) |
| Container | site's native (`.webm`/`.mkv`/…) | `.mp4` |
| streamlink capture | `.ts` | remuxed to `.mp4` |
| Use when | VLC, Plex, any modern player | Final Cut Pro, QuickTime, iMovie |

---

## FAQ

**Which sites are supported?**
Anything [yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)
(~1,700 sites), plus unknown sites via yt-dlp's generic extractor, plus live streams and a few
extra sites via streamlink.

**Why do I need FFmpeg?**
High-quality streams are often split into separate video and audio tracks; FFmpeg merges them (and
handles the FCP re-encode / streamlink remux). Without it, only formats with built-in audio work.

**Where is the file saved?**
In the directory you run the script from (playlists get their own subfolder).

**Can I download private / paywalled content?**
Only what your machine can already access publicly. This tool adds no authentication.

**A site didn't work — what now?**
Make sure `yt-dlp` is up to date (`pip install -U yt-dlp`); extractors change often. Live streams
require `streamlink`, which installs automatically the first time one is needed.

---

## License

MIT License — see [LICENSE](LICENSE).

---

## Acknowledgements

Built on top of:
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — multi-site downloading engine
- [streamlink](https://streamlink.github.io/) — live-stream / fallback capture
- [FFmpeg](https://ffmpeg.org/) — video/audio merging and remuxing
