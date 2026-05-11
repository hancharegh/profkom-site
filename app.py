import os
from io import BytesIO
from datetime import datetime

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
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

from openpyxl import Workbook


# =====================================================
# FLASK
# =====================================================

app = Flask(__name__)
app.secret_key = "super_secret_key_2026"

DATABASE_URL = os.getenv("DATABASE_URL")


# =====================================================
# DATABASE
# =====================================================

def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )


# =====================================================
# INIT DB
# =====================================================

def init_db():

    conn = get_db()
    cur = conn.cursor()

    # USERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL
    )
    """)

    # STUDENTS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id SERIAL PRIMARY KEY,
        barcode TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL
    )
    """)

    # ENTRIES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS entries (
        id SERIAL PRIMARY KEY,

        student_barcode TEXT NOT NULL,
        student_name TEXT NOT NULL,
        secretary TEXT NOT NULL,

        action_text TEXT NOT NULL,

        print_count INTEGER DEFAULT 0,
        copy_count INTEGER DEFAULT 0,
        ruler_count INTEGER DEFAULT 0,
        notebook_count INTEGER DEFAULT 0,
        corrector_count INTEGER DEFAULT 0,
        pencil_count INTEGER DEFAULT 0,
        eraser_sharpener_count INTEGER DEFAULT 0,
        millimeter_count INTEGER DEFAULT 0,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # SCHEDULE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS schedule (
        id SERIAL PRIMARY KEY,
        day_name TEXT UNIQUE NOT NULL,
        secretary_name TEXT
    )
    """)

    # DAYS
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
            INSERT INTO schedule (day_name, secretary_name)
            VALUES (%s, %s)
            """, (day, None))

    # CHAIRMAN
    chairman_name = "Курмаева Юлия Игоревна"

    cur.execute(
        "SELECT * FROM users WHERE name=%s",
        (chairman_name,)
    )

    chairman = cur.fetchone()

    if not chairman:

        cur.execute("""
        INSERT INTO users (name, password, role)
        VALUES (%s, %s, %s)
        """, (
            chairman_name,
            generate_password_hash("1234"),
            "chairman"
        ))

    conn.commit()

    cur.close()
    conn.close()


# =====================================================
# ROLE
# =====================================================

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


# =====================================================
# LOGIN
# =====================================================

@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        name = request.form.get("name")
        password = request.form.get("password")

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM users WHERE name=%s",
            (name,)
        )

        user = cur.fetchone()

        cur.close()
        conn.close()

        if user and check_password_hash(user["password"], password):

            session["user"] = user["name"]
            session["role"] = user["role"]

            if user["role"] == "chairman":
                return redirect("/chairman")

            return redirect("/dashboard")

        flash("Неверный логин или пароль")

    return render_template("login.html")


# =====================================================
# LOGOUT
# =====================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# =====================================================
# DASHBOARD
# =====================================================

@app.route("/dashboard", methods=["GET", "POST"])
@role_required("secretary")
def dashboard():

    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":

        barcode = request.form["barcode"]

        cur.execute(
            "SELECT * FROM students WHERE barcode=%s",
            (barcode,)
        )

        student = cur.fetchone()

        if not student:

            flash("Студент не найден")

            cur.close()
            conn.close()

            return redirect("/dashboard")

        # COUNTS
        print_count = int(request.form.get("print_count", 0))
        copy_count = int(request.form.get("copy_count", 0))
        ruler_count = int(request.form.get("ruler_count", 0))
        notebook_count = int(request.form.get("notebook_count", 0))
        corrector_count = int(request.form.get("corrector_count", 0))
        pencil_count = int(request.form.get("pencil_count", 0))
        eraser_sharpener_count = int(request.form.get("eraser_sharpener_count", 0))
        millimeter_count = int(request.form.get("millimeter_count", 0))

        # LIMITS
        cur.execute("""
        SELECT
            COALESCE(SUM(print_count),0) as prints,
            COALESCE(SUM(copy_count),0) as copies,
            COALESCE(SUM(ruler_count),0) as rulers,
            COALESCE(SUM(notebook_count),0) as notebooks,
            COALESCE(SUM(corrector_count),0) as correctors,
            COALESCE(SUM(pencil_count),0) as pencils,
            COALESCE(SUM(eraser_sharpener_count),0) as erasers,
            COALESCE(SUM(millimeter_count),0) as millimeters
        FROM entries
        WHERE student_barcode=%s
        """, (barcode,))

        limits = cur.fetchone()

        if limits["prints"] + print_count > 30:
            flash("Лимит печати превышен")
            return redirect("/dashboard")

        if limits["copies"] + copy_count > 30:
            flash("Лимит копий превышен")
            return redirect("/dashboard")

        if limits["rulers"] + ruler_count > 1:
            flash("Линейка уже выдана")
            return redirect("/dashboard")

        if limits["notebooks"] + notebook_count > 1:
            flash("Тетрадь уже выдана")
            return redirect("/dashboard")

        if limits["correctors"] + corrector_count > 1:
            flash("Корректор уже выдан")
            return redirect("/dashboard")

        if limits["pencils"] + pencil_count > 1:
            flash("Карандаш уже выдан")
            return redirect("/dashboard")

        if limits["erasers"] + eraser_sharpener_count > 1:
            flash("Ластик/точилка уже выданы")
            return redirect("/dashboard")

        if limits["millimeters"] + millimeter_count > 1:
            flash("Миллиметровка уже выдана")
            return redirect("/dashboard")

        actions = []

        if print_count:
            actions.append(f"Печать: {print_count}")

        if copy_count:
            actions.append(f"Копии: {copy_count}")

        if ruler_count:
            actions.append("Линейка")

        if notebook_count:
            actions.append("Тетрадь")

        if corrector_count:
            actions.append("Корректор")

        if pencil_count:
            actions.append("Карандаш")

        if eraser_sharpener_count:
            actions.append("Ластик/Точилка")

        if millimeter_count:
            actions.append("Миллиметровка")

        action_text = ", ".join(actions)

        cur.execute("""
        INSERT INTO entries (
            student_barcode,
            student_name,
            secretary,
            action_text,

            print_count,
            copy_count,
            ruler_count,
            notebook_count,
            corrector_count,
            pencil_count,
            eraser_sharpener_count,
            millimeter_count
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            barcode,
            student["full_name"],
            session["user"],
            action_text,

            print_count,
            copy_count,
            ruler_count,
            notebook_count,
            corrector_count,
            pencil_count,
            eraser_sharpener_count,
            millimeter_count
        ))

        conn.commit()

        flash("Запись добавлена")

        return redirect("/dashboard")

    cur.execute("""
    SELECT *
    FROM entries
    ORDER BY created_at DESC
    LIMIT 50
    """)

    entries = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "dashboard.html",
        entries=entries
    )


# =====================================================
# CANCEL ENTRY
# =====================================================

@app.route("/delete_entry/<int:entry_id>")
@role_required("secretary")
def delete_entry(entry_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM entries WHERE id=%s",
        (entry_id,)
    )

    conn.commit()

    cur.close()
    conn.close()

    flash("Запись отменена")

    return redirect("/dashboard")


# =====================================================
# CHAIRMAN
# =====================================================

@app.route("/chairman")
@role_required("chairman")
def chairman():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    SELECT *
    FROM users
    WHERE role='secretary'
    ORDER BY name
    """)

    secretaries = cur.fetchall()

    cur.execute("""
    SELECT *
    FROM entries
    ORDER BY created_at DESC
    LIMIT 50
    """)

    entries = cur.fetchall()

    cur.execute("""
    SELECT *
    FROM schedule
    ORDER BY id
    """)

    schedule_rows = cur.fetchall()

    schedule = {}

    for row in schedule_rows:
        schedule[row["day_name"]] = row["secretary_name"]

    cur.close()
    conn.close()

    return render_template(
        "chairman.html",
        secretaries=secretaries,
        entries=entries,
        schedule=schedule
    )


# =====================================================
# ADD SECRETARY
# =====================================================

@app.route("/add_secretary", methods=["POST"])
@role_required("chairman")
def add_secretary():

    name = request.form["name"]
    password = request.form["password"]

    conn = get_db()
    cur = conn.cursor()

    try:

        cur.execute("""
        INSERT INTO users (name, password, role)
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


# =====================================================
# DELETE SECRETARY
# =====================================================

@app.route("/delete_secretary/<int:user_id>")
@role_required("chairman")
def delete_secretary(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM users WHERE id=%s",
        (user_id,)
    )

    conn.commit()

    cur.close()
    conn.close()

    flash("Секретарь удалён")

    return redirect("/chairman")


# =====================================================
# SAVE SCHEDULE
# =====================================================

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

        secretary_name = request.form.get(day)

        cur.execute("""
        UPDATE schedule
        SET secretary_name=%s
        WHERE day_name=%s
        """, (
            secretary_name,
            day
        ))

    conn.commit()

    cur.close()
    conn.close()

    flash("Расписание сохранено")

    return redirect("/chairman")


# =====================================================
# EXPORT EXCEL
# =====================================================

@app.route("/export_excel")
@role_required("chairman")
def export_excel():

    conn = get_db()
    cur = conn.cursor()

    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    secretary = request.args.get("secretary")

    query = """
    SELECT *
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
        query += " AND secretary=%s"
        params.append(secretary)

    query += " ORDER BY created_at DESC"

    cur.execute(query, params)

    rows = cur.fetchall()

    wb = Workbook()
    ws = wb.active

    ws.append([
        "ID",
        "Баркод",
        "Студент",
        "Секретарь",
        "Действие",
        "Дата"
    ])

    for row in rows:

        ws.append([
            row["id"],
            row["student_barcode"],
            row["student_name"],
            row["secretary"],
            row["action_text"],
            str(row["created_at"])
        ])

    file_stream = BytesIO()

    wb.save(file_stream)

    file_stream.seek(0)

    cur.close()
    conn.close()

    return send_file(
        file_stream,
        as_attachment=True,
        download_name="report.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# =====================================================
# START
# =====================================================

init_db()

if __name__ == "__main__":
    app.run(debug=True)
