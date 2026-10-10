"""Educational offline training only; does not configure or deploy a live model."""

import hashlib
import json
from pathlib import Path

from aura.prime.features import extract_candle_features
from aura.prime.ml_linear import SklearnLogisticTrainer

SOURCE = Path("artifacts/governance/real_market_strategy_backtests.json")
OUTPUT = Path("runtime/student_training")


def main():
    source_bytes = SOURCE.read_bytes()
    payload = json.loads(source_bytes)
    candles = payload["candles"]
    samples = []
    # Features contain only candles available at time t. Label is next close direction.
    # This does not model fills/costs and is not a profitability target.
    for i in range(54, len(candles) - 1):
        vector = extract_candle_features(candles[: i + 1], symbol="BTC-USD", timeframe="1h")
        label = int(float(candles[i + 1]["close"]) > float(candles[i]["close"]))
        samples.append((vector.features, label))
    split = int(len(samples) * 0.7)
    train = samples[: split - 1]  # Purge boundary sample whose outcome overlaps test start.
    test = samples[split:]
    if len(train) < 20 or len(test) < 20 or len({label for _, label in train}) != 2:
        raise ValueError("Insufficient chronological samples or both classes missing")
    rows, labels = zip(*train)
    fingerprint = hashlib.sha256(source_bytes).hexdigest()
    artifact = SklearnLogisticTrainer().fit(
        list(rows),
        list(labels),
        model_key="student-btc-direction",
        version="lesson1",
        training_data_fingerprint=fingerprint,
    )
    predictions = [int(artifact.probability(row) >= 0.5) for row, _ in test]
    actual = [label for _, label in test]
    accuracy = sum(a == b for a, b in zip(predictions, actual)) / len(actual)
    training_majority = int(sum(labels) >= len(labels) / 2)
    baseline = sum(label == training_majority for label in actual) / len(actual)
    report = {
        "purpose": "EDUCATIONAL_OFFLINE_ONLY",
        "source": str(SOURCE),
        "source_sha256": fingerprint,
        "train_samples": len(train),
        "test_samples": len(test),
        "purged_boundary_samples": 1,
        "accuracy": accuracy,
        "training_majority_baseline_accuracy": baseline,
        "test_start": candles[54 + split]["close_time"],
        "test_end": candles[-1]["close_time"],
        "live_approved": False,
        "configured_in_env": False,
        "limitations": [
            "Short BTC-only sample",
            "Direction labels ignore fees/slippage and actual execution",
            "No independent validation set or calibrated probability assessment",
            "Accuracy is not strategy win rate or profitability",
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    artifact.save(OUTPUT / "research_model.json")
    (OUTPUT / "training_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    print("Saved under runtime/student_training; NOT connected to trading.")


if __name__ == "__main__":
    main()
