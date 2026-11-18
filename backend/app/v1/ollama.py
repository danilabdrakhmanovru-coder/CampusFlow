"""Local Qwen client for narrative explanations of calculated statistics."""
from datetime import date
from http.client import HTTPConnection, HTTPException as HTTPProtocolError
from ipaddress import ip_address, ip_network
import json
from typing import Literal
from os import environ
import re
from threading import BoundedSemaphore
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_QWEN = "qwen2.5:7b"
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
generation = BoundedSemaphore(1)
PRIVATE_NETWORKS = tuple(ip_network(network) for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))
SYSTEM = (
    "Ты помогаешь диспетчеру вуза оценить уже рассчитанные окна в расписании. "
    "По числовой сводке выбери не больше трёх действий из available_steps в порядке важности. "
    "Сначала выбери действие, которое полезнее всего для этого расписания. "
    "Каждый код используй один раз. Ответ только JSON с массивом next_steps. "
    "Коды действий: neighboring_lessons — проверить пары по обе стороны длинных окон; "
    "same_building — проверить возможность провести соседние пары в одном корпусе; "
    "measure_walking — уточнить неизмеренное время переходов; "
    "compare_variants — запустить поиск допустимых переносов в CampusFlow."
)
STEPS = {
    "neighboring_lessons": "Проверьте пары до и после самых длинных окон. Начните с дней, указанных в разборе.",
    "same_building": "Проверьте, можно ли провести соседние пары в одном корпусе и сократить переходы.",
    "measure_walking": "Уточните время переходов между корпусами, прежде чем оценивать сокращение окон.",
    "compare_variants": "Нажмите «Найти исправления», чтобы сравнить допустимые переносы.",
}


class GapExplanation(BaseModel):
    summary: str
    observations: list[str]
    next_steps: list[str]


class StepSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    next_steps: list[Literal["neighboring_lessons", "same_building", "measure_walking", "compare_variants"]] = Field(
        min_length=1, max_length=3,
    )


def anonymized_metrics(summary, windows, start: date, end: date, minimum: int):
    days = {}
    for window in windows:
        name = WEEKDAYS[window["day"].weekday()]
        bucket = days.setdefault(name, {"count":0, "minutes":0, "longest_minutes":0,
                                       "windows_with_unknown_walking_time":0})
        bucket["count"] += 1
        bucket["minutes"] += window["minutes"]
        bucket["longest_minutes"] = max(bucket["longest_minutes"], window["minutes"])
        if window["transfer"] and window["walking_minutes"] is None:
            bucket["windows_with_unknown_walking_time"] += 1
    return {
        "period_days": (end-start).days+1,
        "min_gap_minutes": minimum,
        "gap_minutes": summary["total"],
        "gap_count": summary["count"],
        "largest_gap_minutes": summary["largest"],
        "days_with_gaps": summary["days"],
        "building_changes": summary["transitions"],
        "quality_score": summary.get("quality"),
        "compact_days": summary.get("compact_days"),
        "lesson_count": summary.get("lesson_count"),
        "by_weekday": days,
    }


def local_endpoint():
    try:
        url = urlsplit(environ.get("CAMPUSFLOW_OLLAMA_URL", "").strip())
    except ValueError:
        raise HTTPException(503, "Проверьте адрес локальной Ollama") from None
    model = environ.get("CAMPUSFLOW_OLLAMA_MODEL", DEFAULT_QWEN).strip()
    host = url.hostname
    if not host:
        raise HTTPException(503, "ИИ-анализ на этом сервере пока не подключён")
    local = host in {"localhost", "host.docker.internal", "ollama"}
    if not local:
        try:
            ip = ip_address(host)
            local = ip.is_loopback or any(ip in network for network in PRIVATE_NETWORKS)
        except ValueError:
            local = False
    if (url.scheme != "http" or not local or url.username or url.password or url.query or url.fragment
            or url.path not in {"", "/"} or "cloud" in model.lower()
            or not re.fullmatch(r"qwen[\w.\-]*:[\w.\-]+", model, flags=re.ASCII)):
        raise HTTPException(503, "Проверьте настройки локальной Ollama и модели Qwen")
    try:
        port = url.port or 11434
    except ValueError:
        raise HTTPException(503, "Проверьте порт локальной Ollama") from None
    return host, port, model


def analyze_gaps(metrics):
    host, port, model = local_endpoint()
    weekdays = metrics["by_weekday"]
    unknown = sum(day["windows_with_unknown_walking_time"] for day in weekdays.values())
    available = ["neighboring_lessons", "compare_variants"]
    if metrics["building_changes"]:
        available.append("same_building")
    if unknown:
        available.append("measure_walking")
    payload = {
        "model": model, "stream": False,
        "format": StepSelection.model_json_schema(),
        "messages": [
            {"role":"system", "content":SYSTEM},
            {"role":"user", "content":json.dumps({**metrics, "available_steps":available}, ensure_ascii=False)},
        ],
        "options":{"temperature":0, "num_ctx":2048, "num_predict":100},
    }
    if not generation.acquire(blocking=False):
        raise HTTPException(429, "Qwen уже разбирает расписание. Повторите чуть позже")
    connection = HTTPConnection(host, port, timeout=90)
    try:
        connection.request("POST", "/api/chat", body=json.dumps(payload).encode(),
                           headers={"Content-Type":"application/json"})
        response = connection.getresponse()
        if response.status == 404:
            raise HTTPException(503, "Модель Qwen не найдена в локальной Ollama")
        if response.status != 200:
            raise HTTPException(503, "Локальная Ollama не смогла выполнить анализ")
        result = json.loads(response.read(65_537))
        if result.get("done_reason") == "length":
            raise ValueError("Incomplete model response")
        selection = StepSelection.model_validate_json(result["message"]["content"])
        steps = [STEPS[key] for key in dict.fromkeys(selection.next_steps) if key in available]
        if not steps:
            raise ValueError("No applicable actions")
        focus_days = sorted(weekdays, key=lambda day:(-weekdays[day]["minutes"], WEEKDAYS.index(day)))[:2]
        observations = [f"{day.capitalize()}: суммарно {weekdays[day]['minutes']} мин. "
                        f"Самое длинное окно — {weekdays[day]['longest_minutes']} мин."
                        for day in focus_days]
        if unknown:
            observations.append(f"Окон со сменой корпуса и неизвестным временем перехода: {unknown}.")
        return GapExplanation(
            summary=f"Окон за период: {metrics['gap_count']}. Всего {metrics['gap_minutes']} мин. "
                    f"Самое длинное окно — {metrics['largest_gap_minutes']} мин.",
            observations=observations, next_steps=steps,
        )
    except TimeoutError:
        raise HTTPException(504, "Qwen не успел завершить анализ. Попробуйте ещё раз") from None
    except (OSError, HTTPProtocolError):
        raise HTTPException(503, "Локальная Ollama недоступна. Проверьте, запущена ли она") from None
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(502, "Qwen вернул неполный ответ. Попробуйте ещё раз") from None
    finally:
        connection.close()
        generation.release()
