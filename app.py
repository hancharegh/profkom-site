import os
import csv
from io import StringIO, BytesIO
import pandas as pd
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    flash,
    send_file,
    jsonify
)
import random
import psycopg2
from psycopg2.extras import RealDictCursor

from functools import wraps
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from openpyxl import Workbook
from datetime import datetime


# ======================================================
# FLASK
# ======================================================

app = Flask(__name__)
app.secret_key = "secret123"


# ======================================================
# DATABASE
# ======================================================

DATABASE_URL = os.getenv("DATABASE_URL")


def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        cursor_factory=RealDictCursor
    )


# ======================================================
# ЛИМИТЫ
# ======================================================

LIMITS = {
    "prints":      30,
    "copies":      30,
    "notebooks":   1,
    "rulers":      1,
    "correctors":  1,
    "pencils":     1,
    "erasers":     1,
    "millimeters": 50
}

FIELD_MAP = {
    "Печать":          "print_count",
    "Копии":           "copy_count",
    "Тетради":         "notebook_count",
    "Линейки":         "ruler_count",
    "Корректоры":      "corrector_count",
    "Карандаши":       "pencil_count",
    "Ластики/Точилки": "eraser_sharpener_count",
    "Миллиметровки":   "millimeter_count",
}

ALLOWED_FIELDS = set(FIELD_MAP.values())


# ======================================================
# ДЕКОРАТОРЫ
# ======================================================

def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect("/")
        return func(*args, **kwargs)
    return wrapper


def role_required(role):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                return redirect("/")
            if session.get("role") != role:
                return redirect("/")
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ======================================================
# INIT DB
# ======================================================

def init_db():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id SERIAL PRIMARY KEY,
        barcode TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS entries (
        id SERIAL PRIMARY KEY,
        student_barcode TEXT,
        student_name TEXT,
        secretary TEXT,
        action_text TEXT,
        print_count             INTEGER DEFAULT 0,
        copy_count              INTEGER DEFAULT 0,
        notebook_count          INTEGER DEFAULT 0,
        ruler_count             INTEGER DEFAULT 0,
        corrector_count         INTEGER DEFAULT 0,
        pencil_count            INTEGER DEFAULT 0,
        eraser_sharpener_count  INTEGER DEFAULT 0,
        millimeter_count        INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS schedule (
        id SERIAL PRIMARY KEY,
        day_name TEXT UNIQUE NOT NULL,
        secretary_name TEXT
    )
    """)

    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"]
    for day in days:
        cur.execute("SELECT * FROM schedule WHERE day_name=%s", (day,))
        if not cur.fetchone():
            cur.execute("INSERT INTO schedule (day_name, secretary_name) VALUES (%s, %s)", (day, ""))

    cur.execute("SELECT * FROM users WHERE role='chairman'")
    if not cur.fetchone():
        cur.execute("""
        INSERT INTO users (name, password, role)
        VALUES (%s, %s, %s)
        ON CONFLICT (name) DO NOTHING
        """, ("Курмаева Юлия Игоревна", generate_password_hash("1234"), "chairman"))

    conn.commit()
    cur.close()
    conn.close()


# ======================================================
# LOGIN
# ======================================================

@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        name = request.form["name"]

        if name.lower() in ["тигр", "tiger"]:
            flash("🐯 доступ только для тигров и тигриц")
            return render_template("login.html")

        password = request.form["password"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE name = %s", (name,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if not user:
            flash("Пользователь не найден")
            return render_template("login.html")

        try:
            password_ok = check_password_hash(user["password"], password)
        except Exception:
            flash("Ошибка пароля")
            return render_template("login.html")

        if password_ok:
            session["user"] = user["name"]
            session["role"] = user["role"]
            if user["role"] == "chairman":
                return redirect("/chairman")
            return redirect("/dashboard")

        flash("Неверный пароль")

    return render_template("login.html")


# ======================================================
# LOGOUT
# ======================================================

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ======================================================
# DASHBOARD (GET only — начальная загрузка)
# ======================================================

@app.route("/dashboard")
@login_required
@role_required("secretary")
def dashboard():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM entries ORDER BY created_at DESC LIMIT 20")
    entries = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("dashboard.html", entries=entries)


# ======================================================
# ISSUE — AJAX выдача продукции
# Возвращает JSON: { ok, message, achievement, limits, entry }
# ======================================================

@app.route("/issue", methods=["POST"])
@login_required
@role_required("secretary")
def issue():

    data    = request.get_json()
    barcode = (data.get("barcode") or "").strip()

    if barcode == "000000":
        return jsonify(ok=False, error="🐯 Верховный тигр вошёл в систему")

    if not barcode:
        return jsonify(ok=False, error="Введите barcode")

    print_count            = int(data.get("print_count") or 0)
    copy_count             = int(data.get("copy_count") or 0)
    notebook_count         = int(data.get("notebook_count") or 0)
    ruler_count            = int(data.get("ruler_count") or 0)
    corrector_count        = int(data.get("corrector_count") or 0)
    pencil_count           = int(data.get("pencil_count") or 0)
    eraser_sharpener_count = int(data.get("eraser_sharpener_count") or 0)
    millimeter_count       = int(data.get("millimeter_count") or 0)

    conn = get_db()
    cur  = conn.cursor()

    cur.execute("SELECT * FROM students WHERE barcode = %s", (barcode,))
    student = cur.fetchone()

    if not student:
        cur.close()
        conn.close()
        return jsonify(ok=False, error="Студент не найден")

    current_month = datetime.now().month
    current_year  = datetime.now().year

    if student.get("limit_month") != current_month or student.get("limit_year") != current_year:
        cur.execute("""
            UPDATE students SET
                print_count=0, copy_count=0, notebook_count=0,
                ruler_count=0, corrector_count=0, pencil_count=0,
                eraser_sharpener_count=0, millimeter_count=0,
                limit_month=%s, limit_year=%s
            WHERE barcode=%s
        """, (current_month, current_year, barcode))
        conn.commit()
        for f in ["print_count","copy_count","notebook_count","ruler_count",
                  "corrector_count","pencil_count","eraser_sharpener_count","millimeter_count"]:
            student[f] = 0

    used = {
        "prints":      student.get("print_count", 0),
        "copies":      student.get("copy_count", 0),
        "notebooks":   student.get("notebook_count", 0),
        "rulers":      student.get("ruler_count", 0),
        "correctors":  student.get("corrector_count", 0),
        "pencils":     student.get("pencil_count", 0),
        "erasers":     student.get("eraser_sharpener_count", 0),
        "millimeters": student.get("millimeter_count", 0),
    }

    checks = [
        (used["prints"]      + print_count            > LIMITS["prints"],      "Превышен лимит печати"),
        (used["copies"]      + copy_count             > LIMITS["copies"],      "Превышен лимит копий"),
        (used["notebooks"]   + notebook_count         > LIMITS["notebooks"],   "Тетрадь уже выдавалась"),
        (used["rulers"]      + ruler_count            > LIMITS["rulers"],      "Линейка уже выдавалась"),
        (used["correctors"]  + corrector_count        > LIMITS["correctors"],  "Корректор уже выдавался"),
        (used["pencils"]     + pencil_count           > LIMITS["pencils"],     "Карандаш уже выдавался"),
        (used["erasers"]     + eraser_sharpener_count > LIMITS["erasers"],     "Ластик/точилка уже выдавались"),
        (used["millimeters"] + millimeter_count       > LIMITS["millimeters"], "Превышен лимит миллиметровок"),
    ]

    for exceeded, msg in checks:
        if exceeded:
            cur.close()
            conn.close()
            return jsonify(ok=False, error=msg)

    cur.execute("""
        UPDATE students SET
            print_count             = print_count + %s,
            copy_count              = copy_count + %s,
            notebook_count          = notebook_count + %s,
            ruler_count             = ruler_count + %s,
            corrector_count         = corrector_count + %s,
            pencil_count            = pencil_count + %s,
            eraser_sharpener_count  = eraser_sharpener_count + %s,
            millimeter_count        = millimeter_count + %s
        WHERE barcode = %s
    """, (print_count, copy_count, notebook_count, ruler_count,
          corrector_count, pencil_count, eraser_sharpener_count,
          millimeter_count, barcode))

    actions = []
    if print_count            > 0: actions.append(f"Печать: {print_count}")
    if copy_count             > 0: actions.append(f"Копии: {copy_count}")
    if notebook_count         > 0: actions.append(f"Тетради: {notebook_count}")
    if ruler_count            > 0: actions.append(f"Линейки: {ruler_count}")
    if corrector_count        > 0: actions.append(f"Корректоры: {corrector_count}")
    if pencil_count           > 0: actions.append(f"Карандаши: {pencil_count}")
    if eraser_sharpener_count > 0: actions.append(f"Ластики/Точилки: {eraser_sharpener_count}")
    if millimeter_count       > 0: actions.append(f"Миллиметровки: {millimeter_count}")

    action_text = ", ".join(actions)

    cur.execute("""
        INSERT INTO entries (
            student_barcode, student_name, secretary, action_text,
            print_count, copy_count, notebook_count, ruler_count,
            corrector_count, pencil_count, eraser_sharpener_count, millimeter_count
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id, created_at
    """, (
        barcode,
        student.get("full_name") or "Неизвестно",
        session.get("user") or "Секретарь",
        action_text,
        print_count, copy_count, notebook_count, ruler_count,
        corrector_count, pencil_count, eraser_sharpener_count, millimeter_count
    ))

    new_entry = cur.fetchone()
    conn.commit()

    cur.execute("SELECT COUNT(*) as total FROM entries WHERE secretary = %s", (session["user"],))
    total_actions = cur.fetchone()["total"]

    achievement = None
    if   total_actions == 100:  achievement = "🏆 Достижение: 100 выдач"
    elif total_actions == 500:  achievement = "🐯 Легенда профкома"
    elif total_actions == 1000: achievement = "👑 Верховный тигр"

    cur.close()
    conn.close()

    fun_messages = [
        "🐯 Тигр успешно накормлен",
        "📚 Бумажная промышленность процветает",
        "⚡ Профком доволен вами",
        "🖨️ Печать пошла в бой",
        "🏆 +100 к уважению секретаря"
    ]

    message = random.choice(fun_messages) if random.randint(1, 10) == 1 else "Выдача успешно сохранена"

    limits = {
        "prints":      max(LIMITS["prints"]      - (used["prints"]      + print_count), 0),
        "copies":      max(LIMITS["copies"]      - (used["copies"]      + copy_count), 0),
        "notebooks":   max(LIMITS["notebooks"]   - (used["notebooks"]   + notebook_count), 0),
        "rulers":      max(LIMITS["rulers"]      - (used["rulers"]      + ruler_count), 0),
        "correctors":  max(LIMITS["correctors"]  - (used["correctors"]  + corrector_count), 0),
        "pencils":     max(LIMITS["pencils"]     - (used["pencils"]     + pencil_count), 0),
        "erasers":     max(LIMITS["erasers"]     - (used["erasers"]     + eraser_sharpener_count), 0),
        "millimeters": max(LIMITS["millimeters"] - (used["millimeters"] + millimeter_count), 0),
    }

    return jsonify(
        ok=True,
        message=message,
        achievement=achievement,
        limits=limits,
        entry={
            "id":              new_entry["id"],
            "student_name":    student.get("full_name"),
            "student_barcode": barcode,
            "secretary":       session.get("user"),
            "action_text":     action_text,
            "created_at":      str(new_entry["created_at"]),
        }
    )


# ======================================================
# UNDO — AJAX
# ======================================================

@app.route("/undo/<int:entry_id>", methods=["POST"])
@login_required
@role_required("secretary")
def undo(entry_id):

    conn = get_db()
    cur  = conn.cursor()

    cur.execute("SELECT * FROM entries WHERE id = %s", (entry_id,))
    entry = cur.fetchone()

    if not entry:
        cur.close()
        conn.close()
        return jsonify(ok=False, error="Запись не найдена")

    for label, field_name in FIELD_MAP.items():
        if field_name not in ALLOWED_FIELDS:
            continue
        amount = entry.get(field_name, 0) or 0
        if amount <= 0:
            continue
        cur.execute(f"""
            UPDATE students
            SET {field_name} = GREATEST({field_name} - %s, 0)
            WHERE barcode = %s
        """, (amount, entry["student_barcode"]))

    cur.execute("DELETE FROM entries WHERE id = %s", (entry_id,))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify(ok=True)


# ======================================================
# CHAIRMAN
# ======================================================

@app.route("/chairman")
@role_required("chairman")
def chairman():

    conn = get_db()
    cur  = conn.cursor()

    cur.execute("SELECT * FROM users WHERE role='secretary' ORDER BY name")
    secretaries = cur.fetchall()

    cur.execute("SELECT COUNT(*) as count FROM students")
    students_count = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) as count FROM entries")
    entries_count = cur.fetchone()["count"]

    cur.execute("SELECT * FROM entries ORDER BY created_at DESC LIMIT 50")
    entries = cur.fetchall()

    cur.execute("SELECT * FROM students ORDER BY full_name")
    students = cur.fetchall()

    cur.execute("SELECT * FROM schedule")
    schedule_rows = cur.fetchall()

    schedule = {"Понедельник":"","Вторник":"","Среда":"","Четверг":"","Пятница":""}
    for row in schedule_rows:
        schedule[row["day_name"]] = row["secretary_name"]

    cur.close()
    conn.close()

    return render_template(
        "chairman.html",
        secretaries=secretaries,
        students=students,
        students_count=students_count,
        entries_count=entries_count,
        entries=entries,
        schedule=schedule
    )


# ======================================================
# ADD SECRETARY
# ======================================================

@app.route("/add_secretary", methods=["POST"])
@role_required("chairman")
def add_secretary():

    name     = request.form["name"]
    password = request.form["password"]

    conn = get_db()
    cur  = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO users (name, password, role) VALUES (%s, %s, %s) RETURNING id",
            (name, generate_password_hash(password), "secretary")
        )
        new_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        conn.close()
        return jsonify(ok=True, id=new_id, name=name)
    except Exception as e:
        cur.close()
        conn.close()
        return jsonify(ok=False, error=str(e))


# ======================================================
# DELETE SECRETARY — AJAX
# ======================================================

@app.route("/delete_secretary/<int:user_id>", methods=["POST"])
@role_required("chairman")
def delete_secretary(user_id):

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=%s AND role='secretary'", (user_id,))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify(ok=True)


# ======================================================
# CHANGE SECRETARY PASSWORD — AJAX
# ======================================================

@app.route("/change_secretary_password/<int:user_id>", methods=["POST"])
@role_required("chairman")
def change_secretary_password(user_id):

    data     = request.get_json()
    password = (data or {}).get("password", "")

    if not password:
        return jsonify(ok=False, error="Пароль не может быть пустым")

    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE users SET password=%s WHERE id=%s AND role='secretary'",
        (generate_password_hash(password), user_id)
    )
    conn.commit()
    cur.close()
    conn.close()

    return jsonify(ok=True)


# ======================================================
# CHANGE PASSWORD (председатель)
# ======================================================

@app.route("/change_password", methods=["POST"])
@role_required("chairman")
def change_password():

    new_password = request.form["new_password"]

    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE users SET password=%s WHERE name=%s",
        (generate_password_hash(new_password), session["user"])
    )
    conn.commit()
    cur.close()
    conn.close()

    flash("Пароль изменён")
    return redirect("/chairman")


# ======================================================
# SAVE SCHEDULE
# ======================================================

@app.route("/save_schedule", methods=["POST"])
@role_required("chairman")
def save_schedule():

    conn = get_db()
    cur  = conn.cursor()

    for day in ["Понедельник","Вторник","Среда","Четверг","Пятница"]:
        cur.execute("UPDATE schedule SET secretary_name=%s WHERE day_name=%s",
                    (request.form.get(day), day))

    conn.commit()
    cur.close()
    conn.close()

    flash("Расписание сохранено")
    return redirect("/chairman")


# ======================================================
# EXPORT EXCEL
# ======================================================

@app.route("/export_excel")
@role_required("chairman")
def export_excel():

    date_from = request.args.get("date_from")
    date_to   = request.args.get("date_to")
    secretary = request.args.get("secretary")

    conn = get_db()
    cur  = conn.cursor()

    query  = "SELECT student_name, secretary, print_count, copy_count, notebook_count, ruler_count, corrector_count, pencil_count, eraser_sharpener_count, millimeter_count, created_at FROM entries WHERE 1=1"
    params = []

    if date_from: query += " AND DATE(created_at) >= %s"; params.append(date_from)
    if date_to:   query += " AND DATE(created_at) <= %s"; params.append(date_to)
    if secretary: query += " AND secretary = %s";          params.append(secretary)

    query += " ORDER BY created_at DESC"

    cur.execute(query, tuple(params))
    entries = cur.fetchall()
    cur.close()
    conn.close()

    data = [{
        "Студент": r["student_name"], "Секретарь": r["secretary"],
        "Печать": r["print_count"], "Копии": r["copy_count"],
        "Тетради": r["notebook_count"], "Линейки": r["ruler_count"],
        "Корректоры": r["corrector_count"], "Карандаши": r["pencil_count"],
        "Ластики/Точилки": r["eraser_sharpener_count"],
        "Миллиметровки": r["millimeter_count"], "Дата": str(r["created_at"])
    } for r in entries]

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(data).to_excel(writer, index=False, sheet_name="Отчет")
    output.seek(0)

    return send_file(output, as_attachment=True, download_name="report.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ======================================================
# UPLOAD STUDENTS
# ======================================================

@app.route("/upload_students", methods=["POST"])
@role_required("chairman")
def upload_students():

    file = request.files.get("file")
    if not file:
        flash("Файл не выбран")
        return redirect("/chairman")

    conn  = get_db()
    cur   = conn.cursor()
    added = 0

    for line in file.read().decode("utf-8").splitlines():
        parts = line.split(";")
        if len(parts) != 2:
            continue
        barcode, full_name = parts[0].strip(), parts[1].strip()
        cur.execute("SELECT * FROM students WHERE barcode=%s", (barcode,))
        if cur.fetchone():
            continue
        cur.execute("INSERT INTO students (barcode, full_name) VALUES (%s, %s)", (barcode, full_name))
        added += 1

    conn.commit()
    cur.close()
    conn.close()

    flash(f"Добавлено студентов: {added}")
    return redirect("/chairman")


# ======================================================
# ADD STUDENT — AJAX
# ======================================================

@app.route("/add_student", methods=["POST"])
@login_required
@role_required("chairman")
def add_student():

    data      = request.get_json()
    barcode   = (data.get("student_id") or "").strip()
    full_name = (data.get("name") or "").strip()

    if not barcode or not full_name:
        return jsonify(ok=False, error="Заполните все поля")

    conn = get_db()
    cur  = conn.cursor()

    try:
        cur.execute("INSERT INTO students (barcode, full_name) VALUES (%s, %s)", (barcode, full_name))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify(ok=True, barcode=barcode, full_name=full_name)
    except Exception as e:
        cur.close()
        conn.close()
        return jsonify(ok=False, error=str(e))


# ======================================================
# DELETE STUDENT — AJAX
# ======================================================

@app.route("/delete_student/<barcode>", methods=["POST"])
@login_required
@role_required("chairman")
def delete_student(barcode):

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM students WHERE barcode = %s", (barcode,))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify(ok=True)


# ======================================================
# SEARCH STUDENTS
# ======================================================

@app.route("/search_students")
@login_required
def search_students():

    query = request.args.get("q", "")
    conn  = get_db()
    cur   = conn.cursor()

    cur.execute("""
        SELECT barcode, full_name FROM students
        WHERE LOWER(full_name) LIKE LOWER(%s) LIMIT 10
    """, (f"%{query}%",))

    students = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify(students)


# ======================================================
# STUDENT LIMITS API
# ======================================================

@app.route("/student_limits/<barcode>")
@login_required
@role_required("secretary")
def student_limits_api(barcode):

    conn = get_db()
    cur  = conn.cursor()

    cur.execute("""
        SELECT
            COALESCE(SUM(print_count),0)            as prints,
            COALESCE(SUM(copy_count),0)             as copies,
            COALESCE(SUM(notebook_count),0)         as notebooks,
            COALESCE(SUM(ruler_count),0)            as rulers,
            COALESCE(SUM(corrector_count),0)        as correctors,
            COALESCE(SUM(pencil_count),0)           as pencils,
            COALESCE(SUM(eraser_sharpener_count),0) as erasers,
            COALESCE(SUM(millimeter_count),0)       as millimeters
        FROM entries
        WHERE student_barcode = %s
        AND DATE_TRUNC('month', created_at) = DATE_TRUNC('month', CURRENT_DATE)
    """, (barcode,))

    used   = cur.fetchone()
    result = {k: max(LIMITS[k] - used[k], 0) for k in LIMITS}

    cur.close()
    conn.close()

    return jsonify(result)


# ======================================================
# PING
# ======================================================

@app.route("/ping")
def ping():
    return "ok"


# ======================================================
# START
# ======================================================

init_db()

if __name__ == "__main__":
    app.run(debug=True)
