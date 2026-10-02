import os
import pytest

from app import seed
from app.db import connect
from app.modules.handover.preview import build_preview, HandoverError
from app.modules.handover.confirm import confirm_handover
from app.modules.handover.projection import board_view, deactivation_check


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seed.init_db()
    yield


def _generate(c, week_id=1, days=2):
    """与 main.generate 同样的取号逻辑，直接在测试连接上落格。"""
    from app.engines.rota import build_week_slots
    mids = [r["id"] for r in c.execute(
        "SELECT id FROM members WHERE active=1 AND data_quality='clean' ORDER BY id")]
    tids = [r["id"] for r in c.execute(
        "SELECT id FROM tasks WHERE data_quality='clean' AND weight>0 ORDER BY id")]
    slots = build_week_slots(mids, tids, days=days)
    c.execute("DELETE FROM assignments WHERE week_id=?", (week_id,))
    for s in slots:
        c.execute("INSERT INTO assignments(week_id,day,task_id,member_id) VALUES (?,?,?,?)",
                  (week_id, s["day"], s["task_id"], s["member_id"]))
    c.commit()
    return slots


def _cells_of(c, member_id, week_id=1):
    return [dict(r) for r in c.execute(
        "SELECT * FROM assignments WHERE week_id=? AND member_id=? ORDER BY day,task_id",
        (week_id, member_id))]


# ---------- 预览：只读、不改库 ----------

def test_preview_lists_cells_without_writing(db):
    c = connect()
    _generate(c)
    before = [dict(r) for r in c.execute("SELECT * FROM assignments ORDER BY id")]
    pvs = [dict(r) for r in c.execute("SELECT * FROM handovers")]

    p = build_preview(c, 1, from_member=1, to_member=2)

    assert p["count"] == len(_cells_of(c, 1))
    assert p["count"] > 0
    assert {x["from_member"] for x in p["cells"]} == {1}
    assert {x["to_member"] for x in p["cells"]} == {2}
    # 预览前后库内容完全一致
    after = [dict(r) for r in c.execute("SELECT * FROM assignments ORDER BY id")]
    assert before == after
    assert [dict(r) for r in c.execute("SELECT * FROM handovers")] == pvs
    c.close()


def test_preview_rejects_bad_receivers(db):
    c = connect()
    _generate(c)
    with pytest.raises(HandoverError) as e:  # 接收人=交出人
        build_preview(c, 1, 1, 1)
    assert e.value.reason == "receiver_is_self"
    with pytest.raises(HandoverError):  # 幽灵成员：停用
        build_preview(c, 1, 1, 4)
    # 在岗但脏
    cur = c.execute("INSERT INTO members(name,active,data_quality) VALUES ('脏脏',1,'dirty')")
    dirty_id = cur.lastrowid; c.commit()
    with pytest.raises(HandoverError) as e:
        build_preview(c, 1, 1, dirty_id)
    assert e.value.reason == "receiver_dirty"
    # 交出人本人已停用
    c.execute("UPDATE members SET active=0 WHERE id=2"); c.commit()
    with pytest.raises(HandoverError) as e:
        build_preview(c, 1, 2, 3)
    assert e.value.reason == "from_member_inactive"
    c.close()


# ---------- 确认：改格、落条、接收人在确认时失效 ----------

def test_confirm_reassigns_cells_and_records_handover(db):
    c = connect()
    _generate(c)
    mine = _cells_of(c, 1)
    result = confirm_handover(c, 1, 1, 2, note="搬家离场")
    c.commit()

    assert result["cell_count"] == len(mine)
    assert _cells_of(c, 1) == []
    taken = [dict(r) for r in c.execute(
        "SELECT day,task_id FROM assignments WHERE week_id=1 AND member_id=2 ORDER BY day,task_id")]
    original = sorted(({"day": x["day"], "task_id": x["task_id"]} for x in mine),
                      key=lambda x: (x["day"], x["task_id"]))
    assert all(x in taken for x in original)

    h = c.execute("SELECT * FROM handovers WHERE id=?", (result["id"],)).fetchone()
    assert h["status"] == "confirmed" and h["note"] == "搬家离场"
    cells = [dict(r) for r in c.execute(
        "SELECT * FROM handover_cells WHERE handover_id=?", (h["id"],))]
    assert len(cells) == len(mine)
    assert {x["from_member"] for x in cells} == {1}
    assert {x["to_member"] for x in cells} == {2}
    c.close()


def test_confirm_fails_when_receiver_became_dirty_after_preview(db):
    """预览后接收人被标脏，确认必须失败且库不变。"""
    c = connect()
    _generate(c)
    build_preview(c, 1, 1, 2)  # 预览通过
    c.execute("UPDATE members SET data_quality='dirty' WHERE id=2"); c.commit()
    with pytest.raises(HandoverError) as e:
        confirm_handover(c, 1, 1, 2)
    assert e.value.reason == "receiver_dirty"
    c.rollback()
    assert len(_cells_of(c, 1)) > 0  # 格子没动
    c.close()


def test_confirm_zero_cell_handover_allowed_for_exit_record(db):
    """本周零格也允许签条留离场记录（否则未排班者永远无法停用）。"""
    c = connect()
    _generate(c)
    c.execute("DELETE FROM assignments WHERE member_id=3"); c.commit()
    result = confirm_handover(c, 1, 3, 2)
    c.commit()
    assert result["cell_count"] == 0
    h = c.execute("SELECT * FROM handovers WHERE id=?", (result["id"],)).fetchone()
    assert h["status"] == "confirmed"
    assert c.execute(
        "SELECT COUNT(*) n FROM handover_cells WHERE handover_id=?", (result["id"],)).fetchone()["n"] == 0
    c.close()


# ---------- 旧 pending 对调：自动作废，列表与看板一致 ----------

def test_confirm_voids_pending_swaps_referencing_old_identity(db):
    c = connect()
    slots = _generate(c)
    # 找到 1↔2 一格和 2↔3 一格（后者不涉及交出人 1）
    by_member = {}
    for s in slots:
        by_member.setdefault(s["member_id"], s)
    a, b = by_member[1], by_member[2]
    cur = c.execute(
        "INSERT INTO swap_requests(week_id,a_day,a_task,b_day,b_task,status,a_member,b_member) "
        "VALUES (1,?,?,?,?,'pending',1,2)",
        (a["day"], a["task_id"], b["day"], b["task_id"]))
    swap_touching = cur.lastrowid
    a2, b2 = by_member[2], by_member[3]
    cur = c.execute(
        "INSERT INTO swap_requests(week_id,a_day,a_task,b_day,b_task,status,a_member,b_member) "
        "VALUES (1,?,?,?,?,'pending',2,3)",
        (a2["day"], a2["task_id"], b2["day"], b2["task_id"]))
    swap_unrelated = cur.lastrowid
    c.commit()

    result = confirm_handover(c, 1, 1, 2)
    c.commit()
    assert result["voided_swap_ids"] == [swap_touching]

    touched = c.execute("SELECT * FROM swap_requests WHERE id=?", (swap_touching,)).fetchone()
    assert touched["status"] == "voided"
    assert touched["void_reason"] == "handover_confirmed"
    other = c.execute("SELECT * FROM swap_requests WHERE id=?", (swap_unrelated,)).fetchone()
    assert other["status"] == "pending"  # 不牵连

    # 看板投影：交接条与本周看板同钉，且格子已全部归接收人
    view = board_view(c, 1)
    assert {x["member_id"] for x in view["assignments"]} >= {2, 3}
    assert 1 not in {x["member_id"] for x in view["assignments"]}
    assert len(view["handovers"]) == 1
    h0 = view["handovers"][0]
    assert h0["from_member_name"] == "阿明" and h0["to_member_name"] == "小雨"
    assert len(h0["cells"]) == result["cell_count"]
    c.close()


# ---------- 无交接条直接停用：拒绝；交后可停；新周不再含停用者 ----------

def test_deactivate_requires_handover_then_succeeds(db):
    from fastapi import HTTPException
    from app import main
    from pydantic import BaseModel

    c = connect()
    _generate(c)
    c.close()

    with pytest.raises(HTTPException) as e:
        main.deactivate_member(1)
    assert e.value.status_code == 400 and e.value.detail == "handover_required"

    c = connect()
    confirm_handover(c, 1, 1, 2)
    c.commit(); c.close()

    # 交后名下无格子，停用成功
    r = main.deactivate_member(1)
    assert r["ok"] is True
    c = connect()
    assert c.execute("SELECT active FROM members WHERE id=1").fetchone()["active"] == 0
    c.close()


def test_new_week_generation_excludes_deactivated_member(db):
    c = connect()
    _generate(c)
    confirm_handover(c, 1, 1, 2)
    c.execute("UPDATE members SET active=0 WHERE id=1")
    c.execute("INSERT INTO weeks(label,status) VALUES ('第13周','draft')")
    c.commit()
    new_week = c.execute("SELECT id FROM weeks ORDER BY id DESC LIMIT 1").fetchone()["id"]

    from app.engines.rota import build_week_slots
    mids = [r["id"] for r in c.execute(
        "SELECT id FROM members WHERE active=1 AND data_quality='clean' ORDER BY id")]
    assert 1 not in mids
    tids = [r["id"] for r in c.execute(
        "SELECT id FROM tasks WHERE data_quality='clean' AND weight>0 ORDER BY id")]
    slots = build_week_slots(mids, tids, days=3)
    assert slots and all(s["member_id"] != 1 for s in slots)
    c.close()


def test_deactivation_blocked_while_cells_remain_in_other_week(db):
    """第1周交了，第2周还有格子 -> 仍拒绝停用。"""
    c = connect()
    _generate(c, week_id=1)
    c.execute("INSERT INTO weeks(label,status) VALUES ('第13周','draft')")
    c.commit()
    new_week = c.execute("SELECT id FROM weeks ORDER BY id DESC LIMIT 1").fetchone()["id"]
    _generate(c, week_id=new_week)

    confirm_handover(c, 1, 1, 2)  # 只交第1周
    c.commit()
    chk = deactivation_check(c, 1)
    assert chk["has_handover"] is True and chk["allowed"] is False
    assert chk["remaining_cells"] > 0
    c.close()
