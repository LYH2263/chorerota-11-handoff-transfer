"""离场交接条 · 看板投影（纯只读）。

把 assignments 与已确认交接条拼成"本周看板 + 同钉移交清单"视图；
另提供停用前的只读校验，供停用接口拦截。
"""

from .preview import HandoverError


def board_view(c, week_id: int) -> dict:
    week = c.execute("SELECT * FROM weeks WHERE id=?", (week_id,)).fetchone()
    if week is None:
        raise HandoverError("week_not_found")

    members = {r["id"]: dict(r) for r in c.execute("SELECT id,name,active,data_quality FROM members")}
    tasks = {r["id"]: r["title"] for r in c.execute("SELECT id,title FROM tasks")}

    assigns = [dict(r) for r in c.execute(
        "SELECT * FROM assignments WHERE week_id=? ORDER BY day, task_id", (week_id,))]
    for a in assigns:
        m = members.get(a["member_id"])
        a["member_name"] = m["name"] if m else "?"
        a["task_title"] = tasks.get(a["task_id"], "?")

    handovers = [dict(r) for r in c.execute(
        "SELECT * FROM handovers WHERE week_id=? AND status='confirmed' ORDER BY id",
        (week_id,))]
    for h in handovers:
        fm = members.get(h["from_member"])
        tm = members.get(h["to_member"])
        h["from_member_name"] = fm["name"] if fm else "?"
        h["to_member_name"] = tm["name"] if tm else "?"
        h["cells"] = [dict(r) for r in c.execute(
            "SELECT day,task_id,from_member,to_member FROM handover_cells WHERE handover_id=? ORDER BY day,task_id",
            (h["id"],))]
        for cell in h["cells"]:
            cell["task_title"] = tasks.get(cell["task_id"], "?")

    return {"week": dict(week), "assignments": assigns, "handovers": handovers}


def deactivation_check(c, member_id: int) -> dict:
    """停用前只读校验：必须签过交接条，且名下已无任何在管格子。"""
    m = c.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    if m is None:
        raise HandoverError("member_not_found")
    has_handover = c.execute(
        "SELECT 1 FROM handovers WHERE from_member=? AND status='confirmed' LIMIT 1",
        (member_id,)).fetchone() is not None
    remaining = c.execute(
        "SELECT COUNT(*) c FROM assignments WHERE member_id=?", (member_id,)).fetchone()["c"]
    return {
        "member_id": member_id,
        "has_handover": has_handover,
        "remaining_cells": remaining,
        "allowed": has_handover and remaining == 0,
    }
