"""
Piano transcription backend.

Accepts an uploaded audio or video file, or a TikTok/YouTube link. Video
files (and link downloads) have their audio track extracted first (via
ffmpeg / yt-dlp), then either way the audio is run through Basic Pitch
(open-source audio-to-MIDI model), returning the detected notes as JSON
so the frontend can render them as falling notes.

Deploy notes:
- Requires Python 3.10 or 3.11 (Basic Pitch's pinned numpy range does not
  build cleanly on 3.12 yet).
- Requires ffmpeg on the server for video uploads and link downloads.
  Deployed via the Dockerfile in this folder (python:3.11-slim + apt-get
  install ffmpeg), rather than relying on a buildpack to infer it —
  Nixpacks' auto-detected start command and multi-stage build silently
  dropped ffmpeg from the final runtime image despite aptPkgs listing
  it, so plain Nixpacks config wasn't reliable here.
- TikTok/YouTube fetching uses yt-dlp, which scrapes each site directly
  (no official API for TikTok; YouTube's extractor is more mature/
  reliable but still unofficial). Sites change often enough that this
  can break and need a `pip install -U yt-dlp` bump; treat it as
  best-effort, and TikTok specifically can get blocked by anti-bot
  measures depending on the server's network — see the note in
  transcribe_url().
- YouTube extraction also requires a JS runtime (yt-dlp uses it to
  decode video URLs) — the Dockerfile installs deno for this. Without
  it, YouTube links fail with "This video is not available" even
  though the link is fine.
- Install deps with: pip install -r requirements.txt
- Run locally with: uvicorn main:app --reload
"""

import asyncio
import os
import re
import subprocess
import tempfile
import uuid
from typing import Dict, List

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Loaded once and reused rather than per-request — predict() accepts either
# a model path (which it loads fresh from disk every call) or an
# already-instantiated Model to reuse. Reloading the model on every single
# transcription was spiking memory on each request instead of paying that
# cost once, which is what was tripping Railway's memory limit.
#
# Lazy rather than loaded at import time: loading it eagerly would mean the
# server has to successfully load the model just to start up and answer
# /health, so if the memory ceiling were ever tight, every deploy would
# crash before serving a single request instead of just the first real one.
from basic_pitch.inference import Model
from basic_pitch import ICASSP_2022_MODEL_PATH

_basic_pitch_model = None


def get_basic_pitch_model():
    global _basic_pitch_model
    if _basic_pitch_model is None:
        _basic_pitch_model = Model(ICASSP_2022_MODEL_PATH)
    return _basic_pitch_model


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

# Extracted audio for TikTok/YouTube links is kept around briefly so the
# frontend can fetch it back for playback (see /audio/{filename}), then
# swept up.
AUDIO_ID_RE = re.compile(r"^[0-9a-f-]{36}\.wav$")
AUDIO_RETENTION_SECONDS = 600

usage_counts: Dict[str, int] = {}
FREE_USES_PER_MONTH = 3
# Off while it's just us testing solo — no real users yet, so there's no
# one to gate. Flip back on (alongside real accounts/a Pro tier) before
# this goes out to actual users.
USAGE_LIMIT_ENABLED = False


class NoteEvent(BaseModel):
    pitch: int
    start_time: float
    duration: float
    velocity: int


class TranscriptionResult(BaseModel):
    notes: List[NoteEvent]
    duration_seconds: float
    uses_remaining: int | None
    is_video: bool
    audio_url: str | None = None
    tempo_bpm: float = 120.0


class TranscribeURLPayload(BaseModel):
    url: str


def get_user_id(cookie_id: str | None) -> str:
    return cookie_id or "anonymous"


def check_and_consume_usage(uid: str) -> None:
    if not USAGE_LIMIT_ENABLED:
        usage_counts[uid] = usage_counts.get(uid, 0) + 1
        return
    used = usage_counts.get(uid, 0)
    if used >= FREE_USES_PER_MONTH:
        raise HTTPException(402, "Free monthly transcriptions used up. Upgrade to keep going.")
    usage_counts[uid] = used + 1


def uses_remaining(uid: str) -> int | None:
    if not USAGE_LIMIT_ENABLED:
        return None
    return max(0, FREE_USES_PER_MONTH - usage_counts.get(uid, 0))


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
    check_and_consume_usage(uid)

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

        notes, duration, tempo_bpm = run_transcription(audio_path)
    finally:
        for p in (tmp_input, extracted_path):
            if p and os.path.exists(p):
                os.remove(p)

    return TranscriptionResult(
        notes=notes,
        duration_seconds=duration,
        uses_remaining=uses_remaining(uid),
        is_video=is_video,
        tempo_bpm=tempo_bpm,
    )


SUPPORTED_LINK_DOMAINS = ["tiktok.com", "youtube.com", "youtu.be"]
# TikTok has been observed blocking requests from cloud/datacenter IPs
# (including Railway's) with "Your IP address is blocked" — that's
# TikTok's own anti-bot system, not fixable from our side short of
# routing through a residential proxy. YouTube's extractor is generally
# more reliable against that kind of blocking.


@app.post("/transcribe-url", response_model=TranscriptionResult)
async def transcribe_url(payload: TranscribeURLPayload, request: Request, user_id: str | None = None):
    url = payload.url.strip()
    if not any(domain in url for domain in SUPPORTED_LINK_DOMAINS):
        raise HTTPException(400, "Only TikTok and YouTube links are supported right now.")

    uid = get_user_id(user_id)
    check_and_consume_usage(uid)

    audio_id = uuid.uuid4()
    audio_path = os.path.join(tempfile.gettempdir(), f"{audio_id}.wav")
    output_template = os.path.join(tempfile.gettempdir(), f"{audio_id}.%(ext)s")

    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "-x", "--audio-format", "wav",
                "--max-filesize", f"{MAX_FILE_SIZE_MB}M",
                "-o", output_template,
                url,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Timed out fetching that video.")

    if result.returncode != 0 or not os.path.exists(audio_path):
        raise HTTPException(400, f"Couldn't fetch that video: {result.stderr[-500:]}")

    try:
        notes, duration, tempo_bpm = run_transcription(audio_path)
    except Exception:
        os.remove(audio_path)
        raise

    asyncio.create_task(_delete_after_delay(audio_path))

    audio_url = str(request.base_url).rstrip("/") + f"/audio/{audio_id}.wav"
    return TranscriptionResult(
        notes=notes,
        duration_seconds=duration,
        uses_remaining=uses_remaining(uid),
        is_video=True,
        audio_url=audio_url,
        tempo_bpm=tempo_bpm,
    )


@app.get("/audio/{filename}")
def get_audio(filename: str):
    """Serves audio extracted from a TikTok/YouTube link back to the
    frontend for playback. Only exists briefly — see AUDIO_RETENTION_SECONDS."""
    if not AUDIO_ID_RE.match(filename):
        raise HTTPException(400, "Invalid filename")
    path = os.path.join(tempfile.gettempdir(), filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Audio not found or expired")
    return FileResponse(path, media_type="audio/wav")


async def _delete_after_delay(path: str, delay_seconds: int = AUDIO_RETENTION_SECONDS):
    await asyncio.sleep(delay_seconds)
    if os.path.exists(path):
        os.remove(path)


def extract_audio_from_video(video_path: str, output_wav_path: str):
    """
    Pulls the audio track out of a video file using ffmpeg. Requires
    ffmpeg to be installed on the server (see Dockerfile).
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


def denoise_audio(y, sr: int, audio_path: str) -> str:
    """
    Runs a spectral-gating noise reduction pass over the audio and writes
    the result next to the original as "<id>.denoised.wav". This cuts down
    on the transcriber picking up room noise, hiss, or talking instead of
    just the piano — it's not source separation (it won't remove another
    instrument playing at the same time as the piano), just general
    background noise suppression.

    Takes the already-loaded signal rather than loading the file itself —
    run_transcription() needs the same signal again for tempo detection, and
    a several-minute recording decoded into memory twice was a real chunk of
    the peak memory a request used.
    """
    import noisereduce as nr
    import soundfile as sf

    # noisereduce's default "stationary" mode treats anything that doesn't
    # fluctuate as noise — which includes a sustained, held piano note, and
    # was gating those out entirely in testing (turning a clean recording
    # into silence). stationary=False adapts over time instead of assuming
    # one fixed noise profile, and prop_decrease=0.75 (vs. the 1.0 default)
    # applies the reduction gently enough to leave clean recordings intact
    # while still meaningfully cutting down noise-driven fragmentation.
    denoised = nr.reduce_noise(y=y, sr=sr, stationary=False, prop_decrease=0.75)

    denoised_path = os.path.splitext(audio_path)[0] + ".denoised.wav"
    sf.write(denoised_path, denoised, sr)
    return denoised_path


def run_transcription(audio_path: str):
    """
    Runs Basic Pitch on the given audio file and returns a list of
    NoteEvent-shaped dicts plus the audio duration in seconds.

    Thresholds are tuned slightly stricter than Basic Pitch's defaults
    to cut down on stray/ghost notes from pedal resonance or noise,
    at a small cost to catching very quiet notes. Worth revisiting
    once we've tested against real recordings.

    minimum_note_length was 90ms; testing against a fast 12-note-in-1.4s
    run showed it dropping 8 of 12 notes (Basic Pitch's model resolves
    the pitch fine, but a note shorter than the floor gets discarded
    entirely). 50ms recovered 11 of 12 with zero change on clean/noisy
    sustained-tone test cases — fast, dense passages need the shorter
    floor, and nothing else seemed to regress from lowering it.
    """
    from basic_pitch.inference import predict
    import librosa

    y, sr = librosa.load(audio_path, sr=None, mono=True)
    denoised_path = denoise_audio(y, sr, audio_path)
    try:
        model_output, midi_data, note_events = predict(
            denoised_path,
            get_basic_pitch_model(),
            onset_threshold=0.6,        # higher = fewer false-positive note starts
            frame_threshold=0.35,       # higher = less bleed/smearing between notes
            minimum_note_length=50,     # ms; drops very short spurious blips
            minimum_frequency=27.5,     # A0, bottom of an 88-key piano
            maximum_frequency=4186.0,   # C8, top of an 88-key piano
        )
    finally:
        os.remove(denoised_path)

    notes = [
        NoteEvent(
            pitch=int(pitch),
            start_time=float(start),
            duration=float(end - start),
            velocity=int(velocity * 127) if velocity <= 1 else int(velocity),
        )
        for (start, end, pitch, velocity, _pitch_bend) in note_events
    ]

    duration = len(y) / sr

    # Best-effort tempo estimate, used for MIDI export playback tempo. Beat
    # tracking is itself an estimate — it can drift on rubato/expressive
    # playing — so treat it as approximate, not a precise reading.
    try:
        tempo_estimate, _ = librosa.beat.beat_track(y=y, sr=sr)
        tempo_bpm = round(float(tempo_estimate), 1) if tempo_estimate else 120.0
    except Exception:
        tempo_bpm = 120.0

    return notes, duration, tempo_bpm
