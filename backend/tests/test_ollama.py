from datetime import date
import json

import pytest
from fastapi import HTTPException

from app.v1 import ollama


def test_prompt_contains_only_aggregates(monkeypatch):
    monday = date(2026, 11, 16)
    summary = {"group":"private-group", "size":12, "count":1, "total":55, "largest":55, "days":1, "transitions":1}
    windows = [{"day":monday, "minutes":55, "transfer":True, "walking_minutes":None,
                "before":"private-subject", "after":"private-teacher", "building":"private-building"}]
    metrics = ollama.anonymized_metrics(summary,windows,monday,monday,40)
    monkeypatch.setenv("CAMPUSFLOW_OLLAMA_URL", "http://host.docker.internal:11434")
    monkeypatch.setenv("CAMPUSFLOW_OLLAMA_MODEL", "qwen2.5:7b")
    answer = {"next_steps":["measure_walking","compare_variants","measure_walking"]}

    class Connection:
        def __init__(self, host, port, timeout):
            assert (host,port,timeout)==("host.docker.internal",11434,90)
        def request(self, method, path, body, headers):
            assert (method,path)==("POST","/api/chat")
            payload=json.loads(body)
            assert payload["model"]=="qwen2.5:7b"
            content=payload["messages"][1]["content"]
            assert "private" not in content and "2026" not in content
            totals=json.loads(content)
            assert totals["gap_minutes"]==55
            assert totals["by_weekday"]["понедельник"]["windows_with_unknown_walking_time"]==1
        def getresponse(self):
            return self
        status=200
        def read(self, limit):
            return json.dumps({"message":{"content":json.dumps(answer)}}).encode()
        def close(self):
            pass

    monkeypatch.setattr(ollama,"HTTPConnection",Connection)
    result=ollama.analyze_gaps(metrics)
    assert result.summary=="Окон за период: 1. Всего 55 мин. Самое длинное окно — 55 мин."
    assert result.observations[0]=="Понедельник: суммарно 55 мин. Самое длинное окно — 55 мин."
    assert result.next_steps==[ollama.STEPS["measure_walking"],ollama.STEPS["compare_variants"]]


@pytest.mark.parametrize("address,model", [
    ("http://example.com:11434", "qwen2.5:7b"), ("http://ollama", "qwen3:cloud"),
    ("http://ollama@external.invalid", "qwen2.5:7b"),
])
def test_rejects_cloud_configs(monkeypatch,address,model):
    monkeypatch.setenv("CAMPUSFLOW_OLLAMA_URL",address)
    monkeypatch.setenv("CAMPUSFLOW_OLLAMA_MODEL",model)
    with pytest.raises(HTTPException) as error:
        ollama.local_endpoint()
    assert error.value.status_code==503
