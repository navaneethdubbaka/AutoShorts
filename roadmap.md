# AutoShorts Video Engine — Agent Build Roadmap

**Constraint that shapes every decision below: this runs on a CPU-only VM. No CUDA, no NVENC, no GPU fallback.** Every tool choice here was picked specifically because it has a real CPU-only performance story — not just "works on CPU in theory."

Treat each phase as a checkpoint: don't start phase N+1 until phase N produces a working, testable artifact. Re-read this whole file before starting, then re-read the relevant phase section immediately before doing the work in it.

---

## 0. Hard constraints to keep in view

- n8n has already done all research, scripting, and scene planning. The backend in this repo **never** calls an LLM to write or rewrite narration/script content. It only does mechanical media production from the JSON it's given.
- Single CPU VM. No GPU. Every model and every render step must have an acceptable CPU-only execution path.
- This is a personal Instagram pipeline (low volume — a handful of videos a day at most), not a multi-tenant SaaS. Don't over-engineer for horizontal scale; do build clean module boundaries so scaling is possible later without a rewrite.
- Recommended minimum VM spec for acceptable render times: **4 vCPU / 8GB RAM** as a floor, **8 vCPU / 16GB RAM** if you want renders to comfortably finish in well under real-time. faster-whisper, ffmpeg encoding, and concurrent asset downloads all compete for the same cores, so more cores buys you real wall-clock improvement here, unlike a lot of web workloads.

---

## 1. Final tech stack (with the CPU-specific reasoning)

| Module | Pick | Why this and not the obvious alternative |
|---|---|---|
| Web framework | FastAPI + Uvicorn (Gunicorn worker manager in prod) | Already specified; nothing CPU-specific here. |
| Job queue | **RQ (Redis Queue) + Redis**, not Celery, not arq | Video rendering and Whisper transcription are CPU-bound, not I/O-bound. arq's whole pitch is async concurrency for I/O-wait workloads (LLM/API calls) — irrelevant here since ffmpeg and faster-whisper block on CPU regardless of async wrapping. Celery is the more "enterprise" choice but adds a result backend, broker config, and Beat/Flower overhead you don't need for a single-VM, single-operator pipeline. RQ is sync, dead simple, uses Redis for both queue and result storage, and worker processes give you real OS-level process isolation — important when one bad ffmpeg call shouldn't take down your API process. Revisit Celery only if you later move to multiple VMs/workers with complex retry/routing needs.
| Speech-to-text + alignment | **faster-whisper (CTranslate2, INT8 quantized)** doing the transcription, **WhisperX's wav2vec2 forced-alignment step** for word-level timestamps — **diarization disabled** | WhisperX itself is built on faster-whisper under the hood. Running the full WhisperX pipeline (transcription + diarization) on CPU is the slow path — diarization adds pyannote-audio as a second model pass and gated HuggingFace downloads you don't need, since you have exactly one narrator per scene, not multiple overlapping speakers. Strip diarization out and you're left with: faster-whisper CPU transcription (INT8 quantization gets ~4x the speed of vanilla Whisper at equivalent accuracy) + a single wav2vec2 forced-alignment pass for word timestamps. Use `small.en` or `distil-large-v3` as the model — large-v3 is overkill for short narration scripts and meaningfully slower on CPU for no real WER benefit on clean studio-quality TTS audio (your input audio is synthetic TTS, not noisy field recording, so a smaller model is fine).
| Primary TTS | **ElevenLabs API** (cloud, no local CPU cost) | Already your default. Use `eleven_flash_v2_5` instead of `eleven_multilingual_v2` unless you need maximum expressiveness — Flash is roughly half the per-character credit cost of Multilingual v2 and has materially lower latency, which matters when this call gates the whole pipeline. For a 30–60s Short, the quality difference is rarely noticeable to viewers; the cost difference compounds over months of daily posting.
| Future/fallback TTS | **Piper TTS** (local, CPU, MIT-licensed, ONNX/VITS) | Design the TTS module behind a provider interface now so this drops in later with zero refactor. Piper runs comfortably faster than real-time on a CPU with no GPU at all — a good free fallback if ElevenLabs quota runs out or you want a zero-marginal-cost mode for testing. Quality is lower than ElevenLabs but acceptable for draft/test renders. Don't build this in Phase 1; just leave the seam for it.
| Stock asset search | **Pexels API primary → Pixabay API fallback** | Both free, both viable for a personal project. Pexels: 200 requests/hour and 20,000/month by default, no attribution legally required (though crediting is good practice and can unlock higher limits on request). Pixabay: 100 requests/60 seconds, CC0-licensed (no attribution needed at all), but explicitly *requires you to cache responses for 24h and not hotlink* — you must download assets to your own server, which the spec already does. Build a thin abstraction (`AssetProvider` interface) with Pexels as `providers[0]` and Pixabay as `providers[1]`, falling through on empty results or 429s. Cache search results locally (by normalized keyword) for at least 24h to respect both providers' terms and to avoid burning quota on repeated keyword searches across videos.
| Timeline/rendering engine | **Raw FFmpeg via `subprocess` with a programmatically-built `filter_complex` graph** — NOT MoviePy for the render path | This is the single most important CPU-performance decision in the whole project. MoviePy is a thin Python wrapper that, for multi-clip projects, ends up invoking ffmpeg multiple times and doing frame-level work back through Python/PIL for some operations — on a CPU-only box this is dramatically slower than building one single ffmpeg filter graph (scale/crop/trim/zoompan/xfade/concat/drawtext/ass-burn) and running it as **one ffmpeg process, one encode pass**. You can use `ffmpeg-python` as a thin builder/syntax-sugar layer if it speeds up development (it just constructs the same CLI args), but the execution path must be native ffmpeg, not MoviePy's `VideoFileClip`/`CompositeVideoClip` rendering pipeline. Use MoviePy only if at all, for local prototyping/debugging individual clips — never in the production render path.
| Captions | **ASS subtitle file with `\k`/`\kf` karaoke tags**, generated from faster-whisper/WhisperX word timestamps, burned in via ffmpeg's native `ass` filter (`-vf "ass=captions.ass"`, requires ffmpeg built with `--enable-libass`, which virtually every modern Linux ffmpeg package includes) | This is how you get TikTok-style "current word highlighted" captions without expensive per-frame image compositing. libass renders the karaoke sweep natively inside the same ffmpeg filter graph as everything else — no extra render pass, no PNG-per-word overlay hack. Build the ASS file with words grouped 4–6 per "Dialogue" line (more than that and the highlight sweep reads as a strobe), `\kf` (smooth fill) rather than `\k` (instant cut) for the nicer animated look, and a 50–100ms gap between word highlight transitions so it doesn't feel jittery on a phone screen.
| Effects (zoom/Ken Burns/pan/fade/etc.) | Native ffmpeg filters: `zoompan`, `fade`, `xfade`, `eq` (color correction), `boxblur` | All standard, all CPU-cheap relative to encoding itself, all composable into the same single filter graph as everything else above.
| Audio mixing | ffmpeg `sidechaincompress` (ducking), `loudnorm` (normalization), `afade`, `amix` — or `pydub` for the simpler non-realtime mixing logic if you want a higher-level API | `sidechaincompress` is the correct, standard way to auto- duck background music under narration without manual keyframing.
| Video encode | `libx264`, **`-preset veryfast` as the default**, `-threads 0` (let ffmpeg use all cores), `-crf 23` | Benchmark `veryfast` vs `faster`/`fast` on your actual VM once it's provisioned — preset speed/quality/file-size tradeoffs are CPU-model-dependent enough that you should measure rather than assume. `veryfast` is the right starting point for short-form social content where turnaround time matters more than squeezing out the last few % of compression efficiency. Avoid `ultrafast` — file size bloats enough on talking-head/B-roll content that it's rarely worth the marginal speed gain.
| Storage | Local disk (`output/`), behind a thin `StorageBackend` interface | Build the interface now (`save(path) -> url`, `get(job_id) -> path`) so swapping in S3/Cloudinary later (per the spec's future-features list) doesn't touch calling code.

---

## 2. Repo layout (matches the spec's folder structure, filled in)

```
video-engine/
  app.py                     # FastAPI app entrypoint
  config.py                  # pydantic-settings: env vars, paths, API keys
  worker.py                  # RQ worker entrypoint (run as separate process)
  routers/
    generate.py               # POST /generate-video
    status.py                 # GET /status/{job_id}
    download.py                # GET /download/{job_id}
    health.py                  # GET /health
  services/
    pipeline.py                # orchestrates the full job: calls each module in order
    tts/
      base.py                  # TTSProvider interface
      elevenlabs_provider.py
      piper_provider.py         # added in Phase 12 (future)
    alignment/
      whisper_align.py          # faster-whisper + wav2vec2 forced alignment, no diarization
    assets/
      base.py                  # AssetProvider interface
      pexels_provider.py
      pixabay_provider.py
      cache.py                  # local search-result + asset cache
    timeline/
      filtergraph_builder.py    # builds the ffmpeg filter_complex string from the scene list
      scene_resolver.py          # maps each scene's assets/effects/overlays into filter nodes
    captions/
      ass_builder.py             # word timestamps -> karaoke .ass file
    effects/
      ffmpeg_filters.py          # zoompan/fade/xfade/eq filter string helpers
    music/
      mixer.py                   # sidechaincompress/loudnorm/afade graph builder
    renderer/
      ffmpeg_runner.py            # subprocess wrapper, single-pass encode, logging, timeout handling
    storage/
      base.py
      local_storage.py
  models/
    schemas.py                  # pydantic models matching the n8n JSON payload exactly
    job.py                      # internal job state model
  utils/
    logging.py
    cleanup.py                  # temp file sweeper
  output/
  temp/
  fonts/
  logos/
  music/
  requirements.txt
  Dockerfile
  docker-compose.yml
```

---

## 3. Phased build plan

### Phase 0 — VM and environment setup
1. Provision the CPU VM (see spec above — 4 vCPU/8GB floor).
2. Install system packages: `ffmpeg` (verify `ffmpeg -version` shows `--enable-libass`, `--enable-libx264`), `redis-server`, `python3.11`, `build-essential`, `libsndfile1` (needed by some audio libs).
3. Create a Python 3.11 virtualenv. Pin dependencies in `requirements.txt`: `fastapi`, `uvicorn[standard]`, `gunicorn`, `rq`, `redis`, `pydantic`, `pydantic-settings`, `faster-whisper`, `whisperx` (or just the alignment piece if you vendor it directly to avoid pulling in pyannote), `requests`, `pydub`, `Pillow`, `opencv-python-headless`, `ffmpeg-python` (optional, for graph building), `python-multipart`.
4. Scaffold the folder structure above. Get `GET /health` returning 200 before writing anything else.
5. Set up `.env` + `config.py` for: `ELEVENLABS_API_KEY`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `REDIS_URL`, `OUTPUT_DIR`, `TEMP_DIR`, `FONTS_DIR`.

**Checkpoint:** `uvicorn app:app` runs, `/health` returns 200, Redis is reachable from Python.

### Phase 1 — API skeleton and job model
1. Write `models/schemas.py` as exact pydantic models for the incoming JSON (project_id, title, script, duration, voice, background_music, captions, resolution, fps, scenes[] with start/end/narration/search_keywords/overlay/transition). Also support the richer `asset_request` (primary/fallback/avoid) and `overlays`/`effects` shape described in the spec's "improvement" section — make these **optional fields** so the current simple n8n payload still validates, but the backend prefers the richer shape when present.
2. `POST /generate-video`: validate payload, create a job record (job_id = project_id or a new uuid), enqueue an RQ job calling `pipeline.run(job_id, payload)`, return `{"job_id": ..., "status": "queued"}` immediately — never block the HTTP request on the actual render.
3. Job state storage: a Redis hash per job_id (`status`, `created_at`, `error`, `output_path`) is sufficient — don't reach for a full database for a single-operator tool. Statuses: `queued -> processing -> completed | failed`.
4. `GET /status/{job_id}` reads that hash. `GET /download/{job_id}` streams the file from `output/` if `status == completed`. `GET /health` checks Redis connectivity too.
5. Add a simple API key check (shared secret header) on `/generate-video` — this endpoint will be hit by n8n over the network, and an unauthenticated POST endpoint that triggers expensive CPU work is an easy DoS target even for a personal project.

**Checkpoint:** posting the sample payload from the spec returns a job_id; `worker.py` picks it up (even if `pipeline.run` is a stub that just sleeps and marks completed); status endpoint reflects the transition.

### Phase 2 — TTS module
1. `TTSProvider` interface: `synthesize(text: str, voice_id: str) -> Path` returning a wav file path.
2. `ElevenLabsProvider`: implement against the TTS endpoint, default to `eleven_flash_v2_5` model id, fall back to `eleven_multilingual_v2` if you explicitly want higher fidelity for a given voice. Handle 429s with exponential backoff (paid tiers still rate-limit). Output as a clean 44.1kHz/48kHz wav, not mp3, so downstream alignment and mixing don't lose quality to a lossy round-trip.
3. Synthesize per-scene narration separately if scenes have independent narration text (lets you align timestamps per-scene more reliably) **or** synthesize the full script once and rely on alignment to map words back to scenes — pick whichever matches how n8n's `scene.narration` fields are actually populated; if every scene has its own `narration`, synthesize per-scene and concatenate, which also sidesteps any alignment drift over the full ~40s clip.
4. Cache TTS output by a hash of (text, voice_id) during development so you're not re-spending ElevenLabs credits on every test run.

**Checkpoint:** given the sample payload, you get a `voice.wav` (or per-scene wavs) on disk, audibly correct.

### Phase 3 — Speech alignment module
1. Load a faster-whisper model once at worker startup (not per-job — model load time is the dominant cost for short clips otherwise), INT8 quantized, `small.en` to start.
2. Run transcription on the synthesized voice audio (you already know the text — you can pass it as an `initial_prompt` to faster-whisper to bias decoding toward your exact script, improving accuracy on brand names/jargon).
3. Run wav2vec2 forced alignment (the WhisperX alignment step, used standalone — skip WhisperX's diarization entirely) to get word-level start/end timestamps.
4. Output the word-timestamp JSON format from the spec (`[{word, start, end}, ...]`) plus a sentence-level rollup for any future use.

**Checkpoint:** word timestamps for the sample narration are sane (spot-check 5–10 words against the audio manually).

### Phase 4 — Asset downloader module
1. `AssetProvider` interface: `search(keywords: list[str], orientation="portrait") -> list[AssetResult]`.
2. `PexelsProvider` and `PixabayProvider` implementations. Try Pexels first; on empty results, non-2xx, or 429, fall through to Pixabay.
3. Build the search query from `search_keywords` (current schema) or `asset_request.primary` (richer schema), with `asset_request.fallback` as the retry query if the primary search returns nothing usable, and `asset_request.avoid` terms used to filter/score down obviously-wrong results client-side (Pexels/Pixabay don't support negative-keyword search server-side, so this is post-filtering on tags/titles).
4. Prefer portrait/vertical source video when available (cuts down on crop artifacts at render time); otherwise grab landscape and plan to crop in the timeline stage.
5. Download to `assets/{job_id}/scene{N}.mp4|.jpg`. Cache search results (not just downloaded files) for 24h keyed by normalized query string, per both providers' usage terms.
6. Always have a local fallback pool (a small curated folder of generic B-roll/solid-color clips in `assets/fallback/`) for the case where both providers return nothing relevant — better to render something than to fail the whole job over one bad scene.

**Checkpoint:** given the sample payload's keywords, you get real downloaded mp4/image files appropriate to "OpenAI," "AI coding," "developer," "coding."

### Phase 5 — Timeline + effects + captions (the filter-graph builder)
This is the core engine. Build it as one cohesive step, not three separate render passes.
1. `filtergraph_builder.py`: for each scene, build a filter chain that scales/crops the source asset to fill 1080x1920 (use `scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920`), trims/loops it to the scene's duration, and applies the scene's effect (zoompan for Ken Burns/zoom, fade in/out at scene boundaries).
2. Concatenate scenes with `xfade` transitions where specified (e.g. `transition: "zoom"` → map to a zoompan-driven custom transition, or to the nearest matching `xfade` transition type — `xfade` supports `fade`, `wipeleft`, `slideup`, `zoomin`, etc. natively).
3. Overlay logos/text per scene using `overlay` and `drawtext` filter nodes, positioned/timed per scene's start/end.
4. Burn in the karaoke ASS captions file (from Phase 6 below) as the final video filter in the same graph.
5. The end result is **one ffmpeg command** with a single, large `filter_complex` doing: per-scene scale/crop/trim/effect → concat/xfade → overlays → captions → final scale/fps normalization to 1080x1920@60fps. One process, one encode.

**Checkpoint:** running the built command against Phase 2–4's outputs produces a single mp4 with correct scene timing, visible (even if rough) transitions and overlays, no captions yet.

### Phase 6 — Caption generation
1. `ass_builder.py`: take the word-timestamp JSON from Phase 3, group into lines of 4–6 words, emit a valid `.ass` file with a karaoke-styled `[V4+ Styles]` block (configure font, size, primary/secondary/outline/back colors — load fonts from `fonts/`) and `\kf` timing tags computed from each word's duration in centiseconds.
2. Style notes for legibility on a phone screen: outline + semi-transparent box background (`BorderStyle=3`, `BackColour` with alpha) rather than bare text, bold weight, font size scaled to 1080px width, bottom-third safe-zone positioning that avoids platform UI overlap (leave margin for Instagram's own UI chrome).
3. Feed the resulting `.ass` path into the filter-graph builder from Phase 5 as the final `ass=` filter node — don't burn captions in a separate ffmpeg pass.

**Checkpoint:** rendered output shows word-by-word highlighted captions in sync with narration.

### Phase 7 — Audio mixing
1. Build the audio side of the same filter graph (or a parallel `-filter_complex` audio chain merged into the same ffmpeg invocation): voice track + background music (looped/trimmed to total duration) → `sidechaincompress` keyed off the voice track to duck music under narration → `loudnorm` for consistent loudness → optional sfx mixed in at cue points → `amix`/final `afade` in/out.
2. Mux the resulting audio into the same single ffmpeg render call as the video filter graph — you want one process producing the final mp4, not a separate audio-mix-then-mux pass if you can avoid it (less disk I/O, less re-encode overhead).

**Checkpoint:** final mp4 has properly ducked, normalized audio — music audibly drops under narration and comes back up between lines.

### Phase 8 — Renderer wrapper and output
1. `ffmpeg_runner.py`: wraps the full assembled command in `subprocess.run`, with explicit `-threads 0`, chosen preset/CRF, timeout (kill runaway jobs — set something generous but bounded, e.g. 10x the target video duration), captures stderr for debugging, raises a typed exception on non-zero exit that the pipeline can catch and mark the job `failed` with a useful error message rather than a silent hang.
2. Benchmark `-preset veryfast` vs `fast`/`faster` on the actual VM with a real ~40s 1080x1920@60fps render and record the numbers (render time, output file size, eyeballed quality) — pick the default based on that, not on documentation alone, since x264 preset behavior is sensitive to the specific CPU.
3. Output to `output/{job_id}.mp4`.

**Checkpoint:** end-to-end pipeline run on the sample payload produces a finished mp4 in `output/`, and you have a measured render-time number for your VM (this number should inform whether you need to upgrade the VM or adjust queue concurrency).

### Phase 9 — Storage and final response
1. `StorageBackend.local`: just confirms the file exists at `output/{job_id}.mp4` and returns a URL built from your configured base URL.
2. `GET /download/{job_id}` serves it (FastAPI `FileResponse` or `StreamingResponse`).
3. Update the job's Redis hash to `completed` with `video_url` and `duration`, matching the spec's response schema exactly (`job_id`, `status`, `video_url`, `duration`) — this is what n8n will read back.

**Checkpoint:** the full `/generate-video → poll /status → GET /download` loop works against the sample payload, end to end, through n8n if you want to test the real integration.

### Phase 10 — Dockerization and process management
1. Multi-stage `Dockerfile`: build stage installs build deps, runtime stage installs only `ffmpeg` + Python runtime deps to keep the image lean. Confirm the base ffmpeg package includes `--enable-libass` and `--enable-libx264` (most Debian/Ubuntu ffmpeg packages do; verify, don't assume, if you're on a minimal base image).
2. `docker-compose.yml`: three services — `redis`, `app` (uvicorn/gunicorn), `worker` (RQ worker, `rq worker` pointed at the same Redis). Mount `output/`, `temp/`, `assets/`, `fonts/`, `music/`, `logos/` as volumes so they persist across container restarts.
3. If not using Docker: a systemd unit for the FastAPI app and a separate systemd unit for the RQ worker, both with `Restart=on-failure`.
4. Set RQ worker concurrency to match available cores minus headroom for the FastAPI process itself — for a 4-core VM, one worker process is probably right; for 8 cores, you might run two workers, but test that two concurrent ffmpeg renders don't slow each other down so much that net throughput is worse than one-at-a-time (CPU contention on x264 encoding is real).

**Checkpoint:** `docker compose up` brings up the full stack; a job submitted to the containerized API completes successfully.

### Phase 11 — Reliability and cleanup
1. `utils/cleanup.py`: a scheduled sweep (cron, or an RQ scheduled job) that deletes `temp/{job_id}/` and `assets/{job_id}/` directories for jobs older than N hours/days, and optionally rotates `output/` (e.g. delete videos older than 30 days, or after you've confirmed they've been posted) so disk doesn't silently fill up on a long-running personal VM.
2. Structured logging (`utils/logging.py`) — at minimum, log job_id, phase, duration-per-phase, and any retries, so a failed job is debuggable from logs alone without re-running it.
3. Per-module retry/error handling: TTS and asset-search calls should retry on transient network errors; if asset search comes back empty after retries and fallback provider, fall back to the local `assets/fallback/` pool rather than failing the whole job.
4. Add basic request logging/rate limiting on `/generate-video` even behind the API key, just as a sanity backstop.

**Checkpoint:** killing the worker mid-render and restarting it doesn't leave the system in a broken state; old temp files actually get cleaned up; a deliberately-broken scene (bad keyword, no asset results) degrades gracefully instead of crashing the whole job.

### Phase 12 — Future features (design now, build later — per the original spec)
Implement these only after Phases 0–11 are solid and you've actually used the pipeline for real videos for a while:
- **Piper TTS provider** as a free local fallback behind the `TTSProvider` interface already built in Phase 2.
- **Multiple aspect ratios** (16:9, 1:1) — mostly a matter of parameterizing the `scale`/`crop` target dimensions in the filter-graph builder instead of hardcoding 1080x1920.
- **Queue-based scaling** beyond one VM — only relevant if you start producing video for other accounts/clients at volume; RQ scales to multiple Redis-connected worker hosts with no architecture change, so this is a "spin up more workers" problem, not a rewrite.
- **Cloud storage** (S3/Cloudinary) — swap in a new `StorageBackend` implementation; calling code shouldn't need to change if the interface from Phase 9 was built cleanly.
- **Thumbnail generation** — a single `ffmpeg -ss {t} -vframes 1` extraction from the finished render; cheap to add.
- **AI-generated B-roll/images** as a fallback when stock search genuinely comes up empty — a new `AssetProvider` implementation, gated behind cost/latency tradeoffs you should evaluate once you see how often stock search actually fails on real scripts.

---

## 4. Things worth testing explicitly before you trust this in production

- Render time for a realistic ~40–60s video on your actual VM, under load (i.e. while another job might also be queued) — this number tells you your real daily throughput ceiling.
- Caption sync drift on a full 60s video — forced alignment can drift slightly on longer clips; spot-check the last few captions against the audio, not just the first few.
- Behavior when a scene's stock search returns zero usable results from both Pexels and Pixabay — confirm it falls back to the local pool instead of crashing the job.
- ElevenLabs rate-limit/429 handling under your actual daily posting cadence, so a transient API hiccup doesn't fail a whole job.
- ffmpeg process timeout behavior — deliberately feed it a malformed filter graph or an asset file ffmpeg can't read, and confirm the job fails cleanly with a readable error in `/status/{job_id}` rather than hanging the worker.