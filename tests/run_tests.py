#!/usr/bin/env python3
"""CueDeck regression suite. Run before every publish:  python3 tests/run_tests.py
Needs: python playwright, Google Chrome (or Playwright chromium), ffmpeg.
Each test maps to an item in the correction register (C-numbers)."""
import asyncio, json, os, shutil, subprocess, sys, tempfile, time, traceback
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8791
URL = f"http://localhost:{PORT}/index.html?test"
CHROME = next((p for p in ["/usr/bin/google-chrome", "/usr/bin/chromium"] if os.path.exists(p)), None)
MEDIA = Path(tempfile.mkdtemp(prefix="cuedeck-media-"))
results = []

def ff(name, args):
    out = MEDIA / name
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args, str(out)], check=True)
    return str(out)

def make_media():
    m = {}
    for f in (220, 330, 440):
        m[f"t{f}"] = ff(f"tone{f}.wav", ["-f", "lavfi", "-i", f"sine=frequency={f}:duration=20", "-ac", "2"])
    m["long"] = ff("long_song.wav", ["-f", "lavfi", "-i", "sine=frequency=262:duration=150", "-ac", "2"])
    m["right"] = ff("right_only.wav", ["-f", "lavfi", "-i", "sine=frequency=500:duration=5",
                    "-af", "pan=stereo|c0=0*c0|c1=c0"])
    m["short25"] = ff("short25.wav", ["-f", "lavfi", "-i", "sine=frequency=600:duration=25", "-ac", "2"])
    return m

def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

async def fresh(pw, wake_stub=False):
    prof = tempfile.mkdtemp(prefix="cuedeck-prof-")
    kw = dict(headless=True, args=["--autoplay-policy=user-gesture-required"], viewport={"width": 1400, "height": 860})
    if CHROME: kw["executable_path"] = CHROME
    ctx = await pw.chromium.launch_persistent_context(prof, **kw)
    if wake_stub:
        await ctx.add_init_script("""
          window.__wake={requests:0,active:null};window.__hidden=false;
          Object.defineProperty(document,'hidden',{get:()=>window.__hidden});
          Object.defineProperty(document,'visibilityState',{get:()=>window.__hidden?'hidden':'visible'});
          Object.defineProperty(navigator,'wakeLock',{value:{request:async()=>{window.__wake.requests++;
            const s={released:false,release:async()=>{s.released=true}};window.__wake.active=s;return s;}}});""")
    page = await ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.dialog_answer = True
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept() if page.dialog_answer else d.dismiss()))
    await page.goto(URL); await page.wait_for_timeout(600)
    await page.mouse.click(700, 5)  # user gesture
    return ctx, page, errors

async def add(page, *files, wait=2500):
    await page.set_input_files("#fileInput", list(files)); await page.wait_for_timeout(wait)

async def playing(page):
    return await page.evaluate("[...document.querySelectorAll('.cue.playing')].map(r=>r.querySelector('.cue-num').textContent)")
async def blur(page): await page.evaluate("document.activeElement&&document.activeElement.blur()")
async def click_cue(page, i): await page.evaluate(f"document.querySelectorAll('.cue[data-cue-id]')[{i}].click()"); await blur(page)
async def escape(page): await blur(page); await page.keyboard.press("Escape"); await page.wait_for_timeout(250)
async def rms(page, ms=250):
    return await page.evaluate(f"""new Promise(r=>{{const a=window.__cuedeck.state.analyser;const buf=new Float32Array(a.fftSize);let s=0,n=0;
      const t0=performance.now();(function f(){{a.getFloatTimeDomainData(buf);for(const v of buf){{s+=v*v;n++}}
      if(performance.now()-t0<{ms})requestAnimationFrame(f);else r(Math.sqrt(s/n));}})();}})""")

async def suite_keys_transport(pw, m):
    ctx, page, errors = await fresh(pw)
    await add(page, m["t220"], m["t330"], m["t440"])
    check("setup: 3 cues READY", await page.evaluate("[...document.querySelectorAll('.cue-status')].every(s=>s.textContent==='READY')"))
    # C1 held key
    await click_cue(page, 0)
    for _ in range(4): await page.keyboard.down("Space")
    await page.keyboard.up("Space"); await page.wait_for_timeout(500)
    check("C1 held Space starts exactly one cue", await playing(page) == ["01"], str(await playing(page)))
    await escape(page)
    # C2 Escape with slider focused; Space fires GO; arrows don't move master
    await click_cue(page, 0); await page.keyboard.press("Space"); await page.wait_for_timeout(300)
    await page.focus("#masterGain"); before = await page.input_value("#masterGain")
    await page.keyboard.press("ArrowDown"); await page.wait_for_timeout(100)
    check("C2 arrows on focused slider don't change master", await page.input_value("#masterGain") == before)
    await page.keyboard.press("Escape"); await page.wait_for_timeout(300)
    check("C2 Escape stops all with master slider focused", await playing(page) == [])
    await click_cue(page, 0); await page.focus("#fadeCurve") if await page.is_visible("#fadeCurve") else None
    await page.focus("#masterGain"); await page.keyboard.press("Space"); await page.wait_for_timeout(300)
    check("C2 Space fires GO with slider focused", await playing(page) == ["01"], str(await playing(page)))
    await page.focus("#cueName"); await page.keyboard.press("Escape"); await page.wait_for_timeout(300)
    check("C2 Escape stops all even while typing a name", await playing(page) == [])
    # C3 reserved hotkeys
    await click_cue(page, 1); await page.click("#learnHotkeyBtn"); await page.keyboard.press("Space"); await page.wait_for_timeout(200)
    msg = await page.text_content("#hotkeyDisplay")
    check("C3 Learn key refuses Space", "reserved" in msg, msg)
    await page.keyboard.press("q"); await page.wait_for_timeout(500)
    check("C3 Learn key accepts Q", (await page.text_content("#hotkeyValue")) == "Q")
    await blur(page); await page.keyboard.press("q"); await page.wait_for_timeout(300)
    check("C3 hotkey Q fires cue 2", await playing(page) == ["02"])
    await page.keyboard.press("Control+s"); await page.wait_for_timeout(200)
    check("C3 Ctrl+S is not taken as Stop", await playing(page) == ["02"])
    await escape(page)
    # C6 end of list
    await click_cue(page, 0)
    for _ in range(3): await page.keyboard.press("Space"); await page.wait_for_timeout(250)
    check("C6 three GOs start three cues", sorted(await playing(page)) == ["01", "02", "03"])
    st = await page.evaluate("window.__cuedeck.state.endOfList")
    marker = await page.evaluate("document.querySelector('.end-marker').classList.contains('armed')")
    await escape(page)
    await page.keyboard.press("Space"); await page.wait_for_timeout(300)
    check("C6 standby is End of list, GO plays nothing", st and marker and await playing(page) == [])
    await page.keyboard.press("ArrowUp"); await page.wait_for_timeout(100)
    check("C6 ArrowUp from End of list arms the last cue",
          await page.evaluate("document.querySelector('.cue.armed .cue-num')?.textContent") == "03")
    # auto-follow moves standby past the followed cue
    await escape(page); await click_cue(page, 0)
    await page.evaluate("(()=>{const c=window.__cuedeck.state.cues[0];c.autoFollow=true;c.trimEnd=1.0})()")
    await page.keyboard.press("Space"); await page.wait_for_timeout(1800)
    armed = await page.evaluate("document.querySelector('.cue.armed .cue-num')?.textContent")
    check("Auto-follow starts cue 2 and stands by on cue 3", await playing(page) == ["02"] and armed == "03", f"{await playing(page)} armed {armed}")
    await escape(page)
    await page.evaluate("(()=>{const c=window.__cuedeck.state.cues[0];c.autoFollow=false;c.trimEnd=c.duration})()")
    # C5 pause while fading
    await click_cue(page, 0); await page.keyboard.press("Space"); await page.wait_for_timeout(300)
    await page.keyboard.press("f"); await page.wait_for_timeout(200)
    await page.keyboard.press("p"); await page.wait_for_timeout(200); await page.keyboard.press("p"); await page.wait_for_timeout(400)
    check("C5 pause during a fade stops it; resume brings nothing back", await playing(page) == [] and
          await page.evaluate("window.__cuedeck.state.active.size") == 0)
    # pause / resume keeps position
    await click_cue(page, 0); await page.keyboard.press("Space"); await page.wait_for_timeout(1200)
    await page.keyboard.press("p"); await page.wait_for_timeout(500)
    off = await page.evaluate("[...window.__cuedeck.state.active.values()][0].pausedOffset")
    await page.keyboard.press("p"); await page.wait_for_timeout(400)
    pos = await page.evaluate("[...window.__cuedeck.state.active.values()][0].position()")
    check("Pause/resume continues from the pause point", 0.9 < off < 1.6 and off <= pos < off + 0.8, f"paused {off:.2f}, now {pos:.2f}")
    await escape(page)
    # C4 resume inside fade-out continues the fade
    await page.evaluate("(()=>{const c=window.__cuedeck.state.cues[0];c.fadeOut=10;c.trimEnd=20})()")
    await page.evaluate("window.__cuedeck.startCue(window.__cuedeck.state.cues[0].id,2,true)"); await page.wait_for_timeout(300)
    full = await rms(page); await escape(page)
    await page.evaluate("window.__cuedeck.startCue(window.__cuedeck.state.cues[0].id,15,true)"); await page.wait_for_timeout(300)
    mid = await rms(page, 150); await escape(page)
    ratio = mid / full if full else 0
    check("C4 resume at 15 s inside a 10 s fade-out sounds at about half level", 0.3 < ratio < 0.7, f"ratio {ratio:.2f}")
    await page.evaluate("(()=>{const c=window.__cuedeck.state.cues[0];c.fadeOut=0})()")
    # C9 crossfade A out, B in
    await click_cue(page, 0); await page.keyboard.press("Space"); await page.wait_for_timeout(400)
    await page.evaluate("(()=>{const c=window.__cuedeck.state.cues[1];c.transitionMode='crossfade';c.transitionTime=2})()")
    await page.evaluate("window.__cuedeck.startCue(window.__cuedeck.state.cues[1].id)"); await page.wait_for_timeout(250)
    g_b_early = await page.evaluate("window.__cuedeck.state.active.get(window.__cuedeck.state.cues[1].id).gain.gain.value")
    a_status = await page.evaluate("window.__cuedeck.state.active.get(window.__cuedeck.state.cues[0].id)?.status")
    await page.wait_for_timeout(2200)
    g_b_late = await page.evaluate("window.__cuedeck.state.active.get(window.__cuedeck.state.cues[1].id).gain.gain.value")
    check("C9 crossfade: A fades out while B fades in over 2 s", a_status == "fading" and g_b_early < 0.5 and g_b_late > 0.95 and await playing(page) == ["02"],
          f"A {a_status}, B {g_b_early:.2f}->{g_b_late:.2f}")
    await escape(page)
    # C10 master ramps (measured while audio plays: Chrome reports a stale value on an idle node)
    await click_cue(page, 0); await page.keyboard.press("Space"); await page.wait_for_timeout(400)
    full = await rms(page)
    v0 = await page.evaluate("""(()=>{const s=document.getElementById('masterGain');s.value=-20;s.dispatchEvent(new Event('input'));
        return window.__cuedeck.state.masterGain.gain.value})()""")
    await page.wait_for_timeout(250)
    v1 = await page.evaluate("window.__cuedeck.state.masterGain.gain.value"); low = await rms(page)
    check("C10 master level ramps (no jump) and lands on −20 dB", v0 > 0.5 and abs(v1 - 0.1) < 0.01 and 0.07 < low / full < 0.13,
          f"{v0:.3f} -> {v1:.3f}, heard ratio {low/full:.3f}")
    await page.evaluate("""(()=>{const s=document.getElementById('masterGain');s.value=0;s.dispatchEvent(new Event('input'))})()""")
    await escape(page)
    # C19 audition doesn't touch the show
    await click_cue(page, 0); await page.keyboard.press("Space"); await page.wait_for_timeout(300)
    await click_cue(page, 1)
    await page.evaluate("(()=>{const c=window.__cuedeck.state.cues[1];c.transitionMode='stop'})()")
    await page.click("#waveAuditionBtn"); await page.wait_for_timeout(700)
    cur = await page.evaluate("window.__cuedeck.state.currentId===window.__cuedeck.state.cues[0].id")
    lab = await page.text_content("#waveAuditionBtn")
    check("C19 audition leaves the live cue playing and current", await playing(page) == ["01"] and cur and "Stop" in lab, f"{await playing(page)} {lab}")
    ph = await page.evaluate("window.__cuedeck.state.editorPlayheads.get(window.__cuedeck.state.cues[1].id)")
    check("C19 audition moves the editor playhead", ph > 0.3, f"{ph:.2f}")
    await escape(page)
    check("C19 Escape stops audition too", (await page.text_content("#waveAuditionBtn")).startswith("▶"))
    # C20 I/O keys inert in Show Mode
    await click_cue(page, 0)
    before = await page.evaluate("JSON.stringify([window.__cuedeck.state.cues[0].trimStart,window.__cuedeck.state.cues[0].trimEnd])")
    await page.click("#showBtn"); await page.wait_for_timeout(900); await blur(page)
    await page.keyboard.press("o"); await page.keyboard.press("i"); await page.wait_for_timeout(300)
    after = await page.evaluate("JSON.stringify([window.__cuedeck.state.cues[0].trimStart,window.__cuedeck.state.cues[0].trimEnd])")
    check("C20 I and O do nothing in Show Mode", before == after, f"{before} -> {after}")
    await page.click("#showBtn"); await page.wait_for_timeout(400)
    await click_cue(page, 0)
    await page.evaluate("window.__cuedeck.state.editorPlayheads.set(window.__cuedeck.state.cues[0].id,3)")
    await page.keyboard.press("i"); await page.wait_for_timeout(200)
    check("C20 I still sets IN in edit mode", abs(await page.evaluate("window.__cuedeck.state.cues[0].trimStart") - 3) < 0.01)
    # C15 loop disables fade-out
    await page.evaluate("(()=>{const c=window.__cuedeck.state.cues[0];c.trimStart=0})()")
    await page.click("#loop + span"); await page.wait_for_timeout(300)
    dis = await page.evaluate("document.getElementById('fadeOut').disabled")
    check("C15 looping shows fade-out as inactive", dis and "looping" in await page.text_content("#fadeOutValue"))
    await page.click("#loop + span"); await page.wait_for_timeout(200)
    # C18 focus ring
    await page.keyboard.press("Tab"); await page.keyboard.press("Tab")
    ow = await page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
    check("C18 keyboard focus is visible", ow not in ("none", ""), ow)
    # C12 version
    ver = await page.evaluate("[document.title, document.getElementById('appSubtitle').textContent, window.__cuedeck.APP_VERSION]")
    check("C12 one version everywhere", ver[2] in ver[0] and ver[2] in ver[1], str(ver))
    # C21 pad titles
    await click_cue(page, 2); await page.fill("#cueName", "Act Two Finale Reprise With Extended Orchestral Playout And Bows"); await blur(page)
    await page.click("#padBtn"); await page.wait_for_timeout(700)
    fit = await page.evaluate("""(()=>{const t=document.querySelectorAll('.cue-title')[2];return [getComputedStyle(t).whiteSpace,t.scrollHeight,parseFloat(t.style.maxHeight)||0]})()""")
    check("C21 long names wrap and fit inside the pad", fit[0] == "normal" and fit[1] <= fit[2] + 1, str(fit))
    await page.click("#padBtn")
    check("No page errors (keys/transport)", not errors, "; ".join(errors[:3]))
    await ctx.close()

async def suite_wake(pw, m):
    ctx, page, errors = await fresh(pw, wake_stub=True)
    await add(page, m["t220"])
    await page.click("#showBtn"); await page.wait_for_timeout(800)
    r1 = await page.evaluate("window.__wake.requests")
    await page.evaluate("window.__wake.active.released=true;window.__hidden=true;document.dispatchEvent(new Event('visibilitychange'))")
    await page.evaluate("window.__hidden=false;document.dispatchEvent(new Event('visibilitychange'))"); await page.wait_for_timeout(200)
    r2 = await page.evaluate("window.__wake.requests")
    check("C8 Show Mode re-takes the screen lock after switching tabs", r1 == 1 and r2 == 2, f"{r1}->{r2}")
    await ctx.close()

async def suite_memory_storage(pw, m):
    ctx, page, errors = await fresh(pw)
    await add(page, m["long"], m["t220"], m["right"], wait=6000)
    modes = await page.evaluate("window.__cuedeck.state.cues.map(c=>[c.mode,!!c.buffer,c.loadState])")
    check("C11 long cue streams (no decoded copy kept); short cues decoded", modes[0][:2] == ["stream", False] and modes[1][:2] == ["buffer", True], str(modes))
    # streamed cue plays, with start latency
    await click_cue(page, 0)
    t = await page.evaluate("""(async()=>{const d=window.__cuedeck,c=d.state.cues[0];const t0=performance.now();await d.startCue(c.id);
        const r=d.state.active.get(c.id);const p0=r.position();while(r.position()<=p0+0.001&&performance.now()-t0<3000)await new Promise(x=>setTimeout(x,5));
        return performance.now()-t0;})()""")
    await page.wait_for_timeout(1000)
    pos = await page.evaluate("[...window.__cuedeck.state.active.values()][0]?.position()")
    check("C11 streamed cue starts promptly and plays", t < 250 and pos and pos > 0.8, f"start {t:.0f} ms, pos {pos}")
    level = await rms(page)
    check("C11 streamed cue is audible on the output", level > 0.02, f"rms {level:.3f}")
    # GO to end with trimmed streamed cue: ends on time and fires auto-follow
    await escape(page)
    await page.evaluate("(()=>{const c=window.__cuedeck.state.cues[0];c.trimStart=10;c.trimEnd=11.5;c.autoFollow=true})()")
    await page.evaluate("window.__cuedeck.startCue(window.__cuedeck.state.cues[0].id)"); await page.wait_for_timeout(2200)
    check("C11 streamed cue stops at OUT and auto-follows", await playing(page) == ["02"], str(await playing(page)))
    await escape(page)
    await page.evaluate("(()=>{const c=window.__cuedeck.state.cues[0];c.trimStart=0;c.trimEnd=c.duration;c.autoFollow=false})()")
    # streamed loop
    await page.evaluate("(()=>{const c=window.__cuedeck.state.cues[0];c.trimStart=5;c.trimEnd=6})()")
    await page.evaluate("(()=>{const c=window.__cuedeck.state.cues[0];c.loop=true})()")
    await page.evaluate("window.__cuedeck.startCue(window.__cuedeck.state.cues[0].id)"); await page.wait_for_timeout(2600)
    lp = await page.evaluate("[...window.__cuedeck.state.active.values()][0]?.position()")
    check("Streamed loop stays between IN and OUT", lp and 4.9 <= lp <= 6.05, f"{lp}")
    await escape(page)
    await page.evaluate("(()=>{const c=window.__cuedeck.state.cues[0];c.loop=false;c.trimStart=0;c.trimEnd=c.duration})()")
    # C17 right-only waveform
    mx = await page.evaluate("Math.max(...window.__cuedeck.state.wavePeaks.get(window.__cuedeck.state.cues[2].id).maxs)")
    check("C17 right-channel-only audio shows a waveform", mx > 0.05, f"{mx:.3f}")
    # reload: everything READY, long cue not decoded again
    await page.evaluate("window.dispatchEvent(new Event('beforeunload'))")
    await page.reload(); await page.wait_for_timeout(3000)
    rel = await page.evaluate("window.__cuedeck.state.cues.map(c=>[c.loadState,c.mode,!!window.__cuedeck.state.wavePeaks.get(c.id)])")
    check("Reload: all cues READY with waveforms; long cue still streamed", all(r[0] == "ready" and r[2] for r in rel) and rel[0][1] == "stream", str(rel))
    # C7 duplicate relink after import; C13 storage tidy; export/import roundtrip
    await click_cue(page, 1); await page.click("#duplicateBtn"); await page.wait_for_timeout(300)
    async with page.expect_download() as dl:
        await page.click("#exportBtn")
    show_path = await (await dl.value).path()
    show = json.load(open(show_path))
    check("Export carries app version and all cues", show["appVersion"] == "2.0" and len(show["cues"]) == 4)
    await page.set_input_files("#showInput", show_path); await page.wait_for_timeout(2500)
    st = await page.evaluate("window.__cuedeck.state.cues.map(c=>c.loadState)")
    check("Re-importing the same show finds the stored audio", st == ["ready"] * 4, str(st))
    renamed = dict(show); renamed["cues"] = [dict(c, id=f"new-{i}") for i, c in enumerate(show["cues"])]
    p2 = MEDIA / "renamed.json"; p2.write_text(json.dumps(renamed))
    await page.set_input_files("#showInput", str(p2)); await page.wait_for_timeout(2000)
    miss = await page.evaluate("window.__cuedeck.state.cues.filter(c=>c.missing).length")
    keys = await page.evaluate("""new Promise(r=>{const q=indexedDB.open('CueDeckDB');q.onsuccess=()=>{const t=q.result.transaction('audio').objectStore('audio').getAllKeys();t.onsuccess=()=>{r(t.result.length);q.result.close()}}})""")
    check("C13 importing a different show clears the old audio", miss == 4 and keys == 0, f"missing {miss}, stored {keys}")
    await page.set_input_files("#fileInput", [m["t220"]]); await page.wait_for_timeout(2500)
    dup = await page.evaluate("window.__cuedeck.state.cues.filter(c=>c.fileName==='tone220.wav').map(c=>c.loadState)")
    check("C7 one file relinks every cue that uses it (duplicates too)", dup == ["ready", "ready"], str(dup))
    # C14 bad show file
    bad = MEDIA / "bad.json"
    bad.write_text(json.dumps({"cues": [{"id": "x", "name": "Bad", "gainDb": "loud", "fadeIn": None, "color": 5}, 7, None]}))
    await page.set_input_files("#showInput", str(bad)); await page.wait_for_timeout(1500)
    rows = await page.evaluate("document.querySelectorAll('.cue[data-cue-id]').length")
    meta = await page.evaluate("document.querySelector('.cue-meta')?.innerText||''")
    check("C14 a damaged show file imports safely", rows == 1 and "0.0 dB" in meta, f"rows {rows} meta {meta!r}")
    garbage = MEDIA / "garbage.json"; garbage.write_text("not json")
    await page.set_input_files("#showInput", str(garbage)); await page.wait_for_timeout(500)
    check("C14 an unreadable file changes nothing", await page.evaluate("document.querySelectorAll('.cue[data-cue-id]').length") == 1)
    check("No page errors (memory/storage)", not errors, "; ".join(errors[:3]))
    await ctx.close()

async def suite_99(pw, m):
    ctx, page, errors = await fresh(pw)
    files = []
    for i in range(99):
        dst = MEDIA / f"song{i:02d}.wav"
        shutil.copy(m["long"] if i % 3 else m["short25"], dst); files.append(str(dst))
    t0 = time.time()
    await page.set_input_files("#fileInput", files)
    await page.wait_for_function("window.__cuedeck.state.cues.length===99 && window.__cuedeck.state.cues.every(c=>c.loadState!=='loading')", timeout=600000)
    secs = time.time() - t0
    info = await page.evaluate("[window.__cuedeck.decodedBytes(),window.__cuedeck.state.cues.filter(c=>c.loadState==='ready').length,window.__cuedeck.state.cues.filter(c=>c.mode==='stream').length]")
    check("C11 99-cue show (66 × 2.5-min songs, 33 short) loads under the memory budget",
          info[1] == 99 and info[0] <= 512 * 1024 * 1024, f"ready {info[1]}, streamed {info[2]}, decoded {info[0]/1048576:.0f} MB, {secs:.0f} s")
    lat = []
    for i in (0, 1, 50, 97, 98):
        t = await page.evaluate(f"""(async()=>{{const d=window.__cuedeck,c=d.state.cues[{i}];const t0=performance.now();await d.startCue(c.id);
          const r=d.state.active.get(c.id);if(!r)return 9999;const p0=r.position();while(r.position()<=p0+0.001&&performance.now()-t0<3000)await new Promise(x=>setTimeout(x,5));
          d.stopCue(c.id,0);return performance.now()-t0;}})()""")
        lat.append(round(t))
    check("C11 cues across the 99-cue show start within 250 ms", max(lat) < 250, f"ms {lat}")
    check("No page errors (99 cues)", not errors, "; ".join(errors[:3]))
    await ctx.close()

SPACE = "window.dispatchEvent(new KeyboardEvent('keydown',{code:'Space',key:' ',bubbles:true}))"
ESC = "window.dispatchEvent(new KeyboardEvent('keydown',{code:'Escape',key:'Escape',bubbles:true}))"

async def suite_independent_check(pw, m):
    """Regression tests for the independent check's findings (IC1–IC8, IC13)."""
    ctx, page, errors = await fresh(pw)
    longs = []
    for i in range(3):
        d = MEDIA / f"long{i}.wav"; shutil.copy(m["long"], d); longs.append(str(d))
    await add(page, *longs, wait=6000)
    # IC1: two GOs within the same moment on streamed cues
    await click_cue(page, 0)
    await page.evaluate(SPACE + ";" + SPACE); await page.wait_for_timeout(1200)
    p1 = await playing(page)
    await page.keyboard.press("Space"); await page.wait_for_timeout(800)
    check("IC1 two instant GOs on long cues both play, and GO still works after", p1 == ["01", "02"] and await playing(page) == ["01", "02", "03"], f"{p1} then {await playing(page)}")
    await escape(page)
    await click_cue(page, 0)
    await page.evaluate(SPACE + ";window.dispatchEvent(new KeyboardEvent('keydown',{code:'ArrowDown',key:'ArrowDown'}))"); await page.wait_for_timeout(1000)
    await page.keyboard.press("Space"); await page.wait_for_timeout(800)
    check("IC1 GO then an instant arrow key: playback keeps working", len(await playing(page)) >= 2, str(await playing(page)))
    await escape(page)
    # IC2: Escape straight after GO on a long cue
    await click_cue(page, 0)
    await page.evaluate(SPACE + ";" + ESC); await page.wait_for_timeout(1200)
    check("IC2 Escape straight after GO stops a long cue that is still starting", await playing(page) == [], str(await playing(page)))
    await page.evaluate("(()=>{const d=window.__cuedeck,c=d.state.cues[1];d.startCue(c.id);d.stopCue(c.id,0)})()"); await page.wait_for_timeout(1200)
    check("IC2 the cue's own stop also cancels a start in progress", await playing(page) == [], str(await playing(page)))
    # IC5: streamed loop whose OUT is the end of the file keeps looping
    await page.evaluate("(()=>{const c=window.__cuedeck.state.cues[0];c.loop=true;c.trimStart=148;c.trimEnd=c.duration;window.__cuedeck.startCue(c.id)})()")
    await page.wait_for_timeout(4500)
    lp = await page.evaluate("[...window.__cuedeck.state.active.values()][0]?.position()")
    check("IC5 streamed loop at the end of the file keeps looping", await playing(page) == ["01"] and lp is not None and 147.9 <= lp <= 150.1, f"{await playing(page)} pos {lp}")
    await escape(page)
    await page.evaluate("(()=>{const c=window.__cuedeck.state.cues[0];c.loop=false;c.trimStart=0;c.trimEnd=c.duration})()")
    # IC6: Show Mode is read-only
    await page.click("#showBtn"); await page.wait_for_timeout(900)
    prevented = await page.evaluate("""(()=>{const r=document.querySelector('.cue[data-cue-id]');const e=new DragEvent('dragstart',{cancelable:true,bubbles:true,dataTransfer:new DataTransfer()});r.dispatchEvent(e);return e.defaultPrevented})()""")
    check("IC6 cues can't be dragged in Show Mode", prevented)
    await page.click("#showBtn"); await page.wait_for_timeout(300)
    # IC8: audition inside the cue stops at OUT
    await page.set_input_files("#fileInput", [m["t220"]]); await page.wait_for_timeout(1500)
    await click_cue(page, 3)
    await page.evaluate("(()=>{const d=window.__cuedeck,c=d.state.cues[3];c.trimEnd=2;d.state.editorPlayheads.set(c.id,1.5)})()")
    await page.click("#waveAuditionBtn"); await page.wait_for_timeout(300)
    on = await page.text_content("#waveAuditionBtn"); await page.wait_for_timeout(1200)
    check("IC8 audition from inside the cue stops at OUT", "Stop" in on and (await page.text_content("#waveAuditionBtn")).startswith("▶"))
    # IC13: cancelling the import confirmation keeps the show
    bad = MEDIA / "other.json"; bad.write_text(json.dumps({"cues": [{"id": "z", "name": "Other", "hotkey": "F"}]}))
    page.dialog_answer = False
    await page.set_input_files("#showInput", str(bad)); await page.wait_for_timeout(800)
    check("IC13 cancelling an import leaves the show untouched", await page.evaluate("window.__cuedeck.state.cues.length") == 4)
    # IC7: a reserved hotkey from an imported show is cleared with a message
    page.dialog_answer = True
    await page.set_input_files("#showInput", str(bad)); await page.wait_for_timeout(3400)
    t = await page.text_content("#toast")
    check("IC7 a clashing old hotkey is cleared and the user is told", "were cleared" in t and await page.evaluate("window.__cuedeck.state.cues[0].hotkey") == "", t)
    check("No page errors (independent-check fixes)", not errors, "; ".join(errors[:3]))
    await ctx.close()

async def suite_upgrade_and_storage(pw, m):
    """IC3/IC4: the saved show survives database failure, old-version wipes and the v1→v2 upgrade."""
    prof = tempfile.mkdtemp(prefix="cuedeck-up-")
    kw = dict(headless=True, args=["--autoplay-policy=user-gesture-required"])
    if CHROME: kw["executable_path"] = CHROME
    ctx = await pw.chromium.launch_persistent_context(prof, **kw)
    old = await ctx.new_page()
    await old.goto(f"http://localhost:{PORT}/tests/fixtures/v1_live.html"); await old.wait_for_timeout(500); await old.mouse.click(700, 5)
    await old.set_input_files("#fileInput", [m["t220"], m["t330"]]); await old.wait_for_timeout(2500)
    # v2 opens while the old tab is still open → blocked upgrade
    new = await ctx.new_page(); errors = []
    new.on("pageerror", lambda e: errors.append(str(e)))
    await new.goto(URL); await new.wait_for_timeout(1500)
    blocked = await new.evaluate("!!document.getElementById('dbBlocker')")
    kept = await new.evaluate("JSON.parse(localStorage.getItem('cuedeck-project')).length")
    check("IC3 upgrade blocked by an old tab: app waits, saved show untouched", blocked and kept == 2, f"blocker {blocked}, saved {kept}")
    await new.set_input_files("#fileInput", [m["right"]]); await new.wait_for_timeout(800)
    check("IC3 while blocked, new audio is refused instead of being lost", await new.evaluate("window.__cuedeck.state.cues.length") == 2)
    await old.close(); await new.wait_for_timeout(3000)
    st = await new.evaluate("window.__cuedeck.state.cues.map(c=>c.loadState)")
    check("IC3 old tab closed: v1 show upgrades with its audio", not await new.evaluate("!!document.getElementById('dbBlocker')") and st == ["ready", "ready"], str(st))
    # IC4: a saved "missing" flag is retried
    await new.evaluate("(()=>{const a=JSON.parse(localStorage.getItem('cuedeck-project'));a[0].missing=true;localStorage.setItem('cuedeck-project',JSON.stringify(a))})()")
    await new.reload(); await new.wait_for_timeout(2500)
    check("IC4 a cue saved as MISSING is retried and comes back", await new.evaluate("window.__cuedeck.state.cues[0].loadState") == "ready")
    # IC3: the old version opened after the update (stale tab / rollback) empties the list → backup restores it
    await new.close()
    stale = await ctx.new_page()
    await stale.goto(f"http://localhost:{PORT}/tests/fixtures/v1_live.html"); await stale.wait_for_timeout(2000)
    wiped = await stale.evaluate("JSON.parse(localStorage.getItem('cuedeck-project')||'[]').length")
    await stale.close()
    back = await ctx.new_page(); await back.goto(URL); await back.wait_for_timeout(2500)
    check("IC3 list emptied by the old version is restored from backup, audio intact",
          wiped == 0 and await back.evaluate("window.__cuedeck.state.cues.map(c=>c.loadState)") == ["ready", "ready"]
          and "backup" in (await back.text_content("#toast") or ""), f"old version left {wiped} cues")
    await back.close()
    # IC3: database won't open → list kept, not overwritten
    await ctx.add_init_script("IDBFactory.prototype.open=function(){throw new Error('blocked by test')}")
    p3 = await ctx.new_page(); await p3.goto(URL); await p3.wait_for_timeout(2000)
    shown = await p3.evaluate("window.__cuedeck.state.cues.length")
    await p3.evaluate("window.dispatchEvent(new Event('beforeunload'))")
    saved = await p3.evaluate("JSON.parse(localStorage.getItem('cuedeck-project')).length")
    check("IC3 database unavailable: cue list still shown and not wiped", shown == 2 and saved == 2, f"shown {shown}, saved {saved}")
    check("No page errors (upgrade/storage)", not errors, "; ".join(errors[:3]))
    await ctx.close()

async def main():
    if not shutil.which("ffmpeg"): sys.exit("ffmpeg is required")
    m = make_media()
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--directory", str(ROOT)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        async with async_playwright() as pw:
            for s in (suite_keys_transport, suite_wake, suite_memory_storage, suite_independent_check, suite_upgrade_and_storage, suite_99):
                if "--quick" in sys.argv and s is suite_99: continue
                try: await s(pw, m)
                except Exception as e:
                    traceback.print_exc(); results.append((s.__name__ + " crashed", False, str(e)))
    finally:
        srv.terminate(); shutil.rmtree(MEDIA, ignore_errors=True)
    passed = sum(1 for r in results if r[1])
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)

asyncio.run(main())
