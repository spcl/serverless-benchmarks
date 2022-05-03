import os
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker


if __name__ == "__main__":
    platforms = ["aws", "azure", "gcp"]
    name = sys.argv[-1] if len(sys.argv) > 1 else "parallel"

    fig, ax = plt.subplots()

    for platform in platforms:
        path = os.path.join("cache", "results", name, platform+".csv")
        if not os.path.exists(path):
            continue

        df = pd.read_csv(path)
        df["duration"] = df["end"] - df["start"]

        generate = df.loc[(df["func"] == "generate")].set_index("rep")
        process = df.loc[(df["func"] == "process")].groupby("rep")
        verify = df.loc[(df["func"] == "verify")].set_index("rep")

        d_total = verify["end"] - generate["start"]
        d_critical = generate["duration"] + process["duration"].max() + verify["duration"]
        d_overhead = 100 * (d_total - d_critical)/d_total

        ys = np.asarray(d_overhead)
        xs = np.arange(ds.shape[0])

        line = ax.plot(xs, ys)[0]
        line.set_label(platform)

    ax.set_title("overhead")
    ax.set_xlabel("repetition")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.set_xticks(np.arange(0, len(xs)+1, 5))
    ax.set_ylabel("overhead [s]")
    ax.yaxis.set_major_formatter(ticker.PercentFormatter())
    fig.legend()

    plt.show()