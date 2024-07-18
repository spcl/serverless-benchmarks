import subprocess 
from time import sleep 

from sebs.faas.config import Config, Credentials, Resources
from sebs.cache import Cache

from sebs.utils import LoggingHandlers
from sebs.storage.config import MinioConfig

from typing import cast, Optional

class FissionCredentials(Credentials):
    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        return FissionCredentials()

    def serialize(self) -> dict:
        return {}


class FissionResources(Resources):
    def __init__(
        self,
        registry: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        registry_updated: bool = False,
    ):
        super().__init__(name="fission")
        self._docker_registry = registry if registry != "" else None
        self._docker_username = username if username != "" else None
        self._docker_password = password if password != "" else None
        self._registry_updated = registry_updated
        self._storage: Optional[MinioConfig] = None
        self._storage_updated = False

    @staticmethod
    def typename() -> str:
        return "Fission.Resources"

    @property
    def docker_registry(self) -> Optional[str]:
        return self._docker_registry

    @property
    def docker_username(self) -> Optional[str]:
        return self._docker_username

    @property
    def docker_password(self) -> Optional[str]:
        return self._docker_password

    @property
    def storage_config(self) -> Optional[MinioConfig]:
        return self._storage

    @property
    def storage_updated(self) -> bool:
        return self._storage_updated

    @property
    def registry_updated(self) -> bool:
        return self._registry_updated

    @staticmethod
    def initialize(res: Resources, dct: dict):
        ret = cast(FissionResources, res)
        ret._docker_registry = dct["registry"]
        ret._docker_username = dct["username"]
        ret._docker_password = dct["password"]

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:

        cached_config = cache.get_config("fission")
        ret = FissionResources()
        if cached_config:
            super(FissionResources, FissionResources).initialize(
                ret, cached_config["resources"]
            )

        # Check for new config - overrides but check if it's different
        if "docker_registry" in config:

            ret.logging.info("Using user-provided Docker registry for Fission.")
            FissionResources.initialize(ret, config["docker_registry"])
            ret.logging_handlers = handlers

            # check if there has been an update
            if not (
                cached_config
                and "resources" in cached_config
                and "docker" in cached_config["resources"]
                and cached_config["resources"]["docker"] == config["docker_registry"]
            ):
                ret._registry_updated = True

        # Load cached values
        elif (
            cached_config
            and "resources" in cached_config
            and "docker" in cached_config["resources"]
        ):
            FissionResources.initialize(ret, cached_config["resources"]["docker"])
            ret.logging_handlers = handlers
            ret.logging.info("Using cached Docker registry for Fission")
        else:
            ret = FissionResources()
            ret.logging.info("Using default Docker registry for Fission.")
            ret.logging_handlers = handlers
            ret._registry_updated = True

        # Check for new config
        if "storage" in config:
            ret._storage = MinioConfig.deserialize(config["storage"])
            ret.logging.info("Using user-provided configuration of storage for Fission.")

            # check if there has been an update
            if not (
                cached_config
                and "resources" in cached_config
                and "storage" in cached_config["resources"]
                and cached_config["resources"]["storage"] == config["storage"]
            ):
                ret.logging.info(
                    "User-provided configuration is different from cached storage, "
                    "we will update existing Fission actions."
                )
                ret._storage_updated = True

        # Load cached values
        elif (
            cached_config
            and "resources" in cached_config
            and "storage" in cached_config["resources"]
        ):
            ret._storage = MinioConfig.deserialize(cached_config["resources"]["storage"])
            ret.logging.info("Using cached configuration of storage for Fission.")

        return ret 


    def create_package(self, package_name: str, path: str, env_name: str) -> None:
        # PK: Add looger 
        # logging.info(f"Deploying fission package...")
        print(f"Deploying fission package...")
        try:
            packages = subprocess.run(
                "fission package list".split(), stdout=subprocess.PIPE, check=True
            )
            subprocess.run(
                f"grep {package_name}".split(),
                check=True,
                input=packages.stdout,
                stdout=subprocess.DEVNULL,
            )
            # logging.info("Package already exist")
            print("Package already exist")
        except subprocess.CalledProcessError:
            process = f"fission package create --sourcearchive {path} \
            --name {package_name} --env {env_name} --buildcmd ./build.sh"
            subprocess.run(process.split(), check=True)
            # logging.info("Waiting for package build...")
            print("Waiting for package build...")
            while True:
                try:
                    packageStatus = subprocess.run(
                        f"fission package info --name {package_name}".split(),
                        stdout=subprocess.PIPE,
                    )
                    subprocess.run(
                        f"grep succeeded".split(),
                        check=True,
                        input=packageStatus.stdout,
                        stderr=subprocess.DEVNULL,
                    )
                    break
                except subprocess.CalledProcessError:
                    if "failed" in packageStatus.stdout.decode("utf-8"):
                        #logging.error("Build package failed")
                        print("Build package failed")
                        raise Exception("Build package failed")
                    sleep(3)
                    continue
            # logging.info("Package ready")
            print("Package ready")


    def create_enviroment(self, name: str, image: str, builder: str):
        print("Add logic to create the enviroment")
        # Here we need to create enviroment if it does not exist else get it from the cache 
        # PK: ADD Caching mechasim here so that not to create enviroment every time or query the enviroment everytime
        try:
            fission_env_list = subprocess.run(
                "fission env list ".split(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                f"grep {name}".split(),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                input=fission_env_list.stdout,
            )
            # PK: Add Logger 
            print(f"Env {name} already exist")
            # ret.logging.info(f"Env {name} already exist")
        except subprocess.CalledProcessError:
            # PK: Add Logger
            # ret.logging.info(f'Creating env for {name} using image "{image}".')
            print(f'Creating env for {name} using image "{image}".')
            try:
                subprocess.run(
                    f"fission env create --name {name} --image {image} \
                    --builder {builder}".split(),
                    check=True,
                    stdout=subprocess.DEVNULL,
                ) 
                print(f"Successfully created the enviroment {name}")
            except subprocess.CalledProcessError:
                print(f"Creating env {name} failed.")
                # PK: Add Logger
                # logging.info(f"Creating env {name} failed. Retrying...")
            # PK: Add Logger


    def update_cache(self, cache: Cache):
        super().update_cache(cache)
        cache.update_config(
            val=self.docker_registry, keys=["fission", "resources", "docker", "registry"]
        )
        cache.update_config(
            val=self.docker_username, keys=["fission", "resources", "docker", "username"]
        )
        cache.update_config(
            val=self.docker_password, keys=["fission", "resources", "docker", "password"]
        )
        if self._storage:
            self._storage.update_cache(["fission", "resources", "storage"], cache)

    def serialize(self) -> dict:
        out: dict = {
            **super().serialize(),
            "docker_registry": self.docker_registry,
            "docker_username": self.docker_username,
            "docker_password": self.docker_password,
        }
        if self._storage:
            out = {**out, "storage": self._storage.serialize()}
        return out




class FissionConfig(Config):
    name: str
    cache: Cache
    shouldShutdown: bool

    def __init__(self, config: dict, cache: Cache):
        super().__init__(name="fission")
        self._credentials = FissionCredentials()
        self._resources = FissionResources()
        self.shutdownStorage = config["shutdownStorage"]
        self.removeCluster = config["removeCluster"]
        self.fission_exec = config["fissionExec"]
        self.cache = cache
    
    @property
    def credentials(self) -> FissionCredentials:
        return self._credentials

    @property
    def resources(self) -> FissionResources:
        return self._resources

    @staticmethod
    def initialize(cfg: Config, dct: dict):
        pass

    def serialize(self) -> dict:
        return {
            "name": "fission",
            "shutdownStorage": self.shutdownStorage,
            "removeCluster": self.removeCluster,
            "fissionExec": self.fission_exec,
            "credentials": self._credentials.serialize(),
            "resources": self._resources.serialize(),
        }

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:
        cached_config = cache.get_config("fission")
        resources = cast(
            FissionResources, FissionResources.deserialize(config, cache, handlers)
        )

        res = FissionConfig(config, cached_config)
        res.logging_handlers = handlers
        res._resources = resources
        return res

    def update_cache(self, cache: Cache):
        cache.update_config(val=self.shutdownStorage, keys=["fission", "shutdownStorage"])
        cache.update_config(val=self.removeCluster, keys=["fission", "removeCluster"])
        cache.update_config(val=self.fission_exec, keys=["fission", "fissionExec"])
        self.resources.update_cache(cache)


