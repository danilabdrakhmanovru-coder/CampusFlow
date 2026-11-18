"""Train from actual dispatcher decisions and keep evaluation separate from training."""
from datetime import timedelta
from os import environ

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime, Text

from .db import Base


class Feedback(Base):
    __tablename__ = "proposal_feedback"
    proposal_id: Mapped[int] = mapped_column(primary_key=True)
    accepted: Mapped[bool]
    reason: Mapped[str]
    features: Mapped[list] = mapped_column(JSONB)
    gain: Mapped[int]
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class RankingModel(Base):
    __tablename__ = "ranking_models"
    id: Mapped[int] = mapped_column(primary_key=True)
    trained_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    sample_count: Mapped[int]
    metrics: Mapped[dict] = mapped_column(JSONB)
    acceptance_model: Mapped[str] = mapped_column(Text)
    value_model: Mapped[str] = mapped_column(Text)


MIN_ROWS = 30
FEATURES = ["window_minutes","weekday","bell_slot","building_change","room_type","group_size","groups","teachers"]


def trained_model(db):
    return db.scalar(select(RankingModel).order_by(RankingModel.id.desc()).limit(1))


def model_status(db):
    active = trained_model(db)
    count = db.scalar(select(func.count()).select_from(Feedback))
    return {"status": "trained" if active else "insufficient_data", "decisions": count, "min_decisions": MIN_ROWS,
            "features": FEATURES, "demo":environ.get("CAMPUSFLOW_DEMO")=="1", "version": active.id if active else None,
            "trained_at": active.trained_at if active else None, "metrics": active.metrics if active else None,
            "sample_count": active.sample_count if active else None,
            "limitations": "Прогноз обучается на решениях диспетчеров текущего стенда. Оценка не заменяет ограничения CP-SAT."}


def train(db, *, automatic=False):
    latest = trained_model(db)
    count = db.scalar(select(func.count()).select_from(Feedback))
    if count < MIN_ROWS or latest and (latest.sample_count == count or
            automatic and latest.trained_at > db.scalar(select(func.now())) - timedelta(days=1)):
        return model_status(db)
    if not db.scalar(text("SELECT pg_try_advisory_xact_lock(61206703)")):
        return model_status(db)
    rows = list(db.scalars(select(Feedback).order_by(Feedback.created_at, Feedback.proposal_id)))
    from lightgbm import LGBMClassifier, LGBMRegressor
    import numpy as np
    data = np.asarray([r.features for r in rows],dtype=float)
    labels = np.array([int(r.accepted) for r in rows])
    gains = np.array([r.gain if r.accepted else 0 for r in rows])
    cut = int(len(rows)*.8)
    if len(set(labels[:cut])) < 2 or len(set(labels[cut:])) < 2:
        return model_status(db)
    predictor = LGBMClassifier(n_estimators=40, min_child_samples=3, num_leaves=7, verbosity=-1, n_jobs=1)
    value = LGBMRegressor(n_estimators=40, min_child_samples=3, num_leaves=7, verbosity=-1, n_jobs=1)
    predictor.fit(data[:cut],labels[:cut])
    value.fit(data[:cut],gains[:cut])
    probability = predictor.booster_.predict(data[cut:])
    predicted = np.maximum(0, value.booster_.predict(data[cut:]))
    # Baseline uses historical acceptance rate and the optimistic removed-window estimate.
    heuristic = data[cut:,0]*labels[:cut].mean()
    metrics = {"brier":float(((probability-labels[cut:])**2).mean()),
               "baseline_brier":float(((labels[:cut].mean()-labels[cut:])**2).mean()),
               "mae_minutes":float(np.abs(predicted-gains[cut:]).mean()),
               "baseline_mae_minutes":float(np.abs(heuristic-gains[cut:]).mean()),
               "train_rows":cut,"holdout_rows":len(rows)-cut}
    predictor.fit(data,labels)
    value.fit(data,gains)
    db.add(RankingModel(sample_count=len(rows), metrics=metrics,
                        acceptance_model=predictor.booster_.model_to_string(),value_model=value.booster_.model_to_string()))
    db.commit()
    return model_status(db)


def scores(model, features):
    if not model:
        return None, None
    from lightgbm import Booster
    from numpy import asarray
    data = asarray([features])
    accept = Booster(model_str=model.acceptance_model).predict(data,num_threads=1)[0]
    gain = Booster(model_str=model.value_model).predict(data,num_threads=1)[0]
    return round(float(accept),3), max(0,round(float(gain)))
