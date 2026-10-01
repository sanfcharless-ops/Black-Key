---
title: keydrops API
emoji: 🎹
colorFrom: yellow
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Piano transcription backend for keydrops
---

# keydrops API

The backend for keydrops. It turns piano recordings, TikTok/YouTube links,
and sheet music into timed notes for the falling-notes player.

This folder is deployed as a Hugging Face Space (the block at the top of
this file is the Space's configuration). Every push to `main` that touches
`backend/` uploads it again via `.github/workflows/deploy-backend.yml`.

Endpoints: `GET /health`, `POST /transcribe` (audio/video file),
`POST /transcribe-url` (TikTok/YouTube link), `POST /transcribe-sheet`
(PDF, image, MusicXML, or MIDI).
