# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""MinIO implementation of self-hosted, S3-compatible object storage."""

from sebs.storage.config import MinioConfig
from sebs.storage.s3compatible import S3CompatibleStorage


class Minio(S3CompatibleStorage):
    """Self-hosted MinIO storage instance running in a Docker container.

    The data volume is a host directory and the container runs as the host user,
    so the directory stays writable and removable without elevated privileges.
    """

    # Docker Hub no longer serves minio/minio; the same images are published on quay.io
    IMAGE = "quay.io/minio/minio"
    COMMAND = "server /data"
    ACCESS_KEY_ENV = "MINIO_ACCESS_KEY"
    SECRET_KEY_ENV = "MINIO_SECRET_KEY"
    HEALTH_PATH = "/minio/health/live"
    BIND_MOUNT = True
    CONFIG_TYPE = MinioConfig

    @staticmethod
    def deployment_name() -> str:
        """
        Get the deployment platform name.

        Returns:
            str: Deployment name ('minio')
        """
        return "minio"
