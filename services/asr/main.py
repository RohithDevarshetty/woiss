"""
ASR (Automatic Speech Recognition) Service
Performs real-time transcription using faster-whisper
"""
import os
import sys
import logging
import json
import io
import time
from datetime import datetime
from typing import List, Dict, Any
import numpy as np
from faster_whisper import WhisperModel

# Add shared modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shared.utils.logging_config import setup_logging
from shared.utils.redis_client import redis_client
from shared.utils.metrics import (
    asr_latency_seconds,
    asr_words_total,
    asr_confidence_score,
    mq_messages_consumed_total,
    mq_messages_published_total,
    errors_total,
    track_duration
)
from shared.messaging import mq_client

# Setup logging
setup_logging(service_name='asr')
logger = logging.getLogger(__name__)

# Model configuration
MODEL_SIZE = os.getenv('WHISPER_MODEL', 'large-v3')  # tiny, base, small, medium, large-v3
DEVICE = os.getenv('DEVICE', 'cuda')  # cuda, cpu
COMPUTE_TYPE = os.getenv('COMPUTE_TYPE', 'float16')  # float16, int8, int8_float16

# Model cache directory
MODEL_CACHE_DIR = os.getenv('MODEL_CACHE_DIR', '/models')


class ASREngine:
    """Manages Whisper ASR model and transcription"""

    def __init__(
        self,
        model_size: str = MODEL_SIZE,
        device: str = DEVICE,
        compute_type: str = COMPUTE_TYPE
    ):
        """
        Initialize ASR engine

        Args:
            model_size: Whisper model size
            device: Device to run on (cuda/cpu)
            compute_type: Compute type for optimization
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type

        logger.info(f"Loading Whisper model: {model_size} on {device} with {compute_type}")

        # Load model
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=MODEL_CACHE_DIR
        )

        logger.info("Whisper model loaded successfully")

    def transcribe(
        self,
        audio_data: bytes,
        language: str = 'en',
        beam_size: int = 1,  # Low beam size for speed
        best_of: int = 1,
        temperature: float = 0.0,
        vad_filter: bool = True,
        word_timestamps: bool = True
    ) -> Dict[str, Any]:
        """
        Transcribe audio data

        Args:
            audio_data: WAV audio bytes
            language: Language code
            beam_size: Beam size for decoding (1 for greedy, higher for accuracy)
            best_of: Number of candidates to consider
            temperature: Sampling temperature
            vad_filter: Enable voice activity detection filter
            word_timestamps: Generate word-level timestamps

        Returns:
            Dict with transcription results
        """
        start_time = time.time()

        try:
            # Convert bytes to numpy array
            audio_array = self._wav_bytes_to_array(audio_data)

            # Transcribe
            segments, info = self.model.transcribe(
                audio_array,
                language=language,
                beam_size=beam_size,
                best_of=best_of,
                temperature=temperature,
                vad_filter=vad_filter,
                word_timestamps=word_timestamps
            )

            # Process segments
            result_segments = []
            total_words = 0

            for segment in segments:
                # Extract words with timestamps
                words = []
                if word_timestamps and segment.words:
                    for word in segment.words:
                        words.append({
                            'word': word.word,
                            'start': word.start,
                            'end': word.end,
                            'confidence': word.probability
                        })
                        total_words += 1

                # Calculate segment confidence (average word confidence)
                if words:
                    segment_confidence = sum(w['confidence'] for w in words) / len(words)
                else:
                    segment_confidence = 0.9  # Default if no word timestamps

                result_segments.append({
                    'start': segment.start,
                    'end': segment.end,
                    'text': segment.text.strip(),
                    'confidence': segment_confidence,
                    'words': words
                })

                # Track confidence metric
                asr_confidence_score.labels(model=self.model_size).observe(segment_confidence)

            # Calculate latency
            latency = time.time() - start_time

            # Track metrics
            asr_latency_seconds.labels(
                model=self.model_size,
                language=language
            ).observe(latency)

            asr_words_total.labels(
                model=self.model_size,
                language=language
            ).inc(total_words)

            return {
                'segments': result_segments,
                'language': info.language,
                'language_probability': info.language_probability,
                'duration': info.duration,
                'latency': latency,
                'total_words': total_words
            }

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            errors_total.labels(service='asr', error_type=type(e).__name__).inc()
            raise

    def _wav_bytes_to_array(self, wav_data: bytes) -> np.ndarray:
        """
        Convert WAV bytes to numpy array

        Args:
            wav_data: WAV audio bytes

        Returns:
            Numpy array (float32, mono, 16kHz)
        """
        import soundfile as sf

        # Read WAV data
        audio, sample_rate = sf.read(io.BytesIO(wav_data), dtype='float32')

        # Ensure mono
        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)

        # Resample to 16kHz if needed
        if sample_rate != 16000:
            import librosa
            audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000)

        return audio


# Global ASR engine instance
asr_engine = None


def process_audio_for_asr(ch, method, properties, body):
    """
    Process audio chunk for ASR transcription

    Args:
        ch: Channel
        method: Method
        properties: Properties
        body: Message body
    """
    global asr_engine

    mq_messages_consumed_total.labels(queue='asr.tasks').inc()

    try:
        # Parse metadata message
        message = json.loads(body)
        session_id = message['session_id']
        user_id = message['user_id']
        chunk_number = message['chunk_number']
        config = message['config']
        language = config.get('language', 'en')

        logger.debug(f"Processing ASR: session={session_id}, chunk={chunk_number}")

        # Get binary audio data (next message)
        method_frame, header_frame, audio_data = ch.basic_get(queue='asr.tasks')

        if audio_data:
            # Transcribe
            with track_duration(asr_latency_seconds, asr_engine.model_size, language):
                result = asr_engine.transcribe(
                    audio_data,
                    language=language,
                    vad_filter=True,
                    word_timestamps=True
                )

            # Prepare result message
            transcript_message = {
                'session_id': session_id,
                'user_id': user_id,
                'chunk_number': chunk_number,
                'timestamp': datetime.utcnow().isoformat(),
                'event_type': 'interim',  # Will be marked as 'final' in post-processing
                'data': {
                    'segments': result['segments'],
                    'language': result['language'],
                    'latency_ms': int(result['latency'] * 1000),
                    'total_words': result['total_words']
                }
            }

            # Publish to post-processing queue
            mq_client.publish(
                exchange='processing.output',
                routing_key='transcript.interim',
                message=transcript_message
            )

            mq_messages_published_total.labels(
                exchange='processing.output',
                routing_key='transcript.interim'
            ).inc()

            # Also publish to diarization queue if enabled
            if config.get('enable_diarization', False):
                diarization_message = {
                    'session_id': session_id,
                    'user_id': user_id,
                    'chunk_number': chunk_number,
                    'timestamp': datetime.utcnow().isoformat(),
                    'audio_data_size': len(audio_data),
                    'segments': result['segments']
                }

                mq_client.publish(
                    exchange='transcription.output',
                    routing_key='audio.segment',
                    message=diarization_message
                )

                # Publish audio data for diarization
                mq_client.publish_binary(
                    exchange='transcription.output',
                    routing_key='audio.segment',
                    data=audio_data
                )

            logger.info(
                f"ASR completed: session={session_id}, "
                f"words={result['total_words']}, "
                f"latency={result['latency']*1000:.0f}ms"
            )

            # Acknowledge both messages
            ch.basic_ack(delivery_tag=method.delivery_tag)
            if method_frame:
                ch.basic_ack(delivery_tag=method_frame.delivery_tag)

        else:
            # No audio data, requeue
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    except Exception as e:
        logger.error(f"Error in ASR processing: {e}")
        errors_total.labels(service='asr', error_type=type(e).__name__).inc()

        # Nack without requeue
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def main():
    """Main entry point"""
    global asr_engine

    logger.info("ASR service starting")

    try:
        # Initialize ASR engine
        asr_engine = ASREngine(
            model_size=MODEL_SIZE,
            device=DEVICE,
            compute_type=COMPUTE_TYPE
        )

        # Connect to RabbitMQ
        mq_client.connect()

        # Declare queues
        mq_client.declare_queue('asr.tasks')

        # Start consuming
        logger.info("Listening for ASR tasks...")
        mq_client.consume(
            queue='asr.tasks',
            callback=process_audio_for_asr,
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
