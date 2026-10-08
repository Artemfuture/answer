"""Активные сделки amoCRM без открытых задач или с просроченными задачами (API v4)."""
import os
import time

import requests

BASE = os.environ["AMO_BASE_URL"].rstrip("/") + "/api/v4"  # https://citycar.amocrm.ru
S = requests.Session()
S.headers["Authorization"] = f"Bearer {os.environ['AMO_TOKEN']}"  # долгосрочный токен / OAuth
CLOSED = {142, 143}  # системные этапы «Успешно реализовано» и «Закрыто и не реализовано»


def fetch_all(path, params=None):
    """Постранично выгружает сущности; пустой список amoCRM отдаёт как 204 No Content."""
    page = 1
    while True:
        r = S.get(f"{BASE}/{path}", params={**(params or {}), "page": page, "limit": 250}, timeout=30)
        if r.status_code == 204:
            return
        r.raise_for_status()
        data = r.json()
        yield from data.get("_embedded", {}).get(path, [])
        if "next" not in data.get("_links", {}):
            return
        page += 1
        time.sleep(0.15)  # лимит API — 7 запросов в секунду


def problem_leads():
    now = int(time.time())
    deadlines = {}  # lead_id -> самый ранний срок среди невыполненных задач
    for t in fetch_all("tasks", {"filter[is_completed]": 0, "filter[entity_type]": "leads"}):
        deadlines[t["entity_id"]] = min(t["complete_till"], deadlines.get(t["entity_id"], t["complete_till"]))
    for lead in fetch_all("leads"):
        if lead["status_id"] in CLOSED or lead.get("is_deleted"):
            continue
        due = deadlines.get(lead["id"])
        if due is None:
            yield {**lead, "problem": "no_tasks", "overdue_days": None}
        elif due < now:
            yield {**lead, "problem": "overdue", "overdue_days": (now - due) // 86400}


if __name__ == "__main__":
    for lead in problem_leads():
        extra = f", просрочка {lead['overdue_days']} дн." if lead["overdue_days"] is not None else ""
        print(f"#{lead['id']} «{lead['name']}» отв. {lead['responsible_user_id']}: {lead['problem']}{extra}")
