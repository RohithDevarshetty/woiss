"""
Audio Ingestion Service
Receives audio chunks from gateway, processes, and routes to ASR
"""
import os
import sys
import logging
import json
import io
from datetime import datetime
from pydub import AudioSegment

# Add shared modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shared.utils.logging_config import setup_logging
from shared.utils.redis_client import redis_client
from shared.utils.metrics import (
    audio_chunks_processed_total,
    audio_processing_duration_seconds,
    storage_upload_duration_seconds,
    storage_upload_bytes_total,
    mq_messages_consumed_total,
    mq_messages_published_total,
    errors_total,
    track_operation
)
from shared.messaging import mq_client
from shared.storage import storage_client, STORAGE_BUCKET_AUDIO

# Setup logging
setup_logging(service_name='ingestion')
logger = logging.getLogger(__name__)

# Audio buffer management
class AudioBuffer:
    """Manages audio buffering and chunking for ASR"""

    def __init__(self, session_id: str, sample_rate: int = 16000):
        self.session_id = session_id
        self.sample_rate = sample_rate
        self.buffer = []
        self.total_duration = 0  # in seconds
        self.chunk_size = 3  # seconds per ASR chunk

    def add_chunk(self, audio_data: bytes, format: str = 'webm'):
        """
        Add audio chunk to buffer

        Args:
            audio_data: Raw audio bytes
            format: Audio format (webm, wav, mp3, etc.)
        """
        try:
            # Convert audio to AudioSegment
            audio = AudioSegment.from_file(
                io.BytesIO(audio_data),
                format=format
            )

            # Convert to mono 16kHz PCM (standard for ASR)
            audio = audio.set_channels(1).set_frame_rate(self.sample_rate)

            self.buffer.append(audio)
            self.total_duration += len(audio) / 1000.0  # milliseconds to seconds

            logger.debug(f"Added audio chunk: session={self.session_id}, duration={len(audio)/1000:.2f}s")

        except Exception as e:
            logger.error(f"Failed to process audio chunk: {e}")
            raise

    def get_chunks_for_asr(self):
        """
        Get buffered audio chunks ready for ASR processing

        Yields:
            Audio segments of chunk_size duration
        """
        if not self.buffer:
            return

        # Concatenate all buffered audio
        combined = sum(self.buffer)
        self.buffer = []

        # Split into chunks of chunk_size seconds
        chunk_duration_ms = self.chunk_size * 1000
        for i in range(0, len(combined), chunk_duration_ms):
            chunk = combined[i:i + chunk_duration_ms]

            if len(chunk) > 0:
                yield chunk

    def export_to_wav(self, audio_segment: AudioSegment) -> bytes:
        """
        Export audio segment to WAV bytes

        Args:
            audio_segment: AudioSegment to export

        Returns:
            WAV bytes
        """
        buffer = io.BytesIO()
        audio_segment.export(buffer, format='wav')
        return buffer.getvalue()


# Session buffers
session_buffers = {}


def process_audio_chunk(ch, method, properties, body):
    """
    Process incoming audio chunk from RabbitMQ

    Args:
        ch: Channel
        method: Method
        properties: Properties
        body: Message body
    """
    mq_messages_consumed_total.labels(queue='audio.input').inc()

    try:
        # Parse message (metadata)
        message = json.loads(body)
        session_id = message['session_id']
        user_id = message['user_id']
        chunk_number = message['chunk_number']
        config = message['config']

        logger.debug(f"Processing audio chunk: session={session_id}, chunk={chunk_number}")

        # Get or create buffer for session
        if session_id not in session_buffers:
            session_buffers[session_id] = AudioBuffer(session_id)

        buffer = session_buffers[session_id]

        # Wait for binary audio data (next message)
        # In real implementation, metadata and data should be correlated via message ID
        # For simplicity, we'll assume they arrive in order
        method_frame, header_frame, audio_data = ch.basic_get(queue='audio.input')

        if audio_data:
            with track_operation(
                audio_chunks_processed_total,
                audio_processing_duration_seconds,
                ('ingestion', 'success')
            ):
                # Add to buffer
                buffer.add_chunk(audio_data, format='webm')

                # Store raw audio to S3 (optional, for compliance/replay)
                object_key = f"{session_id}/chunks/chunk_{chunk_number:06d}.webm"

                with track_operation(
                    storage_upload_bytes_total,
                    storage_upload_duration_seconds,
                    (STORAGE_BUCKET_AUDIO,)
                ):
                    storage_client.upload_fileobj(
                        io.BytesIO(audio_data),
                        STORAGE_BUCKET_AUDIO,
                        object_key,
                        content_type='audio/webm'
                    )

                # Process buffered chunks for ASR
                for asr_chunk in buffer.get_chunks_for_asr():
                    # Convert to WAV for ASR
                    wav_data = buffer.export_to_wav(asr_chunk)

                    # Publish to ASR queue
                    asr_message = {
                        'session_id': session_id,
                        'user_id': user_id,
                        'chunk_number': chunk_number,
                        'timestamp': datetime.utcnow().isoformat(),
                        'config': config,
                        'audio_format': 'wav',
                        'sample_rate': buffer.sample_rate,
                        'duration_seconds': len(asr_chunk) / 1000.0
                    }

                    # Publish metadata
                    mq_client.publish(
                        exchange='transcription.output',
                        routing_key='audio.chunk',
                        message=asr_message
                    )

                    # Publish audio data
                    mq_client.publish_binary(
                        exchange='transcription.output',
                        routing_key='audio.chunk',
                        data=wav_data
                    )

                    mq_messages_published_total.labels(
                        exchange='transcription.output',
                        routing_key='audio.chunk'
                    ).inc()

                    logger.debug(f"Sent chunk to ASR: session={session_id}, size={len(wav_data)} bytes")

            # Acknowledge both messages
            ch.basic_ack(delivery_tag=method.delivery_tag)
            if method_frame:
                ch.basic_ack(delivery_tag=method_frame.delivery_tag)

        else:
            # No audio data available, nack and requeue
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    except Exception as e:
        logger.error(f"Error processing audio chunk: {e}")
        errors_total.labels(service='ingestion', error_type=type(e).__name__).inc()

        # Nack without requeue (send to DLQ if configured)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def main():
    """Main entry point"""
    logger.info("Audio ingestion service starting")

    try:
        # Connect to services
        mq_client.connect()

        # Ensure bucket exists
        storage_client.create_bucket(STORAGE_BUCKET_AUDIO)

        # Declare queues
        mq_client.declare_queue('audio.input')

        # Start consuming
        logger.info("Listening for audio chunks...")
        mq_client.consume(
            queue='audio.input',
            callback=process_audio_chunk,
            prefetch_count=5  # Process 5 chunks concurrently
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
