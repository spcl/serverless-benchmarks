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

        generate = df.loc[(df["func"] == "generate")].set_index("rep")
        process = df.loc[(df["func"] == "process")].groupby("rep")
        d_total = process["end"].max() - generate["start"]

        ys = np.asarray(d_total)
        xs = np.arange(ys.shape[0])

        line = ax.plot(xs, ys)[0]
        line.set_label(platform)

        ys = ys[np.where(~np.isnan(ys))]
        print(platform, "std:", np.std(ys))

    ax.set_title("runtime")
    ax.set_xlabel("repetition")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.set_xticks(np.arange(0, len(xs)+1, 5))
    ax.set_ylabel("duration [s]")
    fig.legend()

    plt.show()