import os
import sys
import json

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker


if __name__ == "__main__":
    platforms = ["aws", "azure", "gcp"]
    name = sys.argv[-1] if len(sys.argv) > 1 else "640.selfish-detour"
    func = "process"

    for platform in platforms:
        path = os.path.join("cache", "results", name, platform+".csv")
        if not os.path.exists(path):
            continue

        df = pd.read_csv(path)
        assert(df.shape[0] == 1)

        tps = df.at[0, "result.tps"]
        tpms = tps/1e3
        min_diff = df.at[0, "result.min_diff"]
        num_iterations = df.at[0, "result.num_iterations"]
        res = json.loads(df.at[0, "result.timestamps"])
        duration = (res[-1] - res[2])/tps
        func_duration = df.at[0, "end"] - df.at[0, "start"]

        print("min:", min_diff, "number of iterations:", num_iterations, "duration:", f"{duration} s", "func duration:", f"{func_duration}s")
        xs = []
        ys = []
        for i in range(0, len(res), 2):
            x = (res[i]-res[0])/tps
            y = (res[i+1]-res[i]-min_diff)/tpms
            ys.append(y)
            xs.append(x)

        print(min(xs), max(xs))
        print(min(ys), max(ys))

        fig, ax = plt.subplots()
        ax.scatter(xs, ys)

        ax.set_title(f"OS noise ({platform})")
        ax.set_xlabel("time [s]")
        ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        # ax.set_xlim([0, 5])
        ax.set_ylabel("time difference [ms]")

        plt.show()
