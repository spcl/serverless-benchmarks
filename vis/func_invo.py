import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker


if __name__ == "__main__":
    platforms = ["aws", "azure", "gcp"]
    name = "func_invo"
    funcs = ["gen_buffer_one", "gen_buffer_two", "gen_buffer_three", "gen_buffer_four", "gen_buffer_five"]
    invos = list(zip(funcs, funcs[1:]))

    fig, ax = plt.subplots()

    for platform in platforms:
        path = os.path.join("cache", "results", name, platform+".csv")
        df = pd.read_csv(path)

        ts = []
        for a, b in invos:
            end = df.loc[(df["func"] == a)]["end"].to_numpy()
            start = df.loc[(df["func"] == b)]["start"].to_numpy()
            ts.append(start-end)

        ts = np.asarray(ts)
        ts = np.mean(ts, axis=0)
        xs = np.arange(1, ts.shape[0]+1)

        line = ax.plot(xs, ts)[0]
        line.set_label(platform)

    ax.set_title("function invocation")
    ax.set_xlabel("repetition")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.set_ylabel("latency [s]")
    fig.legend()

    plt.show()