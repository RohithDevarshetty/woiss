"""
Speaker Diarization Service
Identifies "who spoke when" using pyannote.audio
"""
import os
import sys
import logging
import json
import io
import time
from datetime import datetime
from typing import List, Dict, Any
import torch
import torchaudio
from pyannote.audio import Pipeline

# Add shared modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shared.utils.logging_config import setup_logging
from shared.utils.redis_client import redis_client
from shared.utils.metrics import (
    diarization_latency_seconds,
    diarization_speakers_detected,
    mq_messages_consumed_total,
    mq_messages_published_total,
    errors_total,
    track_duration
)
from shared.messaging import mq_client

# Setup logging
setup_logging(service_name='diarization')
logger = logging.getLogger(__name__)

# Configuration
DEVICE = os.getenv('DEVICE', 'cuda' if torch.cuda.is_available() else 'cpu')
HF_AUTH_TOKEN = os.getenv('HF_AUTH_TOKEN')  # Hugging Face token for pyannote models


class DiarizationEngine:
    """Manages speaker diarization pipeline"""

    def __init__(self, device: str = DEVICE):
        """
        Initialize diarization engine

        Args:
            device: Device to run on (cuda/cpu)
        """
        self.device = device

        logger.info(f"Loading pyannote speaker diarization pipeline on {device}")

        # Load pre-trained pipeline
        # Requires accepting user agreement at: https://huggingface.co/pyannote/speaker-diarization
        self.pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=HF_AUTH_TOKEN
        ).to(torch.device(device))

        logger.info("Diarization pipeline loaded successfully")

    def diarize(self, audio_data: bytes) -> Dict[str, Any]:
        """
        Perform speaker diarization on audio

        Args:
            audio_data: WAV audio bytes

        Returns:
            Dict with speaker segments
        """
        start_time = time.time()

        try:
            # Convert bytes to torch tensor
            waveform, sample_rate = self._load_audio(audio_data)

            # Run diarization
            diarization = self.pipeline({
                'waveform': waveform,
                'sample_rate': sample_rate
            })

            # Extract speaker segments
            segments = []
            speakers = set()

            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append({
                    'start': turn.start,
                    'end': turn.end,
                    'speaker': speaker
                })
                speakers.add(speaker)

            # Calculate latency
            latency = time.time() - start_time

            # Track metrics
            diarization_latency_seconds.observe(latency)
            diarization_speakers_detected.observe(len(speakers))

            return {
                'segments': segments,
                'num_speakers': len(speakers),
                'speakers': list(speakers),
                'latency': latency
            }

        except Exception as e:
            logger.error(f"Diarization failed: {e}")
            errors_total.labels(service='diarization', error_type=type(e).__name__).inc()
            raise

    def _load_audio(self, audio_data: bytes):
        """
        Load audio from bytes

        Args:
            audio_data: WAV audio bytes

        Returns:
            Tuple of (waveform, sample_rate)
        """
        waveform, sample_rate = torchaudio.load(io.BytesIO(audio_data))
        return waveform, sample_rate

    def merge_with_transcript(
        self,
        transcript_segments: List[Dict],
        diarization_segments: List[Dict]
    ) -> List[Dict]:
        """
        Merge speaker labels with transcript segments

        Args:
            transcript_segments: Segments from ASR
            diarization_segments: Segments from diarization

        Returns:
            Merged segments with speaker labels
        """
        merged = []

        for transcript_seg in transcript_segments:
            start = transcript_seg['start']
            end = transcript_seg['end']

            # Find overlapping speaker
            speaker = self._find_speaker_at_time(diarization_segments, start, end)

            merged.append({
                **transcript_seg,
                'speaker': speaker
            })

        return merged

    def _find_speaker_at_time(
        self,
        diarization_segments: List[Dict],
        start: float,
        end: float
    ) -> str:
        """
        Find speaker with maximum overlap in time range

        Args:
            diarization_segments: Speaker segments
            start: Start time
            end: End time

        Returns:
            Speaker label
        """
        # Calculate overlap for each speaker
        speaker_overlaps = {}

        for seg in diarization_segments:
            seg_start = seg['start']
            seg_end = seg['end']
            speaker = seg['speaker']

            # Calculate overlap
            overlap_start = max(start, seg_start)
            overlap_end = min(end, seg_end)
            overlap = max(0, overlap_end - overlap_start)

            if overlap > 0:
                speaker_overlaps[speaker] = speaker_overlaps.get(speaker, 0) + overlap

        # Return speaker with max overlap
        if speaker_overlaps:
            return max(speaker_overlaps, key=speaker_overlaps.get)
        else:
            return 'UNKNOWN'


# Global diarization engine
diarization_engine = None


def process_diarization_task(ch, method, properties, body):
    """
    Process diarization task from RabbitMQ

    Args:
        ch: Channel
        method: Method
        properties: Properties
        body: Message body
    """
    global diarization_engine

    mq_messages_consumed_total.labels(queue='diarization.tasks').inc()

    try:
        # Parse metadata
        message = json.loads(body)
        session_id = message['session_id']
        user_id = message['user_id']
        chunk_number = message['chunk_number']
        transcript_segments = message.get('segments', [])

        logger.debug(f"Processing diarization: session={session_id}, chunk={chunk_number}")

        # Get binary audio data
        method_frame, header_frame, audio_data = ch.basic_get(queue='diarization.tasks')

        if audio_data:
            # Perform diarization
            with track_duration(diarization_latency_seconds):
                diarization_result = diarization_engine.diarize(audio_data)

            # Merge with transcript segments if provided
            if transcript_segments:
                merged_segments = diarization_engine.merge_with_transcript(
                    transcript_segments,
                    diarization_result['segments']
                )
            else:
                merged_segments = diarization_result['segments']

            # Prepare result message
            result_message = {
                'session_id': session_id,
                'user_id': user_id,
                'chunk_number': chunk_number,
                'timestamp': datetime.utcnow().isoformat(),
                'event_type': 'speaker',
                'data': {
                    'segments': merged_segments,
                    'num_speakers': diarization_result['num_speakers'],
                    'speakers': diarization_result['speakers'],
                    'latency_ms': int(diarization_result['latency'] * 1000)
                }
            }

            # Publish to processing queue
            mq_client.publish(
                exchange='processing.output',
                routing_key='diarization.result',
                message=result_message
            )

            mq_messages_published_total.labels(
                exchange='processing.output',
                routing_key='diarization.result'
            ).inc()

            logger.info(
                f"Diarization completed: session={session_id}, "
                f"speakers={diarization_result['num_speakers']}, "
                f"latency={diarization_result['latency']*1000:.0f}ms"
            )

            # Acknowledge messages
            ch.basic_ack(delivery_tag=method.delivery_tag)
            if method_frame:
                ch.basic_ack(delivery_tag=method_frame.delivery_tag)

        else:
            # No audio data, requeue
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    except Exception as e:
        logger.error(f"Error in diarization processing: {e}")
        errors_total.labels(service='diarization', error_type=type(e).__name__).inc()
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def main():
    """Main entry point"""
    global diarization_engine

    logger.info("Diarization service starting")

    try:
        # Initialize diarization engine
        diarization_engine = DiarizationEngine(device=DEVICE)

        # Connect to RabbitMQ
        mq_client.connect()

        # Declare queues
        mq_client.declare_queue('diarization.tasks')

        # Start consuming
        logger.info("Listening for diarization tasks...")
        mq_client.consume(
            queue='diarization.tasks',
            callback=process_diarization_task,
            prefetch_count=1  # Process one at a time for GPU efficiency
        )

    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
    finally:
        mq_client.disconnect()


if __name__ == "__main__":
    main()
