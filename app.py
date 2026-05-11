import os
import csv
from io import StringIO, BytesIO

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
app.secret_key = "super_secret_key"


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
@role_required("secretary")
def dashboard():

    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":

        barcode = request.form["barcode"]

        cur.execute("""
        SELECT *
        FROM students
        WHERE barcode=%s
        """, (barcode,))

        student = cur.fetchone()

        if not student:

            flash("Студент не найден")

            return redirect("/dashboard")

        actions = []

        fields = {
            "Печать": request.form.get("print_count"),
            "Копии": request.form.get("copy_count"),
            "Тетрадь": request.form.get("notebook_count"),
            "Линейка": request.form.get("ruler_count"),
            "Корректор": request.form.get("corrector_count"),
            "Карандаш": request.form.get("pencil_count"),
            "Ластик/точилка": request.form.get("eraser_count"),
            "Миллиметровка": request.form.get("millimeter_count")
        }

        for key, value in fields.items():

            if value and value != "0":

                actions.append(
                    f"{key}: {value}"
                )

        action_text = ", ".join(actions)

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
            student["full_name"],
            session["user"],
            action_text
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


# ======================================================
# CHAIRMAN
# ======================================================

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
    WHERE role='chairman'
    """, (
        generate_password_hash(new_password),
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

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    SELECT *
    FROM entries
    ORDER BY created_at DESC
    """)

    rows = cur.fetchall()

    wb = Workbook()
    ws = wb.active

    ws.append([
        "Баркод",
        "Студент",
        "Секретарь",
        "Действие",
        "Дата"
    ])

    for row in rows:

        ws.append([
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


# ======================================================
# START
# ======================================================

init_db()

if __name__ == "__main__":
    app.run(debug=True)
