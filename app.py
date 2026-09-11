
import os
import json
import shutil
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import models

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "hair-salon-secret-key-2024")

models.init_db()
models._load_config()

@app.before_request
def before_request():
    session.permanent = True

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if models.check_login(username, password):
            op = models.get_operator_by_username(username)
            session["username"] = username
            session["logged_in"] = True
            session["role"] = op["role"] if op else "operator"
            session["display_name"] = op.get("display_name") or username
            return redirect(url_for("index"))
        flash("用户名或密码错误", "error")
    return render_template("login.html", shop_name=models.get_shop_name())

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

def require_login(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            flash("仅管理员可执行该操作", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated

@app.route("/")
@require_login
def index():
    stats = models.get_statistics()
    dist = models.get_member_type_distribution()
    top = models.get_top_consumers(5)
    recent_recharge = models.get_recharge_records(limit=5)
    recent_consume = models.get_consumption_records(limit=5)
    return render_template("index.html",
                         shop_name=models.get_shop_name(),
                         stats=stats, dist=dist, top=top,
                         recent_recharge=recent_recharge,
                         recent_consume=recent_consume)

@app.route("/members")
@require_login
def members():
    keyword = request.args.get("keyword", "").strip()
    status_filter = request.args.get("status", "")
    if keyword:
        result = models.search_members(keyword)
    else:
        result = models.get_all_members()
    if status_filter:
        result = [m for m in result if m["status"] == status_filter]

    status_order = {"正常": 0, "挂失": 1, "注销": 2}
    result.sort(key=lambda m: (status_order.get(m["status"], 9), m["join_date"]))
    return render_template("members.html",
                         shop_name=models.get_shop_name(),
                         members=result, keyword=keyword, status_filter=status_filter)

@app.route("/members/add", methods=["POST"])
@require_login
def member_add():
    name = request.form["name"].strip()
    phone = request.form["phone"].strip()
    gender = request.form.get("gender", "男")
    id_card = request.form.get("id_card", "").strip()
    membership_type = request.form.get("membership_type", "普通会员")
    remark = request.form.get("remark", "").strip()
    operator = session.get("username", "system")

    if not name or not phone:
        flash("姓名和手机号不能为空", "error")
        return redirect(url_for("members"))
    if not models.valid_phone(phone):
        flash("手机号格式不正确", "error")
        return redirect(url_for("members"))

    existing = models.get_member_by_phone(phone)
    if existing and existing["id"] != int(request.form.get("edit_id", 0)):
        flash(f"该手机号已存在会员【{existing['name']}】", "error")
        return redirect(url_for("members"))

    edit_id = request.form.get("edit_id", "").strip()
    if edit_id:
        models.update_member(int(edit_id), name=name, phone=phone, gender=gender,
                             id_card=id_card, membership_type=membership_type, remark=remark)
        flash(f"会员【{name}】信息已更新", "success")
    else:
        models.add_member(name, phone, gender, id_card, membership_type, remark, operator)
        flash(f"会员【{name}】添加成功", "success")
    return redirect(url_for("members"))

@app.route("/members/<int:mid>/delete", methods=["POST"])
@require_login
def member_delete(mid):
    m = models.get_member(mid)
    if not m or m["status"] != "正常":
        flash("该会员状态异常，无法注销", "warning")
        return redirect(url_for("members"))
    refund = models.cancel_member(mid, session.get("username", "system"))
    flash(f"会员【{m['name']}】已注销，退还充值本金 {refund:.2f} 元", "success")
    return redirect(url_for("members"))

@app.route("/members/<int:mid>/status", methods=["POST"])
@require_login
def member_status(mid):
    new_status = request.form.get("status")
    models.update_member(mid, status=new_status)
    status_text = {"正常": "恢复为正常", "挂失": "标记为挂失", "注销": "已注销"}
    flash(f"会员状态已{status_text.get(new_status, new_status)}", "success")
    return redirect(url_for("members"))

@app.route("/recharge", methods=["GET", "POST"])
@require_login
def recharge():
    if request.method == "POST":
        mid = request.form.get("member_id")
        if not mid:
            flash("请先选择会员", "error")
            return redirect(url_for("recharge"))
        try:
            amount = float(request.form["amount"])
            if amount <= 0:
                raise ValueError
        except Exception:
            flash("请输入有效的充值金额", "error")
            return redirect(url_for("recharge"))
        payment = request.form.get("payment", "现金")
        remark = request.form.get("remark", "")
        try:
            bonus = float(request.form.get("bonus", "0") or 0)
            if bonus < 0:
                raise ValueError
        except Exception:
            bonus = 0
        result = models.member_recharge(int(mid), amount, payment,
                                        session.get("username", "system"), remark, bonus)
        if result["ok"]:
            msg = f"充值成功！新余额：{result['new_balance']:.2f} 元"
            if bonus > 0:
                msg += f"（含赠送 {bonus:.2f} 元）"
            flash(msg, "success")
        else:
            flash(result["msg"], "error")
        return redirect(url_for("recharge"))

    keyword = request.args.get("keyword", "").strip()
    members_list = []
    selected_member = None
    if keyword:
        results = models.search_members(keyword)
        members_list = results
        if len(results) == 1:
            selected_member = results[0]
    return render_template("recharge.html",
                         shop_name=models.get_shop_name(),
                         members=members_list,
                         selected=selected_member,
                         keyword=keyword,
                         discounts=models.get_type_discounts(),
                         services=models.get_service_list())

@app.route("/consume", methods=["GET", "POST"])
@require_login
def consume():
    if request.method == "POST":
        mid = request.form.get("member_id")
        if not mid:
            flash("请先选择会员", "error")
            return redirect(url_for("consume"))
        service = request.form["service"]
        try:
            price = float(request.form["price"])
            discount = float(request.form.get("discount", 1.0))
        except Exception:
            flash("请输入有效的价格", "error")
            return redirect(url_for("consume"))
        remark = request.form.get("remark", "")
        barber_id = request.form.get("barber_id", "").strip() or None
        if barber_id:
            try:
                barber_id = int(barber_id)
            except Exception:
                barber_id = None
        result = models.member_consume(int(mid), service, price, discount,
                                       session.get("username", "system"), remark, barber_id)
        if result["ok"]:
            flash(f"消费成功！剩余余额：{result['remaining']:.2f} 元", "success")
        else:
            flash(result["msg"], "error")
        return redirect(url_for("consume"))

    keyword = request.args.get("keyword", "").strip()
    mid_param = request.args.get("member_id", "").strip()
    members_list = []
    selected_member = None
    if mid_param:
        try:
            selected_member = models.get_member(int(mid_param))
        except Exception:
            pass
    if keyword:
        results = models.search_members(keyword)
        members_list = results
        if len(results) == 1:
            selected_member = results[0]
    return render_template("consume.html",
                         shop_name=models.get_shop_name(),
                         members=members_list,
                         selected=selected_member,
                         keyword=keyword,
                         discounts=models.get_type_discounts(),
                         services=models.get_service_list(),
                         barbers=models.get_all_barbers_for_select())

@app.route("/packages/<int:mid>", methods=["GET", "POST"])
@require_login
def package_manage(mid):
    m = models.get_member(mid)
    if not m:
        flash("会员不存在", "error")
        return redirect(url_for("members"))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            name = request.form["pkg_name"].strip()
            try:
                price = float(request.form["pkg_price"])
                count = int(request.form["pkg_count"])
                valid = int(request.form.get("pkg_valid", 0)) or None
            except Exception:
                flash("请填写完整有效的信息", "error")
            else:
                models.add_package(mid, name, price, count, valid,
                                   session.get("username", "system"))
                flash(f"套餐《{name}》添加成功", "success")
        elif action == "use":
            pkg_id = request.form.get("pkg_id")
            if pkg_id:
                result = models.use_package(int(pkg_id), session.get("username", "system"))
                if result["ok"]:
                    flash(f"使用成功，剩余 {result['remaining']} 次", "success")
                else:
                    flash(result["msg"], "error")
        return redirect(url_for("package_manage", mid=mid))

    pkgs = models.get_packages(mid)
    return render_template("packages.html",
                         shop_name=models.get_shop_name(),
                         member=m, packages=pkgs)

@app.route("/records")
@require_login
def records():
    mid = request.args.get("member_id", type=int)
    rec_type = request.args.get("type", "all")
    recharge_records = models.get_recharge_records(mid, limit=100) if mid or rec_type != "consume" else []
    consume_records = models.get_consumption_records(mid, limit=100) if mid or rec_type != "recharge" else []
    all_members = models.get_all_members()
    return render_template("records.html",
                         shop_name=models.get_shop_name(),
                         recharge_records=recharge_records,
                         consume_records=consume_records,
                         members=all_members,
                         selected_member_id=mid,
                         rec_type=rec_type)

@app.route("/records/recharge/<int:rid>/undo", methods=["POST"])
@require_login
def undo_recharge(rid):
    result = models.undo_recharge_record(rid, session.get("username", "system"))
    if result["ok"]:
        flash("充值记录已撤销，余额已扣回", "success")
    else:
        flash(result["msg"], "error")
    return redirect(url_for("records", member_id=request.form.get("member_id", type=int) or None,
                            type=request.form.get("rec_type", "all") or "all"))

@app.route("/records/consume/<int:rid>/undo", methods=["POST"])
@require_login
def undo_consume(rid):
    result = models.undo_consume_record(rid, session.get("username", "system"))
    if result["ok"]:
        flash("消费记录已撤销，金额已退回", "success")
    else:
        flash(result["msg"], "error")
    return redirect(url_for("records", member_id=request.form.get("member_id", type=int) or None,
                            type=request.form.get("rec_type", "all") or "all"))

@app.route("/logs")
@require_login
def logs():
    rows = models.get_conn().execute(
        "SELECT * FROM operation_logs ORDER BY created_at DESC LIMIT 200").fetchall()
    models.get_conn().close()
    return render_template("logs.html",
                         shop_name=models.get_shop_name(),
                         log_rows=[dict(r) for r in rows])

@app.route("/settings", methods=["GET", "POST"])
@require_login
def settings():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "shop_name":
            name = request.form.get("shop_name", "").strip()
            if name:
                models.set_shop_name(name)
                flash("店铺名称已更新", "success")
        elif action == "discounts":
            discounts = {}
            for t in models.MEMBER_TYPES:
                try:
                    v = float(request.form.get(f"discount_{t}", 1.0))
                    if not (0 < v <= 1):
                        raise ValueError
                    discounts[t] = v
                except Exception:
                    flash(f"{t}折扣必须在 0~1 之间", "error")
                    return redirect(url_for("settings"))
            models.set_type_discounts(discounts)
            flash("折扣设置已保存", "success")
        elif action == "services":
            services = []
            names = request.form.getlist("svc_name[]")
            prices = request.form.getlist("svc_price[]")
            for n, p in zip(names, prices):
                if n.strip():
                    try:
                        price = float(p) if p else 0
                    except Exception:
                        price = 0
                    services.append({"name": n.strip(), "price": price})
            if not services:
                flash("服务列表不能为空", "error")
            else:
                models.set_service_list(services)
                flash("服务列表已保存", "success")
        return redirect(url_for("settings"))

    return render_template("settings.html",
                         shop_name=models.get_shop_name(),
                         discounts=models.get_type_discounts(),
                         services=models.get_service_list(),
                         member_types=models.MEMBER_TYPES)

@app.route("/operators", methods=["GET", "POST"])
@require_admin
def operators():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        display_name = request.form.get("display_name", "").strip()
        role = request.form.get("role", "operator")
        if not username or not password:
            flash("用户名和密码不能为空", "error")
        elif models.get_operator_by_username(username):
            flash(f"操作员【{username}】已存在", "error")
        else:
            models.add_operator(username, password, display_name, role,
                                session.get("username", "system"))
            flash(f"操作员【{username}】添加成功", "success")
        return redirect(url_for("operators"))
    return render_template("operators.html",
                         shop_name=models.get_shop_name(),
                         operators=models.get_all_operators())

@app.route("/operators/<int:opid>/update", methods=["POST"])
@require_admin
def operator_update(opid):
    display_name = request.form.get("display_name", "").strip()
    role = request.form.get("role", "operator")
    status = request.form.get("status", "正常")
    models.update_operator(opid, display_name=display_name, role=role, status=status)
    flash("操作员信息已更新", "success")
    return redirect(url_for("operators"))

@app.route("/operators/<int:opid>/reset_password", methods=["POST"])
@require_admin
def operator_reset_password(opid):
    new_pwd = request.form.get("new_password", "").strip()
    if not new_pwd:
        flash("新密码不能为空", "error")
    else:
        models.update_operator(opid, password=new_pwd)
        flash("密码已重置", "success")
    return redirect(url_for("operators"))

@app.route("/operators/<int:opid>/delete", methods=["POST"])
@require_admin
def operator_delete(opid):
    ok = models.delete_operator(opid, session.get("username", "system"))
    flash("操作员已删除" if ok else "无法删除（admin 账号不允许删除）", "success" if ok else "error")
    return redirect(url_for("operators"))

@app.route("/change_password", methods=["GET", "POST"])
@require_login
def change_password():
    if request.method == "POST":
        old_pwd = request.form.get("old_password", "")
        new_pwd = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not new_pwd:
            flash("新密码不能为空", "error")
        elif new_pwd != confirm:
            flash("两次输入的新密码不一致", "error")
        else:
            result = models.change_password(session.get("username"), old_pwd, new_pwd)
            if result["ok"]:
                flash("密码修改成功", "success")
            else:
                flash(result["msg"], "error")
        return redirect(url_for("change_password"))
    return render_template("change_password.html", shop_name=models.get_shop_name())

@app.route("/barbers", methods=["GET", "POST"])
@require_login
def barbers():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            name = request.form.get("name", "").strip()
            phone = request.form.get("phone", "").strip()
            position = request.form.get("position", "理发师").strip()
            if not name:
                flash("理发师姓名不能为空", "error")
            else:
                models.add_barber(name, phone, position, session.get("username", "system"))
                flash(f"理发师【{name}】添加成功", "success")
        elif action == "update":
            bid = int(request.form.get("barber_id", 0))
            name = request.form.get("name", "").strip()
            phone = request.form.get("phone", "").strip()
            position = request.form.get("position", "理发师").strip()
            status = request.form.get("status", "正常")
            if bid and name:
                models.update_barber(bid, name=name, phone=phone, position=position, status=status)
                flash("理发师信息已更新", "success")
        elif action == "delete":
            bid = int(request.form.get("barber_id", 0))
            if bid:
                models.delete_barber(bid, session.get("username", "system"))
                flash("理发师已删除", "success")
        return redirect(url_for("barbers"))
    return render_template("barbers.html",
                         shop_name=models.get_shop_name(),
                         barbers=models.get_all_barbers())

@app.route("/cash_sheets", methods=["GET", "POST"])
@require_login
def cash_sheets():
    is_admin = session.get("role") == "admin"
    today = datetime.now().strftime("%Y-%m-%d")

    if request.method == "POST":
        operator = request.form.get("operator", "").strip()
        date = request.form.get("date", "").strip() or today
        remark = request.form.get("remark", "").strip()
        if not is_admin:
            operator = session.get("username")
        if not operator or not models.get_operator_by_username(operator):
            flash("请选择有效的充值操作员", "error")
            return redirect(url_for("cash_sheets"))
        if models.get_cash_sheet_exists(operator, date):
            flash(f"操作员【{operator}】{date} 已交款，请勿重复交款", "error")
            return redirect(url_for("cash_sheets", operator=operator, date=date))
        summary = models.get_recharge_summary(operator, date)
        if summary["cnt"] == 0:
            flash(f"操作员【{operator}】{date} 无充值记录", "error")
            return redirect(url_for("cash_sheets", operator=operator, date=date))
        models.add_cash_sheet(operator, date, summary["cash"], summary["wechat"],
                              summary["alipay"], summary["card"], summary["cnt"],
                              remark, session.get("username", "system"))
        flash(f"交款成功！{operator} {date} 共 {summary['cnt']} 笔，合计 {summary['amount']:.2f} 元", "success")
        return redirect(url_for("cash_sheets", operator=operator, date=date))

    preview = None
    preview_operator = None
    preview_date = None
    already_paid = False
    operator = request.args.get("operator", "").strip()
    if not is_admin:
        operator = session.get("username")
    date = request.args.get("date", "").strip() or today
    if operator and models.get_operator_by_username(operator):
        preview = models.get_recharge_summary(operator, date)
        already_paid = models.get_cash_sheet_exists(operator, date)
        preview_operator = operator
        preview_date = date

    rows = models.get_cash_sheets(operator=None if is_admin else session.get("username"), date=request.args.get("f_date", "").strip() or None)
    total = sum(r["amount"] for r in rows)
    return render_template("cash_sheets.html",
                         shop_name=models.get_shop_name(),
                         sheets=rows, total=total,
                         is_admin=is_admin,
                         operators=models.get_all_operators(),
                         preview=preview, preview_operator=preview_operator,
                         preview_date=preview_date, already_paid=already_paid,
                         selected_operator=operator, selected_date=date,
                         f_date=request.args.get("f_date", "").strip() or None)

@app.route("/cash_sheets/<int:sid>/delete", methods=["POST"])
@require_login
def cash_sheet_delete(sid):
    username = session.get("username", "system")
    if session.get("role") != "admin":
        sheet = models.get_cash_sheet(sid)
        if not sheet:
            flash("交款单不存在", "error")
        elif sheet["submitted_by"] != username:
            flash("只能撤销自己提交的交款单", "error")
        else:
            result = models.delete_cash_sheet(sid, username)
            flash("交款单已撤销" if result["ok"] else result["msg"], "success" if result["ok"] else "error")
        return redirect(url_for("cash_sheets"))
    result = models.delete_cash_sheet(sid, username)
    flash("交款单已撤销" if result["ok"] else result["msg"], "success" if result["ok"] else "error")
    return redirect(url_for("cash_sheets"))

@app.route("/performance")
@require_login
def performance():
    today = datetime.now().strftime("%Y-%m-%d")
    month_start = datetime.now().strftime("%Y-%m-01")
    start_date = request.args.get("start_date", month_start).strip()
    end_date = request.args.get("end_date", today).strip()
    barber_id = request.args.get("barber_id", "").strip()
    if barber_id:
        try:
            barber_id = int(barber_id)
        except Exception:
            barber_id = None
    else:
        barber_id = None
    rows = models.get_performance_report(start_date, end_date, barber_id)
    totals = {
        "cnt": sum(r["cnt"] for r in rows),
        "total_price": sum(r["total_price"] for r in rows),
        "total_actual": sum(r["total_actual"] for r in rows),
    }
    return render_template("performance.html",
                         shop_name=models.get_shop_name(),
                         report=rows, totals=totals,
                         start_date=start_date, end_date=end_date,
                         barber_id=barber_id,
                         barbers=models.get_all_barbers_for_select())

@app.route("/backup")
@require_login
def backup():
    backup_dir = os.path.join(os.path.dirname(models.DB_PATH), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(models.DB_PATH, os.path.join(backup_dir, name))
    flash(f"数据备份完成！文件：{name}", "success")
    return redirect(url_for("index"))

@app.route("/api/members/search")
@require_login
def api_search_members():
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return jsonify([])
    results = models.search_members(keyword)
    return jsonify(results)

@app.route("/api/member/<int:mid>")
@require_login
def api_get_member(mid):
    m = models.get_member(mid)
    if m:
        m["balance"] = float(m["balance"])
        m["bonus_balance"] = float(m["bonus_balance"])
        m["total_consumed"] = float(m["total_consumed"])
        m["total_recharge"] = float(m["total_recharge"])
    return jsonify(m or {})

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print(f"[OK] {models.get_shop_name()}会员管理系统启动成功")
    print("[INFO] 启动地址: http://127.0.0.1:5000")
    print("[INFO] 默认账号: admin / 123456")
    app.run(host="0.0.0.0", port=5000, debug=True)
