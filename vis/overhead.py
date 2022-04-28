import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker


if __name__ == "__main__":
    platforms = ["aws", "azure", "gcp"]
    name = "parallel"

    fig, ax = plt.subplots()

    for platform in platforms:
        path = os.path.join("cache", "results", name, platform+".csv")
        df = pd.read_csv(path)
        df["duration"] = df["end"] - df["start"]

        generate = df.loc[(df["func"] == "generate")].set_index("rep")
        process = df.loc[(df["func"] == "process")].groupby("rep")

        d_total = process["end"].max() - generate["start"]
        d_critical = generate["duration"] + process["duration"].max()
        d_overhead = d_total - d_critical

        ds = np.asarray(d_overhead)
        xs = np.arange(1, ds.shape[0]+1)

        line = ax.plot(xs, ds)[0]
        line.set_label(platform)

    ax.set_title("overhead")
    ax.set_xlabel("repetition")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.set_ylabel("overhead [s]")
    fig.legend()

    plt.show()