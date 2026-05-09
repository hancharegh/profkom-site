# app.py

import os
import io
import pandas as pd
import csv
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


# =====================================================
# FLASK
# =====================================================

app = Flask(__name__)
app.secret_key = "super_secret_key_2026"


# =====================================================
# DATABASE
# =====================================================

DATABASE_URL = os.getenv("DATABASE_URL")


def get_db():

    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )


# =====================================================
# INIT DATABASE
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
    secretary_name TEXT NOT NULL
)
""")

    cur.execute("SELECT * FROM schedule")

    if not cur.fetchone():

        cur.execute("""
        INSERT INTO schedule (
            monday,
            tuesday,
            wednesday,
            thursday,
            friday
        )
        VALUES (%s,%s,%s,%s,%s)
        """, (
            "",
            "",
            "",
            "",
            ""
        ))

   # CREATE CHAIRMAN

cur.execute(
    "SELECT * FROM users WHERE role=%s",
    ("chairman",)
)

chairman = cur.fetchone()

if not chairman:

    cur.execute("""
    INSERT INTO users (name, password, role)
    VALUES (%s, %s, %s)
    """, (
        "Курмаева Юлия Игоревна",
        generate_password_hash("1234"),
        "chairman"
    ))

else:

    cur.execute("""
    UPDATE users
    SET role=%s
    WHERE name=%s
    """, (
        "chairman",
        "Курмаева Юлия Игоревна"
    ))    
    conn.commit()

    cur.close()
    conn.close()




# =====================================================
# ROLE DECORATOR
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

    student_info = None

    # ПОИСК СТУДЕНТА
    barcode_search = request.args.get("barcode")

    if barcode_search:

        cur.execute("""
        SELECT *
        FROM students
        WHERE barcode=%s
        """, (barcode_search,))

        student = cur.fetchone()

        if student:

            cur.execute("""
            SELECT
                COALESCE(SUM(print_count),0) AS prints,
                COALESCE(SUM(copy_count),0) AS copies
            FROM entries
            WHERE student_barcode=%s
            """, (barcode_search,))

            stats = cur.fetchone()

            student_info = {
                "name": student["full_name"],
                "prints_used": stats["prints"],
                "copies_used": stats["copies"],
                "prints_left": 30 - stats["prints"],
                "copies_left": 30 - stats["copies"]
            }

    # СОХРАНЕНИЕ
    if request.method == "POST":

        try:

            barcode = request.form.get("barcode")

            cur.execute("""
            SELECT *
            FROM students
            WHERE barcode=%s
            """, (barcode,))

            student = cur.fetchone()

            if not student:
                flash("Студент не найден")
                return redirect("/dashboard")

            print_count = int(request.form.get("print_count") or 0)
            copy_count = int(request.form.get("copy_count") or 0)

            cur.execute("""
            SELECT
                COALESCE(SUM(print_count),0) AS prints,
                COALESCE(SUM(copy_count),0) AS copies
            FROM entries
            WHERE student_barcode=%s
            """, (barcode,))

            limits = cur.fetchone()

            if limits["prints"] + print_count > 30:
                flash("Превышен лимит печати")
                return redirect("/dashboard")

            if limits["copies"] + copy_count > 30:
                flash("Превышен лимит копий")
                return redirect("/dashboard")

            cur.execute("""
            INSERT INTO entries (
                student_barcode,
                student_name,
                secretary,

                print_count,
                copy_count,

                ruler_count,
                notebook_count,
                corrector_count,
                pencil_count,
                eraser_sharpener_count,
                millimeter_count
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (

                barcode,
                student["full_name"],
                session["user"],

                print_count,
                copy_count,

                int(request.form.get("ruler_count") or 0),
                int(request.form.get("notebook_count") or 0),
                int(request.form.get("corrector_count") or 0),
                int(request.form.get("pencil_count") or 0),
                int(request.form.get("eraser_sharpener_count") or 0),
                int(request.form.get("millimeter_count") or 0)

            ))

            conn.commit()

            flash("Успешно сохранено")

            return redirect("/dashboard")

        except Exception as e:

            conn.rollback()

            flash(f"Ошибка: {str(e)}")

    # HISTORY
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
        entries=entries,
        student_info=student_info
    )


# =====================================================
# CHAIRMAN
# =====================================================

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
    cur.execute("SELECT COUNT(*) FROM students")
    students_count = cur.fetchone()["count"]

    # Количество записей
    cur.execute("SELECT COUNT(*) FROM entries")
    entries_count = cur.fetchone()["count"]

    # Последние записи
    cur.execute("""
    SELECT *
    FROM entries
    ORDER BY created_at DESC
    LIMIT 30
    """)
    entries = cur.fetchall()

    # Расписание
    cur.execute("""
    SELECT *
    FROM schedule
    LIMIT 1
    """)
    schedule = cur.fetchone()

    # Закрываем только здесь
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


@app.route("/save_schedule", methods=["POST"])
@role_required("chairman")
def save_schedule():

    monday = request.form.get("monday")
    tuesday = request.form.get("tuesday")
    wednesday = request.form.get("wednesday")
    thursday = request.form.get("thursday")
    friday = request.form.get("friday")

    conn = get_db()
    cur = conn.cursor()

    try:

        # очищаем старое расписание
        cur.execute("DELETE FROM schedule")

        # сохраняем новое
        cur.execute("""
        INSERT INTO schedule (
            monday,
            tuesday,
            wednesday,
            thursday,
            friday
        )
        VALUES (%s, %s, %s, %s, %s)
        """, (
            monday,
            tuesday,
            wednesday,
            thursday,
            friday
        ))

        conn.commit()

        flash("Расписание сохранено")

    except Exception as e:

        conn.rollback()

        flash(f"Ошибка: {e}")

    cur.close()
    conn.close()

    return redirect("/chairman")


@app.route("/upload_students", methods=["POST"])
@role_required("chairman")
def upload_students():

    file = request.files.get("file")

    if not file:
        flash("Файл не выбран")
        return redirect("/chairman")

    conn = get_db()
    cur = conn.cursor()

    try:

        content = file.read().decode("utf-8")
        lines = content.splitlines()

        added = 0

        for line in lines:

            parts = line.split(";")

            if len(parts) != 2:
                continue

            barcode = parts[0].strip()
            full_name = parts[1].strip()

            try:

                cur.execute("""
                INSERT INTO students (
                    barcode,
                    full_name
                )
                VALUES (%s, %s)
                """, (
                    barcode,
                    full_name
                ))

                added += 1

            except:
                conn.rollback()

        conn.commit()

        flash(f"Добавлено студентов: {added}")

    except Exception as e:

        flash(f"Ошибка файла: {e}")

    cur.close()
    conn.close()

    return redirect("/chairman")
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
        INSERT INTO users (
            name,
            password,
            role
        )
        VALUES (%s, %s, %s)
        """, (
            name,
            password,
            "secretary"
        ))

        conn.commit()

        flash("Секретарь успешно добавлен")

    except Exception as e:

        conn.rollback()

        print(e)

        flash("Ошибка добавления секретаря")

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
# ADD STUDENT
# =====================================================

@app.route("/add_student", methods=["POST"])
@role_required("chairman")
def add_student():

    conn = get_db()
    cur = conn.cursor()

    try:

        cur.execute("""
        INSERT INTO students (
            barcode,
            full_name
        )
        VALUES (%s,%s)
        """, (

            request.form["barcode"],
            request.form["full_name"]

        ))

        conn.commit()

        flash("Студент добавлен")

    except:
        flash("Ошибка")

    cur.close()
    conn.close()

    return redirect("/chairman")


# =====================================================
# DELETE STUDENT
# =====================================================

@app.route("/delete_student/<int:student_id>")
@role_required("chairman")
def delete_student(student_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM students WHERE id=%s",
        (student_id,)
    )

    conn.commit()

    cur.close()
    conn.close()

    flash("Студент удалён")

    return redirect("/chairman")


# =====================================================
# EXPORT EXCEL
# =====================================================

@app.route("/export_excel")
@role_required("chairman")
def export_excel():

    from openpyxl import Workbook
    from flask import send_file
    import tempfile

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    SELECT *
    FROM entries
    ORDER BY created_at DESC
    """)

    entries = cur.fetchall()

    cur.close()
    conn.close()

    wb = Workbook()
    ws = wb.active

    ws.title = "Отчёт"

    # Заголовки
    headers = [
        "ID",
        "Баркод",
        "Студент",
        "Секретарь",
        "Печать",
        "Копии",
        "Линейки",
        "Тетради",
        "Корректоры",
        "Карандаши",
        "Ластики/точилки",
        "Миллиметровка",
        "Дата"
    ]

    ws.append(headers)

    # Данные
    for row in entries:

        ws.append([
            row["id"],
            row["student_barcode"],
            row["student_name"],
            row["secretary"],
            row["print_count"],
            row["copy_count"],
            row["ruler_count"],
            row["notebook_count"],
            row["corrector_count"],
            row["pencil_count"],
            row["eraser_sharpener_count"],
            row["millimeter_count"],
            str(row["created_at"])
        ])

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")

    wb.save(tmp.name)

    return send_file(
        tmp.name,
        as_attachment=True,
        download_name="report.xlsx"
    )

# =====================================================
# START
# =====================================================

init_db()

if __name__ == "__main__":
    app.run(debug=True)
