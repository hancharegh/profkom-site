import os
import io
import pandas as pd

from functools import wraps

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
        sslmode="require",
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
        full_name TEXT NOT NULL,
        print_limit INTEGER DEFAULT 30,
        copy_limit INTEGER DEFAULT 30
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

    # SCHEDULES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS schedules (
        id SERIAL PRIMARY KEY,
        secretary_name TEXT NOT NULL,
        work_date DATE NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL
    )
    """)

    # CHAIRMAN
    cur.execute(
        "SELECT * FROM users WHERE name=%s",
        ("chairman",)
    )

    chairman = cur.fetchone()

    if not chairman:

        cur.execute(
            """
            INSERT INTO users (name, password, role)
            VALUES (%s, %s, %s)
            """,
            (
                "chairman",
                generate_password_hash("1234"),
                "chairman"
            )
        )

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
                return "Нет доступа", 403

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

        if not user:
            return "Неверный логин или пароль", 400

        if not check_password_hash(user["password"], password):
            return "Неверный логин или пароль", 400

        session["user"] = user["name"]
        session["role"] = user["role"]

        if user["role"] == "chairman":
            return redirect("/chairman")

        return redirect("/dashboard")

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

        barcode = request.form.get("barcode")

        cur.execute(
            "SELECT * FROM students WHERE barcode=%s",
            (barcode,)
        )

        student = cur.fetchone()

        if not student:
            flash("Студент не найден")
            return redirect("/dashboard")

        print_count = int(request.form.get("print_count") or 0)
        copy_count = int(request.form.get("copy_count") or 0)
        ruler_count = int(request.form.get("ruler_count") or 0)
        notebook_count = int(request.form.get("notebook_count") or 0)
        corrector_count = int(request.form.get("corrector_count") or 0)
        pencil_count = int(request.form.get("pencil_count") or 0)
        eraser_sharpener_count = int(request.form.get("eraser_sharpener_count") or 0)
        millimeter_count = int(request.form.get("millimeter_count") or 0)

        if print_count > student["print_limit"]:
            flash("Превышен лимит печати")
            return redirect("/dashboard")

        if copy_count > student["copy_limit"]:
            flash("Превышен лимит копий")
            return redirect("/dashboard")

        cur.execute(
            """
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
            """,
            (
                barcode,
                student["full_name"],
                session["user"],
                print_count,
                copy_count,
                ruler_count,
                notebook_count,
                corrector_count,
                pencil_count,
                eraser_sharpener_count,
                millimeter_count
            )
        )

        conn.commit()

        flash("Запись успешно добавлена")

        return redirect(f"/dashboard?barcode={barcode}")

    barcode_search = request.args.get("barcode")

    student_limits = None

    if barcode_search:

        cur.execute(
            "SELECT * FROM students WHERE barcode=%s",
            (barcode_search,)
        )

        student_limits = cur.fetchone()

    cur.execute(
        """
        SELECT *
        FROM entries
        ORDER BY created_at DESC
        LIMIT 50
        """
    )

    entries = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "dashboard.html",
        entries=entries,
        student_limits=student_limits
    )


# =====================================================
# CHAIRMAN
# =====================================================


@app.route("/chairman")
@role_required("chairman")
def chairman():

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM users WHERE role='secretary' ORDER BY name"
    )

    secretaries = cur.fetchall()

    cur.execute(
        "SELECT * FROM schedules ORDER BY work_date DESC"
    )

    schedules = cur.fetchall()

    cur.execute("SELECT COUNT(*) FROM students")
    students_count = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) FROM entries")
    entries_count = cur.fetchone()["count"]

    cur.execute(
        """
        SELECT *
        FROM entries
        ORDER BY created_at DESC
        LIMIT 30
        """
    )

    entries = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "chairman.html",
        secretaries=secretaries,
        schedules=schedules,
        students_count=students_count,
        entries_count=entries_count,
        entries=entries
    )


# =====================================================
# ADD SECRETARY
# =====================================================


@app.route("/add_secretary", methods=["POST"])
@role_required("chairman")
def add_secretary():

    name = request.form.get("name")
    password = request.form.get("password")

    conn = get_db()
    cur = conn.cursor()

    try:

        cur.execute(
            """
            INSERT INTO users (name, password, role)
            VALUES (%s, %s, %s)
            """,
            (
                name,
                generate_password_hash(password),
                "secretary"
            )
        )

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
# ADD STUDENT
# =====================================================


@app.route("/add_student", methods=["POST"])
@role_required("chairman")
def add_student():

    barcode = request.form.get("barcode")
    full_name = request.form.get("full_name")

    conn = get_db()
    cur = conn.cursor()

    try:

        cur.execute(
            """
            INSERT INTO students (barcode, full_name)
            VALUES (%s, %s)
            """,
            (barcode, full_name)
        )

        conn.commit()

        flash("Студент добавлен")

    except Exception as e:
        flash(f"Ошибка: {e}")

    cur.close()
    conn.close()

    return redirect("/chairman")


# =====================================================
# UPLOAD STUDENTS
# =====================================================


@app.route("/upload_students", methods=["POST"])
@role_required("chairman")
def upload_students():

    file = request.files.get("file")

    if not file:
        flash("Файл не выбран")
        return redirect("/chairman")

    try:

        if file.filename.endswith(".xlsx"):
            df = pd.read_excel(file)
        else:
            df = pd.read_csv(file)

        conn = get_db()
        cur = conn.cursor()

        for _, row in df.iterrows():

            cur.execute(
                """
                INSERT INTO students (barcode, full_name)
                VALUES (%s, %s)
                ON CONFLICT (barcode) DO NOTHING
                """,
                (
                    str(row["barcode"]),
                    str(row["full_name"])
                )
            )

        conn.commit()

        cur.close()
        conn.close()

        flash("Студенты загружены")

    except Exception as e:
        flash(f"Ошибка: {e}")

    return redirect("/chairman")


# =====================================================
# SCHEDULE
# =====================================================


@app.route("/add_schedule", methods=["POST"])
@role_required("chairman")
def add_schedule():

    secretary_name = request.form.get("secretary_name")
    work_date = request.form.get("work_date")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO schedules (
            secretary_name,
            work_date,
            start_time,
            end_time
        )
        VALUES (%s,%s,%s,%s)
        """,
        (
            secretary_name,
            work_date,
            start_time,
            end_time
        )
    )

    conn.commit()

    cur.close()
    conn.close()

    flash("Расписание добавлено")

    return redirect("/chairman")


# =====================================================
# EXPORT EXCEL
# =====================================================


@app.route("/export_excel")
@role_required("chairman")
def export_excel():

    conn = get_db()

    df = pd.read_sql("SELECT * FROM entries", conn)

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)

    output.seek(0)

    return send_file(
        output,
        download_name="report.xlsx",
        as_attachment=True
    )


# =====================================================
# START
# =====================================================


init_db()


if __name__ == "__main__":
    app.run(debug=True)
