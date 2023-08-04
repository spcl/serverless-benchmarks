import datetime
import igraph

def handler(event):

    size = event.get('size')
    if size is None or not isinstance(size, (int, float)):
        return { "status": "failure", 'result': 'Some value(s) is/are not found in JSON data or of incorrect type' }

    graph_generating_begin = datetime.datetime.now()
    graph = igraph.Graph.Barabasi(size, 10)
    graph_generating_end = datetime.datetime.now()

    process_begin = datetime.datetime.now()
    result = graph.bfs(0)
    process_end = datetime.datetime.now()

    graph_generating_time = (graph_generating_end - graph_generating_begin) / datetime.timedelta(microseconds=1)
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)

    return {
            'status': 'success',
            'result': "Returned with no error",
            'measurement': {
                'graph_generating_time': graph_generating_time,
                'compute_time': process_time,
                'result': result
            }
    }
