// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
using System;
using System.Diagnostics;
using System.Text.Json.Nodes;

namespace Benchmark;

// PageRank of a generated Barabási–Albert graph.
//
// The Java and .NET versions implement the same steps in the same order, so that they build the
// same graph and compute the same result, checked against one expected value:
// - Random numbers: SplitMix64 seeded with the input's seed. An integer in [0, n) is the
//   unsigned remainder of the next 64-bit value divided by n.
// - Graph: Barabási–Albert with m = 10, following the Node.js version. Nodes 0..m-1 start
//   without edges; each new node links to m distinct existing nodes, drawn uniformly from the
//   list of edge endpoints (so proportionally to degree) and kept in the order drawn. A graph
//   with size <= m + 1 nodes is complete.
// - PageRank: power iteration with damping 0.85; the rank of nodes without edges is spread
//   evenly; stops when the L1 change falls below 1e-10, after at most 1000 iterations. Sums
//   follow node order and edge insertion order.
public class Function
{
    private const int M = 10;
    private const double Damping = 0.85;
    private const double Tolerance = 1e-10;
    private const int MaxIterations = 1000;

    public JsonObject Handler(JsonObject input)
    {
        int size = input["size"]?.GetValue<int>()
            ?? throw new ArgumentException("expected a number in 'size'");
        ulong seed = (ulong)(input["seed"]?.GetValue<long>() ?? Stopwatch.GetTimestamp());

        long graphBegin = Stopwatch.GetTimestamp();
        Graph graph = BarabasiAlbert(size, M, new SplitMix64(seed));
        long graphEnd = Stopwatch.GetTimestamp();

        long computeBegin = Stopwatch.GetTimestamp();
        double[] rank = PageRank(graph);
        long computeEnd = Stopwatch.GetTimestamp();

        return new JsonObject
        {
            ["result"] = rank[0],
            ["measurement"] = new JsonObject
            {
                ["graph_generating_time"] = Microseconds(graphBegin, graphEnd),
                ["compute_time"] = Microseconds(computeBegin, computeEnd),
            },
        };
    }

    private static long Microseconds(long begin, long end) =>
        (long)Stopwatch.GetElapsedTime(begin, end).TotalMicroseconds;

    // SplitMix64 random number generator.
    private sealed class SplitMix64
    {
        private ulong state;

        public SplitMix64(ulong seed) => state = seed;

        public ulong Next()
        {
            state += 0x9E3779B97F4A7C15UL;
            ulong z = state;
            z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9UL;
            z = (z ^ (z >> 27)) * 0x94D049BB133111EBUL;
            return z ^ (z >> 31);
        }

        // An integer in [0, bound).
        public int NextInt(int bound) => (int)(Next() % (ulong)bound);
    }

    // Undirected graph in compressed sparse row form: the neighbors of node v are
    // Adjacency[Offsets[v]] to Adjacency[Offsets[v + 1] - 1], in edge insertion order.
    private sealed record Graph(int Nodes, int[] Offsets, int[] Adjacency);

    private static Graph BarabasiAlbert(int size, int m, SplitMix64 random)
    {
        if (m >= size - 1)
        {
            int completeCount = size * (size - 1) / 2;
            int[] completeFrom = new int[completeCount];
            int[] completeTo = new int[completeCount];
            int c = 0;
            for (int i = 0; i < size; i++)
            {
                for (int j = 0; j < i; j++)
                {
                    completeFrom[c] = i;
                    completeTo[c] = j;
                    c++;
                }
            }
            return ToCsr(size, completeFrom, completeTo);
        }

        int edgeCount = m * (size - m);
        int[] from = new int[edgeCount];
        int[] to = new int[edgeCount];
        int e = 0;
        // Endpoints of all edges so far; a uniform draw from it picks a node by its degree.
        int[] endpoints = new int[2 * edgeCount];
        int endpointCount = 0;
        int[] targets = new int[m];
        for (int i = 0; i < m; i++)
        {
            targets[i] = i;
        }

        for (int source = m; source < size; source++)
        {
            for (int t = 0; t < m; t++)
            {
                from[e] = source;
                to[e] = targets[t];
                e++;
                endpoints[endpointCount++] = targets[t];
                endpoints[endpointCount++] = source;
            }
            // The next node's targets; not needed after the last node.
            if (source + 1 < size)
            {
                int chosen = 0;
                while (chosen < m)
                {
                    int candidate = endpoints[random.NextInt(endpointCount)];
                    if (!Contains(targets, chosen, candidate))
                    {
                        targets[chosen++] = candidate;
                    }
                }
            }
        }
        return ToCsr(size, from, to);
    }

    private static bool Contains(int[] values, int count, int value)
    {
        for (int i = 0; i < count; i++)
        {
            if (values[i] == value)
            {
                return true;
            }
        }
        return false;
    }

    private static Graph ToCsr(int nodes, int[] from, int[] to)
    {
        int[] offsets = new int[nodes + 1];
        for (int e = 0; e < from.Length; e++)
        {
            offsets[from[e] + 1]++;
            offsets[to[e] + 1]++;
        }
        for (int v = 0; v < nodes; v++)
        {
            offsets[v + 1] += offsets[v];
        }
        int[] adjacency = new int[2 * from.Length];
        int[] next = offsets[..nodes];
        for (int e = 0; e < from.Length; e++)
        {
            adjacency[next[from[e]]++] = to[e];
            adjacency[next[to[e]]++] = from[e];
        }
        return new Graph(nodes, offsets, adjacency);
    }

    private static double[] PageRank(Graph graph)
    {
        int n = graph.Nodes;
        double[] rank = new double[n];
        double[] next = new double[n];
        double[] share = new double[n];
        Array.Fill(rank, 1.0 / n);

        for (int iteration = 0; iteration < MaxIterations; iteration++)
        {
            double dangling = 0.0;
            for (int v = 0; v < n; v++)
            {
                int degree = graph.Offsets[v + 1] - graph.Offsets[v];
                if (degree == 0)
                {
                    dangling += rank[v];
                }
                else
                {
                    share[v] = rank[v] / degree;
                }
            }
            double baseRank = (1.0 - Damping) / n + Damping * dangling / n;

            double change = 0.0;
            for (int v = 0; v < n; v++)
            {
                double sum = 0.0;
                for (int i = graph.Offsets[v]; i < graph.Offsets[v + 1]; i++)
                {
                    sum += share[graph.Adjacency[i]];
                }
                next[v] = baseRank + Damping * sum;
                change += Math.Abs(next[v] - rank[v]);
            }

            (rank, next) = (next, rank);
            if (change < Tolerance)
            {
                break;
            }
        }
        return rank;
    }
}
