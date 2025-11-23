"""
Prometheus metrics collection
"""
from prometheus_client import Counter, Histogram, Gauge, Summary
import time
from contextlib import contextmanager
from typing import Optional

# HTTP metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['service', 'method', 'endpoint', 'status']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['service', 'method', 'endpoint'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0)
)

# WebSocket metrics
websocket_connections_active = Gauge(
    'websocket_connections_active',
    'Number of active WebSocket connections',
    ['service']
)

websocket_messages_total = Counter(
    'websocket_messages_total',
    'Total WebSocket messages',
    ['service', 'direction', 'message_type']
)

# Audio processing metrics
audio_chunks_processed_total = Counter(
    'audio_chunks_processed_total',
    'Total audio chunks processed',
    ['service', 'status']
)

audio_processing_duration_seconds = Histogram(
    'audio_processing_duration_seconds',
    'Audio processing duration in seconds',
    ['service', 'stage'],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)
)

# ASR metrics
asr_latency_seconds = Histogram(
    'asr_latency_seconds',
    'ASR processing latency in seconds',
    ['model', 'language'],
    buckets=(0.1, 0.3, 0.5, 0.8, 1.0, 2.0, 5.0)
)

asr_words_total = Counter(
    'asr_words_total',
    'Total words transcribed',
    ['model', 'language']
)

asr_confidence_score = Summary(
    'asr_confidence_score',
    'ASR confidence scores',
    ['model']
)

# Diarization metrics
diarization_latency_seconds = Histogram(
    'diarization_latency_seconds',
    'Speaker diarization latency in seconds',
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
)

diarization_speakers_detected = Histogram(
    'diarization_speakers_detected',
    'Number of speakers detected',
    buckets=(1, 2, 3, 4, 5, 10, 20)
)

# Session metrics
sessions_created_total = Counter(
    'sessions_created_total',
    'Total sessions created',
    ['tier']
)

sessions_active = Gauge(
    'sessions_active',
    'Number of active sessions',
    ['tier']
)

sessions_ended_total = Counter(
    'sessions_ended_total',
    'Total sessions ended',
    ['tier', 'status']
)

# Transcript metrics
transcript_words_total = Counter(
    'transcript_words_total',
    'Total words in transcripts',
    ['session_id']
)

transcript_update_duration_seconds = Histogram(
    'transcript_update_duration_seconds',
    'Time to update transcript in database',
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0)
)

# Usage/billing metrics
usage_minutes_total = Counter(
    'usage_minutes_total',
    'Total usage minutes',
    ['user_id', 'tier', 'event_type']
)

usage_cost_cents_total = Counter(
    'usage_cost_cents_total',
    'Total usage cost in cents',
    ['user_id', 'tier', 'event_type']
)

# Database metrics
db_query_duration_seconds = Histogram(
    'db_query_duration_seconds',
    'Database query duration in seconds',
    ['operation', 'table'],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0)
)

db_connections_active = Gauge(
    'db_connections_active',
    'Number of active database connections'
)

# Message queue metrics
mq_messages_published_total = Counter(
    'mq_messages_published_total',
    'Total messages published to queue',
    ['exchange', 'routing_key']
)

mq_messages_consumed_total = Counter(
    'mq_messages_consumed_total',
    'Total messages consumed from queue',
    ['queue']
)

mq_message_processing_duration_seconds = Histogram(
    'mq_message_processing_duration_seconds',
    'Message processing duration in seconds',
    ['queue'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0)
)

# Storage metrics
storage_upload_duration_seconds = Histogram(
    'storage_upload_duration_seconds',
    'Storage upload duration in seconds',
    ['bucket'],
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0)
)

storage_upload_bytes_total = Counter(
    'storage_upload_bytes_total',
    'Total bytes uploaded to storage',
    ['bucket']
)

# Error metrics
errors_total = Counter(
    'errors_total',
    'Total errors',
    ['service', 'error_type']
)


@contextmanager
def track_duration(histogram, *labels):
    """
    Context manager to track duration in a histogram

    Usage:
        with track_duration(http_request_duration_seconds, 'gateway', 'GET', '/health'):
            # do work
            pass
    """
    start_time = time.time()
    try:
        yield
    finally:
        duration = time.time() - start_time
        histogram.labels(*labels).observe(duration)


@contextmanager
def track_operation(
    counter_total: Optional[Counter] = None,
    histogram_duration: Optional[Histogram] = None,
    labels: tuple = ()
):
    """
    Context manager to track both count and duration

    Usage:
        with track_operation(
            audio_chunks_processed_total,
            audio_processing_duration_seconds,
            ('ingestion', 'success')
        ):
            # do work
            pass
    """
    start_time = time.time()
    try:
        yield
        if counter_total:
            counter_total.labels(*labels).inc()
    finally:
        if histogram_duration:
            duration = time.time() - start_time
            histogram_duration.labels(*labels).observe(duration)
