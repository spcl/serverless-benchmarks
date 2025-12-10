def handler(event):
    results = event.get("schedules", [])
    if not results:
        return {"top_candidates": []}

    top_k = int(results[0].get("top_k", len(results)))
    top_candidates = sorted(results, key=lambda r: r["score"], reverse=True)[:top_k]

    return {"top_candidates": top_candidates}
