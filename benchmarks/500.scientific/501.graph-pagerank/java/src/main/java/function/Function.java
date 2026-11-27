// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
package function;

import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

/**
 * PageRank of a Barabási–Albert graph, generated as in the Node.js version but with SplitMix64.
 *
 * <p>Written without libraries, so that other languages can implement the same steps in the
 * same order and get exactly the same result.
 */
public class Function {

    private static final int M = 10;
    private static final double DAMPING = 0.85;
    private static final double TOLERANCE = 1e-10;
    private static final int MAX_ITERATIONS = 1000;

    public Map<String, Object> handler(Map<String, Object> event) {
        int size = ((Number) event.get("size")).intValue();
        long seed =
                event.containsKey("seed")
                        ? ((Number) event.get("seed")).longValue()
                        : System.nanoTime();

        long graphBegin = System.nanoTime();
        Graph graph = barabasiAlbert(size, M, new SplitMix64(seed));
        long graphEnd = System.nanoTime();

        long computeBegin = System.nanoTime();
        double[] rank = pagerank(graph);
        long computeEnd = System.nanoTime();

        Map<String, Object> measurement = new HashMap<>();
        measurement.put("graph_generating_time", (graphEnd - graphBegin) / 1000);
        measurement.put("compute_time", (computeEnd - computeBegin) / 1000);

        Map<String, Object> result = new HashMap<>();
        result.put("result", rank[0]);
        result.put("measurement", measurement);
        return result;
    }

    /** SplitMix64 random number generator. */
    static final class SplitMix64 {
        private long state;

        SplitMix64(long seed) {
            this.state = seed;
        }

        long next() {
            state += 0x9E3779B97F4A7C15L;
            long z = state;
            z = (z ^ (z >>> 30)) * 0xBF58476D1CE4E5B9L;
            z = (z ^ (z >>> 27)) * 0x94D049BB133111EBL;
            return z ^ (z >>> 31);
        }

        /** An integer in [0, bound). */
        int nextInt(int bound) {
            return (int) Long.remainderUnsigned(next(), bound);
        }
    }

    /** Undirected graph in compressed sparse row form, neighbors in edge insertion order. */
    static final class Graph {
        final int nodes;
        final int[] offsets;
        final int[] adjacency;

        Graph(int nodes, int[] offsets, int[] adjacency) {
            this.nodes = nodes;
            this.offsets = offsets;
            this.adjacency = adjacency;
        }
    }

    static Graph barabasiAlbert(int size, int m, SplitMix64 random) {
        if (m >= size - 1) {
            int edgeCount = size * (size - 1) / 2;
            int[] from = new int[edgeCount];
            int[] to = new int[edgeCount];
            int e = 0;
            for (int i = 0; i < size; i++) {
                for (int j = 0; j < i; j++) {
                    from[e] = i;
                    to[e] = j;
                    e++;
                }
            }
            return toCsr(size, from, to);
        }

        int edgeCount = m * (size - m);
        int[] from = new int[edgeCount];
        int[] to = new int[edgeCount];
        int e = 0;
        // A uniform draw from all edge endpoints picks a node in proportion to its degree
        int[] endpoints = new int[2 * edgeCount];
        int endpointCount = 0;
        int[] targets = new int[m];
        for (int i = 0; i < m; i++) {
            targets[i] = i;
        }

        for (int source = m; source < size; source++) {
            for (int t = 0; t < m; t++) {
                from[e] = source;
                to[e] = targets[t];
                e++;
                endpoints[endpointCount++] = targets[t];
                endpoints[endpointCount++] = source;
            }
            // Targets of the next node
            if (source + 1 < size) {
                int chosen = 0;
                while (chosen < m) {
                    int candidate = endpoints[random.nextInt(endpointCount)];
                    if (!contains(targets, chosen, candidate)) {
                        targets[chosen++] = candidate;
                    }
                }
            }
        }
        return toCsr(size, from, to);
    }

    private static boolean contains(int[] values, int count, int value) {
        for (int i = 0; i < count; i++) {
            if (values[i] == value) {
                return true;
            }
        }
        return false;
    }

    private static Graph toCsr(int nodes, int[] from, int[] to) {
        int[] offsets = new int[nodes + 1];
        for (int e = 0; e < from.length; e++) {
            offsets[from[e] + 1]++;
            offsets[to[e] + 1]++;
        }
        for (int v = 0; v < nodes; v++) {
            offsets[v + 1] += offsets[v];
        }
        int[] adjacency = new int[2 * from.length];
        int[] next = Arrays.copyOf(offsets, nodes);
        for (int e = 0; e < from.length; e++) {
            adjacency[next[from[e]]++] = to[e];
            adjacency[next[to[e]]++] = from[e];
        }
        return new Graph(nodes, offsets, adjacency);
    }

    static double[] pagerank(Graph graph) {
        int n = graph.nodes;
        double[] rank = new double[n];
        double[] next = new double[n];
        double[] share = new double[n];
        Arrays.fill(rank, 1.0 / n);

        for (int iteration = 0; iteration < MAX_ITERATIONS; iteration++) {
            double dangling = 0.0;
            for (int v = 0; v < n; v++) {
                int degree = graph.offsets[v + 1] - graph.offsets[v];
                if (degree == 0) {
                    dangling += rank[v];
                } else {
                    share[v] = rank[v] / degree;
                }
            }
            double base = (1.0 - DAMPING) / n + DAMPING * dangling / n;

            double change = 0.0;
            for (int v = 0; v < n; v++) {
                double sum = 0.0;
                for (int i = graph.offsets[v]; i < graph.offsets[v + 1]; i++) {
                    sum += share[graph.adjacency[i]];
                }
                next[v] = base + DAMPING * sum;
                change += Math.abs(next[v] - rank[v]);
            }

            double[] swap = rank;
            rank = next;
            next = swap;
            if (change < TOLERANCE) {
                break;
            }
        }
        return rank;
    }
}
