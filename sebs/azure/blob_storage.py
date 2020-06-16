import logging
import uuid
from typing import List

from azure.storage.blob import BlobServiceClient

from sebs.cache import Cache
from ..faas.storage import PersistentStorage

class BlobStorage(PersistentStorage)

    cached = False
    input_containers: List[str] = []
    input_containers_files: List[str] = []
    output_containers: List[str] = []
    temporary_containers: List[str] = []
    _replace_existing = False

    @property
    def replace_existing(self):
        return self._replace_existing

    @replace_existing.setter
    def replace_existing(self, val: bool):
        self._replace_existing = val

    def __init__(self, cache_client: Cache, conn_string: str, replace_existing: bool):
        self.client = BlobServiceClient.from_connection_string(conn_string)
        self.replace_existing = replace_existing

    def input(self): # noqa: A003
        return self.input_containers

    def output(self):
        return self.output_containers

    def create_container(self, name, containers=None):
        found_container = False
        if containers:
            for c in containers:
                container_name = c['name']
                if name in container_name:
                    found_container = True
                    break
        if not found_container:
            random_name = str(uuid.uuid4())[0:16]
            name = '{}-{}'.format(name, random_name)
            self.client.create_container(name)
            logging.info('Created container {}'.format(name))
            return name
        else:
            logging.info('Container {} for {} already exists, skipping.'.format(container_name, name))
            return container_name

    '''
        Azure does not allow dots in container names.
    '''
    def correct_name(self, name :str):
        return name.replace('.', '-')

    '''
    '''
    def add_output_container(self, name :str, suffix: str='output'):

        name = '{}-{}'.format(name, suffix)
        cont_name = self.create_container(self.correct_name(name))
        self.temporary_containers.append(cont_name)
        return cont_name

    def create_buckets(self, benchmark, buckets, cached_buckets):
        if cached_buckets:
            self.input_containers = cached_buckets['containers']['input']
            for container in self.input_containers:
                self.input_containers_files.append(
                    list(
                        map(
                            lambda x : x['name'],
                            self.client.get_container_client(container).list_blobs()
                        )
                    )
                )
            self.output_containers = cached_buckets['containers']['output']
            # Clean output container for new execution.
            for container in self.output_containers:
                logging.info('Clean output container {}'.format(container))
                container_client = self.client.get_container_client(container)
                blobs = list(map(
                            lambda x : x['name'],
                            container_client.list_blobs()
                        ))
                #TODO: reenable with a try/except for failed deletions
                #container_client.delete_blobs(*blobs)

            self.cached = True
            logging.info('Using cached storage input containers {}'.format(self.input_containers))
            logging.info('Using cached storage output containers {}'.format(self.output_containers))
        else:
            benchmark = self.correct_name(benchmark)
            # get existing containers which might fit the benchmark
            containers = self.client.list_containers(
                    name_starts_with=benchmark
            )
            for i in range(0, buckets[0]):
                self.input_containers.append(
                    self.create_container(
                        '{}-{}-input'.format(benchmark, i),
                        containers
                    )
                )
                container = self.input_containers[-1]
                self.input_containers_files.append(
                    list(
                        map(
                            lambda x : x['name'],
                            self.client.get_container_client(container).list_blobs()
                        )
                    )
                )
            for i in range(0, buckets[1]):
                self.output_containers.append(
                    self.create_container(
                        '{}-{}-output'.format(benchmark, i),
                        containers
                    )
                )

    def uploader_func(self, container_idx, file, filepath):
        # Skip upload when using cached containers
        if self.cached and not self.replace_existing:
            return
        container_name = self.input_containers[container_idx]
        if not self.replace_existing:
            for f in self.input_containers_files[container_idx]:
                if f == file:
                    logging.info('Skipping upload of {} to {}'.format(filepath, container_name))
                    return
        client = self.client.get_blob_client(container_name, file)
        with open(filepath, 'rb') as file_data:
            client.upload_blob(data=file_data, overwrite=True)
        logging.info('Upload {} to {}'.format(filepath, container_name))

    '''
        Download file from bucket.

        :param container_name:
        :param file:
        :param filepath:
    '''
    def download(self, container_name :str, file :str, filepath :str):
        logging.info('Download {}:{} to {}'.format(container_name, file, filepath))
        client = self.client.get_blob_client(container_name, file)
        with open(filepath, 'wb') as download_file:
            download_file.write( client.download_blob().readall() )

    '''
        Return list of files in a container.

        :param container:
        :return: list of file names. empty if container empty
    '''
    def list_bucket(self, container :str):
        objects = list(
            map(
                lambda x : x['name'],
                self.client.get_container_client(container).list_blobs()
            )
        )
        return objects
