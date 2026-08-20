# keydrops (v1)

Two pieces:

- **backend/**: a Python API that takes an uploaded audio/video file (or a TikTok/YouTube link) and returns the detected piano notes, using Basic Pitch (open-source, MIT-licensed, free to run).
- **frontend/**: a single HTML page that uploads a file (or a TikTok/YouTube link), calls the backend, and renders the falling-notes player.

###1. Start of the project

### 2. Frontend: deploy to Vercel or Netlify
1. Open `frontend/index.html` and change the line near the top of the script:
   ```
   const API_URL = "http://localhost:8000";
   ```
   to your real Railway URL from step 1.
2. Drag the `frontend/` folder into vercel.com or netlify.com's dashboard (both have a "drag and drop to deploy" option, no command line needed).
3. You'll get a live URL you can share with anyone.

### Try
Upload a short piano recording (30 seconds to a couple minutes is a good first test) and watch it transcribe.

## What's not built yet
- The free-use limit is turned off entirely right now (`USAGE_LIMIT_ENABLED = False` in `backend/main.py`) since it's just solo testing. It's also still tracked in memory, which resets if the server restarts. Before real users show up: turn the limit back on, and swap the in-memory counter for a small database.
- TikTok/YouTube link fetching (`/transcribe-url`) uses yt-dlp, which scrapes each site directly (no official API). TikTok can get blocked by anti-bot measures depending on the server's network. YouTube needs a JS runtime (deno, installed via the Dockerfile) to decode video URLs. Both will need occasional `yt-dlp` version bumps as the sites change. Treat it as best-effort, not guaranteed.
- No payment processing yet (Stripe is the natural choice when we get there).
- No login/signup flow yet, needed once someone hits their free limit and wants to pay.

## What to test first
Just get a real piano recording through the pipeline end to end. Everything else (pricing, accounts, polish) is easier to get right once we know the transcription itself sounds good on music you actually care about.
