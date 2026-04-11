"""
Piano Chord Recognition Service
Analyzes music audio and extracts piano chords/notes
"""
import os
import sys
import logging
import io
import json
from datetime import datetime
from typing import List, Dict, Any, Tuple
import numpy as np
import librosa
import librosa.display
from scipy.signal import find_peaks
from fastapi import FastAPI, UploadFile, File, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# Add shared modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shared.utils.logging_config import setup_logging
from shared.utils.metrics import track_duration, http_request_duration_seconds

# Setup logging
setup_logging(service_name='chord-recognition')
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="Piano Chord Recognition Service",
    description="Extract piano chords and notes from music audio",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic models
class ChordRecognitionResponse(BaseModel):
    duration: float
    tempo: float
    key: str
    time_signature: str
    notes: List[Dict[str, Any]]
    chords: List[Dict[str, Any]]
    sheet_music: List[str]


class NoteDetector:
    """Detects individual notes from audio"""

    def __init__(self, sr: int = 22050):
        """
        Initialize note detector

        Args:
            sr: Sample rate
        """
        self.sr = sr
        self.hop_length = 512
        self.n_fft = 2048

        # MIDI note to name mapping
        self.note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

    def detect_notes(self, audio: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detect notes from audio using pitch tracking

        Args:
            audio: Audio waveform

        Returns:
            List of detected notes with timestamps
        """
        logger.info("Detecting notes from audio...")

        # Compute pitch using piptrack (improved pitch detection)
        pitches, magnitudes = librosa.piptrack(
            y=audio,
            sr=self.sr,
            hop_length=self.hop_length,
            fmin=librosa.note_to_hz('C2'),  # Piano range
            fmax=librosa.note_to_hz('C7')
        )

        # Extract note events
        notes = []
        times = librosa.frames_to_time(np.arange(pitches.shape[1]), sr=self.sr, hop_length=self.hop_length)

        for i, time in enumerate(times):
            # Get the pitch with highest magnitude at this time
            index = magnitudes[:, i].argmax()
            pitch = pitches[index, i]

            if pitch > 0:  # Valid pitch detected
                # Convert frequency to MIDI note
                midi_note = librosa.hz_to_midi(pitch)
                note_name = self._midi_to_note_name(midi_note)

                # Check if this is a new note (not continuation)
                if not notes or notes[-1]['note'] != note_name or (time - notes[-1]['end']) > 0.1:
                    notes.append({
                        'note': note_name,
                        'midi': int(midi_note),
                        'frequency': float(pitch),
                        'start': float(time),
                        'end': float(time),
                        'confidence': float(magnitudes[index, i])
                    })
                else:
                    # Extend the current note
                    notes[-1]['end'] = float(time)

        logger.info(f"Detected {len(notes)} note events")
        return notes

    def detect_notes_with_onsets(self, audio: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detect notes using onset detection and pitch tracking

        Args:
            audio: Audio waveform

        Returns:
            List of detected notes with precise timing
        """
        logger.info("Detecting notes with onset detection...")

        # Detect onsets (note starts)
        onset_frames = librosa.onset.onset_detect(
            y=audio,
            sr=self.sr,
            hop_length=self.hop_length,
            backtrack=True
        )
        onset_times = librosa.frames_to_time(onset_frames, sr=self.sr, hop_length=self.hop_length)

        # Compute chromagram for pitch content
        chroma = librosa.feature.chroma_cqt(y=audio, sr=self.sr, hop_length=self.hop_length)

        # Compute pitch tracking
        pitches, magnitudes = librosa.piptrack(
            y=audio,
            sr=self.sr,
            hop_length=self.hop_length,
            fmin=librosa.note_to_hz('C2'),
            fmax=librosa.note_to_hz('C7')
        )

        notes = []

        # For each onset, detect the notes being played
        for i, onset_time in enumerate(onset_times):
            onset_frame = onset_frames[i]

            # Get pitch at onset
            pitch_idx = magnitudes[:, onset_frame].argmax()
            pitch = pitches[pitch_idx, onset_frame]

            if pitch > 0:
                midi_note = librosa.hz_to_midi(pitch)
                note_name = self._midi_to_note_name(midi_note)

                # Estimate duration (until next onset or 0.5s)
                duration = 0.5
                if i < len(onset_times) - 1:
                    duration = onset_times[i + 1] - onset_time

                notes.append({
                    'note': note_name,
                    'midi': int(midi_note),
                    'frequency': float(pitch),
                    'start': float(onset_time),
                    'duration': float(duration),
                    'end': float(onset_time + duration),
                    'confidence': float(magnitudes[pitch_idx, onset_frame])
                })

            # Also check for chord (multiple notes at once)
            # Get chroma at this onset
            chroma_at_onset = chroma[:, onset_frame]
            active_pitches = np.where(chroma_at_onset > 0.5)[0]

            if len(active_pitches) > 1:
                # This might be a chord
                notes[-1]['chord_notes'] = [self.note_names[p] for p in active_pitches]

        logger.info(f"Detected {len(notes)} note events with onsets")
        return notes

    def _midi_to_note_name(self, midi_note: float) -> str:
        """
        Convert MIDI note number to note name with octave

        Args:
            midi_note: MIDI note number

        Returns:
            Note name (e.g., 'A4', 'C#5')
        """
        midi_int = int(round(midi_note))
        octave = (midi_int // 12) - 1
        note_idx = midi_int % 12
        return f"{self.note_names[note_idx]}{octave}"


class ChordRecognizer:
    """Recognizes chords from audio"""

    def __init__(self, sr: int = 22050):
        """
        Initialize chord recognizer

        Args:
            sr: Sample rate
        """
        self.sr = sr
        self.hop_length = 512

        # Chord templates (major, minor, etc.)
        self.chord_templates = self._create_chord_templates()

    def _create_chord_templates(self) -> Dict[str, np.ndarray]:
        """Create chord templates for matching"""
        templates = {}

        # Major chords (root, major 3rd, perfect 5th)
        templates['major'] = np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0])

        # Minor chords (root, minor 3rd, perfect 5th)
        templates['minor'] = np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0])

        # Seventh chords
        templates['7'] = np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0])

        # Diminished
        templates['dim'] = np.array([1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0])

        return templates

    def recognize_chords(self, audio: np.ndarray) -> List[Dict[str, Any]]:
        """
        Recognize chords from audio

        Args:
            audio: Audio waveform

        Returns:
            List of recognized chords
        """
        logger.info("Recognizing chords from audio...")

        # Compute chromagram
        chroma = librosa.feature.chroma_cqt(y=audio, sr=self.sr, hop_length=self.hop_length)

        # Detect beats for chord change points
        tempo, beat_frames = librosa.beat.beat_track(y=audio, sr=self.sr, hop_length=self.hop_length)

        beat_times = librosa.frames_to_time(beat_frames, sr=self.sr, hop_length=self.hop_length)

        chords = []

        # For each beat segment, identify the chord
        for i in range(len(beat_frames) - 1):
            start_frame = beat_frames[i]
            end_frame = beat_frames[i + 1]

            # Average chroma over this segment
            chroma_segment = chroma[:, start_frame:end_frame].mean(axis=1)

            # Normalize
            chroma_segment = chroma_segment / (chroma_segment.sum() + 1e-8)

            # Find best matching chord
            chord_name = self._match_chord(chroma_segment)

            if chord_name:
                chords.append({
                    'chord': chord_name,
                    'start': float(beat_times[i]),
                    'end': float(beat_times[i + 1]) if i < len(beat_times) - 1 else float(beat_times[i] + 1),
                    'confidence': float(chroma_segment.max())
                })

        logger.info(f"Recognized {len(chords)} chord segments")
        return chords

    def _match_chord(self, chroma: np.ndarray) -> str:
        """
        Match chroma vector to chord template

        Args:
            chroma: 12-dimensional chroma vector

        Returns:
            Chord name (e.g., 'C', 'Am', 'G7')
        """
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

        best_match = None
        best_score = 0

        # Try each root note
        for root in range(12):
            # Try each chord type
            for chord_type, template in self.chord_templates.items():
                # Rotate template to match root
                rotated = np.roll(template, root)

                # Compute similarity
                score = np.dot(chroma, rotated)

                if score > best_score:
                    best_score = score
                    chord_suffix = '' if chord_type == 'major' else ('m' if chord_type == 'minor' else chord_type)
                    best_match = f"{note_names[root]}{chord_suffix}"

        return best_match if best_score > 0.5 else None


class PianoSheetGenerator:
    """Generates piano sheet notation from detected notes"""

    def __init__(self):
        """Initialize sheet generator"""
        pass

    def generate_sheet(self, notes: List[Dict[str, Any]], time_per_line: float = 4.0) -> List[str]:
        """
        Generate simple sheet notation

        Args:
            notes: Detected notes
            time_per_line: Seconds per line of output

        Returns:
            List of sheet music lines (like the Interstellar example)
        """
        if not notes:
            return []

        # Group notes by time segments
        max_time = max(n['end'] for n in notes)
        num_lines = int(np.ceil(max_time / time_per_line))

        sheet_lines = []

        for line_idx in range(num_lines):
            start_time = line_idx * time_per_line
            end_time = (line_idx + 1) * time_per_line

            # Get notes in this time segment
            segment_notes = [n for n in notes if start_time <= n['start'] < end_time]

            # Format as pairs (like "A4 E5   A4 E5")
            line_parts = []
            for note in segment_notes:
                if 'chord_notes' in note and len(note['chord_notes']) > 1:
                    # It's a chord, show multiple notes
                    line_parts.append(' '.join(note['chord_notes']))
                else:
                    line_parts.append(note['note'])

            if line_parts:
                # Group in pairs for readability
                formatted = []
                for i in range(0, len(line_parts), 2):
                    if i + 1 < len(line_parts):
                        formatted.append(f"{line_parts[i]} {line_parts[i+1]}")
                    else:
                        formatted.append(line_parts[i])

                sheet_lines.append('   '.join(formatted))

        return sheet_lines


# Global instances
note_detector = NoteDetector()
chord_recognizer = ChordRecognizer()
sheet_generator = PianoSheetGenerator()


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "chord-recognition"}


@app.post("/v1/recognize", response_model=ChordRecognitionResponse)
async def recognize_chords(
    audio: UploadFile = File(...),
    detect_notes: bool = True,
    detect_chords: bool = True,
    generate_sheet: bool = True
):
    """
    Recognize piano chords and notes from audio file

    Args:
        audio: Audio file (MP3, WAV, etc.)
        detect_notes: Whether to detect individual notes
        detect_chords: Whether to detect chord progressions
        generate_sheet: Whether to generate sheet notation

    Returns:
        Chord recognition results
    """
    with track_duration(http_request_duration_seconds, 'chord-recognition', 'POST', '/v1/recognize'):
        try:
            logger.info(f"Processing audio file: {audio.filename}")

            # Read audio file
            audio_data = await audio.read()

            # Load audio with librosa
            y, sr = librosa.load(io.BytesIO(audio_data), sr=22050, mono=True)

            # Analyze audio
            duration = librosa.get_duration(y=y, sr=sr)
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)

            # Estimate key
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            key = estimate_key(chroma)

            # Detect notes
            notes = []
            if detect_notes:
                notes = note_detector.detect_notes_with_onsets(y)

            # Recognize chords
            chords = []
            if detect_chords:
                chords = chord_recognizer.recognize_chords(y)

            # Generate sheet notation
            sheet_music = []
            if generate_sheet and notes:
                sheet_music = sheet_generator.generate_sheet(notes)

            logger.info(f"Analysis complete: {len(notes)} notes, {len(chords)} chords, duration={duration:.2f}s")

            return ChordRecognitionResponse(
                duration=duration,
                tempo=float(tempo),
                key=key,
                time_signature="4/4",  # Default, can be improved
                notes=notes,
                chords=chords,
                sheet_music=sheet_music
            )

        except Exception as e:
            logger.error(f"Chord recognition failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )


def estimate_key(chroma: np.ndarray) -> str:
    """
    Estimate musical key from chromagram

    Args:
        chroma: Chromagram

    Returns:
        Estimated key (e.g., 'C major', 'A minor')
    """
    # Average chroma over time
    chroma_mean = chroma.mean(axis=1)

    # Find dominant pitch class
    dominant = chroma_mean.argmax()

    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

    # Simple heuristic: assume major key
    # (More sophisticated key detection would use key profiles)
    return f"{note_names[dominant]} major"


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Piano Chord Recognition",
        "version": "1.0.0",
        "endpoints": {
            "recognize": "/v1/recognize",
            "health": "/health",
            "docs": "/docs"
        }
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8003,
        log_level="info"
    )
