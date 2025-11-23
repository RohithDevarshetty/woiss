"""
Post-Processing Service
Adds punctuation, capitalization, and formatting to transcripts
"""
import os
import sys
import logging
import json
import re
from datetime import datetime
from typing import List, Dict, Any

# Add shared modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shared.utils.logging_config import setup_logging
from shared.utils.metrics import (
    mq_messages_consumed_total,
    mq_messages_published_total,
    transcript_update_duration_seconds,
    errors_total,
    track_duration
)
from shared.messaging import mq_client
from shared.database import db_manager, Session, Transcript

# Setup logging
setup_logging(service_name='postprocessing')
logger = logging.getLogger(__name__)


class TextPostProcessor:
    """Handles text post-processing: punctuation, capitalization, formatting"""

    def __init__(self):
        """Initialize post-processor"""
        # In production, could use deepmultilingual-punctuation or similar models
        # For now, using rule-based approach
        pass

    def process(self, text: str) -> str:
        """
        Process text with punctuation and capitalization

        Args:
            text: Raw text from ASR

        Returns:
            Formatted text
        """
        if not text:
            return text

        # Basic capitalization
        text = text.strip()
        if text:
            text = text[0].upper() + text[1:]

        # Add periods at sentence boundaries (simple heuristic)
        text = self._add_punctuation(text)

        # Capitalize after punctuation
        text = self._capitalize_sentences(text)

        # Format numbers and dates (basic)
        text = self._format_numbers(text)

        return text

    def _add_punctuation(self, text: str) -> str:
        """Add basic punctuation"""
        # This is a simplified version; production should use ML models
        # Add period at end if missing
        if text and text[-1] not in '.!?':
            text += '.'

        return text

    def _capitalize_sentences(self, text: str) -> str:
        """Capitalize first letter after sentence-ending punctuation"""
        sentences = re.split(r'([.!?]\s+)', text)
        result = []

        for i, part in enumerate(sentences):
            if part and not part[0].isspace() and i > 0:
                # Capitalize first letter
                part = part[0].upper() + part[1:]
            result.append(part)

        return ''.join(result)

    def _format_numbers(self, text: str) -> str:
        """Format numbers (basic)"""
        # Convert spelled numbers to digits (simplified)
        # Production would use more sophisticated NLP
        return text

    def merge_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Merge consecutive segments from same speaker

        Args:
            segments: List of transcript segments

        Returns:
            Merged segments
        """
        if not segments:
            return []

        merged = []
        current = segments[0].copy()

        for seg in segments[1:]:
            # Merge if same speaker and close in time
            if (seg.get('speaker') == current.get('speaker') and
                seg['start'] - current['end'] < 1.0):  # < 1 second gap
                # Merge
                current['end'] = seg['end']
                current['text'] += ' ' + seg['text']

                # Merge words
                if 'words' in current and 'words' in seg:
                    current['words'].extend(seg['words'])

            else:
                # Process current segment
                current['text'] = self.process(current['text'])
                merged.append(current)
                current = seg.copy()

        # Process last segment
        current['text'] = self.process(current['text'])
        merged.append(current)

        return merged


# Global post-processor
post_processor = TextPostProcessor()


def process_transcript(ch, method, properties, body):
    """
    Process transcript from RabbitMQ

    Args:
        ch: Channel
        method: Method
        properties: Properties
        body: Message body
    """
    mq_messages_consumed_total.labels(queue='postprocessing.tasks').inc()

    try:
        # Parse message
        message = json.loads(body)
        session_id = message['session_id']
        user_id = message['user_id']
        event_type = message.get('event_type', 'interim')
        data = message['data']
        segments = data.get('segments', [])

        logger.debug(f"Processing transcript: session={session_id}, segments={len(segments)}")

        # Post-process segments
        processed_segments = post_processor.merge_segments(segments)

        # Save to database
        with track_duration(transcript_update_duration_seconds):
            with db_manager.session_scope() as db_session:
                # Get or create transcript
                transcript = db_session.query(Transcript).filter(
                    Transcript.session_id == session_id
                ).first()

                if transcript:
                    # Update existing
                    existing_segments = transcript.segments
                    existing_segments.extend(processed_segments)
                    transcript.segments = existing_segments
                    transcript.version += 1
                else:
                    # Create new
                    transcript = Transcript(
                        session_id=session_id,
                        segments=processed_segments,
                        version=1
                    )
                    db_session.add(transcript)

                db_session.commit()

        # Prepare final result for gateway
        final_message = {
            'session_id': session_id,
            'user_id': user_id,
            'event_type': 'final',  # Mark as final after post-processing
            'data': {
                'segments': processed_segments,
                **{k: v for k, v in data.items() if k != 'segments'}
            }
        }

        # Publish to gateway results queue
        mq_client.publish(
            exchange='processing.output',
            routing_key='transcript.final',
            message=final_message
        )

        mq_messages_published_total.labels(
            exchange='processing.output',
            routing_key='transcript.final'
        ).inc()

        logger.info(f"Post-processing completed: session={session_id}")

        # Acknowledge
        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        logger.error(f"Error in post-processing: {e}")
        errors_total.labels(service='postprocessing', error_type=type(e).__name__).inc()
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def main():
    """Main entry point"""
    logger.info("Post-processing service starting")

    try:
        # Initialize database
        db_manager.create_tables()

        # Connect to RabbitMQ
        mq_client.connect()

        # Declare queues
        mq_client.declare_queue('postprocessing.tasks')
        mq_client.bind_queue('postprocessing.tasks', 'processing.output', routing_key='transcript.interim')

        # Start consuming
        logger.info("Listening for post-processing tasks...")
        mq_client.consume(
            queue='postprocessing.tasks',
            callback=process_transcript,
            prefetch_count=10
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
