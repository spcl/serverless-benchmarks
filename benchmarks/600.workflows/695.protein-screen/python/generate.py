import uuid
import numpy as np

# Amino acid alphabet.
AA = np.array(list("ACDEFGHIKLMNPQRSTVWY"))


def make_sequence(seq_len: int, seed: int) -> str:
    rng = np.random.default_rng(seed=seed)
    return "".join(rng.choice(AA, size=seq_len))


def handler(event):
    n_candidates = int(event["n_candidates"])
    seq_len = int(event["seq_len"])
    top_k = int(event.get("top_k", max(1, min(5, n_candidates))))
    request_id = event.get("request_id", str(uuid.uuid4())[:8])

    schedules = []
    for idx in range(n_candidates):
        seq = make_sequence(seq_len, seed=idx)
        schedules.append(
            {
                "candidate_id": f"cand-{request_id}-{idx}",
                "sequence": seq,
                "top_k": top_k,
                "request_id": request_id,
            }
        )

    return {"schedules": schedules}
