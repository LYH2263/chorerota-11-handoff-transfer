"""离场交接条 · 预览（纯只读，不写任何库）。

职责：校验交出人/接收人/周，列出指定周内将被接管的格子。
确认写库见 ``confirm``，看板投影见 ``projection``。
"""


class HandoverError(ValueError):
    """交接校验失败，``reason`` 为机器可读码。"""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _member(c, member_id: int):
    m = c.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    if m is None:
        raise HandoverError("member_not_found")
    return m


def validate(c, week_id: int, from_member: int, to_member: int):
    """交接双方与周的共同校验，预览与确认都走这里。"""
    week = c.execute("SELECT * FROM weeks WHERE id=?", (week_id,)).fetchone()
    if week is None:
        raise HandoverError("week_not_found")
    fm = _member(c, from_member)
    tm = _member(c, to_member)
    if not fm["active"]:
        raise HandoverError("from_member_inactive")
    if tm["id"] == fm["id"]:
        raise HandoverError("receiver_is_self")
    if not tm["active"]:
        raise HandoverError("receiver_inactive")
    if tm["data_quality"] != "clean":
        raise HandoverError("receiver_dirty")
    return week, fm, tm


def build_preview(c, week_id: int, from_member: int, to_member: int) -> dict:
    """返回将被接管的格子清单。只读：调用前后数据库内容不变。"""
    validate(c, week_id, from_member, to_member)
    cells = [dict(r) for r in c.execute(
        """
        SELECT a.id      AS assignment_id,
               a.day     AS day,
               a.task_id AS task_id,
               a.member_id AS from_member,
               ?         AS to_member,
               t.title   AS task_title
        FROM assignments a
        JOIN tasks t ON t.id = a.task_id
        WHERE a.week_id = ? AND a.member_id = ?
        ORDER BY a.day, a.task_id
        """,
        (to_member, week_id, from_member),
    )]
    return {
        "week_id": week_id,
        "from_member": from_member,
        "to_member": to_member,
        "count": len(cells),
        "cells": cells,
    }
