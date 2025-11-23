"""
Messaging module for Real-Time Transcription Platform
"""
from .rabbitmq import RabbitMQClient, setup_topology, mq_client

__all__ = [
    'RabbitMQClient',
    'setup_topology',
    'mq_client',
]
