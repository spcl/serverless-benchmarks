# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""RustFS implementation of self-hosted, S3-compatible object storage."""

from sebs.storage.config import RustFSConfig
from sebs.storage.s3compatible import S3CompatibleStorage


class RustFS(S3CompatibleStorage):
    """Self-hosted RustFS storage instance running in a Docker container.

    RustFS runs as a fixed, unprivileged user inside the container, so the data
    is kept in a named Docker volume instead of a host directory.
    """

    IMAGE = "rustfs/rustfs"
    COMMAND = None
    ACCESS_KEY_ENV = "RUSTFS_ACCESS_KEY"
    SECRET_KEY_ENV = "RUSTFS_SECRET_KEY"
    HEALTH_PATH = "/health"
    BIND_MOUNT = False
    CONFIG_TYPE = RustFSConfig

    @staticmethod
    def deployment_name() -> str:
        """
        Get the deployment platform name.

        Returns:
            str: Deployment name ('rustfs')
        """
        return "rustfs"
