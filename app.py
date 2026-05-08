from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    jsonify,
    send_file
)
from werkzeug.utils import secure_filename
from functools import wraps
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from openpyxl import Workbook

import sqlite3
import csv
import io
import os


# =====================================
# APP
# =====================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "fallback-secret"
)
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# =====================================
# DATABASE
# =====================================

def get_db():

    conn = sqlite3.connect("database.db")

    conn.row_factory = sqlite3.Row

    return conn


# =====================================
# INIT DB
# =====================================

def init_db():

    conn = get_db()

    cur = conn.cursor()

    # USERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        name TEXT UNIQUE,

        password TEXT,

        role TEXT
    )
    """)

    # STUDENTS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (

        id TEXT PRIMARY KEY,

        name TEXT
    )
    """)

    # ENTRIES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS entries (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        student_id TEXT,

        student_name TEXT,

        secretary TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ENTRY ITEMS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS entry_items (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        entry_id INTEGER,

        item TEXT,

        quantity INTEGER
    )
    """)

    conn.commit()

    conn.close()


# =====================================
# LOAD USERS CSV
# =====================================

def load_users_from_csv():

    conn = get_db()

    cur = conn.cursor()

    try:

        with open(
            "users.csv",
            encoding="utf-8"
        ) as f:

            reader = csv.DictReader(f)

            for row in reader:

                # Проверяем существование
                cur.execute("""
                SELECT * FROM users
                WHERE name=?
                """, (row["name"],))

                existing = cur.fetchone()

                if not existing:

                    hashed_password = generate_password_hash(
                        row["password"]
                    )

                    cur.execute("""
                    INSERT INTO users (
                        name,
                        password,
                        role
                    )
                    VALUES (?, ?, ?)
                    """, (
                        row["name"],
                        hashed_password,
                        row["role"]
                    ))

    except:
        pass

    conn.commit()

    conn.close()


# =====================================
# LOAD STUDENTS CSV
# =====================================

def load_students_from_csv():

    conn = get_db()

    cur = conn.cursor()

    try:

        with open(
            "students.csv",
            encoding="utf-8"
        ) as f:

            reader = csv.DictReader(f)

            for row in reader:

                cur.execute("""
                INSERT OR IGNORE INTO students (
                    id,
                    name
                )
                VALUES (?, ?)
                """, (
                    row["id"],
                    row["name"]
                ))

    except:
        pass

    conn.commit()

    conn.close()


# =====================================
# LIMITS
# =====================================

limits = {

    "Печать": 30,

    "Копия": 30,

    "Миллиметровка": 50,

    "Карандаш": 1,

    "Ластик/Точилка": 1,

    "Линейка": 1,

    "Корректор": 1,

    "Тетрадь 48 листов": 1
}


# =====================================
# DECORATORS
# =====================================

def login_required(f):

    @wraps(f)
    def wrapper(*args, **kwargs):

        if "user" not in session:
            return redirect("/")

        return f(*args, **kwargs)

    return wrapper


def chairman_required(f):

    @wraps(f)
    def wrapper(*args, **kwargs):

        if "user" not in session:
            return redirect("/")

        if session.get("role") != "chairman":
            return redirect("/dashboard")

        return f(*args, **kwargs)

    return wrapper


# =====================================
# CALCULATE USAGE
# =====================================

def calculate_usage(student_id):

    usage = {
        item: 0 for item in limits
    }

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
    SELECT
        item,
        SUM(quantity)

    FROM entry_items

    JOIN entries
    ON entries.id = entry_items.entry_id

    WHERE entries.student_id = ?

    GROUP BY item
    """, (student_id,))

    rows = cur.fetchall()

    conn.close()

    for row in rows:

        usage[row[0]] = row[1]

    return usage


# =====================================
# LOGIN
# =====================================

@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        name = request.form["name"]

        password = request.form["password"]

        conn = get_db()

        cur = conn.cursor()

        cur.execute("""
        SELECT * FROM users
        WHERE name=?
        """, (name,))

        user = cur.fetchone()

        conn.close()

        if user and check_password_hash(
            user["password"],
            password
        ):

            session["user"] = user["name"]

            session["role"] = user["role"]

            return redirect("/dashboard")

        return render_template(
            "login.html",
            error="Неверный логин или пароль"
        )

    return render_template("login.html")


# =====================================
# LOGOUT
# =====================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# =====================================
# CHECK STUDENT AJAX
# =====================================

@app.route("/check_student", methods=["POST"])
@login_required
def check_student():

    data = request.get_json()

    student_id = data["id"]

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
    SELECT * FROM students
    WHERE id=?
    """, (student_id,))

    student = cur.fetchone()

    conn.close()

    if not student:

        return jsonify({
            "error": "Студент не найден"
        })

    usage = calculate_usage(student_id)

    remaining = {}

    for item in limits:

        remaining[item] = (
            limits[item] - usage.get(item, 0)
        )

    return jsonify({

        "name": student["name"],

        "remaining": remaining
    })


# =====================================
# DASHBOARD
# =====================================

@app.route(
    "/dashboard",
    methods=["GET", "POST"]
)
@login_required
def dashboard():

    if session.get("role") == "chairman":
        return redirect("/chairman")

    conn = get_db()

    cur = conn.cursor()

    # ADD ENTRY
    if request.method == "POST":

        student_id = request.form["barcode"]

        cur.execute("""
        SELECT * FROM students
        WHERE id=?
        """, (student_id,))

        student = cur.fetchone()

        if not student:

            conn.close()

            return "Студент не найден"

        usage = calculate_usage(student_id)

        quantities = {}

        for item in limits:

            qty = int(
                request.form.get(item, 0)
            )

            if qty > 0:

                if (
                    usage[item] + qty
                    > limits[item]
                ):

                    conn.close()

                    return f"Превышен лимит: {item}"

                quantities[item] = qty

        # CREATE ENTRY
        cur.execute("""
        INSERT INTO entries (

            student_id,

            student_name,

            secretary

        )
        VALUES (?, ?, ?)
        """, (

            student_id,

            student["name"],

            session["user"]
        ))

        entry_id = cur.lastrowid

        # ITEMS
        for item, qty in quantities.items():

            cur.execute("""
            INSERT INTO entry_items (

                entry_id,

                item,

                quantity

            )
            VALUES (?, ?, ?)
            """, (

                entry_id,

                item,

                qty
            ))

        conn.commit()

        return redirect("/dashboard")

    # HISTORY
    cur.execute("""
    SELECT

        e.id,

        e.student_name,

        e.student_id,

        e.secretary,

        e.created_at,

        GROUP_CONCAT(
            i.item || ' x' || i.quantity
        )

    FROM entries e

    LEFT JOIN entry_items i
    ON e.id = i.entry_id

    GROUP BY e.id

    ORDER BY e.id DESC
    """)

    entries = cur.fetchall()

    conn.close()

    return render_template(

        "dashboard.html",

        entries=entries,

        limits=limits
    )


# =====================================
# DELETE ENTRY
# =====================================

@app.route("/delete_entry/<int:id>")
@login_required
def delete_entry(id):

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
    DELETE FROM entry_items
    WHERE entry_id=?
    """, (id,))

    cur.execute("""
    DELETE FROM entries
    WHERE id=?
    """, (id,))

    conn.commit()

    conn.close()

    return redirect("/dashboard")


# =====================================
# CHAIRMAN
# =====================================

@app.route("/chairman")
@chairman_required
def chairman():

    conn = get_db()

    cur = conn.cursor()

    # KPI
    cur.execute("""
    SELECT COUNT(*)
    FROM entries
    """)

    total_entries = cur.fetchone()[0]

    cur.execute("""
    SELECT COUNT(DISTINCT student_id)
    FROM entries
    """)

    total_students = cur.fetchone()[0]

    cur.execute("""
    SELECT SUM(quantity)
    FROM entry_items
    """)

    total_items = cur.fetchone()[0] or 0

    # ITEMS STATS
    cur.execute("""
    SELECT
        item,
        SUM(quantity)

    FROM entry_items

    GROUP BY item
    """)

    items = cur.fetchall()

    conn.close()

    return render_template(

        "chairman.html",

        total_entries=total_entries,

        total_students=total_students,

        total_items=total_items,

        items=items
    )


# =====================================
# STUDENTS PAGE
# =====================================

@app.route("/students")
@chairman_required
def students_page():

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
    SELECT * FROM students
    ORDER BY name
    """)

    students = cur.fetchall()

    conn.close()

    return render_template(
        "students.html",
        students=students
    )


# =====================================
# ADD STUDENT
# =====================================

@app.route(
    "/add_student",
    methods=["POST"]
)
@chairman_required
def add_student():

    student_id = request.form["student_id"]

    name = request.form["name"]

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
    INSERT OR REPLACE INTO students (

        id,

        name

    )
    VALUES (?, ?)
    """, (

        student_id,

        name
    ))

    conn.commit()

    conn.close()

    return redirect("/students")


# =====================================
# DELETE STUDENT
# =====================================

@app.route("/delete_student/<student_id>")
@chairman_required
def delete_student(student_id):

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
    DELETE FROM students
    WHERE id=?
    """, (student_id,))

    conn.commit()

    conn.close()

    return redirect("/students")


# =====================================
# EXPORT EXCEL
# =====================================

@app.route("/export_excel")
@chairman_required
def export_excel():

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
    SELECT

        e.student_name,

        e.student_id,

        e.secretary,

        e.created_at,

        GROUP_CONCAT(
            i.item || ' x' || i.quantity
        )

    FROM entries e

    LEFT JOIN entry_items i
    ON e.id = i.entry_id

    GROUP BY e.id
    """)

    data = cur.fetchall()

    conn.close()

    wb = Workbook()

    ws = wb.active

    ws.title = "Отчёт"

    ws.append([

        "Студент",

        "ID",

        "Секретарь",

        "Дата",

        "Выдано"
    ])

    for row in data:

        ws.append(row)

    stream = io.BytesIO()

    wb.save(stream)

    stream.seek(0)

    return send_file(

        stream,

        download_name="report.xlsx",

        as_attachment=True
    )

# =====================================
# СЕКРЕТАРИ (CRUD)
# =====================================

@app.route("/secretaries")
@chairman_required
def secretaries():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, name
    FROM users
    WHERE role='secretary'
    ORDER BY name
    """)

    users = cur.fetchall()

    conn.close()

    return render_template(
        "secretaries.html",
        users=users
    )

# ДОБАВИТЬ
@app.route("/add_secretary", methods=["POST"])
@chairman_required
def add_secretary():

    name = request.form["name"]
    password = request.form["password"]

    hashed = generate_password_hash(password)

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("""
        INSERT INTO users (name, password, role)
        VALUES (?, ?, 'secretary')
        """, (name, hashed))

        conn.commit()

    except:
        conn.close()
        return "Пользователь уже существует"

    conn.close()

    return redirect("/secretaries")

# УДАЛИТЬ
@app.route("/delete_secretary/<int:user_id>")
@chairman_required
def delete_secretary(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    DELETE FROM users
    WHERE id=? AND role='secretary'
    """, (user_id,))

    conn.commit()
    conn.close()

    return redirect("/secretaries")

# СМЕНА ПАРОЛЯ
@app.route("/change_password/<int:user_id>", methods=["POST"])
@chairman_required
def change_password(user_id):

    new_password = request.form["password"]

    hashed = generate_password_hash(new_password)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    UPDATE users
    SET password=?
    WHERE id=? AND role='secretary'
    """, (hashed, user_id))

    conn.commit()
    conn.close()

    return redirect("/secretaries")
# =====================================
# START
# =====================================

# =====================================
# IMPORT STUDENTS CSV
# =====================================

@app.route("/import_students", methods=["POST"])
@chairman_required
def import_students():

    try:

        if "file" not in request.files:
            return "Файл не найден"

        file = request.files["file"]

        if file.filename == "":
            return "Файл не выбран"

        conn = get_db()
        cur = conn.cursor()

        # ОЧИЩАЕМ СТАРЫХ СТУДЕНТОВ
        cur.execute("""
        DELETE FROM students
        """)

        imported = 0

        # UTF-8 + BOM FIX
        content = file.read().decode(
            "utf-8-sig"
        )

        lines = content.splitlines()

        # АВТООПРЕДЕЛЕНИЕ РАЗДЕЛИТЕЛЯ
        delimiter = ","

        if ";" in lines[0]:
            delimiter = ";"

        reader = csv.DictReader(
            lines,
            delimiter=delimiter
        )

        # ИЩЕМ КОЛОНКИ
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
                "name" in low
                or "фио" in low
                or "фам" in low
            ):
                name_column = col

        if not id_column or not name_column:

            return f"""
            Не найдены колонки.

            Найдены:
            {columns}
            """

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
            VALUES (?, ?)
            """, (
                student_id,
                name
            ))

            imported += 1

        conn.commit()
        conn.close()

        return f"""
        Импортировано студентов: {imported}

        

        <a href="/chairman">
            Назад
        </a>
        """

    except Exception as e:

        return f"""
        Ошибка импорта:

        

        {str(e)}
        """



if __name__ == "__main__":

    init_db()

    load_users_from_csv()

    load_students_from_csv()

    app.run()
