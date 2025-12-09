# benchmarks/600.workflows/6xx.OCR-pipeline/merge.py
import os
import uuid
import shutil

from . import storage

client = storage.storage.get_instance()


def _download_page_txt(
    page: str,
    tmp_dir: str,
    benchmark_bucket: str,
    output_bucket: str,
    prefix: str,
):
    base, _ = os.path.splitext(page)
    remote_name = f"{prefix}{base}.txt"
    local_txt = os.path.join(tmp_dir, f"{base}.txt")

    try:
        client.download(
            benchmark_bucket,
            f"{output_bucket}/{remote_name}",
            local_txt,
        )
        return local_txt
    except Exception:
        # return None
        return None


def handler(event):
    pages = event["segments"]
    benchmark_bucket = event["benchmark_bucket"]
    output_bucket = event["output_bucket"]
    prefix = event["prefix"]

    tmp_dir = os.path.join("/tmp", str(uuid.uuid4()))
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        page_txt_paths = []
        for page in pages:
            p = _download_page_txt(page, tmp_dir, benchmark_bucket, output_bucket, prefix)
            page_txt_paths.append((page, p))

        # merge all pages
        final_doc = os.path.join(tmp_dir, "document.txt")
        with open(final_doc, "w", encoding="utf-8") as fout:
            for page, txt_path in sorted(page_txt_paths, key=lambda x: x[0]):
                fout.write(f"===== Page {page} =====\n")
                if txt_path and os.path.exists(txt_path):
                    with open(txt_path, "r", encoding="utf-8") as fin:
                        fout.write(fin.read())
                else:
                    fout.write("[NO_TEXT]\n")
                fout.write("\n\n")

        # upload final document
        remote_name = f"{prefix}document.txt"
        client.upload(
            benchmark_bucket,
            f"{output_bucket}/{remote_name}",
            final_doc,
            unique_name=False,
        )

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return event
