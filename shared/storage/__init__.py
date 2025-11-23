"""
Storage module for Real-Time Transcription Platform
"""
from .s3_client import S3Client, storage_client, initialize_storage

__all__ = [
    'S3Client',
    'storage_client',
    'initialize_storage',
]
