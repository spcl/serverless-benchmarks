import os
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker


if __name__ == "__main__":
    platforms = ["aws", "azure", "gcp"]
    name = sys.argv[-1] if len(sys.argv) > 1 else "func_invo"
    func = "process"

    fig, ax = plt.subplots()

    for platform in platforms:
        path = os.path.join("cache", "results", name, platform+".csv")
        if not os.path.exists(path):
            continue

        df = pd.read_csv(path)
        reps = df["rep"].max()

        ys = []
        for i in range(1, reps+1):
            start = df.loc[((df["func"] == func) & (df["rep"] == i))].sort_values(["start"])["start"].to_numpy()
            end = df.loc[((df["func"] == func) & (df["rep"] == i))].sort_values(["end"])["end"].to_numpy()

            # sanity checks to verify no functions are overlapping
            assert(np.all(start[:-1] < start[1:]))
            assert(np.all(end[:-1] < end[1:]))
            assert(np.all(end[:-1] < start[1:]))

            ys.append(start[1:] - end[:-1])

        ys = np.asarray(ys)
        ys = np.mean(ys, axis=1)
        xs = np.arange(ys.shape[0])

        line = ax.plot(xs, ys)[0]
        line.set_label(platform)

    ax.set_title("function invocation")
    ax.set_xlabel("repetition")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.set_xticks(np.arange(0, len(xs)+1, 5))
    ax.set_ylabel("latency [s]")
    fig.legend()

    plt.show()