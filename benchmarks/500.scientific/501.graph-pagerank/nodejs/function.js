const createGraph = require('ngraph.graph');
const pagerank = require('ngraph.pagerank');

function generateBarabasiAlbertGraph(size, m) {
	const graph = createGraph();

	for (let i = 0; i < m; i++) {
		graph.addNode(i);
		for (let j = 0; j < i; j++) {
			graph.addLink(i, j);
		}
	}

	for (let i = m; i < size; i++) {
		graph.addNode(i);
		let targets = [];
		let totalDegree = 0;
		graph.forEachNode(node => {
			totalDegree += (graph.getLinks(node.id) || []).length;
		});

		graph.forEachNode(node => {
			const degree = (graph.getLinks(node.id) || []).length;
			const probability = degree / totalDegree;
			if (Math.random() < probability && targets.length < m) {
				targets.push(node.id);
			}
		});

		while (targets.length < m) {
			let randomNode;
			do {
				randomNode = Math.floor(Math.random() * i);
			} while (targets.includes(randomNode));
			targets.push(randomNode);
		}

		targets.forEach(target => {
			graph.addLink(i, target);
		});
	}

	return graph;
}

exports.handler = async function(event) {
	const size = event.size;

	const graphGeneratingBegin = new Date();
	const graph = generateBarabasiAlbertGraph(size, 10);
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
