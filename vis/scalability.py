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
        process = df.loc[(df["func"] == "process")].groupby("rep")
        num_threads = process["container_id"].nunique()

        ys = np.asarray(num_threads)
        xs = np.arange(ys.shape[0])

        line = ax.plot(xs, ys)[0]
        line.set_label(platform)

    ax.set_title("scalability")
    ax.set_xlabel("repetition")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.set_xticks(np.arange(0, len(xs)+1, 5))
    ax.set_ylabel("#threads")
    fig.legend()

    plt.show()