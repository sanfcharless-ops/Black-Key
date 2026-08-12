"""
Piano transcription backend.

Accepts an uploaded audio file, runs it through Basic Pitch (open-source
audio-to-MIDI model), and returns the detected notes as JSON so the
frontend can render them as falling notes.

Deploy notes:
- Requires Python 3.10 or 3.11 (Basic Pitch's pinned numpy range does not
  build cleanly on 3.12 yet). On Railway/Render, set this via a
  runtime.txt file containing: python-3.11.9
- Install deps with: pip install -r requirements.txt
- Run locally with: uvicorn main:app --reload
"""

import os
import tempfile
import uuid
from typing import Dict, List

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Piano Transcription API")

# In production, replace "*" with your actual frontend domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
MAX_FILE_SIZE_MB = 25

# --- Simple in-memory usage tracking (cookie-based) -------------------
# For a real launch, swap this dict for a small database (SQLite/Postgres)
# so counts survive server restarts. This is enough to prove the flow.
usage_counts: Dict[str, int] = {}
FREE_USES_PER_MONTH = 3


class NoteEvent(BaseModel):
    pitch: int          # MIDI note number, 21-108 for piano
    start_time: float    # seconds
    duration: float       # seconds
    velocity: int         # loudness, 0-127


class TranscriptionResult(BaseModel):
    notes: List[NoteEvent]
    duration_seconds: float
    uses_remaining: int


def get_user_id(cookie_id: str | None) -> str:
    return cookie_id or "anonymous"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/transcribe", response_model=TranscriptionResult)
async def transcribe(file: UploadFile = File(...), user_id: str | None = None):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}")

    uid = get_user_id(user_id)
    used = usage_counts.get(uid, 0)
    if used >= FREE_USES_PER_MONTH:
        raise HTTPException(402, "Free monthly transcriptions used up. Upgrade to keep going.")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"File too large. Max size is {MAX_FILE_SIZE_MB}MB.")

    tmp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}{ext}")
    with open(tmp_path, "wb") as f:
        f.write(contents)

    try:
        notes, duration = run_transcription(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    usage_counts[uid] = used + 1

    return TranscriptionResult(
        notes=notes,
        duration_seconds=duration,
        uses_remaining=max(0, FREE_USES_PER_MONTH - usage_counts[uid]),
    )


def run_transcription(audio_path: str):
    """
    Runs Basic Pitch on the given audio file and returns a list of
    NoteEvent-shaped dicts plus the audio duration in seconds.
    """
    from basic_pitch.inference import predict
    from basic_pitch import ICASSP_2022_MODEL_PATH
    import librosa

    model_output, midi_data, note_events = predict(
        audio_path,
        ICASSP_2022_MODEL_PATH,
    )

    notes = [
        NoteEvent(
            pitch=int(pitch),
            start_time=float(start),
            duration=float(end - start),
            velocity=int(velocity * 127) if velocity <= 1 else int(velocity),
        )
        for (start, end, pitch, velocity, _pitch_bend) in note_events
    ]

    duration = librosa.get_duration(path=audio_path)
    return notes, duration
