"""
RabbitMQ messaging client for inter-service communication
"""
import os
import json
import logging
from typing import Callable, Dict, Any, Optional
import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties

logger = logging.getLogger(__name__)

# RabbitMQ configuration from environment
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'localhost')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '5672'))
RABBITMQ_USER = os.getenv('RABBITMQ_USER', 'guest')
RABBITMQ_PASSWORD = os.getenv('RABBITMQ_PASSWORD', 'guest')
RABBITMQ_VHOST = os.getenv('RABBITMQ_VHOST', '/')


class RabbitMQClient:
    """RabbitMQ client for publishing and consuming messages"""

    def __init__(
        self,
        host: str = RABBITMQ_HOST,
        port: int = RABBITMQ_PORT,
        username: str = RABBITMQ_USER,
        password: str = RABBITMQ_PASSWORD,
        virtual_host: str = RABBITMQ_VHOST,
        heartbeat: int = 600,
        blocked_connection_timeout: int = 300
    ):
        """
        Initialize RabbitMQ client

        Args:
            host: RabbitMQ host
            port: RabbitMQ port
            username: RabbitMQ username
            password: RabbitMQ password
            virtual_host: RabbitMQ virtual host
            heartbeat: Heartbeat interval in seconds
            blocked_connection_timeout: Timeout for blocked connections
        """
        self.credentials = pika.PlainCredentials(username, password)
        self.parameters = pika.ConnectionParameters(
            host=host,
            port=port,
            virtual_host=virtual_host,
            credentials=self.credentials,
            heartbeat=heartbeat,
            blocked_connection_timeout=blocked_connection_timeout,
        )
        self.connection: Optional[pika.BlockingConnection] = None
        self.channel: Optional[BlockingChannel] = None

    def connect(self):
        """Establish connection to RabbitMQ"""
        if self.connection is None or self.connection.is_closed:
            self.connection = pika.BlockingConnection(self.parameters)
            self.channel = self.connection.channel()
            logger.info("Connected to RabbitMQ")

    def disconnect(self):
        """Close connection to RabbitMQ"""
        if self.connection and not self.connection.is_closed:
            self.connection.close()
            logger.info("Disconnected from RabbitMQ")

    def declare_exchange(
        self,
        exchange: str,
        exchange_type: str = 'topic',
        durable: bool = True
    ):
        """
        Declare an exchange

        Args:
            exchange: Exchange name
            exchange_type: Exchange type (topic, direct, fanout, headers)
            durable: Whether exchange survives broker restart
        """
        self.connect()
        self.channel.exchange_declare(
            exchange=exchange,
            exchange_type=exchange_type,
            durable=durable
        )
        logger.info(f"Declared exchange: {exchange} (type={exchange_type})")

    def declare_queue(
        self,
        queue: str,
        durable: bool = True,
        arguments: Optional[Dict[str, Any]] = None
    ):
        """
        Declare a queue

        Args:
            queue: Queue name
            durable: Whether queue survives broker restart
            arguments: Optional queue arguments (e.g., TTL, max length)
        """
        self.connect()
        self.channel.queue_declare(
            queue=queue,
            durable=durable,
            arguments=arguments or {}
        )
        logger.info(f"Declared queue: {queue}")

    def bind_queue(
        self,
        queue: str,
        exchange: str,
        routing_key: str = ''
    ):
        """
        Bind queue to exchange with routing key

        Args:
            queue: Queue name
            exchange: Exchange name
            routing_key: Routing key pattern
        """
        self.connect()
        self.channel.queue_bind(
            queue=queue,
            exchange=exchange,
            routing_key=routing_key
        )
        logger.info(f"Bound queue {queue} to exchange {exchange} with routing_key={routing_key}")

    def publish(
        self,
        exchange: str,
        routing_key: str,
        message: Dict[str, Any],
        properties: Optional[BasicProperties] = None,
        mandatory: bool = False
    ):
        """
        Publish message to exchange

        Args:
            exchange: Exchange name
            routing_key: Routing key
            message: Message payload (will be JSON serialized)
            properties: Message properties
            mandatory: Require at least one queue to receive message
        """
        self.connect()

        # Default properties
        if properties is None:
            properties = BasicProperties(
                content_type='application/json',
                delivery_mode=2  # Persistent
            )

        # Serialize message to JSON
        body = json.dumps(message).encode('utf-8')

        self.channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=body,
            properties=properties,
            mandatory=mandatory
        )

        logger.debug(f"Published message to {exchange} with routing_key={routing_key}")

    def publish_binary(
        self,
        exchange: str,
        routing_key: str,
        data: bytes,
        properties: Optional[BasicProperties] = None,
        mandatory: bool = False
    ):
        """
        Publish binary data to exchange (e.g., audio chunks)

        Args:
            exchange: Exchange name
            routing_key: Routing key
            data: Binary data
            properties: Message properties
            mandatory: Require at least one queue to receive message
        """
        self.connect()

        # Default properties for binary data
        if properties is None:
            properties = BasicProperties(
                content_type='application/octet-stream',
                delivery_mode=2  # Persistent
            )

        self.channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=data,
            properties=properties,
            mandatory=mandatory
        )

        logger.debug(f"Published binary data ({len(data)} bytes) to {exchange} with routing_key={routing_key}")

    def consume(
        self,
        queue: str,
        callback: Callable,
        auto_ack: bool = False,
        prefetch_count: int = 1
    ):
        """
        Consume messages from queue

        Args:
            queue: Queue name
            callback: Callback function(channel, method, properties, body)
            auto_ack: Automatically acknowledge messages
            prefetch_count: Number of messages to prefetch
        """
        self.connect()

        # Set QoS
        self.channel.basic_qos(prefetch_count=prefetch_count)

        # Start consuming
        self.channel.basic_consume(
            queue=queue,
            on_message_callback=callback,
            auto_ack=auto_ack
        )

        logger.info(f"Started consuming from queue: {queue}")

        try:
            self.channel.start_consuming()
        except KeyboardInterrupt:
            logger.info("Stopped consuming")
            self.channel.stop_consuming()

    def ack(self, delivery_tag: int):
        """
        Acknowledge message

        Args:
            delivery_tag: Delivery tag from message
        """
        if self.channel:
            self.channel.basic_ack(delivery_tag=delivery_tag)

    def nack(self, delivery_tag: int, requeue: bool = True):
        """
        Negative acknowledge message

        Args:
            delivery_tag: Delivery tag from message
            requeue: Whether to requeue the message
        """
        if self.channel:
            self.channel.basic_nack(delivery_tag=delivery_tag, requeue=requeue)

    def health_check(self) -> bool:
        """
        Check RabbitMQ connectivity

        Returns:
            True if connected, False otherwise
        """
        try:
            self.connect()
            return self.connection is not None and self.connection.is_open
        except Exception as e:
            logger.error(f"RabbitMQ health check failed: {e}")
            return False


# Topology setup for the platform
def setup_topology(client: RabbitMQClient):
    """
    Set up RabbitMQ exchanges, queues, and bindings for the platform

    Topology:
    - audio.input (fanout) → audio.chunks.{priority}
    - transcription.output (topic) → asr.results, diarization.tasks
    - processing.output (topic) → postprocessing.tasks
    """

    # Exchanges
    client.declare_exchange('audio.input', exchange_type='fanout')
    client.declare_exchange('transcription.output', exchange_type='topic')
    client.declare_exchange('processing.output', exchange_type='topic')

    # Queues
    # Audio ingestion queues with priority
    client.declare_queue('audio.chunks.high_priority', arguments={
        'x-max-priority': 10
    })
    client.declare_queue('audio.chunks.standard')

    # ASR and diarization queues
    client.declare_queue('asr.tasks')
    client.declare_queue('diarization.tasks')

    # Post-processing queue
    client.declare_queue('postprocessing.tasks')

    # Bindings
    client.bind_queue('audio.chunks.high_priority', 'audio.input', routing_key='')
    client.bind_queue('audio.chunks.standard', 'audio.input', routing_key='')

    client.bind_queue('asr.tasks', 'transcription.output', routing_key='audio.chunk')
    client.bind_queue('diarization.tasks', 'transcription.output', routing_key='audio.segment')

    client.bind_queue('postprocessing.tasks', 'processing.output', routing_key='transcript.interim')

    logger.info("RabbitMQ topology setup complete")


# Global RabbitMQ client instance
mq_client = RabbitMQClient()
