# AI Music Video Studio (isolated MVP)

Standalone FastAPI web application in `music-video-studio/`. No AutoMake routes, packages or main-branch files are changed.

## Features
- Responsive image/song uploader, consent check, queued job status, downloadable 9:16 H.264 MP4.
- CPU **preview** renders whole-song portrait-motion video with original audio (no lip-sync).
- **Lip-sync** sends photo + audio to a configured GPU-backed Hugging Face Gradio Space and muxes the original song back into a vertical MP4. It explicitly fails without provider config: no fake lip-sync.
- Duration limited to 10 minutes. Uploaded content is stored on local disk; this is a prototype, **not production multi-user storage**.

## Run locally
```sh
cd music-video-studio
docker build -f Dockerfile -t music-video-studio ..
docker run -p 10000:10000 -e PORT=10000 music-video-studio
```
Open http://localhost:10000.

## Real lip-sync GPU connection
Use a *working, authorized* MuseTalk 1.5 Gradio Space. First inspect its "Use via API" tab and verify the endpoint signature takes image then audio and returns an MP4:
```
HF_SPACE_ID=your-org/your-musetalk-space
HF_API_NAME=/your_verified_endpoint
HF_TOKEN=optional_token_for_private_space
```
The Gradio adapter now matches the upstream MuseTalk 1.5 parameter order and sends sequential audio clips (12 seconds default). The exact endpoint and GPU availability remain **unverified**. This is an integration point, not proof that the chosen Space can produce a 4-minute song. Some providers impose execution limits; production must chunk long audio and stitch segments. Do not send private audio to unknown third-party Spaces.

## Deploy to Render as separate service
- Source: jolleyleads/ai-ops-command-center, branch `music-video-studio-mvp`
- Runtime: Docker
- Dockerfile path: `music-video-studio/Dockerfile`
- Docker build context: `.`
- Health: `/health`
- Persistent job processing needs an external queue and persistent object storage. Render ephemeral storage and in-process threads are suitable only for a small proof of concept.
- Do not put GPU model weights on the Render CPU web service. Use a dedicated GPU host or a configured Hugging Face Space.

## Safety
The user confirms ownership or consent for portrait/voice/music. Add authentication, per-user isolation, retention enforcement, quotas, rate limiting, malware scanning and billing before public launch.

## Provider integration note (2026-11-04)
Upstream MuseTalk 1.5 Gradio `generate` expects `(audio, reference_image, bbox_shift, extra_margin, parsing_mode, left_cheek_width, right_cheek_width)`. The adapter uses `HF_API_NAME=/generate` and segments tracks to 12-second WAV requests, concatenates generated clips and muxes original audio. This was checked against upstream source, not by running GPU inference. A public ZeroGPU Space has quotas and is **not** an assured production backend. Set HF_SPACE_ID only for a Space you own or whose operator authorizes use, after confirming privacy rules. Users should not upload sensitive content to unknown public Spaces.

## Deployment gating
Lip-sync option is disabled in the UI when no GPU Space is configured; its API returns 503. This is deliberate to avoid pretending previews contain real lip-sync. Current threading, memory-only job state and ephemeral uploads are not suitable for a multi-user commercial deployment.
