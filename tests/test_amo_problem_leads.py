"""Тесты на подставных ответах amoCRM API: без сети и без реального аккаунта."""
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

os.environ.setdefault("AMO_BASE_URL", "https://test.amocrm.ru/")
os.environ.setdefault("AMO_TOKEN", "test-token")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import amo_problem_leads as amo  # noqa: E402

NOW = int(time.time())
DAY = 86400


def lead(lead_id, status_id=10, **extra):
    return {"id": lead_id, "name": f"Сделка {lead_id}", "status_id": status_id, "responsible_user_id": 7, **extra}


def page(entity, items, has_next=False):
    return {"_embedded": {entity: items}, "_links": {"next": {"href": "..."}} if has_next else {}}


def run(tasks_pages, leads_pages):
    """Подменяет HTTP-запросы: отсутствующая страница отдаётся как 204 No Content."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, dict(params)))
        pages = tasks_pages if url.endswith("/tasks") else leads_pages
        body = pages.get(params["page"])
        response = mock.Mock(status_code=200 if body else 204)
        response.json.return_value = body
        return response

    with mock.patch.object(amo.S, "get", side_effect=fake_get), mock.patch.object(amo.time, "sleep"):
        result = {item["id"]: (item["problem"], item["overdue_days"]) for item in amo.problem_leads()}
    return result, calls


def test_finds_leads_without_tasks_and_with_overdue_tasks():
    tasks = {
        1: page("tasks", [
            {"entity_id": 2, "complete_till": NOW - 3 * DAY},  # просрочена на 3 дня
            {"entity_id": 3, "complete_till": NOW + DAY},      # срок ещё не наступил
            {"entity_id": 4, "complete_till": NOW + DAY},
        ], has_next=True),
        2: page("tasks", [{"entity_id": 4, "complete_till": NOW - DAY - 60}]),  # у сделки 4 есть и просроченная
    }
    leads = {1: page("leads", [lead(1), lead(2), lead(3), lead(4)], has_next=True)}  # страница 2 -> 204

    result, calls = run(tasks, leads)

    assert result == {1: ("no_tasks", None), 2: ("overdue", 3), 4: ("overdue", 1)}
    assert [c[1]["page"] for c in calls] == [1, 2, 1, 2]


def test_skips_closed_and_deleted_leads():
    leads = {1: page("leads", [lead(5, status_id=142), lead(6, status_id=143), lead(7, is_deleted=True)])}

    result, _ = run({}, leads)

    assert result == {}


def test_requests_only_open_lead_tasks():
    _, calls = run({}, {})

    url, params = calls[0]
    assert url == "https://test.amocrm.ru/api/v4/tasks"
    assert params["filter[is_completed]"] == 0
    assert params["filter[entity_type]"] == "leads"
    assert params["limit"] == 250


@pytest.mark.parametrize("status", [401, 429, 500])
def test_api_errors_are_not_swallowed(status):
    response = mock.Mock(status_code=status)
    response.raise_for_status.side_effect = amo.requests.HTTPError(str(status))
    with mock.patch.object(amo.S, "get", return_value=response), pytest.raises(amo.requests.HTTPError):
        list(amo.problem_leads())
