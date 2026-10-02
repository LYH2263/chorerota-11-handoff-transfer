# Chorerota · 家庭值日轮转

底座：成员+任务 → round-robin 生成周表 → 申请对调 → 确认改表。

| 服务 | 端口 |
| --- | --- |
| 前端 | 5100 |
| API | 10100 |

```bash
docker compose up --build
pytest backend/app/tests
```

种子含 clean/dirty。0-1 空桩：`streak_badge` / `skip_week` / `chore_photo`。

## 离场交接条

成员停用前必须先签交接条：`POST /api/handovers/preview`（只读列出将被接管的格子，不改库）→ `POST /api/handovers/confirm`（格子改派接收人、落交接条）→ `POST /api/members/{id}/deactivate`（无条或名下仍有格子则 400）。接收人停用/dirty/与交出人相同则确认失败；确认后仍引用交出人旧身份的 pending 对调自动作废（`voided` / `void_reason=handover_confirmed`），对调列表与看板即刻一致；新周生成本就只取 active+clean，停用交出人不再落格。实现按 `app/modules/handover/` 下 `preview.py` / `confirm.py` / `projection.py`（看板投影，移交清单与本周看板同钉）分模块。
