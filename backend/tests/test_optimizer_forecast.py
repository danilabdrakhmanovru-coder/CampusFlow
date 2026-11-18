from datetime import date, timedelta

from app.v1.forecast import train_load, train_synthetic_no_show
from app.v1.optimizer import LessonChoices, Option, measure, optimize


def test_optimizer_closes_window_and_respects_occupancy():
    original = Option(1, "6", 3, 6)
    near = Option(1, "6", 1, 6)
    wrong_building = Option(2, "7", 1, 1)
    later = Option(1, "6", 2, 6)
    lesson = LessonChoices(1, ("g:1", "t:1"), original, (original, near, wrong_building, later))
    fixed = [("g:1", 0, "6"), ("t:1", 0, "6"), ("r:1", 1, "6")]
    result = optimize([lesson], fixed)
    assert result["status"] == "optimal"
    assert result["assignments"][0]["slot"] == 3
    assert result["assignments"][0]["room_id"] == 1
    assert measure([(lesson.people, later)], fixed)["group_empty_periods"] == 1


def test_optimizer_disallows_overlapping_groups():
    alternative = Option(1, "6", 0, 0)
    other_room = Option(2, "6", 0, 0)
    lessons = [LessonChoices(1, ("g:1",), alternative, (alternative,)),
               LessonChoices(2, ("g:1",), other_room, (other_room,))]
    assert optimize(lessons, [])["status"] == "infeasible"


def test_forecast_chronological_split_and_synthetic_label():
    first = date(2026, 9, 1)
    rows = {(first + timedelta(days=i), "6", slot): (i + slot) % 4
            for i in range(30) for slot in range(9)}
    assert train_load({}, {"6": 4}) is None
    model, metrics = train_load(rows, {"6": 4})
    assert metrics["split_date"] == "2026-09-25"
    assert metrics["train_rows"] == 216
    assert metrics["test_rows"] == 54
    assert len(model.predict([[0, 6, 0]])) == 1
    _, metrics = train_synthetic_no_show()
    assert metrics["source"] == "synthetic"
    assert 0 < metrics["brier"] < 1


def test_booking_demand_requires_real_history():
    from app.v1.forecast import train_booking_demand

    first = date(2026, 9, 1)
    assert train_booking_demand({(first, "6"): 30}, ["6"]) is None
    history = {(first + timedelta(days=i), "6"): 2 + i % 3 for i in range(35)}
    model, metrics = train_booking_demand(history, ["6"])
    assert model.predict([[2, 6]])[0] >= 0
    assert metrics["mae"] >= 0 and metrics["historical_baseline_mae"] >= 0

def test_group_metrics_empty_lesson_gap_and_measured_transition():
    from datetime import date
    from types import SimpleNamespace
    from sqlalchemy.dialects.postgresql import Range
    from app.v1.analytics import moment
    from app.v1.group_insights import group_metrics

    day=date(2026,11,20)
    def item(key,start,end,building):
        return SimpleNamespace(id=key,subject=f"Пара {key}",room_id=key,building=building,
                               period=Range(moment(day,start),moment(day,end),bounds="[)"))
    lengths={"QA":25}
    reference=item(1,480,560,"6")
    other=item(2,695,775,"7")
    assert group_metrics("QA",[],lengths,{})[0]["score"]==0
    assert group_metrics("QA",[reference],lengths,{})[1]==[]
    summary,gaps=group_metrics("QA",[reference,other],lengths,{(1,2):15})
    assert summary["total"]==120 and summary["count"]==1 and summary["transitions"]==1
    assert gaps[0]["walking_minutes"]==15 and gaps[0]["break_minutes"]==135
    assert group_metrics("QA",[reference,other],{"QA":4},{})[0]["score"] is None

def test_full_lesson_window_is_within_one_day():
    from datetime import date, timedelta
    from types import SimpleNamespace
    from sqlalchemy.dialects.postgresql import Range
    from app.v1.analytics import moment
    from app.v1.group_insights import group_metrics

    day=date(2026,11,16)
    def item(key,d,start,end):
        return SimpleNamespace(id=key,subject=f"Пара {key}",room_id=1,building="6",
                               period=Range(moment(d,start),moment(d,end),bounds="[)"))
    monday=[item(1,day,575,655),item(2,day,695,775)]
    thursday=day+timedelta(days=3)
    rows=monday+[item(3,thursday,480,560),item(4,thursday,695,775)]
    summary,gaps=group_metrics("QA",rows,{"QA":20},{})
    assert summary["count"]==1 and summary["days"]==1 and summary["total"]==135
    assert [g["day"] for g in gaps]==[thursday]
    assert gaps[0]["start"]==moment(thursday,560)
    assert gaps[0]["end"]==moment(thursday,695)

def test_teacher_breaks_do_not_include_other_days():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from sqlalchemy.dialects.postgresql import Range
    from app.v1.teaching_rules import teacher_gaps
    zone = ZoneInfo('Asia/Yekaterinburg')
    def row(day, hour):
        start = datetime(2026,11,day,hour,0,tzinfo=zone)
        return {'teachers':['t1'], 'period':Range(start,start.replace(hour=hour+1))}
    before = teacher_gaps([row(16,8),row(16,10),row(18,8)],zone)
    after = teacher_gaps([row(16,8),row(16,12),row(18,8)],zone)
    assert before['t1'] == 60 and after['t1'] == 180
