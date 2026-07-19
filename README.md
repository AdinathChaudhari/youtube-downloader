# anydl — Universal Downloader

Download from **almost any URL** — fully interactive, no flags needed. Paste a link and it figures
out *how* to fetch it: a video site, a live stream, a direct file, an FTP path, or a torrent.

It works like a mini [ghost-downloader](https://github.com/xiaoyouchr/ghost-downloader-3): instead
of one engine, it's a **router** that dispatches each URL to the best tool for it.

## Quick start

```bash
pip install yt-dlp                 # one-time (auto-installs on first run anyway)
brew install ffmpeg aria2          # macOS; ffmpeg required, aria2 recommended
python video_downloader.py         # then follow the prompts
```

Then:

1. **Paste URLs** — any site, one per line; type `done` when finished.
2. **`FCP compatible output? [y/n]`** — `y` re-encodes video to H.264/AAC `.mp4` for Final Cut
   Pro / QuickTime; `n` keeps the original (best quality). Only affects video.
3. It downloads each URL, auto-picking the right engine (video site, live stream, direct file,
   FTP, or torrent). Press <kbd>Ctrl-C</kbd> to skip the current item and continue the queue.

Files land in the current directory (playlists get their own subfolder). That's it — everything
below is detail.

| URL type | Engine used |
|---|---|
| Video sites / playlists (YouTube, Vimeo, X, TikTok, Reddit, Twitch VODs, +1,700 more) | **yt-dlp** |
| Pages with embedded video, HLS/DASH manifests (`.m3u8` / `.mpd`) | **yt-dlp** (generic) |
| Live streams (and yt-dlp failures) | **streamlink** |
| Direct files over HTTP/S — `.mp4`, `.zip`, `.pdf`, images, installers, *anything* | **aria2c** (multi-connection) or built-in |
| FTP | **aria2c** or built-in |
| Torrents / magnet links | **aria2c** (BitTorrent) |

> Formerly "YouTube Downloader" — YouTube still works exactly as before; it's now just one of
> hundreds of supported sources.

There is no such thing as *literally* any URL (login walls, DRM, and JS-gated players will always
resist), but this covers the overwhelming majority of "I just want to save this" cases.

---

## How it decides (the router)

For each URL, in order:

1. **`magnet:` / `.torrent`** → aria2c BitTorrent (`--seed-time=0`, auto-stops).
2. **`ftp://`** → aria2c, or the built-in stdlib downloader.
3. **A known video site** (matched against yt-dlp's ~1,800 extractors) → yt-dlp video path.
4. Otherwise, **one ranged `GET` probe** (never `HEAD` — it 403s on presigned GitHub/S3 links),
   then classify by sniffing the first bytes → content-disposition → content-type → extension:
   - **Manifest** (`#EXTM3U`, `.m3u8`, `.mpd`) → yt-dlp.
   - **File** (binary content-type / known extension) → direct download.
   - **Page** → yt-dlp video extraction → streamlink → give up cleanly (never saves the HTML).

Each queue item is independent — <kbd>Ctrl-C</kbd> skips the current download and moves to the next.

---

## Requirements

### System
- **Python** 3.8+
- **FFmpeg** — merging video+audio, FCP remuxing (`brew install ffmpeg`)
- **aria2** *(optional but recommended)* — unlocks torrents/magnets, FTP, and fast multi-connection
  file downloads. Without it, HTTP/FTP files still download via a built-in stdlib downloader, and
  torrents print an install hint.

```bash
# macOS
brew install ffmpeg aria2

# Ubuntu / Debian
sudo apt install ffmpeg aria2
```

### Python packages

```bash
pip install yt-dlp        # streamlink installs on demand, only if a live/unsupported URL needs it
```

> `yt-dlp` (and `streamlink`, when first required) auto-install on first run if missing. The direct
> HTTP/FTP downloader uses only the Python standard library — no extra packages.

---

## Installation

```bash
git clone https://github.com/AdinathChaudhari/youtube-downloader.git
cd youtube-downloader
python video_downloader.py
```

---

## Usage

```bash
python video_downloader.py
```

You'll be prompted for URLs (one per line, `done` to finish), then whether to make video
FCP/QuickTime-compatible. Then it just goes.

### Video site

```
Detected a known video site → yt-dlp
Title: Some Talk
Available qualities:
  [1] 1080p  (video — audio merged automatically)
  [2] 720p   (video+audio)
  [3] best available  (auto-selects the best video+audio)
Select quality [1-3]: 1
Downloading 1080p [FCP-compatible (H.264/AAC)]...
Done!
```

### Direct file (any type)

```
URL 1 (or 'done'): https://github.com/owner/repo/releases/download/v1/app.dmg
...
Detected direct file: app.dmg
Downloading app.dmg (84.2 MB)...
  ✓ Saved: ./app.dmg
```

### Torrent / magnet

```
URL 1 (or 'done'): magnet:?xt=urn:btih:...
Downloading torrent/magnet via aria2c (Ctrl-C to abort)...
  ✓ Done
```

### Live stream

```
URL 1 (or 'done'): https://www.twitch.tv/somechannel
yt-dlp can't grab this directly (live stream); using streamlink...
  For a live stream, press Ctrl-C to stop recording.
  ✓ Saved (remuxed to .mp4): somechannel.mp4
```

Playlists download into their own named folder. You can mix any of the above in one queue.

---

## FCP / QuickTime Compatibility

Answer **`y`** to force video into H.264 + AAC + `.mp4` for native Final Cut Pro / QuickTime
playback:

| | Normal (`n`) | FCP (`y`) |
|---|---|---|
| Video codec | AV1 / VP9 (best quality) | H.264 (AVC) |
| Audio codec | Opus (best quality) | AAC |
| Container | site's native | `.mp4` |

FCP mode also applies to **direct-downloaded video files**: if the file is already H.264/HEVC + AAC
in a non-`.mp4` container, it's losslessly remuxed to `.mp4`; other codecs are left as-is with a
note (it never silently transcodes). Torrents / archives / FTP ignore FCP mode.

---

## FAQ

**Which URLs work?**
Anything [yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md), plus
unknown pages via its generic extractor, plus any direct HTTP/FTP file, plus torrents/magnets
(with aria2), plus live streams (via streamlink).

**Do I need aria2?**
Only for torrents/magnets. Everything else works without it — aria2 just makes HTTP/FTP downloads
faster (multi-connection) and resumable.

**Why did it save a `.part` file?**
An interrupted or incomplete download. Direct downloads write to `name.part` and only rename to the
final name once complete (and aria2 resumes its own partials), so you never get a truncated file
masquerading as finished.

**Can I download private / paywalled content?**
Only what your machine can already access publicly. This tool adds no authentication. (Browser
cookie support is a planned enhancement.)

**A site didn't work — what now?**
Update yt-dlp (`pip install -U yt-dlp`); extractors change constantly.

---

## License

MIT License — see [LICENSE](LICENSE).

## Acknowledgements

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — multi-site video engine
- [aria2](https://aria2.github.io/) — multi-connection HTTP / FTP / BitTorrent engine
- [streamlink](https://streamlink.github.io/) — live-stream capture
- [FFmpeg](https://ffmpeg.org/) — merging & remuxing
- Architecture inspired by [ghost-downloader-3](https://github.com/xiaoyouchr/ghost-downloader-3)
