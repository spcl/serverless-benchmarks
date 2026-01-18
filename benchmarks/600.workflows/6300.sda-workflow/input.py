import json
import os

class MemgraphConfig:
    def __init__(self, host:str, port:int, username:str, password:str):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        if self.host == "localhost":
            raise ValueError("Memgraph database for SDA workflow has to be reachable from the internet. Set the following environment variables via the command line or the SeBS .env file: \n\tMEMGRAPH_HOST\n\tMEMGRAPH_PORT\n\tMEMGRAPH_USER\n\tMEMGRAPH_PASSWORD")

    @staticmethod
    def from_env():
        with open(".env", "r") as f:
            for line in f:
                key, value = line.strip().split("=", 1)
                os.environ[key] = value
        return MemgraphConfig(
            host=os.getenv("MEMGRAPH_HOST", "localhost"),
            port=int(os.getenv("MEMGRAPH_PORT", 7687)),
            username=os.getenv("MEMGRAPH_USER", ""),
            password=os.getenv("MEMGRAPH_PASSWORD", "")
        )

class SDAConfig:
    def __init__(self, memgraph_config: MemgraphConfig, splits:int=0, required_area:float=0.0,
                  max_edge_distance:float=0.0, max_neighbours: int = 5, clustering_distance: float = 500.0,merge_workers:int=2, visualize_edges:bool= True):
        self.memgraph_config = memgraph_config
        self.splits = splits
        self.required_area = required_area
        self.max_edge_distance = max_edge_distance
        self.max_neighbours = max_neighbours
        self.clustering_distance = clustering_distance
        self.merge_workers = merge_workers
        self.visualize_edges = visualize_edges

    def get(self):
        return  {
            "binary-filters": [
                {
                    "name": "InsidePolygonFilter"
                }
            ],
            "centrality-measures": [
                {
                    "name": "DegreeCentrality"
                },
                {
                    "name": "MeanLocalSignificance"
                },
                {
                    "name": "SmallerNeighboursRatio"
                }
            ],
            "contraction-predicates": [
                {
                    "distance": self.clustering_distance,
                    "name": "DistanceBiPredicate"
                }
            ],
            "maxDistanceMeters": self.max_edge_distance,
            "maxNeighbours": self.max_neighbours,
            "memgraph-host": self.memgraph_config.host,
            "memgraph-port": self.memgraph_config.port,
            "memgraph-user": self.memgraph_config.username,
            "memgraph-password": self.memgraph_config.password,
            "merge-workers": self.merge_workers,
            "neighbouring-predicates": [],
            "splits": self.splits,
            "unary-filters": [
                {
                    "name": "ApproxAreaFilter",
                    "requiredArea": self.required_area
                }
            ],
            "visualize-edges": self.visualize_edges
        }
    
    @staticmethod
    def from_benchmark_size(size:str):
        memgraph_config:MemgraphConfig = MemgraphConfig.from_env()
        configs = {
            "test": SDAConfig(memgraph_config, splits=0, required_area=5000.0, max_edge_distance=3000.0, max_neighbours=5, clustering_distance=500.0, merge_workers=1, visualize_edges=False),
            "small": SDAConfig(memgraph_config, splits=1, required_area=500.0, max_edge_distance=1000.0, max_neighbours=5, clustering_distance=500.0, merge_workers=2, visualize_edges=True),
            "large": SDAConfig(memgraph_config, splits=2, required_area=500.0, max_edge_distance=500.0, max_neighbours=5, clustering_distance=200.0, merge_workers=2, visualize_edges=True),
        }
        return configs[size]
    
def get_config_file_name(size):
    return f"sda-config-{size}.json"

def create_config_file(size):
    config = SDAConfig.from_benchmark_size(size)
    cfg_dir = os.path.join(os.path.dirname(__file__), "cfg")
    os.makedirs(cfg_dir, exist_ok=True)
    config_file_path = os.path.join(cfg_dir, get_config_file_name(size))
    with open(config_file_path, "w") as f:
        json.dump(config.get(), f, indent=4)
    return config_file_path

def get_input_file(size):
    input_files = {
        "test" : "Corvara_IT.tiff",
        "small": "Corvara_IT.tiff",
        "large": "Wuerzburg_DE.tiff",
    }
    return input_files[size]

def buckets_count():
    return (1, 5)

def upload_all_data(upload_func,data_dir):
    sizes=["test", "small", "large"]
    for size in sizes:
        input_file = get_input_file(size)
        config_path = create_config_file(size)
        upload_func(0, input_file, os.path.join(data_dir, input_file))
        upload_func(0, get_config_file_name(size), config_path)

    

def generate_input(data_dir, size, benchmarks_bucket,input_buckets, output_buckets, upload_func, nosql_func):
    upload_all_data(upload_func,data_dir)
    return {
        "config_file": get_config_file_name(size),
        "input_file": get_input_file(size),
        "input_bucket": input_buckets[0],
        "split_output_bucket": output_buckets[0],
        "filter_output_bucket": output_buckets[1],
        "cluster_output_bucket": output_buckets[2],
        "analysis_output_bucket": output_buckets[3],
        "final_output_bucket": output_buckets[4],
        "benchmark_bucket": benchmarks_bucket
    }