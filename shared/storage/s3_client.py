"""
S3-compatible storage client for audio recordings and artifacts
Supports both MinIO (self-hosted) and AWS S3
"""
import os
import logging
from typing import Optional, BinaryIO, Dict, Any
from datetime import timedelta
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Storage configuration from environment
STORAGE_ENDPOINT = os.getenv('STORAGE_ENDPOINT')  # MinIO endpoint (e.g., 'http://localhost:9000')
STORAGE_ACCESS_KEY = os.getenv('STORAGE_ACCESS_KEY', 'minioadmin')
STORAGE_SECRET_KEY = os.getenv('STORAGE_SECRET_KEY', 'minioadmin')
STORAGE_REGION = os.getenv('STORAGE_REGION', 'us-east-1')
STORAGE_BUCKET_AUDIO = os.getenv('STORAGE_BUCKET_AUDIO', 'audio-recordings')
STORAGE_BUCKET_MODELS = os.getenv('STORAGE_BUCKET_MODELS', 'ml-models')
STORAGE_USE_SSL = os.getenv('STORAGE_USE_SSL', 'false').lower() == 'true'


class S3Client:
    """S3-compatible storage client"""

    def __init__(
        self,
        endpoint_url: Optional[str] = STORAGE_ENDPOINT,
        access_key: str = STORAGE_ACCESS_KEY,
        secret_key: str = STORAGE_SECRET_KEY,
        region: str = STORAGE_REGION,
        use_ssl: bool = STORAGE_USE_SSL
    ):
        """
        Initialize S3 client

        Args:
            endpoint_url: S3 endpoint URL (None for AWS S3, set for MinIO)
            access_key: Access key ID
            secret_key: Secret access key
            region: AWS region
            use_ssl: Use SSL/TLS
        """
        self.endpoint_url = endpoint_url
        self.region = region

        # Configure boto3 client
        config = Config(
            signature_version='s3v4',
            region_name=region,
            retries={'max_attempts': 3, 'mode': 'adaptive'}
        )

        self.client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=config,
            use_ssl=use_ssl
        )

        self.resource = boto3.resource(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=config,
            use_ssl=use_ssl
        )

    def create_bucket(self, bucket_name: str):
        """
        Create a bucket if it doesn't exist

        Args:
            bucket_name: Name of the bucket
        """
        try:
            self.client.head_bucket(Bucket=bucket_name)
            logger.info(f"Bucket {bucket_name} already exists")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                # Bucket doesn't exist, create it
                try:
                    if self.region == 'us-east-1':
                        self.client.create_bucket(Bucket=bucket_name)
                    else:
                        self.client.create_bucket(
                            Bucket=bucket_name,
                            CreateBucketConfiguration={'LocationConstraint': self.region}
                        )
                    logger.info(f"Created bucket: {bucket_name}")
                except ClientError as create_error:
                    logger.error(f"Failed to create bucket {bucket_name}: {create_error}")
                    raise
            else:
                logger.error(f"Error checking bucket {bucket_name}: {e}")
                raise

    def upload_file(
        self,
        file_path: str,
        bucket: str,
        object_name: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        content_type: Optional[str] = None
    ) -> str:
        """
        Upload a file to S3

        Args:
            file_path: Path to file to upload
            bucket: Bucket name
            object_name: S3 object name (defaults to file basename)
            metadata: Optional metadata dict
            content_type: Content type (e.g., 'audio/wav')

        Returns:
            S3 object key
        """
        if object_name is None:
            object_name = os.path.basename(file_path)

        extra_args = {}
        if metadata:
            extra_args['Metadata'] = metadata
        if content_type:
            extra_args['ContentType'] = content_type

        try:
            self.client.upload_file(
                file_path,
                bucket,
                object_name,
                ExtraArgs=extra_args if extra_args else None
            )
            logger.info(f"Uploaded {file_path} to s3://{bucket}/{object_name}")
            return object_name
        except ClientError as e:
            logger.error(f"Failed to upload {file_path}: {e}")
            raise

    def upload_fileobj(
        self,
        file_obj: BinaryIO,
        bucket: str,
        object_name: str,
        metadata: Optional[Dict[str, str]] = None,
        content_type: Optional[str] = None
    ) -> str:
        """
        Upload a file-like object to S3

        Args:
            file_obj: File-like object to upload
            bucket: Bucket name
            object_name: S3 object name
            metadata: Optional metadata dict
            content_type: Content type

        Returns:
            S3 object key
        """
        extra_args = {}
        if metadata:
            extra_args['Metadata'] = metadata
        if content_type:
            extra_args['ContentType'] = content_type

        try:
            self.client.upload_fileobj(
                file_obj,
                bucket,
                object_name,
                ExtraArgs=extra_args if extra_args else None
            )
            logger.info(f"Uploaded file object to s3://{bucket}/{object_name}")
            return object_name
        except ClientError as e:
            logger.error(f"Failed to upload file object: {e}")
            raise

    def download_file(
        self,
        bucket: str,
        object_name: str,
        file_path: str
    ):
        """
        Download a file from S3

        Args:
            bucket: Bucket name
            object_name: S3 object name
            file_path: Local file path to save to
        """
        try:
            self.client.download_file(bucket, object_name, file_path)
            logger.info(f"Downloaded s3://{bucket}/{object_name} to {file_path}")
        except ClientError as e:
            logger.error(f"Failed to download {object_name}: {e}")
            raise

    def download_fileobj(
        self,
        bucket: str,
        object_name: str,
        file_obj: BinaryIO
    ):
        """
        Download an S3 object to a file-like object

        Args:
            bucket: Bucket name
            object_name: S3 object name
            file_obj: File-like object to write to
        """
        try:
            self.client.download_fileobj(bucket, object_name, file_obj)
            logger.info(f"Downloaded s3://{bucket}/{object_name} to file object")
        except ClientError as e:
            logger.error(f"Failed to download {object_name}: {e}")
            raise

    def delete_object(self, bucket: str, object_name: str):
        """
        Delete an object from S3

        Args:
            bucket: Bucket name
            object_name: S3 object name
        """
        try:
            self.client.delete_object(Bucket=bucket, Key=object_name)
            logger.info(f"Deleted s3://{bucket}/{object_name}")
        except ClientError as e:
            logger.error(f"Failed to delete {object_name}: {e}")
            raise

    def list_objects(
        self,
        bucket: str,
        prefix: str = '',
        max_keys: int = 1000
    ) -> list:
        """
        List objects in bucket

        Args:
            bucket: Bucket name
            prefix: Object key prefix filter
            max_keys: Maximum number of keys to return

        Returns:
            List of object keys
        """
        try:
            response = self.client.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                MaxKeys=max_keys
            )
            if 'Contents' in response:
                return [obj['Key'] for obj in response['Contents']]
            return []
        except ClientError as e:
            logger.error(f"Failed to list objects in {bucket}: {e}")
            raise

    def generate_presigned_url(
        self,
        bucket: str,
        object_name: str,
        expiration: int = 3600,
        http_method: str = 'GET'
    ) -> str:
        """
        Generate a presigned URL for temporary access to an object

        Args:
            bucket: Bucket name
            object_name: S3 object name
            expiration: URL expiration time in seconds
            http_method: HTTP method (GET, PUT, etc.)

        Returns:
            Presigned URL
        """
        try:
            if http_method == 'GET':
                url = self.client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': bucket, 'Key': object_name},
                    ExpiresIn=expiration
                )
            elif http_method == 'PUT':
                url = self.client.generate_presigned_url(
                    'put_object',
                    Params={'Bucket': bucket, 'Key': object_name},
                    ExpiresIn=expiration
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {http_method}")

            logger.info(f"Generated presigned URL for s3://{bucket}/{object_name}")
            return url
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise

    def set_lifecycle_policy(
        self,
        bucket: str,
        days_to_expiration: int,
        prefix: str = ''
    ):
        """
        Set lifecycle policy to auto-delete objects after N days

        Args:
            bucket: Bucket name
            days_to_expiration: Number of days until object deletion
            prefix: Object key prefix to apply policy to
        """
        lifecycle_config = {
            'Rules': [
                {
                    'Id': f'expire-after-{days_to_expiration}-days',
                    'Status': 'Enabled',
                    'Prefix': prefix,
                    'Expiration': {
                        'Days': days_to_expiration
                    }
                }
            ]
        }

        try:
            self.client.put_bucket_lifecycle_configuration(
                Bucket=bucket,
                LifecycleConfiguration=lifecycle_config
            )
            logger.info(f"Set lifecycle policy on {bucket} to delete objects after {days_to_expiration} days")
        except ClientError as e:
            logger.error(f"Failed to set lifecycle policy: {e}")
            raise

    def health_check(self) -> bool:
        """
        Check S3 connectivity

        Returns:
            True if S3 is accessible, False otherwise
        """
        try:
            self.client.list_buckets()
            return True
        except ClientError as e:
            logger.error(f"S3 health check failed: {e}")
            return False


# Global storage client instance
storage_client = S3Client()


def initialize_storage():
    """Initialize storage buckets"""
    try:
        storage_client.create_bucket(STORAGE_BUCKET_AUDIO)
        storage_client.create_bucket(STORAGE_BUCKET_MODELS)

        # Set lifecycle policy to delete audio after 30 days (compliance/cost)
        storage_client.set_lifecycle_policy(STORAGE_BUCKET_AUDIO, days_to_expiration=30)

        logger.info("Storage initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize storage: {e}")
        raise
