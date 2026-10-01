"""
Sheet music -> falling notes.

Three kinds of input, from most to least accurate:

- MIDI (.mid/.midi): read directly, nothing is guessed.
- MusicXML (.musicxml/.xml/.mxl), e.g. exported from MuseScore, Finale,
  Sibelius, Dorico: read directly with music21. Exact pitches, rhythms,
  ties, repeats, tempo markings, and which staff (hand) each note is on.
- Scans (PDF/PNG/JPG): run through Audiveris, an open-source optical
  music recognition (OMR) engine, which writes MusicXML that then goes
  through the same path as above. Accuracy depends a lot on the input:
  a clean digital PDF or a flat 300dpi scan comes out well; a phone photo
  at an angle, with shadows, or handwritten music will have mistakes.

Audiveris is a Java program installed into the Docker image (see
install_audiveris.sh). If it isn't present, scans fail with a clear
message while MIDI/MusicXML uploads keep working.
"""

import glob
import os
import shutil
import subprocess
import tempfile
from typing import List, Optional, Tuple

MIN_PITCH, MAX_PITCH = 21, 108  # A0..C8, same 88 keys the frontend draws

MIDI_EXTENSIONS = {".mid", ".midi"}
MUSICXML_EXTENSIONS = {".musicxml", ".xml", ".mxl"}
SCAN_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
SHEET_EXTENSIONS = MIDI_EXTENSIONS | MUSICXML_EXTENSIONS | SCAN_EXTENSIONS

# A multi-page score can take Audiveris a while (roughly 10-40s per page on
# a small server), so this is generous on purpose.
OMR_TIMEOUT_SECONDS = int(os.environ.get("AUDIVERIS_TIMEOUT", "600"))

# Grace notes have no written duration; give them a short audible one so
# they still show up as a (thin) falling note instead of vanishing.
GRACE_NOTE_SECONDS = 0.08


class SheetMusicError(Exception):
    """Raised with a message that's safe to show to the user as-is."""


def _note(pitch: int, start: float, duration: float, velocity: int, hand: Optional[str]) -> dict:
    # Fold anything outside the 88 keys back in by octaves rather than
    # dropping it — an 8va marking misread by OMR shouldn't lose the note.
    while pitch < MIN_PITCH:
        pitch += 12
    while pitch > MAX_PITCH:
        pitch -= 12
    return {
        "pitch": int(pitch),
        "start_time": float(start),
        "duration": float(max(duration, 0.03)),
        "velocity": int(max(1, min(127, velocity))),
        "hand": hand,
    }


# ---------- MIDI ----------

def notes_from_midi(path: str) -> Tuple[List[dict], float]:
    import pretty_midi

    try:
        midi = pretty_midi.PrettyMIDI(path)
    except Exception:
        raise SheetMusicError("That MIDI file couldn't be read. It may be damaged.")

    instruments = [inst for inst in midi.instruments if not inst.is_drum and inst.notes]
    if not instruments:
        raise SheetMusicError("That MIDI file doesn't contain any notes.")

    # Piano MIDI exported from notation software is very often two tracks,
    # one per hand. When that's the case, trust it: the higher track is the
    # right hand. Anything else falls back to the frontend's guesser.
    hands = [None] * len(instruments)
    if len(instruments) == 2:
        avg = [sum(n.pitch for n in inst.notes) / len(inst.notes) for inst in instruments]
        hands = ["right", "left"] if avg[0] >= avg[1] else ["left", "right"]

    notes = []
    for inst, hand in zip(instruments, hands):
        for n in inst.notes:
            notes.append(_note(n.pitch, n.start, n.end - n.start, n.velocity, hand))

    tempos = midi.get_tempo_changes()[1]
    tempo = float(tempos[0]) if len(tempos) else 120.0
    return notes, tempo


# ---------- MusicXML ----------

def _seconds_converter(score):
    """Returns a function mapping a quarter-length offset to seconds, honoring
    every tempo marking in the score (not just the first)."""
    try:
        boundaries = score.metronomeMarkBoundaries()
    except Exception:
        boundaries = []

    segments = []  # (start_ql, end_ql, start_seconds, seconds_per_quarter)
    elapsed = 0.0
    for start, end, mark in boundaries:
        try:
            spq = mark.secondsPerQuarter()
        except Exception:
            spq = 0.5
        if not spq or spq <= 0:
            spq = 0.5
        segments.append((float(start), float(end), elapsed, spq))
        elapsed += (float(end) - float(start)) * spq
    if not segments:
        segments = [(0.0, float("inf"), 0.0, 0.5)]

    def to_seconds(ql: float) -> float:
        for start, end, start_sec, spq in segments:
            if ql < end:
                return start_sec + (ql - start) * spq
        start, end, start_sec, spq = segments[-1]
        return start_sec + (ql - start) * spq

    first_bpm = 60.0 / segments[0][3]
    return to_seconds, first_bpm


def notes_from_musicxml(path: str) -> Tuple[List[dict], float]:
    from music21 import converter

    try:
        score = converter.parse(path)
    except Exception:
        raise SheetMusicError("That MusicXML file couldn't be read.")

    # Play repeats the way a person would. Badly-formed repeat barlines
    # (common in OMR output) make this throw; in that case just read it
    # straight through once.
    try:
        score = score.expandRepeats()
    except Exception:
        pass

    # Merge tied notes into one long note, so a whole note tied over a
    # barline falls as one bar instead of two separate key presses.
    try:
        score = score.stripTies()
    except Exception:
        pass

    to_seconds, first_bpm = _seconds_converter(score)

    parts = list(score.parts) or [score]
    # A normal piano score is two staves (music21 splits them into two
    # PartStaff objects): treble on top for the right hand, bass below for
    # the left. That's real information from the page, far better than
    # guessing from pitch, so keep it when the layout is that simple.
    hands: List[Optional[str]] = [None] * len(parts)
    if len(parts) == 2:
        hands = ["right", "left"]

    notes: List[dict] = []
    for part, hand in zip(parts, hands):
        for el in part.flatten().notes:
            start_ql = float(el.offset)
            is_grace = el.duration.isGrace
            end_ql = start_ql + float(el.duration.quarterLength)
            start = to_seconds(start_ql)
            duration = GRACE_NOTE_SECONDS if is_grace else to_seconds(end_ql) - start

            velocity = 80
            try:
                if el.volume is not None and el.volume.velocity:
                    velocity = int(el.volume.velocity)
            except Exception:
                pass

            pitches = el.pitches if el.isChord else ([el.pitch] if hasattr(el, "pitch") else [])
            for p in pitches:
                if p is None or p.midi is None:
                    continue
                notes.append(_note(p.midi, start, duration, velocity, hand))

    if not notes:
        raise SheetMusicError("No notes were found in that score.")
    return notes, round(first_bpm, 1)


# ---------- Scans (Audiveris OMR) ----------

def find_audiveris() -> Optional[str]:
    candidates = [
        os.environ.get("AUDIVERIS_CMD"),
        shutil.which("audiveris"),
        shutil.which("Audiveris"),
        "/opt/audiveris/bin/Audiveris",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def scan_to_musicxml(input_path: str, work_dir: str) -> List[str]:
    """Runs Audiveris on a PDF or image and returns the paths of the MusicXML
    files it wrote (one per movement, usually just one)."""
    audiveris = find_audiveris()
    if not audiveris:
        raise SheetMusicError(
            "Scanning PDFs and photos isn't set up on this server yet. "
            "If you have a MusicXML or MIDI file of the piece, upload that instead."
        )

    out_dir = os.path.join(work_dir, "omr")
    os.makedirs(out_dir, exist_ok=True)

    env = dict(os.environ)
    heap = os.environ.get("AUDIVERIS_MAX_HEAP", "1g")
    env["JAVA_TOOL_OPTIONS"] = f"{env.get('JAVA_TOOL_OPTIONS', '')} -Djava.awt.headless=true -Xmx{heap}".strip()

    try:
        result = subprocess.run(
            [audiveris, "-batch", "-export", "-output", out_dir, "--", input_path],
            capture_output=True,
            text=True,
            timeout=OMR_TIMEOUT_SECONDS,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise SheetMusicError("Reading that score took too long. Try uploading fewer pages at a time.")

    exported = sorted(glob.glob(os.path.join(out_dir, "**", "*.mxl"), recursive=True))
    exported += sorted(glob.glob(os.path.join(out_dir, "**", "*.musicxml"), recursive=True))
    if not exported:
        print("Audiveris produced no MusicXML. stdout/stderr tail:\n", result.stdout[-2000:], result.stderr[-2000:])
        raise SheetMusicError(
            "Couldn't find any music on that page. Scans work best as a straight-on, well-lit, "
            "high-resolution image or a PDF exported from notation software."
        )
    return exported


def notes_from_scan(input_path: str, work_dir: str) -> Tuple[List[dict], float]:
    exported = scan_to_musicxml(input_path, work_dir)

    # A score with several movements comes out as several files; play them
    # back to back in order.
    all_notes: List[dict] = []
    tempo = None
    offset = 0.0
    for path in exported:
        try:
            notes, bpm = notes_from_musicxml(path)
        except SheetMusicError:
            continue
        for n in notes:
            n["start_time"] += offset
        all_notes.extend(notes)
        offset = max(n["start_time"] + n["duration"] for n in all_notes) + 1.0
        tempo = tempo or bpm

    if not all_notes:
        raise SheetMusicError("The scanner read the page but couldn't make out any notes.")
    return all_notes, tempo or 120.0


# ---------- Entry point ----------

def transcribe_sheet(path: str) -> Tuple[List[dict], float, float]:
    """Returns (notes, duration_seconds, tempo_bpm) for any supported sheet
    music file. Note dicts match the backend's NoteEvent shape, plus a
    "hand" key that's "left"/"right" when the score says so, else None."""
    ext = os.path.splitext(path)[1].lower()
    if ext in MIDI_EXTENSIONS:
        notes, tempo = notes_from_midi(path)
    elif ext in MUSICXML_EXTENSIONS:
        notes, tempo = notes_from_musicxml(path)
    elif ext in SCAN_EXTENSIONS:
        work_dir = tempfile.mkdtemp(prefix="omr-")
        try:
            notes, tempo = notes_from_scan(path, work_dir)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
    else:
        raise SheetMusicError(f"Unsupported sheet music file type: {ext}")

    # Start the piece at 0 even if the score opens with rests.
    first = min(n["start_time"] for n in notes)
    if first > 0:
        for n in notes:
            n["start_time"] -= first

    notes.sort(key=lambda n: (n["start_time"], n["pitch"]))
    duration = max(n["start_time"] + n["duration"] for n in notes)
    return notes, duration, tempo
