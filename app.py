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
# Убрана дублирующая get_connection() — используем одну get_db()
# ======================================================

DATABASE_URL = os.getenv("DATABASE_URL")


def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        cursor_factory=RealDictCursor
    )


# ======================================================
# ЛИМИТЫ — единая константа, больше не дублируется
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

# Карта меток action_text → поле в таблице students/entries
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

# Whitelist полей для защиты от SQL-инъекции в undo
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

    # Добавлены отдельные числовые колонки для корректной работы undo
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

        cur.execute(
            "SELECT * FROM schedule WHERE day_name=%s",
            (day,)
        )

        if not cur.fetchone():

            cur.execute("""
            INSERT INTO schedule (day_name, secretary_name)
            VALUES (%s, %s)
            """, (day, ""))

    cur.execute("SELECT * FROM users WHERE role='chairman'")

    if not cur.fetchone():

        cur.execute("""
        INSERT INTO users (name, password, role)
        VALUES (%s, %s, %s)
        ON CONFLICT (name) DO NOTHING
        """, (
            "Курмаева Юлия Игоревна",
            generate_password_hash("1234"),
            "chairman"
        ))

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
# DASHBOARD
# ======================================================

@app.route("/dashboard", methods=["GET", "POST"])
@login_required
@role_required("secretary")
def dashboard():

    conn = get_db()
    cur = conn.cursor()

    error          = None
    message        = None
    achievement    = None
    student_limits = None

    if request.method == "POST":

        barcode = request.form.get("barcode", "").strip()

        if barcode == "000000":

            error = "🐯 Верховный тигр вошёл в систему"

            cur.execute("""
                SELECT * FROM entries
                ORDER BY created_at DESC LIMIT 20
            """)
            entries = cur.fetchall()
            cur.close()
            conn.close()

            return render_template(
                "dashboard.html",
                entries=entries,
                error=error,
                message=None,
                achievement=None,
                student_limits=None
            )

        if not barcode:

            error = "Введите barcode"

        else:

            print_count            = int(request.form.get("print_count", 0) or 0)
            copy_count             = int(request.form.get("copy_count", 0) or 0)
            notebook_count         = int(request.form.get("notebook_count", 0) or 0)
            ruler_count            = int(request.form.get("ruler_count", 0) or 0)
            corrector_count        = int(request.form.get("corrector_count", 0) or 0)
            pencil_count           = int(request.form.get("pencil_count", 0) or 0)
            eraser_sharpener_count = int(request.form.get("eraser_sharpener_count", 0) or 0)
            millimeter_count       = int(request.form.get("millimeter_count", 0) or 0)

            cur.execute("SELECT * FROM students WHERE barcode = %s", (barcode,))
            student = cur.fetchone()

            if not student:

                error = "Студент не найден"

            else:

                current_month = datetime.now().month
                current_year  = datetime.now().year

                last_month = student.get("limit_month")
                last_year  = student.get("limit_year")

                if last_month != current_month or last_year != current_year:

                    cur.execute("""
                        UPDATE students
                        SET
                            print_count             = 0,
                            copy_count              = 0,
                            notebook_count          = 0,
                            ruler_count             = 0,
                            corrector_count         = 0,
                            pencil_count            = 0,
                            eraser_sharpener_count  = 0,
                            millimeter_count        = 0,
                            limit_month             = %s,
                            limit_year              = %s
                        WHERE barcode = %s
                    """, (current_month, current_year, barcode))

                    conn.commit()

                    student["print_count"]            = 0
                    student["copy_count"]             = 0
                    student["notebook_count"]         = 0
                    student["ruler_count"]            = 0
                    student["corrector_count"]        = 0
                    student["pencil_count"]           = 0
                    student["eraser_sharpener_count"] = 0
                    student["millimeter_count"]       = 0

                used = {
                    "prints":      student.get("print_count", 0),
                    "copies":      student.get("copy_count", 0),
                    "notebooks":   student.get("notebook_count", 0),
                    "rulers":      student.get("ruler_count", 0),
                    "correctors":  student.get("corrector_count", 0),
                    "pencils":     student.get("pencil_count", 0),
                    "erasers":     student.get("eraser_sharpener_count", 0),
                    "millimeters": student.get("millimeter_count", 0)
                }

                if used["prints"] + print_count > LIMITS["prints"]:
                    error = "Превышен лимит печати"

                elif used["copies"] + copy_count > LIMITS["copies"]:
                    error = "Превышен лимит копий"

                elif used["notebooks"] + notebook_count > LIMITS["notebooks"]:
                    error = "Тетрадь уже выдавалась"

                elif used["rulers"] + ruler_count > LIMITS["rulers"]:
                    error = "Линейка уже выдавалась"

                elif used["correctors"] + corrector_count > LIMITS["correctors"]:
                    error = "Корректор уже выдавался"

                elif used["pencils"] + pencil_count > LIMITS["pencils"]:
                    error = "Карандаш уже выдавался"

                elif used["erasers"] + eraser_sharpener_count > LIMITS["erasers"]:
                    error = "Ластик/точилка уже выдавались"

                elif used["millimeters"] + millimeter_count > LIMITS["millimeters"]:
                    error = "Превышен лимит миллиметровок"

                else:

                    cur.execute("""
                        UPDATE students
                        SET
                            print_count             = print_count + %s,
                            copy_count              = copy_count + %s,
                            notebook_count          = notebook_count + %s,
                            ruler_count             = ruler_count + %s,
                            corrector_count         = corrector_count + %s,
                            pencil_count            = pencil_count + %s,
                            eraser_sharpener_count  = eraser_sharpener_count + %s,
                            millimeter_count        = millimeter_count + %s
                        WHERE barcode = %s
                    """, (
                        print_count, copy_count, notebook_count,
                        ruler_count, corrector_count, pencil_count,
                        eraser_sharpener_count, millimeter_count,
                        barcode
                    ))

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
                            corrector_count, pencil_count, eraser_sharpener_count,
                            millimeter_count
                        )
                        VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s
                        )
                    """, (
                        barcode,
                        student.get("full_name") or "Неизвестно",
                        session.get("user") or "Секретарь",
                        action_text,
                        print_count, copy_count, notebook_count, ruler_count,
                        corrector_count, pencil_count, eraser_sharpener_count,
                        millimeter_count
                    ))

                    conn.commit()

                    messages = [
                        "Выдача успешно сохранена",
                        "🐯 Тигр успешно накормлен",
                        "📚 Бумажная промышленность процветает",
                        "⚡ Профком доволен вами",
                        "🖨️ Печать пошла в бой",
                        "🏆 +100 к уважению секретаря"
                    ]

                    message = (
                        random.choice(messages)
                        if random.randint(1, 10) == 1
                        else "Выдача успешно сохранена"
                    )

                    cur.execute("""
                        SELECT COUNT(*) as total
                        FROM entries
                        WHERE secretary = %s
                    """, (session["user"],))

                    total_actions = cur.fetchone()["total"]

                    if total_actions == 100:
                        achievement = "🏆 Достижение: 100 выдач"
                    elif total_actions == 500:
                        achievement = "🐯 Легенда профкома"
                    elif total_actions == 1000:
                        achievement = "👑 Верховный тигр"

                    student_limits = {
                        "prints":      LIMITS["prints"]      - (used["prints"]      + print_count),
                        "copies":      LIMITS["copies"]      - (used["copies"]      + copy_count),
                        "notebooks":   LIMITS["notebooks"]   - (used["notebooks"]   + notebook_count),
                        "rulers":      LIMITS["rulers"]      - (used["rulers"]      + ruler_count),
                        "correctors":  LIMITS["correctors"]  - (used["correctors"]  + corrector_count),
                        "pencils":     LIMITS["pencils"]     - (used["pencils"]     + pencil_count),
                        "erasers":     LIMITS["erasers"]     - (used["erasers"]     + eraser_sharpener_count),
                        "millimeters": LIMITS["millimeters"] - (used["millimeters"] + millimeter_count)
                    }

    cur.execute("""
        SELECT * FROM entries
        ORDER BY created_at DESC LIMIT 20
    """)

    entries = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "dashboard.html",
        entries=entries,
        error=error,
        message=message,
        student_limits=student_limits,
        achievement=achievement   # ИСПРАВЛЕНО: раньше не передавалось
    )


# ======================================================
# UNDO
# ИСПРАВЛЕНО: откатываем точные значения из колонок записи,
#             а не парсим action_text вручную
# ИСПРАВЛЕНО: GREATEST защищает от отрицательных значений
# ======================================================

@app.route("/undo/<int:entry_id>", methods=["POST"])
@login_required
@role_required("secretary")
def undo(entry_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM entries WHERE id = %s", (entry_id,))
    entry = cur.fetchone()

    if not entry:
        cur.close()
        conn.close()
        return redirect("/dashboard")

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

    return redirect("/dashboard")


# ======================================================
# CHAIRMAN
# ИСПРАВЛЕНО: добавлена передача students в шаблон
# ======================================================

@app.route("/chairman")
@role_required("chairman")
def chairman():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM users
        WHERE role='secretary'
        ORDER BY name
    """)
    secretaries = cur.fetchall()

    cur.execute("SELECT COUNT(*) as count FROM students")
    students_count = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) as count FROM entries")
    entries_count = cur.fetchone()["count"]

    cur.execute("""
        SELECT * FROM entries
        ORDER BY created_at DESC LIMIT 50
    """)
    entries = cur.fetchall()

    # ИСПРАВЛЕНО: передаём список студентов (раньше отсутствовал)
    cur.execute("SELECT * FROM students ORDER BY full_name")
    students = cur.fetchall()

    cur.execute("SELECT * FROM schedule")
    schedule_rows = cur.fetchall()

    schedule = {
        "Понедельник": "",
        "Вторник": "",
        "Среда": "",
        "Четверг": "",
        "Пятница": ""
    }

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
    cur = conn.cursor()

    try:
        cur.execute("""
        INSERT INTO users (name, password, role)
        VALUES (%s, %s, %s)
        """, (name, generate_password_hash(password), "secretary"))

        conn.commit()
        flash("Секретарь добавлен")

    except Exception as e:
        flash(f"Ошибка: {e}")

    cur.close()
    conn.close()

    return redirect("/chairman")


# ======================================================
# DELETE SECRETARY
# ======================================================

@app.route("/delete_secretary/<int:user_id>", methods=["POST"])
@role_required("chairman")
def delete_secretary(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM users WHERE id=%s AND role='secretary'",
        (user_id,)
    )

    conn.commit()
    cur.close()
    conn.close()

    flash("Секретарь удалён")
    return redirect("/chairman")


# ======================================================
# CHANGE SECRETARY PASSWORD
# ======================================================

@app.route("/change_secretary_password/<int:user_id>", methods=["POST"])
@role_required("chairman")
def change_secretary_password(user_id):

    password = request.form["password"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET password=%s
        WHERE id=%s AND role='secretary'
    """, (generate_password_hash(password), user_id))

    conn.commit()
    cur.close()
    conn.close()

    flash("Пароль секретаря изменён")
    return redirect("/chairman")


# ======================================================
# CHANGE PASSWORD
# ИСПРАВЛЕНО: было session["name"], должно быть session["user"]
# ======================================================

@app.route("/change_password", methods=["POST"])
@role_required("chairman")
def change_password():

    new_password = request.form["new_password"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET password=%s
        WHERE name=%s
    """, (
        generate_password_hash(new_password),
        session["user"]   # ИСПРАВЛЕНО: было session["name"]
    ))

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
    cur = conn.cursor()

    for day in ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"]:

        secretary = request.form.get(day)

        cur.execute("""
        UPDATE schedule
        SET secretary_name=%s
        WHERE day_name=%s
        """, (secretary, day))

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
    cur = conn.cursor()

    query = """
        SELECT
            student_name, secretary,
            print_count, copy_count, notebook_count, ruler_count,
            corrector_count, pencil_count, eraser_sharpener_count,
            millimeter_count, created_at
        FROM entries
        WHERE 1=1
    """

    params = []

    if date_from:
        query += " AND DATE(created_at) >= %s"
        params.append(date_from)

    if date_to:
        query += " AND DATE(created_at) <= %s"
        params.append(date_to)

    if secretary:
        query += " AND secretary = %s"
        params.append(secretary)

    query += " ORDER BY created_at DESC"

    cur.execute(query, tuple(params))
    entries = cur.fetchall()

    cur.close()
    conn.close()

    data = [{
        "Студент":         row["student_name"],
        "Секретарь":       row["secretary"],
        "Печать":          row["print_count"],
        "Копии":           row["copy_count"],
        "Тетради":         row["notebook_count"],
        "Линейки":         row["ruler_count"],
        "Корректоры":      row["corrector_count"],
        "Карандаши":       row["pencil_count"],
        "Ластики/Точилки": row["eraser_sharpener_count"],
        "Миллиметровки":   row["millimeter_count"],
        "Дата":            str(row["created_at"])
    } for row in entries]

    df = pd.DataFrame(data)
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Отчет")

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="report.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ======================================================
# UPLOAD STUDENTS
# ИСПРАВЛЕНО: добавлен @app.route (функция была недоступна)
# ======================================================

@app.route("/upload_students", methods=["POST"])
@role_required("chairman")
def upload_students():

    file = request.files.get("file")

    if not file:
        flash("Файл не выбран")
        return redirect("/chairman")

    conn = get_db()
    cur = conn.cursor()

    content = file.read().decode("utf-8").splitlines()
    added = 0

    for line in content:

        parts = line.split(";")

        if len(parts) != 2:
            continue

        barcode   = parts[0].strip()
        full_name = parts[1].strip()

        cur.execute(
            "SELECT * FROM students WHERE barcode=%s",
            (barcode,)
        )

        if cur.fetchone():
            continue

        cur.execute("""
            INSERT INTO students (barcode, full_name)
            VALUES (%s, %s)
        """, (barcode, full_name))

        added += 1

    conn.commit()
    cur.close()
    conn.close()

    flash(f"Добавлено студентов: {added}")
    return redirect("/chairman")


# ======================================================
# ADD STUDENT
# ======================================================

@app.route("/add_student", methods=["POST"])
@login_required
@role_required("chairman")
def add_student():

    barcode   = request.form.get("student_id", "").strip()
    full_name = request.form.get("name", "").strip()

    if not barcode or not full_name:
        flash("Заполните все поля")
        return redirect("/chairman")

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO students (barcode, full_name)
            VALUES (%s, %s)
        """, (barcode, full_name))

        conn.commit()
        flash("Студент добавлен")

    except Exception as e:
        flash(f"Ошибка: {e}")

    cur.close()
    conn.close()

    return redirect("/chairman")


# ======================================================
# DELETE STUDENT
# ======================================================

@app.route("/delete_student/<barcode>", methods=["POST"])
@login_required
@role_required("chairman")
def delete_student(barcode):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM students WHERE barcode = %s", (barcode,))

    conn.commit()
    cur.close()
    conn.close()

    flash("Студент удалён")
    return redirect("/chairman")


# ======================================================
# SEARCH STUDENTS
# ======================================================

@app.route("/search_students")
@login_required
def search_students():

    query = request.args.get("q", "")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT barcode, full_name
        FROM students
        WHERE LOWER(full_name) LIKE LOWER(%s)
        LIMIT 10
    """, (f"%{query}%",))

    students = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify(students)


# ======================================================
# STUDENT LIMITS API
# ИСПРАВЛЕНО: использует глобальную константу LIMITS
# ИСПРАВЛЕНО: результат не уходит в отрицательные значения
# ======================================================

@app.route("/student_limits/<barcode>")
@login_required
@role_required("secretary")
def student_limits_api(barcode):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            COALESCE(SUM(print_count), 0)            as prints,
            COALESCE(SUM(copy_count), 0)             as copies,
            COALESCE(SUM(notebook_count), 0)         as notebooks,
            COALESCE(SUM(ruler_count), 0)            as rulers,
            COALESCE(SUM(corrector_count), 0)        as correctors,
            COALESCE(SUM(pencil_count), 0)           as pencils,
            COALESCE(SUM(eraser_sharpener_count), 0) as erasers,
            COALESCE(SUM(millimeter_count), 0)       as millimeters
        FROM entries
        WHERE student_barcode = %s
        AND DATE_TRUNC('month', created_at) = DATE_TRUNC('month', CURRENT_DATE)
    """, (barcode,))

    used = cur.fetchone()

    result = {
        key: max(LIMITS[key] - used[key], 0)
        for key in LIMITS
    }

    cur.close()
    conn.close()

    return jsonify(result)


# ======================================================
# PING (anti-sleep)
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
