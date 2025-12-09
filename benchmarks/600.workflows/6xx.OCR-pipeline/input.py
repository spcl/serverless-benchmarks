# benchmarks/600.workflows/6xx.OCR-pipeline/input.py
import os

size_generators = {
    "test": (16, 4),
    "small": (64, 8),
    "large": (256, 16),
}


def buckets_count():
    return (1, 1)


def generate_input(
    data_dir,
    size,
    benchmarks_bucket,
    input_buckets,
    output_buckets,
    upload_func,
    nosql_func,
):
    if data_dir is None:
        raise ValueError(
            "/path/to/ocr_data/\n"
            "  └── pages/\n"
            "       ├── page1.png\n"
            "       ├── page2.png\n"
            "       └── ..."
        )

    num_pages, batch_size = size_generators[size]

    # 1) upload pages
    pages_dir = os.path.join(data_dir, "pages")
    if not os.path.isdir(pages_dir):
        raise ValueError(f"pages dir not exist: {pages_dir}")

    page_files = sorted(
        f for f in os.listdir(pages_dir) if f.lower().endswith((".png", ".jpg", ".jpeg"))
    )
    if not page_files:
        raise ValueError(f"no jpg/png under dir: {pages_dir}")

    new_pages = []
    for i in range(num_pages):
        page = page_files[i % len(page_files)]
        # unified: 00000000.png
        ext = os.path.splitext(page)[1].lower() or ".png"
        name = f"{i:08d}{ext}"
        path = os.path.join(pages_dir, page)

        new_pages.append(name)
        upload_func(0, name, path)

    assert len(new_pages) == num_pages

    return {
        "segments": new_pages,
        "benchmark_bucket": benchmarks_bucket,
        "input_bucket": input_buckets[0],
        "output_bucket": output_buckets[0],
        "batch_size": batch_size,
        "lang": "en",
    }
