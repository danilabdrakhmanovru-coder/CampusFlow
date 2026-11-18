"""Train independent forecasting models and report their provenance."""
from collections import defaultdict
from hashlib import sha256

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import brier_score_loss, mean_absolute_error



def building_feature(building):
    code = str(building)
    return int(code) if code.isascii() and code.isdecimal() else int.from_bytes(sha256(code.encode()).digest()[:4], "big")


def train_load(observations, room_counts):
    """observations: mapping (date, building, bell index) -> distinct room count."""
    days = sorted({day for day, _, _ in observations})
    if len(days) < 14:
        return None
    rows, targets, timestamps = [], [], []
    for (day, building, slot), occupied in sorted(observations.items()):
        rows.append((day.weekday(), building_feature(building), slot))
        targets.append(occupied / room_counts[building])
        timestamps.append(day)
    split = days[int(len(days) * .8)]
    x, y = np.array(rows), np.array(targets)
    train = np.array([day < split for day in timestamps])
    model = HistGradientBoostingRegressor(max_iter=70, max_depth=4, random_state=19)
    model.fit(x[train], y[train])
    predicted = np.clip(model.predict(x[~train]), 0, 1)
    buckets = defaultdict(list)
    for key, value in zip(x[train], y[train]):
        buckets[tuple(key)].append(value)
    baseline = [np.mean(buckets.get(tuple(key), y[train])) for key in x[~train]]
    return model, {"mae": float(mean_absolute_error(y[~train], predicted)),
                   "historical_baseline_mae": float(mean_absolute_error(y[~train], baseline)),
                   "split_date": split.isoformat(), "train_rows": int(train.sum()), "test_rows": int((~train).sum())}


def train_synthetic_no_show():
    rng = np.random.default_rng(19)
    x = np.column_stack((rng.integers(0, 7, 5000), rng.integers(0, 9, 5000), rng.integers(0, 15, 5000)))
    probability = .08 + .11 * (x[:, 0] >= 5) + .14 * (x[:, 1] >= 7) + .012 * x[:, 2]
    y = rng.binomial(1, probability)
    model = HistGradientBoostingClassifier(max_iter=60, max_depth=3, random_state=19)
    model.fit(x[:4000], y[:4000])
    return model, {"source": "synthetic", "test_rows": 1000,
                   "brier": float(brier_score_loss(y[4000:], model.predict_proba(x[4000:])[:, 1]))}


def train_booking_demand(observed_days, buildings):
    from datetime import timedelta

    if not observed_days or sum(observed_days.values()) < 30:
        return None
    first = min(day for day, _ in observed_days)
    last = max(day for day, _ in observed_days)
    if (last - first).days < 27:
        return None
    days = [first + timedelta(days=i) for i in range((last-first).days+1)]
    cut = days[int(len(days)*.8)]
    features, targets, train = [], [], []
    for day in days:
        for building in buildings:
            features.append((day.weekday(), building_feature(building)))
            targets.append(observed_days.get((day, building), 0))
            train.append(day < cut)
    x, y, mask = np.array(features), np.array(targets), np.array(train)
    model = HistGradientBoostingRegressor(max_iter=70, max_depth=3, random_state=19)
    model.fit(x[mask], y[mask])
    prediction = np.maximum(0, model.predict(x[~mask]))
    averages = {building_feature(b): y[mask & (x[:, 1] == building_feature(b))].mean() for b in buildings}
    return model, {"mae": float(mean_absolute_error(y[~mask], prediction)),
                   "historical_baseline_mae": float(mean_absolute_error(
                       y[~mask], [averages[b] for b in x[~mask, 1]],
                   )), "split_date": cut.isoformat()}
