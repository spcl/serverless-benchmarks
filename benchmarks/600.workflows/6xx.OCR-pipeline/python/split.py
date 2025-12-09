# benchmarks/600.workflows/6xx.OCR-pipeline/split.py
import uuid


def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def handler(event):
    segs = _chunks(event["segments"], event["batch_size"])
    input_bucket = event["input_bucket"]
    output_bucket = event["output_bucket"]
    benchmark_bucket = event["benchmark_bucket"]
    lang = event.get("lang", "en")

    return {
        "segments": [
            {
                "prefix": str(uuid.uuid4().int & ((1 << 64) - 1))[:8],
                "segments": ss,
                "lang": lang,
                "input_bucket": input_bucket,
                "output_bucket": output_bucket,
                "benchmark_bucket": benchmark_bucket,
            }
            for ss in segs
        ]
    }
