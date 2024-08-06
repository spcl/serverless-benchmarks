# #!/usr/bin/env python3
# from sebs.faas.storage import PersistentStorage
# from typing import List, Tuple, Any
# import logging
# from time import sleep
# import minio
# import secrets
# import os
#
#
# class Minio(PersistentStorage):
#
#     storage_container: Any
#     input_buckets: List[str] = []
#     output_buckets: List[str] = []
#     input_index = 0
#     output_index = 0
#     access_key: str = ""
#     secret_key: str = ""
#     port = 9000
#     location = "fissionBenchmark"
#     connection: Any
#     docker_client = None
#
#     def __init__(self, docker_client):
#         self.docker_client = docker_client
#         self.start()
#         sleep(10)
#         self.connection = self.get_connection()
#
#     def start(self):
#         self.startMinio()
#
#     def startMinio(self):
#         minioVersion = "minio/minio:latest"
#         self.access_key = secrets.token_urlsafe(32)
#         self.secret_key = secrets.token_hex(32)
#         logging.info("Minio container starting")
#         logging.info("ACCESS_KEY={}".format(self.access_key))
#         logging.info("SECRET_KEY={}".format(self.secret_key))
#         self.storage_container = self.docker_client.containers.run(
#             minioVersion,
#             command="server /data",
#             ports={str(self.port): self.port},
#             environment={
#                 "MINIO_ACCESS_KEY": self.access_key,
#                 "MINIO_SECRET_KEY": self.secret_key,
#             },
#             remove=True,
#             stdout=True,
#             stderr=True,
#             detach=True,
#         )
#         self.storage_container.reload()
#         networks = self.storage_container.attrs["NetworkSettings"]["Networks"]
#         self.url = "{IPAddress}:{Port}".format(
#             IPAddress=networks["bridge"]["IPAddress"], Port=self.port
#         )
#         logging.info("Started minio instance at {}".format(self.url))
#
#     def get_connection(self):
#         return minio.Minio(
#             self.url,
#             access_key=self.access_key,
#             secret_key=self.secret_key,
#             secure=False,
#         )
#
#     def input(self) -> List[str]:
#         return self.input_buckets
#
#     def add_input_bucket(self, name: str, cache: bool = True) -> Tuple[str, int]:
#         input_index = self.input_index
#         bucket_name = "{}-{}-input".format(name, input_index)
#         exist = self.connection.bucket_exists(bucket_name)
#         try:
#             if cache:
#                 self.input_index += 1
#                 if exist:
#                     return (bucket_name, input_index)
#                 else:
#                     self.connection.make_bucket(bucket_name, location=self.location)
#                     self.input_buckets.append(bucket_name)
#                     return (bucket_name, input_index)
#             if exist:
#                 return (bucket_name, input_index)
#             self.connection.make_bucket(bucket_name, location=self.location)
#             self.input_buckets.append(bucket_name)
#             return (bucket_name, input_index)
#         except (
#             minio.error.BucketAlreadyOwnedByYou,
#             minio.error.BucketAlreadyExists,
#             minio.error.ResponseError,
#         ) as err:
#             logging.error("Bucket creation failed!")
#             raise err
#
#     def add_output_bucket(
#         self, name: str, suffix: str = "output", cache: bool = True
#     ) -> Tuple[str, int]:
#         output_index = self.output_index
#         bucket_name = "{}-{}-{}".format(name, output_index, suffix)
#         exist = self.connection.bucket_exists(bucket_name)
#         try:
#             if cache:
#                 self.output_index += 1
#                 if exist:
#                     return (bucket_name, output_index)
#                 else:
#                     self.connection.make_bucket(bucket_name, location=self.location)
#                     self.output_buckets.append(bucket_name)
#                     return (bucket_name, output_index)
#             if exist:
#                 return (bucket_name, output_index)
#             self.connection.make_bucket(bucket_name, location=self.location)
#             self.output_buckets.append(bucket_name)
#             return (bucket_name, output_index)
#         except (
#             minio.error.BucketAlreadyOwnedByYou,
#             minio.error.BucketAlreadyExists,
#             minio.error.ResponseError,
#         ) as err:
#             logging.error("Bucket creation failed!")
#             raise err
#
#     def output(self) -> List[str]:
#         return self.output_buckets
#
#     def download(self, bucket_name: str, key: str, filepath: str) -> None:
#         objects = self.connection.list_objects_v2(bucket_name)
#         objects = [obj.object_name for obj in objects]
#         for obj in objects:
#             self.connection.fget_object(bucket_name, obj, os.path.join(filepath, obj))
#
#     def upload(self, bucket_name: str, filepath: str, key: str):
#         self.connection.put_object(bucket_name, filepath)
#
#     def list_bucket(self, bucket_name: str) -> List[str]:
#         buckets = []
#         for bucket in self.connection.list_buckets():
#             if bucket.name == bucket_name:
#                 buckets.append(bucket.name)
#         return buckets
#
#     def allocate_buckets(self, benchmark: str, buckets: Tuple[int, int]):
#         inputNumber = buckets[0]
#         outputNumber = buckets[1]
#         for i in range(inputNumber):
#             self.add_input_bucket(benchmark)
#         for i in range(outputNumber):
#             self.add_output_bucket(benchmark)
#
#     def uploader_func(self, bucket_idx: int, file: str, filepath: str) -> None:
#         pass
