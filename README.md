# keydrops (v1)

Two pieces:

- **backend/**: a Python API that takes an uploaded audio/video file (or a TikTok/YouTube link) and returns the detected piano notes, using Basic Pitch (open-source, MIT-licensed, free to run). It also reads sheet music (`/transcribe-sheet`): MusicXML and MIDI files exactly, and PDFs/photos through Audiveris, an open-source sheet music scanner installed by the Dockerfile.
- **frontend/**: a single HTML page that uploads a file (or a TikTok/YouTube link), calls the backend, and renders the falling-notes player.

### 1. Backend: free on Hugging Face Spaces
The backend runs as a free Docker Space on Hugging Face (2 CPUs, 16GB of memory, no card needed). Pushing to `main` deploys it automatically through `.github/workflows/deploy-backend.yml`.

One-time setup:
1. Make a free account at https://huggingface.co/join.
2. Create an access token with **Write** permission at https://huggingface.co/settings/tokens.
3. In this GitHub repo, go to **Settings → Secrets and variables → Actions → New repository secret**, name it `HF_TOKEN`, and paste the token.
4. Run the workflow: **Actions → Deploy backend to Hugging Face → Run workflow** (or just push to `main`). It creates the Space on the first run and prints the API URL in the run summary.
5. The first build takes a while (around 10 to 15 minutes; TensorFlow and Audiveris are big). Watch it under the Space's **Logs** tab. It's ready when `https://<username>-keydrops-api.hf.space/health` answers `{"status":"ok"}`.

Things to know about the free tier:
- The Space goes to sleep after about 48 hours with no visitors. The website pings it on page load to wake it, but the first person after a long quiet stretch waits a minute or so.
- Optional secrets (`YTDLP_COOKIES`, `YTDLP_PROXY`, see below) go in the Space's **Settings → Variables and secrets**.

### 2. Frontend: deploy to Vercel or Netlify
1. `API_URL` near the top of the script in `frontend/index.html` must match the Space's address, `https://<username>-keydrops-api.hf.space`.
2. Drag the `frontend/` folder into vercel.com or netlify.com's dashboard (both have a "drag and drop to deploy" option, no command line needed). If the site is connected to this GitHub repo instead, it redeploys by itself on every push to `main`.
3. You'll get a live URL you can share with anyone.

### Try
Upload a short piano recording (30 seconds to a couple minutes is a good first test) and watch it transcribe.

## Sheet music
- MusicXML (`.musicxml`, `.mxl`) and MIDI come through exactly as written, including which hand plays what. If a piece exists on MuseScore, export it as MusicXML for a perfect result.
- PDFs and photos are scanned by Audiveris. A clean PDF exported from notation software or a flat 300dpi scan works well. Phone photos at an angle, with shadows, or handwritten scores will have mistakes.
- Scanning is slow-ish (roughly 10 to 40 seconds a page) and Audiveris is a Java program that wants about 1GB of memory while it runs. The free Space has plenty; on a smaller host, lower `AUDIVERIS_MAX_HEAP` if it runs out of memory.
- If the Audiveris install fails during the Docker build, the build still succeeds; PDF/photo uploads just answer "scanning isn't set up" while everything else keeps working. Check the build log for "Audiveris ready".
- Playback for sheet music is a sampled grand piano generated in the browser, so seek/speed/loop/transpose all work like they do for recordings.

## When TikTok/YouTube links stop working
- yt-dlp now upgrades itself every time the server boots, so a redeploy or restart picks up fixes for site changes.
- If YouTube says "confirm you're not a bot", set a `YTDLP_COOKIES` secret on the Space to the contents of a `cookies.txt` exported from a browser logged into a throwaway Google account.
- If TikTok blocks the server's IP, set `YTDLP_PROXY` to a residential proxy URL. Uploading the video file always works regardless.

## What's not built yet
- The free-use limit is turned off entirely right now (`USAGE_LIMIT_ENABLED = False` in `backend/main.py`) since it's just solo testing. It's also still tracked in memory, which resets if the server restarts. Before real users show up: turn the limit back on, and swap the in-memory counter for a small database.
- TikTok/YouTube link fetching (`/transcribe-url`) uses yt-dlp, which scrapes each site directly (no official API). TikTok can get blocked by anti-bot measures depending on the server's network. YouTube needs a JS runtime (deno, installed via the Dockerfile) to decode video URLs. Both will need occasional `yt-dlp` version bumps as the sites change. Treat it as best-effort, not guaranteed.
- No payment processing yet (Stripe is the natural choice when we get there).
- No login/signup flow yet, needed once someone hits their free limit and wants to pay.

## What to test first
Just get a real piano recording through the pipeline end to end. Everything else (pricing, accounts, polish) is easier to get right once we know the transcription itself sounds good on music you actually care about.
