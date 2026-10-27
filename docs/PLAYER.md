# Player: watching the library in the browser

Status: steps 1 and 2 built 2026-10-26 (0.42.0: browse, direct play, full screen, .srt subtitles; 0.43.0: repacking in the browser, sound for AC3/E-AC3/DTS as stereo FLAC, the original-language track, seeking; 0.44.0: subtitles copied out of files, larger subtitles, Open with, downloads), in the local trial. Decisions are the reader's (pick lists, 26 Oct); findings were measured or sourced on that day.

## 1. What it is

A section of muthur, **Watch** in its sidebar (26 Oct: it should look like the rest of muthur), with **TV** and **Films** as tabs (TV first and chosen when you open it), each with a row of what was added last above a visual browser of posters with filters; a show opens in the same frame. Only watching leaves the frame: a large player that fits the tab and can go full screen. Firefox comes first; Chrome and Edge must work too.

### Hard rules

- **The files stay as they are.** No transcoding, no remuxing, no conversion on the NAS, no change to any video. muthur may only *add* things, and for now not even subtitle files in the library (see §4).
- **No Jellyfin, no GPL code.** MIT, Apache-2.0, MPL-2.0 and LGPL are fine.
- **Play natively what the browser can.** What it can't, the browser does itself (decoding sound in WebAssembly), never the NAS.
- What can't play at all is accepted: those videos stay in Kodi.
- Choosing an audio track is a nice-to-have; a file whose English track comes third may play its first track.

## 2. What the library holds (scan, 26 Oct)

ffprobe of every video in TV and Film: **5,544 files** (TV 4,901, Film 643), no read errors.

| | Files | Share | Measured in Chrome 152 on this PC |
|---|---:|---:|---|
| Plays out of the box: MKV/MP4 with H.264 (incl. 10-bit), HEVC (8/10-bit, HDR), AV1, and AAC, MP3, Opus, Vorbis or FLAC | 2,665 | 48% | picture and sound |
| Picture plays, sound silent: AC3 / E-AC3 | 1,838 | 33% | picture, **silent**, no error |
| Picture plays, sound silent: DTS | 275 | 5% | picture, **silent** |
| Won't play: XviD/MPEG-4 Part 2 in AVI (721), MPEG-2 (24), others (3) | 748 | 14% | AVI doesn't open at all |
| AVI with a codec the browser knows | 15 | 0.3% | AVI doesn't open |

Edge decodes AC3/E-AC3 itself (Jellyfin's codec table, not measured here): about 81% plays there.

Containers: MKV 3,545 · MP4 1,242 · AVI 725 · M4V 29. Video: H.264 3,266 · HEVC 10-bit 1,036 · MPEG-4 721 · HEVC 352 · H.264 10-bit 110 · HEVC HDR 30. Default audio: AAC 2,593 · E-AC3 978 · AC3 944 · MP3 667 · DTS 275.

- **More than one audio track:** 337 files, mostly English+English (commentary) and English+Japanese.
- **Subtitles:**
  - a `.srt` beside the video: 2,635 files
  - text subtitles inside the file: 2,441
  - image subtitles only (PGS/VobSub): 358
  - none at all: 494

## 3. What browsers do (measured and sourced)

Measured on this PC (built-in browser, Chrome 152 engine, NVIDIA GPU), with a test page of one short clip per kind (`scratchpad/mkvtest`):

- MKV with H.264/AAC plays.
- HEVC 8- and 10-bit play (hardware), and so does H.264 10-bit.
- AC3, E-AC3 and DTS give picture without sound.
- AVI (XviD or H.264) fails to open.
- **An MKV's embedded subtitle doesn't appear** (0 text tracks).
- **There is no API to choose an audio track**, so only the default track plays.

**Firefox, measured by the reader on this PC (26 Oct):** the same as Chrome, except that **H.264 in 10-bit doesn't play** ("the file is corrupt"; 110 files). HEVC 8- and 10-bit play with sound. AC3, E-AC3 and DTS are silent, and AVI doesn't open. The player decides H.264 10-bit by browser: Kodi only in Firefox, playable in Chrome and Edge. Sourced:

- Firefox 145 plays MKV with H.264, HEVC, VP8, VP9 and AV1, with AAC, Opus or Vorbis [1].
- HEVC needs hardware and the Windows HEVC extension [2].
- `audioTracks` is off by default in Firefox and Chrome [3].
- RTX Video Super Resolution works in Firefox 126+ on a plain video element [4].

**Firefox stutters on some MKVs (26 Oct).** Dune (HEVC 10-bit) and Welcome to the Sticks (H.264) drop about 25% of their frames in Firefox and none in Chrome. Removing the sound track changes nothing. **The same picture, copied unchanged into MP4, plays smoothly.** So Firefox's MKV reader (new since 145) is the cause, not the files, the share or the decoder; Valerian's MKV is unaffected.

**What each browser can do with a stream built in the page** (Media Source Extensions and WebCodecs, measured on this PC with `caps.html`):

| | Firefox 158 | Chrome 152 |
|---|---|---|
| Player accepts H.264, HEVC (8/10-bit), AV1 in an MP4 stream | yes | yes |
| H.264 10-bit in an MP4 stream | no | yes |
| Sound as AAC, Opus or FLAC in the stream | yes | yes |
| AC-3 / E-AC-3 in the stream | no | no |
| Encode sound in the page: Opus | 5.1 and stereo | stereo only |
| Encode sound in the page: AAC | no | stereo only |
| Decode HEVC in the page (WebCodecs, to draw the picture yourself) | **no** | yes |

So the picture must go through the browser's own player, never be drawn by the page (Firefox can't decode HEVC in WebCodecs).

Server side: Starlette's `FileResponse` answers HTTP Range requests (206), so seeking works without extra code [5].

**Sound without touching the file:**
- **Mediabunny** (MPL-2.0, ~7.4k stars) reads MKV and MP4 over HTTP and decodes with WebCodecs [6].
- Its **@mediabunny/ac3** extension (MPL-2.0) is a size-optimised WebAssembly build of FFmpeg's AC-3/E-AC-3 decoders [7][8].
- **@mediabunny/dts** does the same for DTS [9].
- **@mediabunny/flac-encoder** encodes FLAC in the page with libFLAC as WebAssembly; no browser encodes FLAC itself [13].
- Mediabunny copies tracks without re-encoding when it can, can drop tracks, and writes fragmented MP4 that a Media Source Extensions buffer takes [14][15].
- Mediabunny doesn't read subtitle tracks from MKV [6].

Considered and not chosen:
- movi-player: Apache-2.0, plays MKV/AC3 with FFmpeg WASM and WebCodecs, but young (v0.4) [10].
- libav.js: software only [11].
- vlc.js: unreleased [12].
- Jellyfin: excluded by the reader.

## 4. Decisions (26 Oct)

| Question | Decision |
|---|---|
| Sound for AC3/E-AC3/DTS | **Lossless FLAC in a stream built in the browser** (decided after the Firefox measurements): Mediabunny reads the file, copies the picture unchanged, decodes the sound (AC3/DTS extensions), mixes it down to **stereo** (the browser always plays on stereo speakers) and encodes it as FLAC. The fragmented MP4 goes to the browser's own player, which keeps sync, pause and seeking itself. |
| When to repack | **Only when needed**: direct play when the browser handles the file well. Repack in the browser for every MKV in Firefox (its MKV reader stutters on some, unpredictably), for every file whose sound needs decoding, and when the track to play isn't the file's default. |
| Audio track | **Always the original language**: the film's or show's original language (TMDB's `original_language`), so Spirited Away plays in Japanese and Bienvenue chez les Ch'tis in French. When no track is tagged with it, the file's default. Subtitles stay English first. |
| Subtitles | **Existing `.srt` files first**, turned into WebVTT on the fly (nothing written). Embedded subtitles later. |
| Subtitles inside the file | **Copied out beside the video as `.srt`** (decided 26 Oct, after Welcome to the Sticks had only embedded ones): when a video has text subtitles inside and none beside it, the player starts a job that copies them out with ffmpeg (the video is only read), following muthur's subtitle rule (English, Dutch only without English), journalled so History can put it back, with a progress bar. Not while dry run is on. Kodi then lists those languages twice. Since 0.53 a download's text subtitles are also copied out when it is imported (27 Oct). Image subtitles (PGS, VobSub, e.g. Casino Royale's 43 tracks) can't become `.srt` without text recognition: later. |
| Subtitle size | Sized to the screen (a wide film's subtitles were too small); three sizes under the *Aa* button, remembered per browser. On by default: English, else a subtitle file whose name gives no language. |
| Open with | A small *⋯* menu in the watch view: **Play on the TV** (Kodi's Player.Open), **VLC / another app** on Android (an `intent:` link; VLC gets the `.srt`), **your own player** on a computer (a one-line `.m3u` with the share path, so the player finds the `.srt` itself), **Copy path** and **Copy link**. Links for outside players carry a key (an HMAC of that one video's id and an expiry, 12 hours) instead of the sign-in. A page can't see which players are installed. Kodi-only videos open the watch view for this menu. |
| Downloads | **The file as it is**, and each `.srt` beside it; **a season as one ZIP**, packed as it is sent, without compression (the NAS converts nothing). For the few people in the house: a phone for a flight, a laptop for a holiday. |
| Watched status | **Nothing**: the player doesn't read or write Kodi's watched status or resume points, and starts at the beginning. |
| Place | **Watch, a section of muthur** (TV · Films · Test set as tabs); first decided as its own page with its own side bar, changed 26 Oct because it looked out of place. |
| Episode details | **A panel beside the list** on click (on a phone a sheet from below): still, air date, length, score, summary (episode NFO, TMDB filling in), Play and Download. Chosen 26 Oct over a summary under each episode, a hover card and a page per episode. |
| Local trial | **muthur's dev server on this PC** (`scripts/dev.py`, http://127.0.0.1:8580), reading `//nostromo/Iedereen/TV` and `Film` through Windows' own access. Dry run on in that local copy first, so it can't change a file on the share. |
| Test set | **muthur picks one real file per kind** (below); a *Test set* filter shows only those. The reader judges them in Firefox. |
| Filters | Watched / unwatched (read from muthur's backup), genre, year, rating, recently added. |
| What won't play | **Shown, dimmed and marked "Plays in Kodi only"**, without a play button. |
| VLC hand-off | Parked. |

## 5. Design

### Pages

- **`/player`**: side bar with *TV* and *Films* (and *Test set* during the trial). The main area is a grid of posters, very visual, with filters and sorting above it. A film's poster plays it (large play button on hover/focus). A show opens its seasons and episodes, each episode with its thumbnail and a play button.
- **The player**: fills the tab (the video at the largest size that fits), controls over the picture, a full-screen button (the Fullscreen API on the player's own box, so subtitles and controls stay visible), keyboard: space, ←/→ 10 s, F, M, Esc. A back button returns to where you were in the grid.
- **Kodi-only items**: dimmed, marked *Plays in Kodi only*, no play button.

### How a file plays

1. **Native**: `<video src="/api/player/file/{id}">`. The browser fetches with Range requests; muthur serves the file as it is.
2. **Repacked in the browser**: Mediabunny opens the same URL (Range requests) and builds a fragmented MP4 into a Media Source Extensions buffer of a `<video>` element. The picture's packets are copied unchanged. The chosen audio track is copied when the browser plays it (AAC, Opus, FLAC); otherwise it is decoded (AC3/E-AC3/DTS), mixed to stereo and encoded as FLAC. The page stays about a minute ahead of the playhead and drops what is well behind. A seek outside what is buffered restarts the build from the key frame before that point. Decided by the browser, the file's container and codecs, and the original language, before playing.
3. **Kodi only**: no play.

### Backend (muthur)

- **`GET /api/player/items`**: shows, episodes and films with poster, year, rating, genre, watched, date added and a playability class (native / browser sound / Kodi only).
- **`GET /api/player/file/{id}`**: the video with Range support. Ids map to files inside the TV and Film roots only, never a path from the browser. Behind muthur's login like everything else.
- **`GET /api/player/subtitles/{id}`**: the `.srt` beside the video as WebVTT, converted in memory (character set detected, timing kept), nothing written.
- **Codec facts per file**: the ffprobe facts muthur already caches (`probe_cache`, by path, size and modification time), filled by a one-off job over the library (about 10 minutes on the NAS) and kept current for new files.
- **Genres**: the index starts reading `<genre>` from the NFOs.

## 6. Steps

1. **Trial, browse and native play**: `/player` with TV/Films, poster grid, filters, the test set, the player page with native playback, full screen, and `.srt` subtitles. Run locally against the share, with dry run on.
2. **Repacking in the browser**: Mediabunny with the AC3, DTS and FLAC-encoder extensions; picture copied, sound copied or decoded to stereo FLAC; the original-language track; seeking. Fixes the silent third and Firefox's MKV stutter.
3. **On the NAS**: the codec scan as a job, then release and deploy (only while muthur is idle).
4. Later, each its own decision: embedded text subtitles (muthur's own cache), image subtitles (PGS/VobSub, e.g. libpgs-js, MIT), an audio-track menu, watched status and resume, VLC hand-off for what won't play.

### Test set (one real file per kind, picked from the scan)

- MP4 H.264+AAC
- MKV H.264+AAC with a `.srt` beside it
- MKV with AC3
- MKV with E-AC3
- MKV with DTS
- HEVC 10-bit
- HEVC HDR
- H.264 10-bit
- two audio tracks with English not first
- a long film (seeking)
- an XviD AVI ("Plays in Kodi only")

## Sources

1. Firefox 145 release notes: https://www.firefox.com/en-US/firefox/145.0/releasenotes/ ; Windows Report on MKV in Firefox: https://windowsreport.com/mozilla-firefox-is-officially-getting-mkv-video-support/
2. Mozilla bug 1942047 (HEVC on Windows): https://bugzilla.mozilla.org/show_bug.cgi?id=1942047 ; Jellyfin codec table: https://jellyfin.org/docs/general/clients/codec-support/
3. caniuse, audioTracks: https://caniuse.com/audiotracks
4. Firefox 126 release notes (RTX VSR): https://www.firefox.com/en-US/firefox/126.0/releasenotes/
5. Starlette responses (FileResponse range requests): https://starlette.dev/responses/
6. Mediabunny: https://github.com/Vanilagy/mediabunny ; formats and codecs: https://mediabunny.dev/guide/supported-formats-and-codecs
7. @mediabunny/ac3: https://mediabunny.dev/guide/extensions/ac3
8. Its licence (MPL-2.0): https://raw.githubusercontent.com/Vanilagy/mediabunny/main/packages/ac3/LICENSE
9. @mediabunny/dts: https://mediabunny.dev/guide/extensions/dts
10. movi-player: https://github.com/mrujjwalg/movi-player
11. libav.js: https://github.com/Yahweasel/libav.js
12. vlc.js status: https://forum.videolan.org/viewtopic.php?p=545739
13. @mediabunny/flac-encoder: https://mediabunny.dev/guide/extensions/flac-encoder
14. Mediabunny, converting media files (copy, discard): https://mediabunny.dev/guide/converting-media-files
15. Mediabunny, writing media files (fragmented MP4, append-only for MSE): https://mediabunny.dev/guide/writing-media-files
