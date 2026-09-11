
import sqlite3
import os
import json
import re
import shutil
from datetime import datetime, timedelta
from functools import wraps

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "barber_shop.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, phone TEXT UNIQUE, gender TEXT DEFAULT '男',
        id_card TEXT, membership_type TEXT DEFAULT '普通会员',
        balance REAL DEFAULT 0, bonus_balance REAL DEFAULT 0,
        total_consumed REAL DEFAULT 0,
        total_recharge REAL DEFAULT 0, join_date TEXT NOT NULL,
        status TEXT DEFAULT '正常', remark TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS recharge_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER NOT NULL,
        amount REAL NOT NULL, bonus REAL DEFAULT 0, payment_method TEXT DEFAULT '现金',
        operator TEXT, remark TEXT, created_at TEXT NOT NULL,
        FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE)""")
    c.execute("""CREATE TABLE IF NOT EXISTS consumption_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER NOT NULL,
        service_name TEXT NOT NULL, price REAL NOT NULL,
        actual_price REAL NOT NULL, discount REAL DEFAULT 1.0,
        deduct_principal REAL DEFAULT 0, deduct_bonus REAL DEFAULT 0,
        operator TEXT, remark TEXT, created_at TEXT NOT NULL,
        FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE)""")
    c.execute("""CREATE TABLE IF NOT EXISTS packages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER NOT NULL,
        package_name TEXT NOT NULL, package_price REAL NOT NULL,
        service_count INTEGER NOT NULL, remaining_count INTEGER NOT NULL,
        valid_days INTEGER, expire_date TEXT,
        status TEXT DEFAULT '有效', start_date TEXT NOT NULL,
        end_date TEXT, created_at TEXT NOT NULL,
        FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE)""")
    c.execute("""CREATE TABLE IF NOT EXISTS operation_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, operator TEXT,
        action TEXT NOT NULL, target_type TEXT, target_id INTEGER,
        details TEXT, created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY, value TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS operators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        display_name TEXT, role TEXT DEFAULT 'operator',
        status TEXT DEFAULT '正常', created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""")

    c.execute("""CREATE TABLE IF NOT EXISTS barbers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, phone TEXT, position TEXT DEFAULT '理发师',
        status TEXT DEFAULT '正常', created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""")

    c.execute("""CREATE TABLE IF NOT EXISTS cash_sheets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operator TEXT NOT NULL, sheet_date TEXT,
        amount REAL NOT NULL,
        cash_amount REAL DEFAULT 0, wechat_amount REAL DEFAULT 0,
        alipay_amount REAL DEFAULT 0, card_amount REAL DEFAULT 0,
        cnt INTEGER DEFAULT 0, remark TEXT, submitted_by TEXT,
        created_at TEXT NOT NULL)""")

    member_cols = [r["name"] for r in c.execute("PRAGMA table_info(members)").fetchall()]
    if "bonus_balance" not in member_cols:
        c.execute("ALTER TABLE members ADD COLUMN bonus_balance REAL DEFAULT 0")
    recharge_cols = [r["name"] for r in c.execute("PRAGMA table_info(recharge_records)").fetchall()]
    if "bonus" not in recharge_cols:
        c.execute("ALTER TABLE recharge_records ADD COLUMN bonus REAL DEFAULT 0")
    consume_cols = [r["name"] for r in c.execute("PRAGMA table_info(consumption_records)").fetchall()]
    if "deduct_principal" not in consume_cols:
        c.execute("ALTER TABLE consumption_records ADD COLUMN deduct_principal REAL DEFAULT 0")
    if "deduct_bonus" not in consume_cols:
        c.execute("ALTER TABLE consumption_records ADD COLUMN deduct_bonus REAL DEFAULT 0")
    if "barber_id" not in consume_cols:
        c.execute("ALTER TABLE consumption_records ADD COLUMN barber_id INTEGER")
    cash_cols = [r["name"] for r in c.execute("PRAGMA table_info(cash_sheets)").fetchall()]
    if "sheet_date" not in cash_cols:
        c.execute("ALTER TABLE cash_sheets ADD COLUMN sheet_date TEXT")
    if "cnt" not in cash_cols:
        c.execute("ALTER TABLE cash_sheets ADD COLUMN cnt INTEGER DEFAULT 0")
    if "submitted_by" not in cash_cols:
        c.execute("ALTER TABLE cash_sheets ADD COLUMN submitted_by TEXT")
    conn.commit()
    conn.close()
    _ensure_default_admin()

def log_op(operator, action, target_type=None, target_id=None, details=""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO operation_logs(operator,action,target_type,target_id,details,created_at) VALUES(?,?,?,?,?,?)",
        (operator, action, target_type, target_id, details, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def _insert_log(cursor, operator, action, target_type=None, target_id=None, details=""):
    cursor.execute(
        "INSERT INTO operation_logs(operator,action,target_type,target_id,details,created_at) VALUES(?,?,?,?,?,?)",
        (operator, action, target_type, target_id, details, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

def _ensure_default_admin():

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    try:
        conn.execute("INSERT OR IGNORE INTO operators(username,password,display_name,role,status,created_at,updated_at) VALUES('admin','123456','管理员','admin','正常',?,?)",
                     (now, now))
        conn.commit()
    finally:
        conn.close()

def get_all_operators():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM operators ORDER BY role DESC, id ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_operator_by_username(username):
    conn = get_conn()
    r = conn.execute("SELECT * FROM operators WHERE username=?", (username,)).fetchone()
    conn.close()
    return dict(r) if r else None

def add_operator(username, password, display_name="", role="operator", operator="system"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    try:
        conn.execute("INSERT INTO operators(username,password,display_name,role,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                     (username, password, display_name, role, "正常", now, now))
        conn.commit()
        log_op(operator, "新增操作员", "operator", None, f"新增操作员：{username}")
    finally:
        conn.close()

def update_operator(opid, **kwargs):
    allowed = {"display_name", "role", "status", "password"}
    valid = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not valid:
        return False
    valid["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_s = ", ".join(f"{k}=?" for k in valid)
    vals = list(valid.values()) + [opid]
    conn = get_conn()
    try:
        conn.execute(f"UPDATE operators SET {set_s} WHERE id=?", vals)
        conn.commit()
    finally:
        conn.close()
    return True

def delete_operator(opid, operator="system"):
    conn = get_conn()
    try:
        r = conn.execute("SELECT username FROM operators WHERE id=?", (opid,)).fetchone()
        if not r:
            return False
        if r["username"] == "admin":
            return False
        conn.execute("DELETE FROM operators WHERE id=?", (opid,))
        conn.commit()
        log_op(operator, "删除操作员", "operator", opid, f"删除操作员：{r['username']}")
        return True
    finally:
        conn.close()

def change_password(username, old_password, new_password):

    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM operators WHERE username=?", (username,)).fetchone()
        if not r:
            return {"ok": False, "msg": "操作员不存在"}
        if r["password"] != old_password:
            return {"ok": False, "msg": "原密码错误"}
        conn.execute("UPDATE operators SET password=?,updated_at=? WHERE id=?",
                     (new_password, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), r["id"]))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()

def get_all_barbers(status=None):
    conn = get_conn()
    if status:
        rows = conn.execute("SELECT * FROM barbers WHERE status=? ORDER BY id ASC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM barbers ORDER BY status DESC, id ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_barber(name, phone="", position="理发师", operator="system"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO barbers(name,phone,position,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (name, phone, position, "正常", now, now))
        bid = cur.lastrowid
        _insert_log(cur, operator, "新增理发师", "barber", bid, f"新增理发师：{name}")
        conn.commit()
        return bid
    finally:
        conn.close()

def update_barber(bid, **kwargs):
    allowed = {"name", "phone", "position", "status"}
    valid = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not valid:
        return False
    valid["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_s = ", ".join(f"{k}=?" for k in valid)
    vals = list(valid.values()) + [bid]
    conn = get_conn()
    try:
        conn.execute(f"UPDATE barbers SET {set_s} WHERE id=?", vals)
        conn.commit()
    finally:
        conn.close()
    return True

def delete_barber(bid, operator="system"):
    conn = get_conn()
    try:
        r = conn.execute("SELECT name FROM barbers WHERE id=?", (bid,)).fetchone()
        if not r:
            return False
        conn.execute("DELETE FROM barbers WHERE id=?", (bid,))
        conn.commit()
        log_op(operator, "删除理发师", "barber", bid, f"删除理发师：{r['name']}")
        return True
    finally:
        conn.close()

def get_recharge_summary(operator, date):

    conn = get_conn()
    rows = conn.execute(
        "SELECT payment_method, COUNT(*) AS cnt, COALESCE(SUM(amount),0) AS total FROM recharge_records WHERE operator=? AND DATE(created_at)=? GROUP BY payment_method",
        (operator, date)).fetchall()
    conn.close()
    summary = {"cash": 0, "wechat": 0, "alipay": 0, "card": 0, "cnt": 0, "amount": 0}
    for r in rows:
        key = {"现金": "cash", "微信": "wechat", "支付宝": "alipay", "银行卡": "card"}.get(r["payment_method"])
        if key:
            summary[key] = r["total"]
        summary["cnt"] += r["cnt"]
        summary["amount"] += r["total"]
    return summary

def get_cash_sheet_exists(operator, date):

    conn = get_conn()
    r = conn.execute("SELECT id FROM cash_sheets WHERE operator=? AND sheet_date=?", (operator, date)).fetchone()
    conn.close()
    return r is not None

def add_cash_sheet(operator, sheet_date, cash, wechat, alipay, card, cnt=0, remark="", submitted_by="system"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    amount = cash + wechat + alipay + card
    conn = get_conn()
    try:
        conn.execute("INSERT INTO cash_sheets(operator,sheet_date,amount,cash_amount,wechat_amount,alipay_amount,card_amount,cnt,remark,submitted_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (operator, sheet_date, amount, cash, wechat, alipay, card, cnt, remark, submitted_by, now))
        conn.commit()
        log_op(submitted_by, "交款", "cash_sheet", None,
               f"操作员 {operator} 交款 {amount:.2f} 元（{sheet_date}）")
    finally:
        conn.close()

def get_cash_sheets(operator=None, date=None, limit=200):
    conn = get_conn()
    sql = "SELECT * FROM cash_sheets"
    cond, args = [], []
    if operator:
        cond.append("operator=?")
        args.append(operator)
    if date:
        cond.append("sheet_date=?")
        args.append(date)
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY sheet_date DESC, created_at DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_cash_sheet(sid):
    conn = get_conn()
    r = conn.execute("SELECT * FROM cash_sheets WHERE id=?", (sid,)).fetchone()
    conn.close()
    return dict(r) if r else None

def delete_cash_sheet(sid, operator="system"):

    conn = get_conn()
    try:
        r = conn.execute("SELECT operator,sheet_date,amount FROM cash_sheets WHERE id=?", (sid,)).fetchone()
        if not r:
            return {"ok": False, "msg": "交款单不存在"}
        conn.execute("DELETE FROM cash_sheets WHERE id=?", (sid,))
        conn.commit()
        log_op(operator, "撤销交款", "cash_sheet", sid,
               f"撤销交款：{r['operator']} {r['sheet_date']} {r['amount']:.2f} 元")
        return {"ok": True}
    finally:
        conn.close()

def get_performance_report(start_date, end_date, barber_id=None):

    conn = get_conn()
    sql = """SELECT b.id AS barber_id, b.name AS barber_name, b.position,
                    COUNT(c.id) AS cnt,
                    COALESCE(SUM(c.price),0) AS total_price,
                    COALESCE(SUM(c.actual_price),0) AS total_actual
             FROM consumption_records c
             LEFT JOIN barbers b ON c.barber_id=b.id
             WHERE DATE(c.created_at) BETWEEN ? AND ?"""
    args = [start_date, end_date]
    if barber_id:
        sql += " AND c.barber_id=?"
        args.append(barber_id)
    sql += " GROUP BY c.barber_id ORDER BY total_actual DESC"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_barbers_for_select():

    return get_all_barbers(status="正常")

def get_all_members():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM members ORDER BY join_date DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_member(mid):
    conn = get_conn()
    r = conn.execute("SELECT * FROM members WHERE id=?", (mid,)).fetchone()
    conn.close()
    return dict(r) if r else None

def get_member_by_phone(phone):
    conn = get_conn()
    r = conn.execute("SELECT * FROM members WHERE phone=? AND status='正常'", (phone,)).fetchone()
    conn.close()
    return dict(r) if r else None

def search_members(keyword):
    kw = f"%{keyword}%"
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM members WHERE name LIKE ? OR phone LIKE ? OR id_card LIKE ? ORDER BY join_date DESC",
        (kw, kw, kw)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_member(name, phone, gender="男", id_card="", membership_type="普通会员",
               remark="", operator="system"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO members(name,phone,gender,id_card,membership_type,balance,total_consumed,total_recharge,join_date,status,remark,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (name, phone, gender, id_card, membership_type, 0, 0, 0, now, "正常", remark, now, now))
    mid = cur.lastrowid
    _insert_log(cur, operator, "添加会员", "member", mid, f"新增会员：{name}({phone})")
    conn.commit()
    conn.close()
    return mid

def update_member(mid, **kwargs):
    allowed = {"name", "phone", "gender", "id_card", "membership_type", "remark", "status"}
    valid = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not valid:
        return False
    valid["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_s = ", ".join(f"{k}=?" for k in valid)
    vals = list(valid.values()) + [mid]
    conn = get_conn()
    conn.execute(f"UPDATE members SET {set_s} WHERE id=?", vals)
    conn.commit()
    conn.close()
    return True

def cancel_member(mid, operator="system"):
    conn = get_conn()
    cur = conn.cursor()
    m = cur.execute("SELECT name,phone,balance FROM members WHERE id=?", (mid,)).fetchone()
    if not m:
        conn.close()
        return 0
    refund = m["balance"]
    cur.execute("UPDATE members SET status='注销',balance=0,bonus_balance=0,updated_at=? WHERE id=?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), mid))
    _insert_log(cur, operator, "注销会员", "member", mid,
                f"注销会员：{m[0]}({m[1]})，退还本金 {refund:.2f} 元")
    conn.commit()
    conn.close()
    return refund

def member_recharge(mid, amount, payment="现金", operator="system", remark="", bonus=0):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    cur = conn.cursor()
    m = cur.execute("SELECT balance,bonus_balance,total_recharge FROM members WHERE id=?", (mid,)).fetchone()
    if not m:
        conn.close()
        return {"ok": False, "msg": "会员不存在"}
    nb = m["balance"] + amount
    nbb = m["bonus_balance"] + bonus
    nt = m["total_recharge"] + amount
    cur.execute("INSERT INTO recharge_records(member_id,amount,bonus,payment_method,operator,remark,created_at) VALUES(?,?,?,?,?,?,?)",
                (mid, amount, bonus, payment, operator, remark, now))
    cur.execute("UPDATE members SET balance=?,bonus_balance=?,total_recharge=?,updated_at=? WHERE id=?",
                (nb, nbb, nt, now, mid))
    bonus_txt = f"，赠送 {bonus:.2f} 元" if bonus else ""
    _insert_log(cur, operator, "会员充值", "member", mid,
                f"充值 {amount:.2f} 元{bonus_txt}，方式：{payment}")
    conn.commit()
    conn.close()
    return {"ok": True, "new_balance": nb + nbb}

def member_consume(mid, service, price, discount=1.0, operator="system", remark="", barber_id=None):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    actual = price * discount
    conn = get_conn()
    cur = conn.cursor()
    m = cur.execute("SELECT balance,bonus_balance,total_consumed FROM members WHERE id=?", (mid,)).fetchone()
    if not m:
        conn.close()
        return {"ok": False, "msg": "会员不存在"}
    total = m["balance"] + m["bonus_balance"]
    if total < actual:
        conn.close()
        return {"ok": False, "msg": f"余额不足，还需 {actual - total:.2f} 元"}

    if m["balance"] >= actual:
        nb = m["balance"] - actual
        nbb = m["bonus_balance"]
        dp, db = actual, 0
    else:
        dp = m["balance"]
        db = actual - dp
        nb = 0
        nbb = m["bonus_balance"] - db
    nc = m["total_consumed"] + actual
    cur.execute("INSERT INTO consumption_records(member_id,service_name,price,actual_price,discount,deduct_principal,deduct_bonus,barber_id,operator,remark,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (mid, service, price, actual, discount, dp, db, barber_id, operator, remark, now))
    cur.execute("UPDATE members SET balance=?,bonus_balance=?,total_consumed=?,updated_at=? WHERE id=?",
                (nb, nbb, nc, now, mid))
    _insert_log(cur, operator, "会员消费", "member", mid, f"消费 {service} 原价{price} 实付{actual:.2f}")
    conn.commit()
    conn.close()
    return {"ok": True, "remaining": nb + nbb}

def undo_recharge_record(rid, operator="system"):

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    cur = conn.cursor()
    r = cur.execute("SELECT * FROM recharge_records WHERE id=?", (rid,)).fetchone()
    if not r:
        conn.close()
        return {"ok": False, "msg": "充值记录不存在"}
    m = cur.execute("SELECT name,balance,bonus_balance,total_recharge FROM members WHERE id=?", (r["member_id"],)).fetchone()
    if not m:
        conn.close()
        return {"ok": False, "msg": "会员不存在"}
    total_refund = r["amount"] + r["bonus"]
    if m["balance"] + m["bonus_balance"] < total_refund:
        conn.close()
        return {"ok": False, "msg": "该笔充值金额已被消费，无法撤销"}
    nb = m["balance"] - r["amount"]
    nbb = m["bonus_balance"] - r["bonus"]
    nt = m["total_recharge"] - r["amount"]
    cur.execute("DELETE FROM recharge_records WHERE id=?", (rid,))
    cur.execute("UPDATE members SET balance=?,bonus_balance=?,total_recharge=?,updated_at=? WHERE id=?",
                (nb, nbb, nt, now, r["member_id"]))
    _insert_log(cur, operator, "撤销充值", "recharge", rid,
                f"撤销充值 {r['amount']:.2f} 元（含赠送 {r['bonus']:.2f}），会员：{m['name']}")
    conn.commit()
    conn.close()
    return {"ok": True}

def undo_consume_record(rid, operator="system"):

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    cur = conn.cursor()
    r = cur.execute("SELECT * FROM consumption_records WHERE id=?", (rid,)).fetchone()
    if not r:
        conn.close()
        return {"ok": False, "msg": "消费记录不存在"}
    m = cur.execute("SELECT name,balance,bonus_balance,total_consumed FROM members WHERE id=?", (r["member_id"],)).fetchone()
    if not m:
        conn.close()
        return {"ok": False, "msg": "会员不存在"}
    nb = m["balance"] + r["deduct_principal"]
    nbb = m["bonus_balance"] + r["deduct_bonus"]
    nc = m["total_consumed"] - r["actual_price"]
    cur.execute("DELETE FROM consumption_records WHERE id=?", (rid,))
    cur.execute("UPDATE members SET balance=?,bonus_balance=?,total_consumed=?,updated_at=? WHERE id=?",
                (nb, nbb, nc, now, r["member_id"]))
    _insert_log(cur, operator, "撤销消费", "consume", rid,
                f"撤销消费 {r['service_name']} {r['actual_price']:.2f} 元，会员：{m['name']}")
    conn.commit()
    conn.close()
    return {"ok": True}

def get_recharge_records(mid=None, limit=50):
    conn = get_conn()
    if mid:
        rows = conn.execute(
            "SELECT r.*, m.name, m.phone FROM recharge_records r LEFT JOIN members m ON r.member_id=m.id WHERE r.member_id=? ORDER BY r.created_at DESC LIMIT ?",
            (mid, limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT r.*, m.name, m.phone FROM recharge_records r LEFT JOIN members m ON r.member_id=m.id ORDER BY r.created_at DESC LIMIT ?",
            (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_consumption_records(mid=None, limit=50):
    conn = get_conn()
    if mid:
        rows = conn.execute(
            "SELECT c.*, m.name, m.phone, b.name AS barber_name FROM consumption_records c LEFT JOIN members m ON c.member_id=m.id LEFT JOIN barbers b ON c.barber_id=b.id WHERE c.member_id=? ORDER BY c.created_at DESC LIMIT ?",
            (mid, limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT c.*, m.name, m.phone, b.name AS barber_name FROM consumption_records c LEFT JOIN members m ON c.member_id=m.id LEFT JOIN barbers b ON c.barber_id=b.id ORDER BY c.created_at DESC LIMIT ?",
            (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_packages(mid=None):
    conn = get_conn()
    if mid:
        rows = conn.execute(
            "SELECT p.*, m.name, m.phone FROM packages p LEFT JOIN members m ON p.member_id=m.id WHERE p.member_id=? ORDER BY p.start_date DESC",
            (mid,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT p.*, m.name, m.phone FROM packages p LEFT JOIN members m ON p.member_id=m.id ORDER BY p.start_date DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_package(mid, pname, price, count, valid_days=None, operator="system"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sd = datetime.now().strftime("%Y-%m-%d")
    ed = (datetime.now() + timedelta(days=valid_days)).strftime("%Y-%m-%d") if valid_days else None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO packages(member_id,package_name,package_price,service_count,remaining_count,valid_days,expire_date,status,start_date,end_date,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (mid, pname, price, count, count, valid_days, ed, "有效", sd, ed, now))
    pid = cur.lastrowid
    _insert_log(cur, operator, "添加套餐", "package", pid,
                f"为会员 {mid} 添加套餐：{pname} 次数{count}")
    conn.commit()
    conn.close()
    return True

def use_package(pid, operator="system"):
    conn = get_conn()
    cur = conn.cursor()
    p = cur.execute("SELECT * FROM packages WHERE id=?", (pid,)).fetchone()
    if not p or p["status"] != "有效":
        conn.close()
        return {"ok": False, "msg": "套餐无效"}
    nr = p["remaining_count"] - 1
    st = "已用完" if nr == 0 else "有效"
    cur.execute("UPDATE packages SET remaining_count=?,status=? WHERE id=?",
                (nr, st, pid))
    _insert_log(cur, operator, "使用套餐", "package", pid,
                f"套餐《{p['package_name']}》剩余 {nr} 次")
    conn.commit()
    conn.close()
    return {"ok": True, "remaining": nr}

def get_statistics():
    conn = get_conn()
    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")
    s = {}
    s["total_members"] = conn.execute("SELECT COUNT(*) c FROM members WHERE status='正常'").fetchone()["c"]
    s["today_revenue"] = conn.execute("SELECT COALESCE(SUM(actual_price),0) t FROM consumption_records WHERE DATE(created_at)=?", (today,)).fetchone()["t"]
    s["month_revenue"] = conn.execute("SELECT COALESCE(SUM(actual_price),0) t FROM consumption_records WHERE strftime('%Y-%m',created_at)=?", (month,)).fetchone()["t"]
    s["month_recharge"] = conn.execute("SELECT COALESCE(SUM(amount),0) t FROM recharge_records WHERE strftime('%Y-%m',created_at)=?", (month,)).fetchone()["t"]
    s["total_balance"] = conn.execute("SELECT COALESCE(SUM(balance+bonus_balance),0) t FROM members WHERE status='正常'").fetchone()["t"]
    s["month_new"] = conn.execute("SELECT COUNT(*) c FROM members WHERE strftime('%Y-%m',join_date)=?", (month,)).fetchone()["c"]
    conn.close()
    return s

def get_member_type_distribution():
    conn = get_conn()
    rows = conn.execute(
        "SELECT membership_type, COUNT(*) c, SUM(balance+bonus_balance) b, SUM(total_consumed) t FROM members WHERE status='正常' GROUP BY membership_type ORDER BY c DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_top_consumers(limit=5):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM members WHERE status='正常' ORDER BY total_consumed DESC LIMIT ?",
        (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

MEMBER_TYPES = ["普通会员", "金卡会员", "白金会员", "钻石会员"]

_DEFAULT_DISCOUNTS = {
    "普通会员": 1.0, "金卡会员": 0.90, "白金会员": 0.85, "钻石会员": 0.80
}
_DEFAULT_SHOP_NAME = "发型屋"
_DEFAULT_SERVICES = [
    {"name": "男士剪发", "price": 30}, {"name": "女士剪发", "price": 40},
    {"name": "染发", "price": 120}, {"name": "烫发", "price": 150},
    {"name": "理发+染发", "price": 130}, {"name": "理发+烫发", "price": 160},
    {"name": "洗剪吹", "price": 35}, {"name": "头部护理", "price": 50},
    {"name": "眉毛设计", "price": 60}, {"name": "儿童剪发", "price": 20},
    {"name": "老年剪发", "price": 15}, {"name": "其他", "price": 0},
]

_TYPE_DISCOUNT_DATA = dict(_DEFAULT_DISCOUNTS)
_SERVICE_LIST_DATA = list(_DEFAULT_SERVICES)
_SHOP_NAME_DATA = _DEFAULT_SHOP_NAME

def _load_config():
    global _TYPE_DISCOUNT_DATA, _SERVICE_LIST_DATA, _SHOP_NAME_DATA
    conn = get_conn()
    cursor = conn.cursor()
    discounts = dict(_DEFAULT_DISCOUNTS)
    rows = cursor.execute("SELECT key, value FROM config WHERE key LIKE 'discount_%'").fetchall()
    for row in rows:
        t, v = row["key"], float(row["value"])
        type_name = t[len("discount_"):]
        if type_name in discounts:
            discounts[type_name] = v
    _TYPE_DISCOUNT_DATA = discounts
    svc_rows = cursor.execute("SELECT value FROM config WHERE key='services'").fetchone()
    if svc_rows:
        try:
            services = json.loads(svc_rows["value"])
            if services and isinstance(services[0], str):
                services = [{"name": s, "price": 0} for s in services]
            if services:
                _SERVICE_LIST_DATA = services
            else:
                _SERVICE_LIST_DATA = list(_DEFAULT_SERVICES)
        except (json.JSONDecodeError, TypeError, IndexError):
            _SERVICE_LIST_DATA = list(_DEFAULT_SERVICES)
    else:
        _SERVICE_LIST_DATA = list(_DEFAULT_SERVICES)
    shop_rows = cursor.execute("SELECT value FROM config WHERE key='shop_name'").fetchone()
    _SHOP_NAME_DATA = shop_rows["value"] if shop_rows else _DEFAULT_SHOP_NAME
    conn.close()

def get_type_discounts():
    return dict(_TYPE_DISCOUNT_DATA)

def get_service_list():
    return list(_SERVICE_LIST_DATA)

def set_type_discounts(discounts: dict):
    conn = get_conn()
    cur = conn.cursor()
    for t, v in discounts.items():
        cur.execute("INSERT OR REPLACE INTO config(key, value) VALUES(?,?)",
                    ("discount_" + t, str(v)))
    conn.commit()
    conn.close()
    _load_config()

def set_service_list(services: list):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO config(key, value) VALUES(?,?)",
                 ("services", json.dumps(services, ensure_ascii=False)))
    conn.commit()
    conn.close()
    _load_config()

def get_shop_name():
    return _SHOP_NAME_DATA

def set_shop_name(name: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO config(key, value) VALUES(?,?)",
                 ("shop_name", name.strip()))
    conn.commit()
    conn.close()
    _load_config()

def _get_service_price(service_name):
    for s in get_service_list():
        if s.get("name") == service_name:
            return s.get("price", 0)
    return 0

def valid_phone(p): return bool(re.match(r"^1[3-9]\d{9}$", p))
def valid_idcard(p): return bool(re.match(r"^\d{17}[\dXx]$", p))

_LOGIN_USER = "admin"
_LOGIN_PASS = "123456"

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        username = session.get("username") if "session" in globals() else None
        if not username:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def check_login(username, password):
    op = get_operator_by_username(username)
    if not op:
        return False
    if op["status"] != "正常":
        return False
    return op["password"] == password
