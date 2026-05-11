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
            SELECT
                COALESCE(SUM(print_count),0) as prints,
                COALESCE(SUM(copy_count),0) as copies,
                COALESCE(SUM(notebook_count),0) as notebooks,
                COALESCE(SUM(ruler_count),0) as rulers,
                COALESCE(SUM(corrector_count),0) as correctors,
                COALESCE(SUM(pencil_count),0) as pencils,
                COALESCE(SUM(eraser_sharpener_count),0) as erasers,
                COALESCE(SUM(millimeter_count),0) as millimeters
            FROM entries
            WHERE student_barcode=%s
        """, (barcode,))

        used = cur.fetchone()

        LIMITS = {
            "prints": 30,
            "copies": 30,
            "notebooks": 1,
            "rulers": 1,
            "correctors": 1,
            "pencils": 1,
            "erasers": 1,
            "millimeters": 1
        }

        if used["prints"] + print_count > LIMITS["prints"]:
            flash("Лимит печати превышен")
            return redirect("/dashboard")

        if used["copies"] + copy_count > LIMITS["copies"]:
            flash("Лимит копий превышен")
            return redirect("/dashboard")

        if used["notebooks"] + notebook_count > LIMITS["notebooks"]:
            flash("Лимит тетрадей превышен")
            return redirect("/dashboard")

        if used["rulers"] + ruler_count > LIMITS["rulers"]:
            flash("Лимит линеек превышен")
            return redirect("/dashboard")

        if used["correctors"] + corrector_count > LIMITS["correctors"]:
            flash("Лимит корректоров превышен")
            return redirect("/dashboard")

        if used["pencils"] + pencil_count > LIMITS["pencils"]:
            flash("Лимит карандашей превышен")
            return redirect("/dashboard")

        if used["erasers"] + eraser_sharpener_count > LIMITS["erasers"]:
            flash("Лимит ластиков/точилок превышен")
            return redirect("/dashboard")

        if used["millimeters"] + millimeter_count > LIMITS["millimeters"]:
            flash("Лимит миллиметровок превышен")
            return redirect("/dashboard")
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

        # HISTORY

    cur.execute("""
        SELECT *
        FROM entries
        ORDER BY created_at DESC
        LIMIT 50
    """)

    entries = cur.fetchall()

    student_limits = None

    barcode = request.args.get("barcode")

    if barcode:

        cur.execute("""
            SELECT
                COALESCE(SUM(print_count),0) as prints,
                COALESCE(SUM(copy_count),0) as copies,
                COALESCE(SUM(notebook_count),0) as notebooks,
                COALESCE(SUM(ruler_count),0) as rulers,
                COALESCE(SUM(corrector_count),0) as correctors,
                COALESCE(SUM(pencil_count),0) as pencils,
                COALESCE(SUM(eraser_sharpener_count),0) as erasers,
                COALESCE(SUM(millimeter_count),0) as millimeters
            FROM entries
            WHERE student_barcode=%s
        """, (barcode,))

        used = cur.fetchone()

        student_limits = {
            "prints": 30 - used["prints"],
            "copies": 30 - used["copies"],
            "notebooks": 1 - used["notebooks"],
            "rulers": 1 - used["rulers"],
            "correctors": 1 - used["correctors"],
            "pencils": 1 - used["pencils"],
            "erasers": 1 - used["erasers"],
            "millimeters": 1 - used["millimeters"]
        }

    cur.close()
    conn.close()

    return render_template(
        "dashboard.html",
        entries=entries,
        student_limits=student_limits
    )

@app.route("/undo_last")
@role_required("secretary")
def undo_last():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM entries
        WHERE id = (
            SELECT id
            FROM entries
            WHERE secretary=%s
            ORDER BY created_at DESC
            LIMIT 1
        )
    """, (session["user"],))

    conn.commit()

    cur.close()
    conn.close()

    flash("Последняя операция отменена")

    return redirect("/dashboard")

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
