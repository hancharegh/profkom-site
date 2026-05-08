import os

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    flash
)

import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps


# =====================================================
# FLASK
# =====================================================

app = Flask(__name__)
app.secret_key = "super_secret_key_2026"


# =====================================================
# DATABASE
# =====================================================

DATABASE_URL = os.environ.get("DATABASE_URL")


import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")
print(DATABASE_URL)

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
        username TEXT UNIQUE NOT NULL,
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

    # CREATE CHAIRMAN
    cur.execute(
        "SELECT * FROM users WHERE username=%s",
        ("chairman",)
    )

    chairman = cur.fetchone()

    if not chairman:

        cur.execute("""
        INSERT INTO users (username, password, role)
        VALUES (%s, %s, %s)
        """, (
            "chairman",
            generate_password_hash("1234"),
            "chairman"
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
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM users WHERE username=%s AND password=%s",
            (username, password)
        )

        user = cur.fetchone()

        cur.close()
        conn.close()

        if user:
            session["user"] = username
            return redirect("/dashboard")

        return "Неверный логин или пароль", 400

    return render_template("login.html")


# =====================================================
# LOGOUT
# =====================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# =====================================================
# SECRETARY DASHBOARD
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

        print_count = int(request.form.get("print_count", 0))
        copy_count = int(request.form.get("copy_count", 0))
        ruler_count = int(request.form.get("ruler_count", 0))
        notebook_count = int(request.form.get("notebook_count", 0))
        corrector_count = int(request.form.get("corrector_count", 0))
        pencil_count = int(request.form.get("pencil_count", 0))
        eraser_sharpener_count = int(request.form.get("eraser_sharpener_count", 0))
        millimeter_count = int(request.form.get("millimeter_count", 0))

        # LIMITS
        if print_count > 30:
            flash("Максимум 30 печати")
            return redirect("/dashboard")

        if copy_count > 30:
            flash("Максимум 30 копий")
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
            ruler_count,
            notebook_count,
            corrector_count,
            pencil_count,
            eraser_sharpener_count,
            millimeter_count
        ))

        conn.commit()

        flash("Запись успешно добавлена")

        return redirect("/dashboard")

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
        entries=entries
    )


# =====================================================
# CHAIRMAN PANEL
# =====================================================

@app.route("/chairman")
@role_required("chairman")
def chairman():

    conn = get_db()
    cur = conn.cursor()

    # SECRETARIES
    cur.execute("""
    SELECT *
    FROM users
    WHERE role='secretary'
    ORDER BY username
    """)

    secretaries = cur.fetchall()

    # STUDENTS COUNT
    cur.execute("SELECT COUNT(*) FROM students")
    students_count = cur.fetchone()["count"]

    # ENTRIES COUNT
    cur.execute("SELECT COUNT(*) FROM entries")
    entries_count = cur.fetchone()["count"]

    # LAST ENTRIES
    cur.execute("""
    SELECT *
    FROM entries
    ORDER BY created_at DESC
    LIMIT 30
    """)

    entries = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "chairman.html",
        secretaries=secretaries,
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

    username = request.form["username"]
    password = request.form["password"]

    conn = get_db()
    cur = conn.cursor()

    try:

        cur.execute("""
        INSERT INTO users (username, password, role)
        VALUES (%s, %s, %s)
        """, (
            username,
            generate_password_hash(password),
            "secretary"
        ))

        conn.commit()

        flash("Секретарь добавлен")

    except:
        flash("Ошибка добавления")

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

    barcode = request.form["barcode"]
    full_name = request.form["full_name"]

    conn = get_db()
    cur = conn.cursor()

    try:

        cur.execute("""
        INSERT INTO students (barcode, full_name)
        VALUES (%s, %s)
        """, (
            barcode,
            full_name
        ))

        conn.commit()

        flash("Студент добавлен")

    except:
        flash("Ошибка добавления")

    cur.close()
    conn.close()

    return redirect("/chairman")


# =====================================================
# START
# =====================================================

init_db()

if __name__ == "__main__":
    app.run(debug=True)
