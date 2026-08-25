# anydl — Universal Downloader

Fully interactive CLI that downloads from ~any URL by **routing** each one to the right engine
(video sites, live streams, direct files, FTP, torrents/magnets). Formerly a YouTube-only tool;
the router design is inspired by [ghost-downloader-3](https://github.com/xiaoyouchr/ghost-downloader-3).

## Stack

- Python 3.8+, single-file script (`anydl.py`)
- `yt-dlp` (auto-installs on first run) — video sites + generic extractor
- `streamlink` (auto-installs on first use) — live streams / yt-dlp fallback
- `aria2c` (optional, detected via PATH) — multi-connection HTTP, FTP, BitTorrent, magnet
- Pure-stdlib `urllib` fallback for HTTP/FTP files (no extra pip deps)
- External: `ffmpeg`/`ffprobe` — merging separate streams, FCP re-encode, and remuxing

## Layout & entry points

- `anydl.py` — the entire tool. Key pieces:
  - `handle_url()` — the router (see order below).
  - `known_extractor()` — matches a URL against yt-dlp's ~1,800 specific extractors.
  - `probe_url()` / `classify()` — one ranged `GET` (never `HEAD`), then classify
    MANIFEST / FILE / PAGE by body-sniff → content-disposition → content-type → extension.
  - `build_quality_options()` / `pick_option()` — site-agnostic quality picker (never dead-ends).
  - yt-dlp path: `yt_dlp_flow()`, `download_single()`, `download_playlist()`.
  - engines: `download_via_aria2()`, `_download_urllib_to()`, `download_direct()`,
    `download_ftp()`, `download_torrent()`, `download_with_streamlink()`.
  - `maybe_fcp_remux()` — lossless `.mp4` remux of direct video files, ffprobe-gated.

## Routing order (`handle_url`)

1. `magnet:` / `.torrent` → aria2c BitTorrent (needs aria2; else prints install hint).
2. `ftp://` → aria2c, else stdlib urllib. `ftps`/`sftp`/`data`/`file` are rejected.
3. Known yt-dlp extractor → yt-dlp video path (no HTTP probe).
4. Else probe once, classify: MANIFEST → yt-dlp; FILE → direct download; PAGE → yt-dlp →
   streamlink → give up (PAGE never direct-downloads, so it can't save an HTML page).
   Probe failure → UNKNOWN: yt-dlp → guarded direct → streamlink.

## Running it

```bash
pip install yt-dlp     # or just run it — auto-installs
brew install ffmpeg aria2   # macOS; ffmpeg required, aria2 recommended (torrents/FTP/fast HTTP)
python anydl.py
```

Prompts for URLs one per line (`done` to finish), then FCP-compatible output y/n, then a quality
pick per video (skipped for direct files/torrents). Playlists download into their own named folder.
`Ctrl-C` skips the current queue item and continues.

## Conventions & gotchas

- **aria2 is optional but unlocks the most**: torrents/magnets require it; without it HTTP/FTP files
  still download via stdlib but torrents just print an install hint.
- **Probe with a ranged `GET`, never `HEAD`** — HEAD 403s on presigned GitHub-release / S3 URLs.
  Classify on the *final* (post-redirect) URL and headers.
- Direct downloads write to `name.part`, then atomically rename — no truncated files masquerading
  as complete. aria2 resumes its own `.aria2` partials.
- FCP mode: re-encodes yt-dlp video to H.264/AAC `.mp4`; for direct-downloaded video files it only
  *remuxes* (never transcodes) and only when ffprobe confirms H.264/HEVC + AAC.
- `get_full_info`/`probe` pass `remote_components: ["ejs:github"]` to yt-dlp — needed for current
  YouTube extraction, harmless elsewhere.
- **A stale yt-dlp is the #1 cause of "it just stopped".** Big sites rotate their player every few
  weeks; an out-of-date copy still lists formats fine, then dies mid-transfer on a bare
  `HTTP Error 403`. `ensure_yt_dlp()` reads the installed version via `importlib.metadata` (no
  import), and upgrades when it's older than `YT_DLP_MAX_AGE_DAYS`. The upgrade **must** happen
  before the first `import yt_dlp` — swapping the package under a running process is a no-op for a
  re-import, so there's no mid-run rescue. A failed `pip` never aborts the run.
- **Don't fall back to streamlink on a CDN rejection.** `_looks_stale()` matches the
  403 / "unable to download video data" / "requested format is not available" signatures; when one
  of those hits a URL a *specific* extractor claimed, the media was found and the transfer was
  refused — streamlink has no VOD plugin to offer and just ends in "No plugin can handle URL"
  after installing 8 MB of deps. Print the upgrade hint instead. Any *other* download error still
  falls through to streamlink, which is the never-a-dead-end path.
- **One dead item must never abort a batch.** A playlist's quality pick is sampled from a real
  video's format list, but long playlists routinely open with a blocked/deleted/private item.
  `sample_playlist_formats()` walks down to the first entry that extracts (up to
  `FORMAT_SAMPLE_LIMIT`), then falls back to `BEST_OPTION` ("best available") if they're all dead —
  the per-video loop already tolerates individual failures. `main()` mirrors this: any unexpected
  error on one queued URL is caught and skipped, same as `Ctrl-C`.
- **A failed playlist item leaves a paper trail.** `write_failed_manifest()` writes
  `<playlist>/failed.txt` (index, title, one-line reason, URL) whenever anything failed — the
  console tally scrolls away on a 200+ item run. Every comment line starts with `#` so the file is
  both human-readable and machine-usable: `grep -v '^#' failed.txt` is a bare URL list you can
  paste back into anydl to retry. It never raises; a manifest problem must not fail a run that
  already downloaded.
- No credentials/config; no persistent state. **Browser-cookie support** kicks in only as a
  *retry*: when yt-dlp fails with a sign-in / bot-check ("confirm you're not a bot"), `_extract()`
  asks **once** which browser you're logged in on (`choose_cookie_browser()` → cached in
  `_COOKIE_BROWSER` for the session), then re-runs with `cookiesfrombrowser=(browser,None,None,None)`.
  The working cookies are threaded through the rest of that URL's extraction/download so the keychain
  prompts at most once. Common (non-blocked) downloads pay no cost and get no prompt. We *ask* rather
  than auto-detect by disk path because only the user knows which browser holds the YouTube login
  (matches the cookie-browser prompt in the sibling tools streamlist / audiobook-maker-pro / ipod-drop).
