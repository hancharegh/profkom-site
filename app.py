from flask import Flask, render_template, request, redirect, session, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse
import csv
import os
from io import BytesIO

from openpyxl import Workbook

# =====================================================
# FLASK
# =====================================================

app = Flask(__name__)

app.secret_key = "super_secret_key"

UPLOAD_FOLDER = "uploads"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


conn = psycopg2.connect(
    DATABASE_URL,
    sslmode="require",
    cursor_factory=RealDictCursor
)
DATABASE_URL = os.environ.get("DATABASE_URL")

print(DATABASE_URL)

# =====================================================
# LIMITS
# =====================================================

limits = {
    "Печать": 30,
    "Копия": 30,
    "Миллиметровка": 50,
    "Карандаш": 1,
    "Точилка / Ластик": 1,
    "Линейка": 1,
    "Корректор": 1,
    "Тетрадь 48 листов": 1
}

# =====================================================
# DATABASE
# =====================================================

def get_db():
    result = urlparse(DATABASE_URL)

    conn = psycopg2.connect(
        host=result.hostname,
        port=result.port,
        user=result.username,
        password=result.password,
        dbname=result.path[1:],
        sslmode="require",
        cursor_factory=RealDictCursor
    )

    return conn

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

        id TEXT PRIMARY KEY,

        name TEXT NOT NULL

    )
    """)

    # ENTRIES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS entries (

        id SERIAL PRIMARY KEY,

        student_id TEXT,

        student_name TEXT,

        secretary TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

    )
    """)

    # ENTRY ITEMS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS entry_items (

        id SERIAL PRIMARY KEY,

        entry_id INTEGER,

        item_name TEXT,

        quantity INTEGER

    )
    """)

    # HISTORY
    cur.execute("""
    CREATE TABLE IF NOT EXISTS history (

        id SERIAL PRIMARY KEY,

        action TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

    )
    """)

    # DUTY
    cur.execute("""
    CREATE TABLE IF NOT EXISTS duty_schedule (

        day TEXT PRIMARY KEY,

        secretary TEXT

    )
    """)

    conn.commit()

    # ADMIN
    cur.execute("""
    SELECT * FROM users
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

            "Председатель",

            generate_password_hash("admin123"),

            "chairman"

        ))

        conn.commit()

    conn.close()

# =====================================================
# DECORATORS
# =====================================================

def chairman_required(func):

    def wrapper(*args, **kwargs):

        if "user" not in session:
            return redirect("/")

        if session["role"] != "chairman":
            return redirect("/dashboard")

        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__

    return wrapper

# =====================================================
# LOGIN
# =====================================================

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

        conn.close()

        if not user:
            return render_template(
                "login.html",
                error="Неверный логин"
            )

        if not check_password_hash(
            user["password"],
            password
        ):
            return render_template(
                "login.html",
                error="Неверный пароль"
            )

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
def dashboard():

    if "user" not in session:
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    message = ""

    if request.method == "POST":

        student_id = request.form["barcode"]

        cur.execute("""
        SELECT *
        FROM students
        WHERE id=%s
        """, (student_id,))

        student = cur.fetchone()

        if not student:
            return "Студент не найден"

        quantities = {}

        for item in limits:

            qty = int(
                request.form.get(item, 0)
            )

            if qty > 0:
                quantities[item] = qty

        # LIMITS
        for item, qty in quantities.items():

            cur.execute("""
            SELECT COALESCE(
                SUM(entry_items.quantity),
                0
            ) AS total

            FROM entry_items

            JOIN entries
            ON entries.id = entry_items.entry_id

            WHERE entries.student_id=%s
            AND entry_items.item_name=%s
            """, (

                student_id,
                item

            ))

            used = cur.fetchone()["total"]

            if used + qty > limits[item]:

                conn.close()

                return f"""
                Превышен лимит:
                {item}
                """

        # ENTRY
        cur.execute("""
        INSERT INTO entries (

            student_id,
            student_name,
            secretary

        )
        VALUES (%s, %s, %s)

        RETURNING id
        """, (

            student["id"],
            student["name"],
            session["user"]

        ))

        entry_id = cur.fetchone()["id"]

        for item, qty in quantities.items():

            cur.execute("""
            INSERT INTO entry_items (

                entry_id,
                item_name,
                quantity

            )
            VALUES (%s, %s, %s)
            """, (

                entry_id,
                item,
                qty

            ))

        cur.execute("""
        INSERT INTO history (
            action
        )
        VALUES (%s)
        """, (

            f"{session['user']} выдал канцелярию студенту {student['name']}",

        ))

        conn.commit()

        message = "Запись добавлена"

    # ENTRIES
    cur.execute("""
    SELECT *
    FROM entries
    ORDER BY created_at DESC
    LIMIT 30
    """)

    entries = cur.fetchall()

    conn.close()

    return render_template(

        "dashboard.html",

        limits=limits,

        entries=entries,

        message=message

    )

# =====================================================
# AJAX STUDENT
# =====================================================

@app.route("/check_student")
def check_student():

    barcode = request.args.get("barcode")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    SELECT *
    FROM students
    WHERE id=%s
    """, (barcode,))

    student = cur.fetchone()

    conn.close()

    if not student:
        return jsonify({
            "found": False
        })

    return jsonify({

        "found": True,

        "name": student["name"]

    })

# =====================================================
# CHAIRMAN
# =====================================================

@app.route("/chairman")
@chairman_required
def chairman():

    conn = get_db()
    cur = conn.cursor()

    # TOTAL ENTRIES
    cur.execute("""
    SELECT COUNT(*) AS total
    FROM entries
    """)

    total_entries = cur.fetchone()["total"]

    # TOTAL STUDENTS
    cur.execute("""
    SELECT COUNT(*) AS total
    FROM students
    """)

    total_students = cur.fetchone()["total"]

    # ITEMS
    cur.execute("""
    SELECT

        item_name,

        SUM(quantity) AS total

    FROM entry_items

    GROUP BY item_name

    ORDER BY total DESC
    """)

    items = cur.fetchall()

    total_items = sum(
        item["total"]
        for item in items
    )

    conn.close()

    return render_template(

        "chairman.html",

        total_entries=total_entries,

        total_students=total_students,

        total_items=total_items,

        items=items

    )

# =====================================================
# SECRETARIES
# =====================================================

@app.route("/secretaries")
@chairman_required
def secretaries():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    SELECT *
    FROM users
    WHERE role='secretary'
    ORDER BY name
    """)

    users = cur.fetchall()

    cur.execute("""
    SELECT *
    FROM duty_schedule
    """)

    schedule = cur.fetchall()

    conn.close()

    days = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница"
    ]

    return render_template(

        "secretaries.html",

        users=users,

        schedule=schedule,

        days=days

    )

# =====================================================
# ADD SECRETARY
# =====================================================

@app.route("/add_secretary", methods=["POST"])
@chairman_required
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

    except:
        conn.close()
        return "Пользователь уже существует"

    conn.close()

    return redirect("/secretaries")

# =====================================================
# DELETE SECRETARY
# =====================================================

@app.route("/delete_secretary/<int:user_id>")
@chairman_required
def delete_secretary(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    DELETE FROM users
    WHERE id=%s
    """, (user_id,))

    conn.commit()

    conn.close()

    return redirect("/secretaries")

# =====================================================
# CHANGE PASSWORD
# =====================================================

@app.route("/change_password/<int:user_id>", methods=["POST"])
@chairman_required
def change_password(user_id):

    password = request.form["password"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    UPDATE users
    SET password=%s
    WHERE id=%s
    """, (

        generate_password_hash(password),

        user_id

    ))

    conn.commit()

    conn.close()

    return redirect("/secretaries")

# =====================================================
# UPDATE DUTY
# =====================================================

@app.route("/update_duty", methods=["POST"])
@chairman_required
def update_duty():

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
        INSERT INTO duty_schedule (

            day,
            secretary

        )
        VALUES (%s, %s)

        ON CONFLICT (day)

        DO UPDATE SET
        secretary = EXCLUDED.secretary
        """, (

            day,
            secretary

        ))

    conn.commit()

    conn.close()

    return redirect("/secretaries")

# =====================================================
# IMPORT CSV
# =====================================================

@app.route("/import_students", methods=["POST"])
@chairman_required
def import_students():

    file = request.files["file"]

    content = file.read().decode("utf-8-sig")

    lines = content.splitlines()

    delimiter = ","

    if ";" in lines[0]:
        delimiter = ";"

    reader = csv.DictReader(
        lines,
        delimiter=delimiter
    )

    columns = reader.fieldnames

    id_column = None
    name_column = None

    for col in columns:

        low = col.lower()

        if (
            "id" in low
            or "barcode" in low
            or "баркод" in low
        ):
            id_column = col

        if (
            "фио" in low
            or "name" in low
            or "фам" in low
        ):
            name_column = col

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    DELETE FROM students
    """)

    imported = 0

    for row in reader:

        student_id = row[id_column].strip()

        name = row[name_column].strip()

        if not student_id or not name:
            continue

        cur.execute("""
        INSERT INTO students (

            id,
            name

        )
        VALUES (%s, %s)
        """, (

            student_id,
            name

        ))

        imported += 1

    conn.commit()

    conn.close()

    return f"""
    Импортировано:
    {imported}

    <br><br>

    <a href='/chairman'>
        Назад
    </a>
    """

# =====================================================
# EXPORT EXCEL
# =====================================================

@app.route("/export_excel")
@chairman_required
def export_excel():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    SELECT *
    FROM entries
    ORDER BY created_at DESC
    """)

    entries = cur.fetchall()

    wb = Workbook()

    ws = wb.active

    ws.title = "Отчет"

    ws.append([
        "Студент",
        "ID",
        "Секретарь",
        "Дата"
    ])

    for entry in entries:

        ws.append([

            entry["student_name"],

            entry["student_id"],

            entry["secretary"],

            str(entry["created_at"])

        ])

    file = BytesIO()

    wb.save(file)

    file.seek(0)

    conn.close()

    return send_file(

        file,

        as_attachment=True,

        download_name="report.xlsx",

        mimetype="""
        application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
        """

    )

# =====================================================
# START
# =====================================================
init_db()
if __name__ == "__main__":

    os.makedirs(
        "uploads",
        exist_ok=True
    )

    

    app.run(debug=True)
