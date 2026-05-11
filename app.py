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
    send_file
)

import psycopg2
from psycopg2.extras import RealDictCursor

from functools import wraps
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from openpyxl import Workbook


# ======================================================
# FLASK
# ======================================================

app = Flask(__name__)
app.secret_key = "secret123"
def get_connection():

    return psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        sslmode="require"
    )

def login_required(func):

    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):

        if "user" not in session:
            return redirect("/")

        return func(*args, **kwargs)

    return wrapper


def role_required(role):

    from functools import wraps

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):

            if session.get("role") != role:
                return redirect("/")

            return func(*args, **kwargs)

        return wrapper

    return decorator


# ======================================================
# DATABASE
# ======================================================

DATABASE_URL = os.getenv("DATABASE_URL")


def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )


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

    days = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница"
    ]

    for day in days:

        cur.execute(
            "SELECT * FROM schedule WHERE day_name=%s",
            (day,)
        )

        exists = cur.fetchone()

        if not exists:

            cur.execute("""
            INSERT INTO schedule (
                day_name,
                secretary_name
            )
            VALUES (%s, %s)
            """, (
                day,
                ""
            ))

    chairman_name = "Курмаева Юлия Игоревна"

    cur.execute("""
    SELECT *
    FROM users
    WHERE role='chairman'
    """)

    chairman = cur.fetchone()

    if not chairman:

        cur.execute("""
        INSERT INTO users (
            name,
            password,
            role
        )
        VALUES (%s, %s, %s)
        """, (
            chairman_name,
            generate_password_hash("1234"),
            "chairman"
        ))

    conn.commit()

    cur.close()
    conn.close()


# ======================================================
# ROLE CHECK
# ======================================================

def role_required(role):

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):

            if "user" not in session:
                return redirect("/")

            if session.get("role") != role:
                return "Нет доступа"

            return func(*args, **kwargs)

        return wrapper

    return decorator


# ======================================================
# LOGIN
# ======================================================

@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        name = request.form["name"]
        password = request.form["password"]

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
        SELECT *
        FROM users
        WHERE name=%s
        """, (name,))

        user = cur.fetchone()

        cur.close()
        conn.close()

        if user:

            if check_password_hash(
                user["password"],
                password
            ):

                session["user"] = user["name"]
                session["role"] = user["role"]

                if user["role"] == "chairman":
                    return redirect("/chairman")

                return redirect("/dashboard")

        flash("Неверный логин или пароль")

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

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    error = None
    success = None
    student_limits = None

    LIMITS = {
        "Печать": 20,
        "Копия": 20,
        "Тетрадь": 1,
        "Линейка": 1,
        "Корректор": 1,
        "Карандаш": 1,
        "Ластик/Точилка": 1,
        "Миллиметровка": 2
    }

    FIELD_MAP = {
        "Печать": "print_count",
        "Копия": "copy_count",
        "Тетрадь": "notebook_count",
        "Линейка": "ruler_count",
        "Корректор": "corrector_count",
        "Карандаш": "pencil_count",
        "Ластик/Точилка": "eraser_sharpener_count",
        "Миллиметровка": "millimeter_count"
    }

    if request.method == "POST":

        barcode = request.form.get("barcode", "").strip()
        action = request.form.get("action", "").strip()

        if not barcode or not action:

            error = "Заполните все поля"

        else:

            cur.execute("""
                SELECT *
                FROM students
                WHERE barcode = %s
            """, (barcode,))

            student = cur.fetchone()

            if not student:

                error = "Студент не найден"

            else:

                field_name = FIELD_MAP[action]

                current_value = student[field_name]

                if current_value >= LIMITS[action]:

                    error = f"Лимит для '{action}' исчерпан"

                else:

                    cur.execute(f"""
                        UPDATE students
                        SET {field_name} = {field_name} + 1
                        WHERE barcode = %s
                    """, (barcode,))

                    cur.execute("""
                        INSERT INTO entries (
                            student_barcode,
                            student_name,
                            secretary,
                            action_text
                        )
                        VALUES (%s, %s, %s, %s)
                    """, (
                        barcode,
                        student["name"],
                        session["user"],
                        action
                    ))

                    conn.commit()

                    success = f"{action} успешно выдан"

                    cur.execute("""
                        SELECT *
                        FROM students
                        WHERE barcode = %s
                    """, (barcode,))

                    student_limits = cur.fetchone()

    cur.execute("""
        SELECT *
        FROM entries
        ORDER BY created_at DESC
        LIMIT 20
    """)

    entries = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "dashboard.html",
        user=session["user"],
        entries=entries,
        error=error,
        success=success,
        student_limits=student_limits,
        limits=LIMITS
    )

@app.route("/undo_action/<int:entry_id>", methods=["POST"])
@login_required
@role_required("secretary")
def undo_action(entry_id):

    entry_id = int(entry_id)

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT *
        FROM entries
        WHERE id = %s
    """, (entry_id,))

    entry = cur.fetchone()

    if not entry:
        cur.close()
        conn.close()
        return redirect("/dashboard")

    barcode = entry["student_barcode"]
    action = entry["action_text"]

    field_map = {
        "Печать": "print_count",
        "Копия": "copy_count",
        "Тетрадь": "notebook_count",
        "Линейка": "ruler_count",
        "Корректор": "corrector_count",
        "Карандаш": "pencil_count",
        "Ластик/Точилка": "eraser_sharpener_count",
        "Миллиметровка": "millimeter_count"
    }

    if action in field_map:

        field = field_map[action]

        cur.execute(f"""
            UPDATE students
            SET {field} = GREATEST({field} - 1, 0)
            WHERE barcode = %s
        """, (barcode,))

    cur.execute("""
        DELETE FROM entries
        WHERE id = %s
    """, (entry_id,))

    conn.commit()

    cur.close()
    conn.close()

    return redirect("/dashboard")
# ======================================================
# CHAIRMAN
# ======================================================

@app.route("/chairman")
@role_required("chairman")
def chairman():

    conn = get_db()
    cur = conn.cursor()

    # Секретари
    cur.execute("""
        SELECT *
        FROM users
        WHERE role='secretary'
        ORDER BY name
    """)

    secretaries = cur.fetchall()

    # Количество студентов
    cur.execute("""
        SELECT COUNT(*) as count
        FROM students
    """)

    students_count = cur.fetchone()["count"]

    # Количество выдач
    cur.execute("""
        SELECT COUNT(*) as count
        FROM entries
    """)

    entries_count = cur.fetchone()["count"]

    # Последние действия
    cur.execute("""
        SELECT *
        FROM entries
        ORDER BY created_at DESC
        LIMIT 50
    """)

    entries = cur.fetchall()

    # Расписание
    cur.execute("""
        SELECT *
        FROM schedule
    """)

    schedule_rows = cur.fetchall()

    schedule = {
        "Понедельник": "",
        "Вторник": "",
        "Среда": "",
        "Четверг": "",
        "Пятница": ""
    }

    for row in schedule_rows:
        schedule[row["day"]] = row["secretary_name"]

    cur.close()
    conn.close()

    return render_template(
        "chairman.html",
        secretaries=secretaries,
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

    name = request.form["name"]
    password = request.form["password"]

    conn = get_db()
    cur = conn.cursor()

    try:

        cur.execute("""
        INSERT INTO users (
            name,
            password,
            role
        )
        VALUES (%s, %s, %s)
        """, (
            name,
            generate_password_hash(password),
            "secretary"
        ))

        conn.commit()

        flash("Секретарь добавлен")

    except Exception as e:

        flash(f"Ошибка: {e}")

    cur.close()
    conn.close()

    return redirect("/chairman")


# ======================================================
# CHANGE PASSWORD
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
        session["user"]
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

    days = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница"
    ]

    for day in days:

        secretary = request.form.get(day)

        cur.execute("""
        UPDATE schedule
        SET secretary_name=%s
        WHERE day_name=%s
        """, (
            secretary,
            day
        ))

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
    date_to = request.args.get("date_to")
    secretary = request.args.get("secretary")

    conn = get_db()
    cur = conn.cursor()

    query = """
        SELECT
            student_name,
            secretary,
            print_count,
            copy_count,
            notebook_count,
            ruler_count,
            corrector_count,
            pencil_count,
            eraser_sharpener_count,
            millimeter_count,
            created_at
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

    data = []

    for row in entries:

        data.append({

            "Студент": row["student_name"],
            "Секретарь": row["secretary"],

            "Печать": row["print_count"],
            "Копии": row["copy_count"],

            "Тетради": row["notebook_count"],
            "Линейки": row["ruler_count"],
            "Корректоры": row["corrector_count"],
            "Карандаши": row["pencil_count"],
            "Ластики/Точилки": row["eraser_sharpener_count"],
            "Миллиметровки": row["millimeter_count"],

            "Дата": str(row["created_at"])
        })

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

@app.route("/upload_students", methods=["POST"])
@role_required("chairman")
def upload_students():

    file = request.files["file"]

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

        barcode = parts[0].strip()
        full_name = parts[1].strip()

        cur.execute("""
            SELECT * FROM students
            WHERE barcode=%s
        """, (barcode,))

        exists = cur.fetchone()

        if exists:
            continue

        cur.execute("""
            INSERT INTO students (
                barcode,
                full_name
            )
            VALUES (%s,%s)
        """, (
            barcode,
            full_name
        ))

        added += 1

    conn.commit()

    cur.close()
    conn.close()

    flash(f"Добавлено студентов: {added}")

    return redirect("/chairman")
# ======================================================
# START
# ======================================================

init_db()

if __name__ == "__main__":
    app.run(debug=True)
