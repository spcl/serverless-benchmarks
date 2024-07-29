
from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.nosql import NoSQLStorage

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class Datastore(NoSQLStorage):
    @staticmethod
    def typename() -> str:
        return "GCP.Datastore"

    @staticmethod
    def deployment_name():
        return "gcp"

    @property
    def project_id(self):
        return self._project_id

    def __init__(
        self,
        benchmark: str,
        cache_client: Cache,
        resources: Resources,
        region: str,
        project_id: str
    ):
        super().__init__(benchmark, region, cache_client, resources)
        self.client = build("datastore", "v1", cache_discovery=False)
        self._project_id = project_id

    def create_table(self, table_name: str, primary_key: str):
        self.logging.info("Creating Datastore table {}".format(table_name))

        transaction = self.client.projects().beginTransaction(
            projectId=self.project_id,
            body={
                "databaseId": '', # Could be changed
                "transactionOptions": { "readWrite": {} }
            }
        ).execute()["transaction"]

        try:
            self.client.projects().commit(
                projectId=self.project_id,
                body={
                    "databaseId": '',
                    "mutations": [{
                        "insert": {
                            "key": {
                                # "partitionId": {},
                                "path": {
                                    "kind": table_name,
                                    "name": primary_key
                                }
                            }
                        }
                    }],
                    "transaction": transaction
                }
            ).execute()

            self.tables[table_name] = primary_key
            self.logging.info("Created Datastore table {}".format(table_name))
        except HttpError as err:
            if ("entity already exists" in err.content.decode("utf-8")):
                self.tables[table_name] = primary_key
                self.logging.info("Reusing existing Datastore table {}".format(table_name))
                return

            raise RuntimeError("Failed to create Datastore table: {}".format(err))

    # Recreate
    def clear_table(self, table_name: str) -> str:
        self.logging.info("Clearing Datastore table {}".format(table_name))

        primary_key = self.tables[table_name] # Need to save it
        self.remove_table(table_name)
        self.create_table(table_name, primary_key)

    def remove_table(self, table_name: str) -> str:
        self.logging.info("Removing Datastore table {}".format(table_name))

        transaction = self.client.projects().beginTransaction(
            projectId=self.project_id,
            body={
                "databaseId": '',
                "transactionOptions": { "readWrite": {} }
            }
        ).execute()["transaction"]

        self.client.projects().commit(
            projectId=self.project_id,
            body={
                "databaseId": '',
                "mutations": [{
                    "delete": {
                        "path": {
                            "kind": table_name,
                            "name": self.tables[table_name]
                        }
                    }
                }],
                "transaction": transaction
            }
        ).execute()

        del self.tables[table_name]
        self.logging.info("Removed Datastore table {}".format(table_name))