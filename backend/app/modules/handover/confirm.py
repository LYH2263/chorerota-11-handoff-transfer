"""离场交接条 · 确认写库。

确认时：
1. 再跑一次 :func:`app.modules.handover.preview.validate`（接收人可能在预览后变停用/变脏）；
2. 把指定周内交出人名下的格子全部改派给接收人；
3. 自动作废仍引用交出人旧身份的 pending 对调（快照成员命中即 voided）；
4. 落一条 ``confirmed`` 交接条及其格子明细。

取舍：旧 pending 对调选择"自动作废"而非"确认时才失败"，
这样交接完成的瞬间对调列表即与看板一致，不会留下一确认就报错的僵尸申请。
"""

from datetime import datetime

from .preview import validate

VOID_REASON = "handover_confirmed"


def confirm_handover(c, week_id: int, from_member: int, to_member: int, note: str = "") -> dict:
    """在一个已打开的连接上执行交接，由调用方负责 commit/rollback。"""
    validate(c, week_id, from_member, to_member)

    cells = [dict(r) for r in c.execute(
        "SELECT id AS assignment_id, day, task_id FROM assignments "
        "WHERE week_id=? AND member_id=? ORDER BY day, task_id",
        (week_id, from_member),
    )]

    # 1) 格子改派给接收人（零格时只留离场记录，不动任何格子）
    if cells:
        c.execute(
            "UPDATE assignments SET member_id=? WHERE week_id=? AND member_id=?",
            (to_member, week_id, from_member),
        )

    # 2) 自动作废仍引用交出人旧身份的 pending 对调（以申请时的成员快照判定）
    voided = [dict(r) for r in c.execute(
        "SELECT id FROM swap_requests "
        "WHERE week_id=? AND status='pending' AND (a_member=? OR b_member=?)",
        (week_id, from_member, from_member),
    )]
    if voided:
        c.execute(
            "UPDATE swap_requests SET status='voided', void_reason=? "
            "WHERE week_id=? AND status='pending' AND (a_member=? OR b_member=?)",
            (VOID_REASON, week_id, from_member, from_member),
        )

    # 3) 落交接条 + 格子明细
    cur = c.execute(
        "INSERT INTO handovers(week_id,from_member,to_member,cell_count,status,note,created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (week_id, from_member, to_member, len(cells), "confirmed", note,
         datetime.now().isoformat(timespec="seconds")),
    )
    hid = cur.lastrowid
    c.executemany(
        "INSERT INTO handover_cells(handover_id,assignment_id,day,task_id,from_member,to_member) "
        "VALUES (?,?,?,?,?,?)",
        [(hid, x["assignment_id"], x["day"], x["task_id"], from_member, to_member) for x in cells],
    )

    return {
        "id": hid,
        "week_id": week_id,
        "from_member": from_member,
        "to_member": to_member,
        "cell_count": len(cells),
        "voided_swap_ids": [v["id"] for v in voided],
    }
