# CueDeck Correction Register (v2.0)

Full audit with evidence: Claude Project doc `claude/cuedeck/CDK_Intake_Audit_25Nov.md`.
Approved by Justin, 25 Nov 2026 ("go ahead").

| id | Fix | Test (tests/run_tests.py) | Status |
|---|---|---|---|
| C1 | Held keys never re-fire (GO, hotkeys, transport) | held Space → one cue | Fixed |
| C2 | Escape always stops all, even while typing. Sliders/selects/switches hand focus back. Space/arrows act as show keys unless in a text or number field | slider focus → Escape, Space, arrows | Fixed |
| C3 | Learn key refuses Space, Esc, arrows, F, S, P, I, O. Show keys need no modifier, so Ctrl/Cmd+S isn't Stop | Space refused, Q works, Ctrl+S ignored | Fixed |
| C4 | Resume inside a fade continues at the right level | resume at 15 s in 10 s fade-out ≈ half level | Fixed |
| C5 | Pause during a fade finishes it as a stop | fade → P → P → silence | Fixed |
| C6 | After the last cue, standby = "End of cue list"; GO does nothing (D4). ↑ re-arms the last cue | 3 GOs, then GO → nothing | Fixed |
| C7 | One file relinks every missing cue with that name; unmatched files are added as new cues | duplicate relinks | Fixed |
| C8 | Show Mode re-takes the screen lock after a tab switch | stubbed wake lock 1 → 2 | Fixed |
| C9 | Crossfade: A fades out while B fades in over the same time (D3) | B gain 0.1 → 1.0 over 2 s | Fixed |
| C10 | Master level is smoothed (15 ms) | ramp + heard −20 dB | Fixed |
| C11 | Cues ≤ 30 s and loops are decoded (512 MB budget); longer cues stream from the stored file; waveform cached in IndexedDB | 99-cue show: 278 MB, starts ≈ 35 ms | Fixed |
| C12 | One `APP_VERSION` feeds title, subtitle, export | all show 2.0 | Fixed |
| C13 | Import keeps stored audio for matching cues and clears audio for cues no longer in the show | renamed import → 0 stored | Fixed |
| C14 | Import validates every field (same defaults as reload); unreadable file changes nothing | damaged + garbage files | Fixed |
| C15 | Loop: fade-out shown as "off while looping", slider disabled, chip shows fade-in only | | Fixed |
| C16 | Merge duplicate buttons, undo delete | none | **Deferred** (changes the layout; for the design pass) |
| C17 | Waveform uses all channels | right-only file shows a wave | Fixed |
| C18 | Visible keyboard focus ring | outline on Tab | Fixed |
| C19 | Audition is preview only: no start transition, never current, no standby change; Escape/STOP ALL stop it; button toggles | live cue keeps playing | Fixed |
| C20 | I/O only in edit mode with the editor showing | Show Mode I/O → no change | Fixed |
| C21 | Pad titles wrap and shrink to fit (ported from `3428c76`) | long name fits | Fixed |

## Found and fixed during the build
- Auto-follow now moves standby past the cue it starts. Before, GO replayed the auto-followed cue.
- Resuming a paused cue no longer runs "stop/crossfade other cues", so it can't cut cues started since the pause.
- Import of the same show on the same browser finds its audio (no relinking needed).
- IndexedDB v2 upgrade is blocked if an old CueDeck tab is open. The app tells the user to close it.

## Known limits
- Browsers have one audio output, so Audition is heard on the main output (as before).
- A streamed loop (a loop longer than the memory budget allows) may have a tiny gap at the loop point. Loops normally decode, so they're gapless.
- Not yet tested on Safari/iPad (see README).
