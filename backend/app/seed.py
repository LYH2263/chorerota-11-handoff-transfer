from app.db import connect

def _has_column(c, table: str, column: str) -> bool:
    return any(r["name"] == column for r in c.execute(f"PRAGMA table_info({table})"))

def init_db():
    c = connect()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY, name TEXT, active INT, data_quality TEXT);
    CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, title TEXT, weight INT, data_quality TEXT);
    CREATE TABLE IF NOT EXISTS weeks(id INTEGER PRIMARY KEY, label TEXT, status TEXT);
    CREATE TABLE IF NOT EXISTS assignments(id INTEGER PRIMARY KEY AUTOINCREMENT, week_id INT, day INT, task_id INT, member_id INT);
    CREATE TABLE IF NOT EXISTS swap_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, week_id INT, a_day INT, a_task INT, b_day INT, b_task INT, status TEXT, note TEXT,
        a_member INT, b_member INT, void_reason TEXT);
    CREATE TABLE IF NOT EXISTS handovers(id INTEGER PRIMARY KEY AUTOINCREMENT, week_id INT, from_member INT, to_member INT, cell_count INT, status TEXT, note TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS handover_cells(id INTEGER PRIMARY KEY AUTOINCREMENT, handover_id INT, assignment_id INT, day INT, task_id INT, from_member INT, to_member INT);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    """)
    # 旧库迁移：给老的 swap_requests 补成员快照列
    if not _has_column(c, "swap_requests", "a_member"):
        c.execute("ALTER TABLE swap_requests ADD COLUMN a_member INT")
    if not _has_column(c, "swap_requests", "b_member"):
        c.execute("ALTER TABLE swap_requests ADD COLUMN b_member INT")
    if not _has_column(c, "swap_requests", "void_reason"):
        c.execute("ALTER TABLE swap_requests ADD COLUMN void_reason TEXT")
    # 旧 pending 对调没有成员快照，按当前看板回填，便于后续失效判定
    old = c.execute("SELECT * FROM swap_requests WHERE status='pending' AND a_member IS NULL").fetchall()
    for r in old:
        sa = c.execute(
            "SELECT member_id FROM assignments WHERE week_id=? AND day=? AND task_id=?",
            (r["week_id"], r["a_day"], r["a_task"])).fetchone()
        sb = c.execute(
            "SELECT member_id FROM assignments WHERE week_id=? AND day=? AND task_id=?",
            (r["week_id"], r["b_day"], r["b_task"])).fetchone()
        if sa and sb:
            c.execute("UPDATE swap_requests SET a_member=?, b_member=? WHERE id=?",
                      (sa["member_id"], sb["member_id"], r["id"]))
    if c.execute("SELECT COUNT(*) c FROM members").fetchone()["c"] == 0:
        c.executemany("INSERT INTO members(name,active,data_quality) VALUES (?,?,?)", [
            ("阿明", 1, "clean"), ("小雨", 1, "clean"), ("爷爷", 1, "clean"),
            ("幽灵成员", 0, "dirty"),
        ])
        c.executemany("INSERT INTO tasks(title,weight,data_quality) VALUES (?,?,?)", [
            ("洗碗", 1, "clean"), ("倒垃圾", 1, "clean"), ("扫地", 2, "clean"),
            ("负权重任务", -1, "dirty"),
        ])
        c.execute("INSERT INTO weeks(label,status) VALUES ('第12周','draft')")
        c.execute("INSERT INTO settings(key,value) VALUES ('household','绿纸之家')")
        c.commit()
    c.close()
