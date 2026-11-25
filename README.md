# CueDeck

A single-file browser audio cue player for live shows (school productions, VET Live Production, gigs). Live at https://cue-deck-pro.netlify.app/.

## Files
- `index.html`: the whole app (HTML, CSS, JS). Deploy this file.
- `tests/run_tests.py`: regression suite (headless Chrome + ffmpeg). **Run it before every publish:** `python3 tests/run_tests.py` (`--quick` skips the 99-cue load test).
- `CORRECTIONS.md`: the correction register and decisions.

## History
- `3428c76`: Drive `CueDeck_v1_9.html` (ChatGPT, 1 Jul 2026), kept for reference.
- `c5754cb`: the live Netlify file (ChatGPT v1.9 + waveform editor). Baseline for Claude's work.
- `v2.0` branch: Claude's corrections C1–C21 (see `CORRECTIONS.md`).

## Editing rules
- Keep it one self-contained file. No build step and no external requests.
- Saved data lives in the browser at the site's address: settings in localStorage (`cuedeck-project`, `cuedeck-master-db`, `cuedeck-global-transition-*`); audio and waveform caches in IndexedDB `CueDeckDB` (stores `audio`, `peaks`; version 2). Never rename these keys, or saved shows disappear.
- Keep the address `cue-deck-pro.netlify.app`. A new address starts empty (export the show first).
- Live-show rules the tests enforce: one key press = one action; Escape always stops everything; editing (Audition, I/O) never touches what's playing; Show Mode is read-only.
- Memory model: cues ≤ 30 s and loops are decoded (budget 512 MB). Longer cues stream from the stored file, and their waveform is cached once.
- `?test` in the address exposes `window.__cuedeck` for the test suite only.

## Not yet verified
- Safari/iPad. The tests run in Chrome. Before the first show on an iPad: load a few cues, GO through them, try Audition, a crossfade and Show Mode.
