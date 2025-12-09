# benchmarks/600.workflows/6xx.OCR-pipeline/recognize.py
import os
import uuid
import shutil
import logging

import easyocr

from . import storage

logger = logging.getLogger(__name__)
client = storage.storage.get_instance()

_readers = {}


def _get_reader(lang: str):
    """
    lazy initialize easyocr.Reader
    lang: 'en', 'ch_sim', 'ch_tra', 'ja' etc
    """
    if lang not in _readers:
        _readers[lang] = easyocr.Reader([lang], gpu=False)
        logger.info("Initialized easyocr.Reader for lang=%s", lang)
    return _readers[lang]


def handler(event):
    input_bucket = event["input_bucket"]
    output_bucket = event["output_bucket"]
    benchmark_bucket = event["benchmark_bucket"]
    pages = event["segments"]
    prefix = event["prefix"]
    lang = event.get("lang", "en")

    tmp_dir = os.path.join("/tmp", str(uuid.uuid4()))
    os.makedirs(tmp_dir, exist_ok=True)

    reader = _get_reader(lang)

    try:
        for page in pages:
            # 1) download image
            local_img = os.path.join(tmp_dir, page)
            client.download(
                benchmark_bucket,
                f"{input_bucket}/{page}",
                local_img,
            )

            # 2) OCR
            # detail=0 -> only text
            try:
                results = reader.readtext(local_img, detail=0)
            except Exception as e:
                logger.error("OCR failed on %s: %s", page, e)
                results = [f"[OCR_ERROR] {e}"]

            text = "\n".join(str(x) for x in results)

            # 3) per-page txt
            base, _ = os.path.splitext(page)
            local_txt = os.path.join(tmp_dir, f"{base}.txt")
            with open(local_txt, "w", encoding="utf-8") as f:
                f.write(text)

            # 4) upload to output_bucket（with prefix）
            remote_name = f"{prefix}{base}.txt"
            client.upload(
                benchmark_bucket,
                f"{output_bucket}/{remote_name}",
                local_txt,
                unique_name=False,
            )

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # pass to merge
    return event
