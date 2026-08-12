"""
Piano transcription backend.

Accepts an uploaded audio or video file. Video files have their audio
track extracted first (via ffmpeg), then either way the audio is run
through Basic Pitch (open-source audio-to-MIDI model), returning the
detected notes as JSON so the frontend can render them as falling notes.

Deploy notes:
- Requires Python 3.10 or 3.11 (Basic Pitch's pinned numpy range does not
  build cleanly on 3.12 yet). On Railway/Render, set this via a
  runtime.txt file containing: python-3.11.9
- Requires ffmpeg on the server for video uploads. nixpacks.toml in this
  folder tells Railway to install it automatically.
- Install deps with: pip install -r requirements.txt
- Run locally with: uvicorn main:app --reload
"""

import os
import subprocess
import tempfile
import uuid
from typing import Dict, List

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Piano Transcription API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
ALLOWED_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
MAX_FILE_SIZE_MB = 60  # raised from 25MB since video files run bigger

usage_counts: Dict[str, int] = {}
FREE_USES_PER_MONTH = 3


class NoteEvent(BaseModel):
    pitch: int
    start_time: float
    duration: float
    velocity: int


class TranscriptionResult(BaseModel):
    notes: List[NoteEvent]
    duration_seconds: float
    uses_remaining: int
    is_video: bool


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
    is_video = ext in VIDEO_EXTENSIONS

    uid = get_user_id(user_id)
    used = usage_counts.get(uid, 0)
    if used >= FREE_USES_PER_MONTH:
        raise HTTPException(402, "Free monthly transcriptions used up. Upgrade to keep going.")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"File too large. Max size is {MAX_FILE_SIZE_MB}MB.")

    tmp_input = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}{ext}")
    with open(tmp_input, "wb") as f:
        f.write(contents)

    audio_path = tmp_input
    extracted_path = None
    try:
        if is_video:
            extracted_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.wav")
            extract_audio_from_video(tmp_input, extracted_path)
            audio_path = extracted_path

        notes, duration = run_transcription(audio_path)
    finally:
        for p in (tmp_input, extracted_path):
            if p and os.path.exists(p):
                os.remove(p)

    usage_counts[uid] = used + 1

    return TranscriptionResult(
        notes=notes,
        duration_seconds=duration,
        uses_remaining=max(0, FREE_USES_PER_MONTH - usage_counts[uid]),
        is_video=is_video,
    )


def extract_audio_from_video(video_path: str, output_wav_path: str):
    """
    Pulls the audio track out of a video file using ffmpeg. Requires
    ffmpeg to be installed on the server (see nixpacks.toml).
    """
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-vn",                 # drop video stream
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "1",
            output_wav_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(500, f"Couldn't extract audio from video: {result.stderr[-500:]}")


def run_transcription(audio_path: str):
    """
    Runs Basic Pitch on the given audio file and returns a list of
    NoteEvent-shaped dicts plus the audio duration in seconds.

    Thresholds are tuned slightly stricter than Basic Pitch's defaults
    to cut down on stray/ghost notes from pedal resonance or noise,
    at a small cost to catching very quiet notes. Worth revisiting
    once we've tested against real recordings.
    """
    from basic_pitch.inference import predict
    from basic_pitch import ICASSP_2022_MODEL_PATH
    import librosa

    model_output, midi_data, note_events = predict(
        audio_path,
        ICASSP_2022_MODEL_PATH,
        onset_threshold=0.6,        # higher = fewer false-positive note starts
        frame_threshold=0.35,       # higher = less bleed/smearing between notes
        minimum_note_length=90,     # ms; drops very short spurious blips
        minimum_frequency=27.5,     # A0, bottom of an 88-key piano
        maximum_frequency=4186.0,   # C8, top of an 88-key piano
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
