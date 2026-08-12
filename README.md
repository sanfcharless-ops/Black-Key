# Falling Piano — v1

Two pieces:

- **backend/** — a Python API that takes an uploaded audio file and returns the detected piano notes, using Basic Pitch (open-source, MIT-licensed, free to run).
- **frontend/** — a single HTML page that uploads a file, calls the backend, and renders the falling-notes player.

## Getting it live (no coding required, just following steps)

### 1. Backend — deploy to Railway
1. Create a free account at railway.app.
2. Create a new project, choose "Deploy from GitHub repo" (you'll need to push the `backend/` folder to a GitHub repo first — ask me if you want help with that part).
3. Railway will detect `requirements.txt` and `runtime.txt` automatically and install everything.
4. Once deployed, Railway gives you a public URL like `https://your-app.up.railway.app`. That's your API.
5. Test it by visiting `https://your-app.up.railway.app/health` — you should see `{"status": "ok"}`.

### 2. Frontend — deploy to Vercel or Netlify
1. Open `frontend/index.html` and change the line near the top of the script:
   ```
   const API_URL = "http://localhost:8000";
   ```
   to your real Railway URL from step 1.
2. Drag the `frontend/` folder into vercel.com or netlify.com's dashboard (both have a "drag and drop to deploy" option, no command line needed).
3. You'll get a live URL you can share with anyone.

### 3. Try it
Upload a short piano recording (30 seconds to a couple minutes is a good first test) and watch it transcribe.

## What's not built yet
- The 3-free-uses limit is tracked in memory right now, which means it resets if the server restarts. Fine for testing, not fine for launch — swap it for a small database before real users show up.
- Transpose button is a placeholder — needs an actual pitch-shift function and to be wired to a real payment/subscription check.
- No payment processing yet (Stripe is the natural choice when we get there).
- No login/signup flow yet — needed once someone hits their free limit and wants to pay.

## What to test first
Just get a real piano recording through the pipeline end to end. Everything else — pricing, accounts, polish — is easier to get right once we know the transcription itself sounds good on music you actually care about.
