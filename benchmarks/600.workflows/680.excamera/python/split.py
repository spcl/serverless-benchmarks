def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def handler(event):
    segs = chunks(event["segments"], event["batch_size"])
    input_bucket = event["input_bucket"]
    output_bucket = event["output_bucket"]

    return {
        "segments": [
            {
                "segments": ss,
                "input_bucket": input_bucket,
                "output_bucket": output_bucket,
                "reencode-first-frame": idx > 0,
                "rebase": idx > 1
            } for idx, ss in enumerate(segs)
        ]
    }
