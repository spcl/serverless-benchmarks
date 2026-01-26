import json
import os
from typing import cast, List, Optional, Tuple
import time
from googleapiclient.errors import HttpError

from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources
from sebs.utils import LoggingHandlers

# FIXME: Replace type hints for static generators after migration to 3.7
# https://stackoverflow.com/questions/33533148/how-do-i-specify-that-the-return-type-of-a-method-is-the-same-as-the-class-itsel

"""
    Credentials for FaaS system used to authorize operations on functions
    and other resources.

    The order of credentials initialization:
    1. Load credentials from cache.
    2. If any new values are provided in the config, they override cache values.
    3. If nothing is provided, initialize using environmental variables.
    4. If no information is provided, then failure is reported.
"""


class GCPCredentials(Credentials):
    def __init__(self, gcp_credentials: str):
        super().__init__()

        self._gcp_credentials = gcp_credentials

        gcp_data = json.load(open(self._gcp_credentials, "r"))
        self._project_id = gcp_data["project_id"]

    @property
    def gcp_credentials(self) -> str:
        return self._gcp_credentials

    @property
    def project_name(self) -> str:
        return self._project_id

    @staticmethod
    def initialize(gcp_credentials: str) -> "GCPCredentials":
        return GCPCredentials(gcp_credentials)

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:

        cached_config = cache.get_config("gcp")
        ret: GCPCredentials
        project_id: Optional[str] = None

        # Load cached values
        if cached_config and "credentials" in cached_config:
            project_id = cached_config["credentials"]["project_id"]

        # Check for new config
        if "credentials" in config and "credentials-json" in config["credentials"]:
            ret = GCPCredentials.initialize(config["credentials"]["credentials-json"])
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ret.gcp_credentials
        # Look for default GCP credentials
        elif "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
            ret = GCPCredentials(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
        # Look for our environment variables
        elif "GCP_SECRET_APPLICATION_CREDENTIALS" in os.environ:
            ret = GCPCredentials(os.environ["GCP_SECRET_APPLICATION_CREDENTIALS"])
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ret.gcp_credentials
        else:
            raise RuntimeError(
                "GCP login credentials are missing! Please set the path to .json "
                "with cloud credentials in config or in the GCP_SECRET_APPLICATION_CREDENTIALS "
                "environmental variable"
            )
        ret.logging_handlers = handlers

        if project_id is not None and project_id != ret._project_id:
            ret.logging.error(
                f"The project id {ret._project_id} from provided "
                f"credentials is different from the ID {project_id} in the cache! "
                "Please change your cache directory or create a new one!"
            )
            raise RuntimeError(
                f"GCP login credentials do not match the project {project_id} in cache!"
            )

        return ret

    """
        Serialize to JSON for storage in cache.
    """

    def serialize(self) -> dict:
        out = {"project_id": self._project_id}
        return out

    def update_cache(self, cache: Cache):
        cache.update_config(val=self._project_id, keys=["gcp", "credentials", "project_id"])


"""
    Class grouping resources allocated at the FaaS system to execute functions
    and deploy various services. Examples might include IAM roles and API gateways
    for HTTP triggers.

    Storage resources are handled seperately.
"""


class GCPResources(Resources):
    def __init__(self):
        super().__init__(name="gcp")
        self._container_repository = None

    @staticmethod
    def initialize(res: Resources, dct: dict):
        ret = cast(GCPResources, res)
        super(GCPResources, GCPResources).initialize(ret, dct)
        return ret

    """
        Serialize to JSON for storage in cache.
    """

    def serialize(self) -> dict:
        out = super().serialize()
        out["container_repository"] = self._container_repository
        return out

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> "Resources":

        cached_config = cache.get_config("gcp")
        ret = GCPResources()
        if cached_config and "resources" in cached_config:
            GCPResources.initialize(ret, cached_config["resources"])
            ret.logging_handlers = handlers
            ret.logging.info("Using cached resources for GCP")
        else:

            if "resources" in config:
                GCPResources.initialize(ret, config["resources"])
                ret.logging_handlers = handlers
                ret.logging.info("No cached resources for GCP found, using user configuration.")
            else:
                GCPResources.initialize(ret, {})
                ret.logging_handlers = handlers
                ret.logging.info("No resources for GCP found, initialize!")

        return ret

    def update_cache(self, cache: Cache):
        super().update_cache(cache)

    @property
    def container_repository(self) -> str:
        return self._container_repository

    def check_container_repository_exists(self, config: Config, ar_client):
        try:
            parent = f"projects/{config.credentials.project_name}/locations/{config.region}"
            repo_full_name = f"{parent}/repositories/{self._container_repository}"
            self.logging.info("Checking if container repository exists...")
            ar_client.projects().locations().repositories().get(name=repo_full_name).execute()
            return True
        except HttpError as e:
            if e.resp.status == 404:
                self.logging.error("Container repository does not exist.")
                return False
            else:
                raise e

    def create_container_repository(self, ar_client, parent):
        request_body = {
            "format": "DOCKER",
            "description": "Container repository for SEBS"
        }
        self._container_repository = f"sebs-benchmarks-{self._resources_id}"
        operation = ar_client.projects().locations().repositories().create(
            parent=parent,
            body=request_body,
            repositoryId=self._container_repository
        ).execute()
        
        while True:
            # Operations for AR are global or location specific
            op_name = operation['name']
            op = ar_client.projects().locations().operations().get(name=op_name).execute()
            
            if op.get('done'):
                if 'error' in op:
                    raise Exception(f"Failed to create repo: {op['error']}")
                self.logging.info("Repository created successfully.")
                break
            time.sleep(2)

    def get_container_repository(self, config: Config, ar_client):
        if self._container_repository is not None:
            return self._container_repository
        
        self._container_repository = f"sebs-benchmarks-{self._resources_id}"
        if self.check_container_repository_exists(config, ar_client):
            return self._container_repository

        parent = f"projects/{config.credentials.project_name}/locations/{config.region}"
        self.create_container_repository(ar_client, parent)
        return self._container_repository

        

"""
    FaaS system config defining cloud region (if necessary), credentials and
    resources allocated.
"""


class GCPConfig(Config):

    _project_name: str

    def __init__(self, credentials: GCPCredentials, resources: GCPResources):
        super().__init__(name="gcp")
        self._credentials = credentials
        self._resources = resources

    @property
    def region(self) -> str:
        return self._region

    @property
    def project_name(self) -> str:
        return self.credentials.project_name

    @property
    def credentials(self) -> GCPCredentials:
        return self._credentials

    @property
    def resources(self) -> GCPResources:
        return self._resources

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> "Config":
        cached_config = cache.get_config("gcp")
        credentials = cast(GCPCredentials, GCPCredentials.deserialize(config, cache, handlers))
        resources = cast(GCPResources, GCPResources.deserialize(config, cache, handlers))
        config_obj = GCPConfig(credentials, resources)
        config_obj.logging_handlers = handlers

        if cached_config:
            config_obj.logging.info("Loading cached config for GCP")
            GCPConfig.initialize(config_obj, cached_config)
        else:
            config_obj.logging.info("Using user-provided config for GCP")
            GCPConfig.initialize(config_obj, config)

        # mypy makes a mistake here
        updated_keys: List[Tuple[str, Tuple[str]]] = [["region", ["gcp", "region"]]]  # type: ignore
        # for each attribute here, check if its version is different than the one provided by
        # user; if yes, then update the value
        for config_key, keys in updated_keys:

            old_value = getattr(config_obj, config_key)
            # ignore empty values
            if getattr(config_obj, config_key) != config[config_key] and config[config_key]:
                config_obj.logging.info(
                    f"Updating cached key {config_key} with {old_value} "
                    f"to user-provided value {config[config_key]}."
                )
                setattr(config_obj, f"_{config_key}", config[config_key])
                cache.update_config(val=getattr(config_obj, config_key), keys=keys)

        return config_obj

    @staticmethod
    def initialize(cfg: Config, dct: dict):
        config = cast(GCPConfig, cfg)
        config._region = dct["region"]

    def serialize(self) -> dict:
        out = {
            "name": "gcp",
            "region": self._region,
            "credentials": self._credentials.serialize(),
            "resources": self._resources.serialize(),
        }
        return out

    def update_cache(self, cache: Cache):
        cache.update_config(val=self.region, keys=["gcp", "region"])
        self.credentials.update_cache(cache)
        self.resources.update_cache(cache)
