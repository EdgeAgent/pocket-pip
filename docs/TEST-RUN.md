# Pocket Pip — Test Run Receipts

All tests run 2026-11-16 (America/Toronto) in the build VM. Times below are
UTC as stamped by the VM (EST = UTC − 5). Nothing here is claimed that
isn't shown.

---

## 1. Bridge + simulator — full conversation loop ✅ PASS

Bridge started (`python3 bridge/bridge.py`, demo brain), simulator ran its
scripted 3-message conversation against it. Exit code 0.

```
=== Pocket Pip bridge+simulator test run ===
2026-11-17T03:31:41+00:00
Pocket Pip simulator -> http://localhost:8765
Bridge health: ok (brain: demo)
  [watch] state -> IDLE      (Pip on his cloud)

YOU: Hey Pip, are you there?
  [watch] state -> LISTENING (capturing message)
  [watch] state -> THINKING  (POST /chat -> bridge)
  [watch] state -> TALKING   (reply on screen)
PIP: Hey Kevin. Pip here, on the cloud, ready when you are.
  [watch] brain used: demo
  [watch] state -> IDLE      (back to the cloud)

YOU: What time is it at home base?
  [watch] state -> LISTENING (capturing message)
  [watch] state -> THINKING  (POST /chat -> bridge)
  [watch] state -> TALKING   (reply on screen)
PIP: It's 03:31 AM here at home base.
  [watch] brain used: demo
  [watch] state -> IDLE      (back to the cloud)

YOU: Check on Robot Orchestra for me.
  [watch] state -> LISTENING (capturing message)
  [watch] state -> THINKING  (POST /chat -> bridge)
  [watch] state -> TALKING   (reply on screen)
PIP: Robot Orchestra is safe on the home server. Roboto says hi.
  [watch] brain used: demo
  [watch] state -> IDLE      (back to the cloud)

Scripted conversation complete.
=== exit: 0 ===
2026-11-17T03:31:45+00:00
```

Re-run at 03:37 UTC the same night reproduced the identical result
(exit 0, all three exchanges, all four state transitions per turn).
The Ollama brain path was **not** exercised — no Ollama server exists in
the test VM; it is covered by code review only, and the bridge falls back
to the demo brain if Ollama is unreachable.

## 2. Firmware compile (M5Stack StopWatch env) ✅ PASS

```
cd firmware && pio run -e pocket-pip
PlatformIO Core 6.2.0 · espressif32 @ 8.0.0 · board esp32-s3-devkitc-1
(16 MB flash / PSRAM overrides — see platformio.ini board note)

RAM:   [==        ]  15.9% (used 51972 bytes from 327680 bytes)
Flash: [==        ]  18.3% (used 1196723 bytes from 6553600 bytes)
Building .pio/build/pocket-pip/firmware.bin
esptool v5.4.0 — Creating ESP32-S3 image... Successfully created ESP32-S3 image.
======================== [SUCCESS] Took 589.62 seconds ========================
```

`firmware.bin` produced (1,223,696 bytes). This proves the code compiles
and links for ESP32-S3. It does **not** prove it runs on a real StopWatch —
no hardware was available to flash. The BLE env (`pocket-pip-ble`) was not
compiled; BLE is feature-flagged off by design (see SPEC §3).

## 3. Watch preview (`preview/index.html`) ✅ standalone

- Grep for external references (`src=`, `href=`, `url(`, `@import`,
  `http(s)://`): **none**. One self-contained file — inline CSS/JS/SVG,
  system font stack only. Works offline, opened straight from disk.

## 4. Desk face (`display/index.html`) ✅ standalone, exactly 1920 × 480

- Stage element is exactly **1920 px × 480 px** (the LESOWN P88's native
  resolution); a JS fit function scales it to any other window, and on the
  P88 at fullscreen the scale is exactly 1.
- Grep for external loads (`<script src`, `<link`, `@import`, `url(`):
  **none**. The only URL in the file is the bridge API base
  (`http://localhost:8765`, overridable via `?bridge=`) — a fetch target,
  not an asset.
- Live mode: the page probes `GET /health` and posts to `/chat`. From a
  `file://` open, browser CORS rules may block those calls (the bridge
  sends no CORS headers) — the page then runs its built-in demo brain,
  which mirrors `bridge.py`'s demo replies line for line, and plays an
  ambient sample exchange when idle. Verified by code inspection; a
  physical P88 + host test is Kevin's to run (plug in, F11).

## Not tested / not proven

- No real StopWatch hardware: no flash, no on-device run, no Wi-Fi join.
- No real P88: rendering verified at the code level (exact pixel stage,
  self-containment), not on the physical panel.
- Ollama brain path untested (no server in the VM).
- BLE: not implemented, not compiled — intentionally.

---

# Finishing pass — voice channel, bridge-served faces, screenshots

Run 2026-11-16 (America/Toronto), same VM, after the base build above.

## 5. Voice channel — honest-unavailable path ✅ PASS

Bridge started with **no** voice env vars set (the default):

- `GET /voice/status` → `stt_configured: false, tts_configured: false,
  server_voice_available: false`, with the two paths and the P88 note
  (no mic/speaker on the bar — the host's are used).
- `POST /voice {"text": "Hey Pip, are you there?"}` → **HTTP 503**:
  "voice unavailable: speech synthesis is not configured on the bridge
  (set POCKETPIP_PIPER_CMD). The reply text is included; no audio was
  made." — the demo-brain reply text rides along, but no audio is faked.
- `POST /voice {"audio_base64": ...}` → **HTTP 503**: speech-to-text not
  configured (set POCKETPIP_WHISPER_CMD). Nothing transcribed.
- `POST /voice` without the token → **HTTP 401**, same as /chat.
- `GET /health` now carries the same voice block plus `"serves":
  ["/display/", "/preview/"]`.

## 6. Voice channel — config plumbing with stub tools ✅ PASS (plumbing only)

Real faster-whisper and Piper are **not installed in this VM**
(`python3 -c "import faster_whisper"` fails; no `piper` binary), so the
plumbing was proven with stub commands standing in for them:

- `POCKETPIP_PIPER_CMD='python3 /tmp/stub_tts.py'` — stub reads text on
  stdin, writes a real WAV (0.25 s sine) to stdout.
- `POCKETPIP_WHISPER_CMD='python3 /tmp/stub_stt.py {file}'` — stub prints
  a fixed transcript for the audio path it is handed.

Results:

- `GET /voice/status` → `stt: True, tts: True, available: True`.
- `POST /voice {"text": "Hey Pip, are you there?"}` → 200, reply
  "Hey Kevin. Pip here, on the cloud, ready when you are.", and
  `audio_base64` decoding to **11,044 bytes** with a verified
  `RIFF`/`WAVE` header.
- `POST /voice {"audio_base64": <bytes>}` → 200, transcript
  "Check on Robot Orchestra for me." (the stub's line, proving the
  `{file}` substitution and stdout capture), reply "Robot Orchestra is
  safe on the home server. Roboto says hi.", valid WAV audio attached.

This proves the endpoint, the env-var config, the subprocess plumbing,
and the response shape. It does **not** prove real speech recognition or
real speech synthesis — that needs Piper + a whisper CLI installed on the
host (documented in SPEC §2). No live microphone capture was tested:
the VM has no mic. The desk face's browser path (Web Speech API) is
wired and DOM-verified (§7); a human voice run is Kevin's to do in
Chrome/Edge on the host.

## 7. Bridge serves the faces — same origin ✅ PASS

- `GET /display/` → 200 `text/html`; `GET /preview/` → 200; `GET /`
  → 200 (the desk face). Path traversal (`/display/../bridge/bridge.py`,
  sent raw) → **404**. CORS preflight (`OPTIONS /chat`) → **204** with
  allow headers; API responses carry `Access-Control-Allow-Origin: *`,
  so a `file://` open can also reach the bridge now.
- Headless Chromium loaded `http://localhost:8765/display/` (served by
  the bridge) and the live DOM showed: badge **"● Live bridge"**,
  bridge fact "Health check passed. This page is served by the bridge
  itself — same origin, no CORS friction.", and the Voice rail populated
  ("Ears: browser speech + bridge whisper · Mouth: browser voice +
  bridge piper" — against the stub-configured bridge of §6).
- Desk-face JS re-checked after the voice work: extracted script passes
  `node --check`; still zero external references.
- Regression: the simulator's scripted 3-message conversation re-ran
  against the new bridge code — exit 0, identical exchanges.

## 8. README screenshots — rendered from the real surfaces ✅

Rendered with Playwright driving headless Chromium against the live
bridge (not mockups):

- `assets/screenshot-display.png` (1920 × 480) — the desk face after a
  real two-message conversation through `POST /chat`, badge "Live
  bridge", mic button and Voice rail visible.
- `assets/screenshot-preview.png` (1120 × 860) — the round watch-face
  preview page as served at `/preview/`.
- For GitHub, each PNG is also wrapped as an `.svg` carrying the same
  pixels (base64-embedded raster): the connector's snapshot push
  validates UTF-8 text and rejects raw PNG bytes outright
  ("snapshot file `assets/screenshot-display.png` is not UTF-8"), so the
  README references the `.svg` twins and the raw `.png` originals stay
  in the local repo. Same pixels, honest container.

Found and fixed during the shoot: the rail overflowed the 480 px stage
(the new Voice section and footer were clipped). The rail was compacted
(state chips in a 2 × 2 grid, tighter type) and re-measured in the DOM:
voice section bottom at 417 px, footer bottom at 468 px — inside the
stage. The shipped screenshot is the fixed layout.

## Still not proven after this pass

- Real Piper/faster-whisper run (not installed in the VM — config and
  plumbing proven with stubs only, §6).
- A live human voice through the desk-face mic (no mic in the VM).
- Everything in the base list above: no StopWatch hardware, no physical
  P88, Ollama path untested, BLE unimplemented.

---

# Visual swap — the polished portrait, poses, sizes

Run 2026-11-16 late evening (America/Toronto), after Kevin rejected the
hand-drawn SVG pet ("looks like shit") and then approved the glossy 3D
portrait, uploading his own copy back (1600 × 1600 PNG — that upload is
the canonical source, `assets/pip-character.png`; it is the same image
as the generated webp, `assets/pip-character.webp`).

## 9. Portrait + pose set wired into both faces ✅ PASS

- The inline SVG pet is **gone** from `display/index.html` and
  `preview/index.html` (grep: no `<svg`, no mouth elements). The banner
  was rebuilt around the portrait (same layout/text, portrait embedded,
  circle-clipped into the watch motif).
- Canonical wiring: the faces embed the images as data URIs, so they
  stay single self-contained files and the GitHub snapshot route (UTF-8
  text only) can carry them. The bridge additionally serves `/assets/`
  (added this run; `GET /assets/pip-character.webp` → 200,
  `image/webp`, 218,462 bytes; `/health` now lists it under `serves`).
- **Poses per state** (Kevin's ask: "typing when he's typing… a
  dashboard or something"): idle = main portrait; listening = portrait
  + CSS glow/scale; thinking = `assets/poses/pip-thinking.webp`;
  **working/typing** = `assets/poses/pip-typing.webp` (head down, hands
  on the keyboard, screen glow in the sunglasses) — the desk face now
  runs listening → thinking → **typing** while the reply is produced →
  talking; talking = `assets/poses/pip-talking.webp` (waving, laptop
  closed). The preview mirrors the same map with the round variant for
  idle/listening and a Typing state button.
- Verified in headless Chromium against the live bridge, both faces:
  for all five states, the pet `<img>` `src` equals the mapped pose and
  the computed animation matches — idle `bob`, listening `listenPulse`
  (scale + teal glow), thinking `thinkTilt`, working `typeTap`,
  talking `talkBounce`. Extracted JS passes `node --check` on both
  pages; the bridge/simulator behaviour is untouched.
- **Dashboard rail:** the desk face's right rail is now titled
  "Dashboard — agent state" and gained a **Last exchange** readout
  (updated every turn, text and voice). First render overflowed the
  480 px stage (footer bottom 572 px) — the rail was compacted (3-column
  state chips, tighter type/gaps) and re-measured: footer bottom
  **468 px**, last-exchange bottom 425 px — inside the stage.
- **Responsive:** the desk face still scales its 1920 × 480 stage to any
  window; below a 2:1 aspect it now also engages compact mode (rail
  hidden, pet zone widened). Verified at 800 × 480: compact class on,
  rail `display: none` (screenshot `assets/screenshot-display-small.png`).
- **Screenshots re-rendered** from the live pages (Playwright + headless
  Chromium, same method as §8): `screenshot-display.png` (1920 × 480,
  two-message live-bridge conversation, new portrait + dashboard rail)
  and `screenshot-preview.png` (1120 × 860, round portrait in the watch,
  five state buttons). One layout fix during the shoot: the square
  portrait pushed the watch bubble into the hint line — pet zone
  narrowed 62% → 52% and re-measured (bubble bottom 579 px < hint top
  588 px). `.svg` twins regenerated for both screenshots and for the
  round + bar size variants the README shows, same base64-raster wrap
  as §8.
- Binary assets (`pip-character.png/.webp`, `poses/*.webp`,
  `sizes/*.png`, `pip-animated.mp4`, screenshot `.png` originals) are
  committed in the local repo; the snapshot push carries the UTF-8
  files (the faces and banner embed the pixels, the twins wrap the
  rest), exactly as with the §8 screenshot originals.
