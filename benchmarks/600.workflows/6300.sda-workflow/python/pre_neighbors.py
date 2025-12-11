import re

class Coordinate:
    def __init__(self,x:int,y:int):
        self.x = x
        self.y = y

    def chebyshev_distance(self, other) -> int:
        return max(abs(self.x - other.x), abs(self.y - other.y))

    @staticmethod
    def from_filename(filename: str):
        match = re.search(r'.+_(\d+)_(\d+)_filtered.shp', filename)
        if match:
            filename = match.group(1)
            coord = Coordinate(int(match.group(1)), int(match.group(2)))
            return coord
        else:
            raise ValueError("Filename does not match expected pattern")

class SpatialFile:
    def __init__(self, filename: str):
        self.filename = filename
        self.coordinate = Coordinate.from_filename(filename)
        self.neighbors = []
    
    def add_neighbor(self, neighbor_filename: str):
        self.neighbors.append(neighbor_filename)

    def __eq__(self, other) -> bool:
        if not isinstance(other, SpatialFile):
            return False
        return self.filename == other.filename
    
    def is_adjacent(self, other) -> bool:
        return self.coordinate.chebyshev_distance(other.coordinate) <= 1
        
def handler(event):
    files = [SpatialFile(file_workload["filtered_shp_file"]) for file_workload in event["filter_workloads"]]
    for file in files:
        for other_file in files:
            if file != other_file and file.is_adjacent(other_file):
                file.add_neighbor(other_file.filename)
    event.pop("filter_workloads", None)
    return {
        "neighbors_workloads":[
            {
                "filtered_shp_file": file.filename,
                "adjacent_files": file.neighbors,
                **event
            } for file in files
        ],
        **event
    }