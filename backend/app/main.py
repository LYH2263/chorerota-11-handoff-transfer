import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import seed
from app.db import connect
from app.engines.rota import build_week_slots, swap_legal, apply_swap
from app.modules.handover import preview as handover_preview
from app.modules.handover import confirm as handover_confirm
from app.modules.handover import projection as handover_projection
from app.modules.handover.preview import HandoverError

app = FastAPI(title="Chorerota", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup(): seed.init_db()

@app.get("/api/health")
def health(): return {"ok": True, "project": "chorerota"}

@app.get("/api/members")
def list_members():
    c = connect(); rows = [dict(r) for r in c.execute("SELECT * FROM members")]; c.close(); return rows

@app.post("/api/members")
def add_member(body: dict):
    c = connect()
    cur = c.execute("INSERT INTO members(name,active,data_quality) VALUES (?,?,?)",
                    (body.get("name","未命名"), int(body.get("active",1)), body.get("data_quality","clean")))
    c.commit(); mid = cur.lastrowid; c.close(); return {"id": mid}

@app.post("/api/members/{member_id}/deactivate")
def deactivate_member(member_id: int):
    """停用成员前必须先签交接条；无交接条（或名下仍有格子）一律拒绝。"""
    c = connect()
    try:
        check = handover_projection.deactivation_check(c, member_id)
    except HandoverError as e:
        c.close(); raise HTTPException(404, e.reason)
    if not check["allowed"]:
        c.close()
        if not check["has_handover"]:
            raise HTTPException(400, "handover_required")
        raise HTTPException(400, "cells_remaining:" + str(check["remaining_cells"]))
    c.execute("UPDATE members SET active=0 WHERE id=?", (member_id,))
    c.commit(); c.close()
    return {"ok": True, "member_id": member_id}

class HandoverBody(BaseModel):
    week_id: int
    from_member: int
    to_member: int
    note: str = ""

@app.post("/api/handovers/preview")
def handover_preview_api(body: HandoverBody):
    """只读：列出将被接管的格子，不改库。"""
    c = connect()
    try:
        return handover_preview.build_preview(c, body.week_id, body.from_member, body.to_member)
    except HandoverError as e:
        raise HTTPException(400, e.reason)
    finally:
        c.close()

@app.post("/api/handovers/confirm")
def handover_confirm_api(body: HandoverBody):
    """确认：格子改派接收人，引用交出人旧身份的 pending 对调自动作废，落交接条。"""
    c = connect()
    try:
        result = handover_confirm.confirm_handover(
            c, body.week_id, body.from_member, body.to_member, body.note)
        c.commit()
    except HandoverError as e:
        c.rollback(); c.close(); raise HTTPException(400, e.reason)
    except Exception:
        c.rollback(); c.close(); raise
    c.close()
    return result

@app.get("/api/tasks")
def list_tasks():
    c = connect(); rows = [dict(r) for r in c.execute("SELECT * FROM tasks")]; c.close(); return rows

@app.post("/api/tasks")
def add_task(body: dict):
    c = connect()
    cur = c.execute("INSERT INTO tasks(title,weight,data_quality) VALUES (?,?,?)",
                    (body.get("title","任务"), int(body.get("weight",1)), body.get("data_quality","clean")))
    c.commit(); tid = cur.lastrowid; c.close(); return {"id": tid}

@app.get("/api/weeks")
def list_weeks():
    c = connect(); rows = [dict(r) for r in c.execute("SELECT * FROM weeks")]; c.close(); return rows

@app.get("/api/weeks/{week_id}/board")
def week_board(week_id: int):
    c = connect()
    try:
        return handover_projection.board_view(c, week_id)
    except HandoverError as e:
        raise HTTPException(404, e.reason)
    finally:
        c.close()

class GenBody(BaseModel):
    days: int = 7

@app.post("/api/weeks/{week_id}/generate")
def generate(week_id: int, body: GenBody = GenBody()):
    c = connect()
    week = c.execute("SELECT * FROM weeks WHERE id=?", (week_id,)).fetchone()
    if not week: c.close(); raise HTTPException(404, "week not found")
    mids = [r["id"] for r in c.execute("SELECT id FROM members WHERE active=1 AND data_quality='clean' ORDER BY id")]
    tids = [r["id"] for r in c.execute("SELECT id FROM tasks WHERE data_quality='clean' AND weight>0 ORDER BY id")]
    slots = build_week_slots(mids, tids, days=body.days)
    c.execute("DELETE FROM assignments WHERE week_id=?", (week_id,))
    for s in slots:
        c.execute("INSERT INTO assignments(week_id,day,task_id,member_id) VALUES (?,?,?,?)",
                  (week_id, s["day"], s["task_id"], s["member_id"]))
    c.execute("UPDATE weeks SET status='ready' WHERE id=?", (week_id,))
    c.commit(); c.close()
    return {"count": len(slots), "slots": slots}

class SwapBody(BaseModel):
    a_day: int; a_task: int; b_day: int; b_task: int; note: str = ""

@app.post("/api/weeks/{week_id}/swaps")
def request_swap(week_id: int, body: SwapBody):
    c = connect()
    assigns = [dict(r) for r in c.execute("SELECT day,task_id,member_id FROM assignments WHERE week_id=?", (week_id,))]
    check = swap_legal(assigns, body.a_day, body.a_task, body.b_day, body.b_task)
    if not check["ok"]:
        c.close(); raise HTTPException(400, check["reason"])
    cur = c.execute(
        "INSERT INTO swap_requests(week_id,a_day,a_task,b_day,b_task,status,note,a_member,b_member) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (week_id, body.a_day, body.a_task, body.b_day, body.b_task, "pending", body.note,
         check["a_member"], check["b_member"]))
    c.commit(); sid = cur.lastrowid; c.close()
    return {"id": sid, "status": "pending", **check}

@app.get("/api/swaps")
def list_swaps():
    c = connect(); rows = [dict(r) for r in c.execute("SELECT * FROM swap_requests ORDER BY id DESC")]; c.close(); return rows

@app.post("/api/swaps/{swap_id}/confirm")
def confirm_swap(swap_id: int):
    c = connect()
    sw = c.execute("SELECT * FROM swap_requests WHERE id=?", (swap_id,)).fetchone()
    if not sw: c.close(); raise HTTPException(404, "swap not found")
    if sw["status"] == "voided":
        c.close(); raise HTTPException(400, "voided:" + (sw["void_reason"] or ""))
    if sw["status"] != "pending":
        c.close(); raise HTTPException(400, "not_pending")
    assigns = [dict(r) for r in c.execute(
        "SELECT id,day,task_id,member_id FROM assignments WHERE week_id=?", (sw["week_id"],))]
    # 申请时锁定了格子的成员快照；看板已被交接/改表挪动则申请作废，不能盲改
    cur_a = next((a for a in assigns if a["day"] == sw["a_day"] and a["task_id"] == sw["a_task"]), None)
    cur_b = next((a for a in assigns if a["day"] == sw["b_day"] and a["task_id"] == sw["b_task"]), None)
    if cur_a is None or cur_b is None:
        c.close(); raise HTTPException(400, "slot_missing")
    if cur_a["member_id"] != sw["a_member"] or cur_b["member_id"] != sw["b_member"]:
        c.execute("UPDATE swap_requests SET status='voided', void_reason='stale' WHERE id=?", (swap_id,))
        c.commit(); c.close(); raise HTTPException(400, "stale_voided")
    slots = [{"day": a["day"], "task_id": a["task_id"], "member_id": a["member_id"]} for a in assigns]
    try:
        new_slots = apply_swap(slots, sw["a_day"], sw["a_task"], sw["b_day"], sw["b_task"])
    except ValueError as e:
        c.close(); raise HTTPException(400, str(e))
    for a, s in zip(assigns, new_slots):
        c.execute("UPDATE assignments SET member_id=? WHERE id=?", (s["member_id"], a["id"]))
    c.execute("UPDATE swap_requests SET status='confirmed' WHERE id=?", (swap_id,))
    c.commit(); c.close()
    return {"ok": True, "swap_id": swap_id}

@app.get("/api/settings")
def get_settings():
    c = connect(); rows = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}; c.close(); return rows

@app.put("/api/settings")
def put_settings(body: dict):
    c = connect()
    for k, v in body.items():
        c.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
    c.commit(); c.close(); return {"ok": True}
