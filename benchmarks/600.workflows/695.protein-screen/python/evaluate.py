import numpy as np

# Simple per-residue propensities to mimic a scoring function.
AA_SCORES = {
    "A": 1.2,
    "C": 1.5,
    "D": -0.5,
    "E": -0.4,
    "F": 1.7,
    "G": 0.8,
    "H": 0.1,
    "I": 1.3,
    "K": -0.6,
    "L": 1.4,
    "M": 1.0,
    "N": -0.2,
    "P": 0.0,
    "Q": -0.1,
    "R": -0.7,
    "S": 0.2,
    "T": 0.3,
    "V": 1.1,
    "W": 1.8,
    "Y": 1.6,
}


def score_sequence(seq: str) -> float:
    values = np.array([AA_SCORES[aa] for aa in seq], dtype=np.float32)
    # Combine mean/stdev as a toy "fitness" proxy.
    return float(values.mean() + values.std())


def handler(schedule):
    seq = schedule["sequence"]
    score = score_sequence(seq)
    return {
        "candidate_id": schedule["candidate_id"],
        "score": score,
        "top_k": schedule.get("top_k", 1),
    }
