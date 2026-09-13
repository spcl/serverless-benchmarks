const createGraph = require('ngraph.graph');
const pagerank = require('ngraph.pagerank');

const { xoroshiro128plus } = require('pure-rand/generator/xoroshiro128plus');
const { uniformFloat64 } = require('pure-rand/distribution/uniformFloat64');
const { uniformInt } = require('pure-rand/distribution/uniformInt');

function randomDistinctSubset(pool, k, prng) {
  // Perform successive weighted sampling without replacement.
  //
  // Pick `k` distinct elements from `pool`, sampling uniformly with replacement
  // and rejecting duplicates (via a Set). Uniform draws over the repeated-nodes
  // bag yield degree-proportional selection.
  const chosen = new Set();
  while (chosen.size < k) {
    const idx = uniformInt(prng, 0, pool.length - 1);
    chosen.add(pool[idx]);
  }
  return [...chosen];
}

function generateBarabasiAlbertGraph(seed, size, m) {

  if (size < 1) throw new Error('require size >= 1');
  if (m < 1) throw new Error('require m >= 1');

  // This is a "hack" to make our implemnetation match the reference implementation in igraph.
  // We do not use the same approach as igraph.
  //
  // We verified that when size == m, igraph returns complete graph with N nodes
  // and N*(N-1)/2 edges. So we do the same here.
  if (m >= size - 1) {
    const complete = createGraph();
    for (let i = 0; i < size; i++) {
      complete.addNode(i);
    }
    for (let i = 0; i < size; i++) {
      for (let j = 0; j < i; j++) {
        // connect source to its m distinct targets
        // since other benchmark versions (Python, C++) are undirected,
        // we add links in both directions
        complete.addLink(i, j);
        complete.addLink(j, i);
      }
    }
    return complete;
  }

  // Use the default recommended PRNG choice
  let prng = xoroshiro128plus(seed);

	const graph = createGraph();

  for (let i = 0; i < m; i++) {
    graph.addNode(i);
  }
 
  // initial attachment targets: the m seed nodes
  let targets = [];
  for (let i = 0; i < m; i++) {
    targets.push(i);
  }
 
  // bag of edge endpoints (empty until the first source is wired up)
  const repeatedNodes = [];
 
  for (let source = m; source < size; source++) {
    graph.addNode(source);
 
    // connect source to its m distinct targets
    // since other benchmark versions (Python, C++) are undirected,
    // we add links in both directions
    for (const t of targets) {
      graph.addLink(source, t);
      graph.addLink(t, source);
    }
 
    // every new edge contributes both endpoints to the bag
    for (const t of targets) {
      repeatedNodes.push(t);
      repeatedNodes.push(source);
    }
 
    // choose m DISTINCT targets for the next source, degree-proportionally
    // skip at the last iteration since it will not be used.
    if (source + 1 < size) {
      targets = randomDistinctSubset(repeatedNodes, m, prng);
    }
  }

	return graph;
}

exports.handler = async function(event) {
	const size = event.size;

	const graphGeneratingBegin = new Date();
	const graph = generateBarabasiAlbertGraph(event.seed, size, 10);
	const graphGeneratingEnd = new Date();

	const processBegin = new Date();
	const result = pagerank(graph);
	const processEnd = new Date();

	const graphGeneratingTime = graphGeneratingEnd - graphGeneratingBegin;
	const processTime = processEnd - processBegin;

	const firstNodeRank = result['0'] || 0;

	return {
		result: firstNodeRank,
		measurement: {
			graph_generating_time: graphGeneratingTime,
			compute_time: processTime
		}
	};
};
