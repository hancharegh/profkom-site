import os
from io import BytesIO
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
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


# ======================================================
# FLASK
# ======================================================

app = Flask(__name__)
app.secret_key = "secret123"


# ======================================================
# DATABASE
# ======================================================

DATABASE_URL = os.getenv("DATABASE_URL")


def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        cursor_factory=RealDictCursor
    )


# ======================================================
# ЛИМИТЫ
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

ALLOWED_FIELDS = set(FIELD_MAP.values())

# Человекочитаемые названия ролей
ROLE_LABELS = {
    "chairman":      "Председатель",
    "vice_chairman": "Зам. председателя",
    "secretary":     "Секретарь",
    "bureau":        "Профбюро",
}

# Куда редиректить после выбора роли
ROLE_REDIRECTS = {
    "chairman":      "/chairman",
    "vice_chairman": "/vice_chairman",
    "secretary":     "/dashboard",
    "bureau":        "/bureau",
}


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


def role_required(*roles):

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                return redirect("/")
            if session.get("role") not in roles:
                return redirect("/")
            return func(*args, **kwargs)

        return wrapper

    return decorator


# ======================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С РОЛЯМИ
# ======================================================

def get_user_roles(user):
    """
    Возвращает список ролей пользователя.
    Поддерживает как старый формат (role TEXT),
    так и новый (roles TEXT[]).
    """
    # Новый формат — массив ролей
    roles_raw = user.get("roles")
    if roles_raw:
        if isinstance(roles_raw, list):
            return roles_raw
        # psycopg2 может вернуть строку вида {secretary,bureau}
        if isinstance(roles_raw, str):
            return [r.strip() for r in roles_raw.strip("{}").split(",") if r.strip()]

    # Старый формат — одиночная роль
    role = user.get("role")
    if role:
        return [role]

    return ["secretary"]


def get_user_bureau_for_role(user, role):
    """
    Возвращает номер бюро для роли bureau.
    Поддерживает как старый (bureau INTEGER),
    так и новый формат (bureaus JSONB: {"bureau": [3, 5]}).
    """
    if role != "bureau":
        return None

    # Новый формат — словарь бюро по ролям
    bureaus_raw = user.get("bureaus")
    if bureaus_raw:
        if isinstance(bureaus_raw, dict):
            return bureaus_raw.get("bureau", [None])[0]
        if isinstance(bureaus_raw, str):
            import json
            try:
                d = json.loads(bureaus_raw)
                return d.get("bureau", [None])[0]
            except Exception:
                pass

    # Старый формат — одно поле bureau
    return user.get("bureau")


# ======================================================
# ГЕНЕРАЦИЯ ID СТУДЕНТА
# ======================================================

def generate_student_id(cur, bureau: int) -> str:

    cur.execute("""
        SELECT student_id FROM students
        WHERE bureau = %s
        ORDER BY student_id
    """, (bureau,))

    rows = cur.fetchall()
    existing = set()

    for row in rows:
        sid = row["student_id"]
        try:
            seq = int(sid[1:])
            existing.add(seq)
        except (ValueError, IndexError):
            pass

    seq = 1
    while seq in existing:
        seq += 1

    return f"{bureau}{seq:03d}"


# ======================================================
# INIT DB
# ======================================================

def init_db():

    conn = get_db()
    cur  = conn.cursor()

    # Таблица users с поддержкой массива ролей
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id       SERIAL PRIMARY KEY,
        name     TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        roles    TEXT[]  NOT NULL DEFAULT ARRAY['secretary'],
        bureaus  JSONB   DEFAULT NULL,
        -- Старые поля оставляем для совместимости при миграции
        role     TEXT    DEFAULT NULL,
        bureau   INTEGER DEFAULT NULL
    )
    """)

    # Добавляем новые колонки если таблица уже существует
    for col, definition in [
        ("roles",   "TEXT[] DEFAULT ARRAY['secretary']"),
        ("bureaus", "JSONB DEFAULT NULL"),
    ]:
        cur.execute(f"""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS {col} {definition}
        """)

    # Мигрируем старые записи: переносим role → roles, bureau → bureaus
    cur.execute("""
        UPDATE users
        SET roles = ARRAY[role]
        WHERE role IS NOT NULL
          AND (roles IS NULL OR roles = ARRAY['secretary'])
          AND role != 'secretary'
    """)

    cur.execute("""
        UPDATE users
        SET roles = ARRAY[role]
        WHERE role IS NOT NULL
          AND roles IS NULL
    """)

    # Мигрируем bureau → bureaus для роли bureau
    cur.execute("""
        UPDATE users
        SET bureaus = jsonb_build_object('bureau', jsonb_build_array(bureau))
        WHERE bureau IS NOT NULL
          AND bureaus IS NULL
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id                     SERIAL PRIMARY KEY,
        student_id             TEXT UNIQUE NOT NULL,
        full_name              TEXT NOT NULL,
        bureau                 INTEGER NOT NULL,
        print_count            INTEGER DEFAULT 0,
        copy_count             INTEGER DEFAULT 0,
        notebook_count         INTEGER DEFAULT 0,
        ruler_count            INTEGER DEFAULT 0,
        corrector_count        INTEGER DEFAULT 0,
        pencil_count           INTEGER DEFAULT 0,
        eraser_sharpener_count INTEGER DEFAULT 0,
        millimeter_count       INTEGER DEFAULT 0,
        limit_month            INTEGER DEFAULT NULL,
        limit_year             INTEGER DEFAULT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS entries (
        id                     SERIAL PRIMARY KEY,
        student_id             TEXT,
        student_name           TEXT,
        secretary              TEXT,
        action_text            TEXT,
        print_count            INTEGER DEFAULT 0,
        copy_count             INTEGER DEFAULT 0,
        notebook_count         INTEGER DEFAULT 0,
        ruler_count            INTEGER DEFAULT 0,
        corrector_count        INTEGER DEFAULT 0,
        pencil_count           INTEGER DEFAULT 0,
        eraser_sharpener_count INTEGER DEFAULT 0,
        millimeter_count       INTEGER DEFAULT 0,
        created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS schedule (
        id             SERIAL PRIMARY KEY,
        day_name       TEXT UNIQUE NOT NULL,
        secretary_name TEXT
    )
    """)

    for day in ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"]:
        cur.execute("SELECT * FROM schedule WHERE day_name = %s", (day,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO schedule (day_name, secretary_name) VALUES (%s, %s)",
                (day, "")
            )

    # Председатель по умолчанию
    cur.execute("SELECT * FROM users WHERE 'chairman' = ANY(roles)")
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO users (name, password, roles)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO NOTHING
        """, (
            "Курмаева Юлия Игоревна",
            generate_password_hash("1234"),
            ["chairman"]
        ))

    conn.commit()
    cur.close()
    conn.close()


# ======================================================
# ВСПОМОГАТЕЛЬНЫЕ ДАННЫЕ ДЛЯ ADMIN-ПАНЕЛЕЙ
# ======================================================

def get_admin_data():

    conn = get_db()
    cur  = conn.cursor()

    # Все пользователи кроме председателя
    cur.execute("""
        SELECT * FROM users
        WHERE NOT ('chairman' = ANY(roles))
        ORDER BY name
    """)
    secretaries = cur.fetchall()

    cur.execute("SELECT COUNT(*) as count FROM students")
    students_count = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) as count FROM entries")
    entries_count = cur.fetchone()["count"]

    cur.execute("SELECT * FROM entries ORDER BY created_at DESC LIMIT 50")
    entries = cur.fetchall()

    cur.execute("SELECT * FROM students ORDER BY bureau, student_id")
    students = cur.fetchall()

    cur.execute("SELECT * FROM schedule")
    schedule_rows = cur.fetchall()

    schedule = {
        "Понедельник": "",
        "Вторник":     "",
        "Среда":       "",
        "Четверг":     "",
        "Пятница":     ""
    }

    for row in schedule_rows:
        schedule[row["day_name"]] = row["secretary_name"]

    cur.close()
    conn.close()

    return dict(
        secretaries    = secretaries,
        students       = students,
        students_count = students_count,
        entries_count  = entries_count,
        entries        = entries,
        schedule       = schedule
    )


# ======================================================
# ОБЩАЯ ЛОГИКА ВЫДАЧИ
# ======================================================

def do_issue(student_id, counts, secretary_name):

    print_count            = int(counts.get("print_count")            or 0)
    copy_count             = int(counts.get("copy_count")             or 0)
    notebook_count         = int(counts.get("notebook_count")         or 0)
    ruler_count            = int(counts.get("ruler_count")            or 0)
    corrector_count        = int(counts.get("corrector_count")        or 0)
    pencil_count           = int(counts.get("pencil_count")           or 0)
    eraser_sharpener_count = int(counts.get("eraser_sharpener_count") or 0)
    millimeter_count       = int(counts.get("millimeter_count")       or 0)

    conn = get_db()
    cur  = conn.cursor()

    cur.execute("SELECT * FROM students WHERE student_id = %s", (student_id,))
    student = cur.fetchone()

    if not student:
        cur.close()
        conn.close()
        return jsonify(ok=False, error="Студент не найден")

    # Сброс лимитов при смене месяца
    current_month = datetime.now().month
    current_year  = datetime.now().year

    if (
        student.get("limit_month") != current_month
        or student.get("limit_year") != current_year
    ):
        cur.execute("""
            UPDATE students SET
                print_count            = 0,
                copy_count             = 0,
                notebook_count         = 0,
                ruler_count            = 0,
                corrector_count        = 0,
                pencil_count           = 0,
                eraser_sharpener_count = 0,
                millimeter_count       = 0,
                limit_month            = %s,
                limit_year             = %s
            WHERE student_id = %s
        """, (current_month, current_year, student_id))
        conn.commit()

        for field in [
            "print_count", "copy_count", "notebook_count", "ruler_count",
            "corrector_count", "pencil_count", "eraser_sharpener_count",
            "millimeter_count"
        ]:
            student[field] = 0

    used = {
        "prints":      student.get("print_count",            0),
        "copies":      student.get("copy_count",             0),
        "notebooks":   student.get("notebook_count",         0),
        "rulers":      student.get("ruler_count",            0),
        "correctors":  student.get("corrector_count",        0),
        "pencils":     student.get("pencil_count",           0),
        "erasers":     student.get("eraser_sharpener_count", 0),
        "millimeters": student.get("millimeter_count",       0)
    }

    checks = [
        (used["prints"]      + print_count            > LIMITS["prints"],      "Превышен лимит печати"),
        (used["copies"]      + copy_count             > LIMITS["copies"],      "Превышен лимит копий"),
        (used["notebooks"]   + notebook_count         > LIMITS["notebooks"],   "Тетрадь уже выдавалась"),
        (used["rulers"]      + ruler_count            > LIMITS["rulers"],      "Линейка уже выдавалась"),
        (used["correctors"]  + corrector_count        > LIMITS["correctors"],  "Корректор уже выдавался"),
        (used["pencils"]     + pencil_count           > LIMITS["pencils"],     "Карандаш уже выдавался"),
        (used["erasers"]     + eraser_sharpener_count > LIMITS["erasers"],     "Ластик/точилка уже выдавались"),
        (used["millimeters"] + millimeter_count       > LIMITS["millimeters"], "Превышен лимит миллиметровок"),
    ]

    for condition, msg in checks:
        if condition:
            cur.close()
            conn.close()
            return jsonify(ok=False, error=msg)

    cur.execute("""
        UPDATE students SET
            print_count            = print_count            + %s,
            copy_count             = copy_count             + %s,
            notebook_count         = notebook_count         + %s,
            ruler_count            = ruler_count            + %s,
            corrector_count        = corrector_count        + %s,
            pencil_count           = pencil_count           + %s,
            eraser_sharpener_count = eraser_sharpener_count + %s,
            millimeter_count       = millimeter_count       + %s
        WHERE student_id = %s
    """, (
        print_count, copy_count, notebook_count, ruler_count,
        corrector_count, pencil_count, eraser_sharpener_count,
        millimeter_count, student_id
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
            student_id, student_name, secretary, action_text,
            print_count, copy_count, notebook_count, ruler_count,
            corrector_count, pencil_count, eraser_sharpener_count,
            millimeter_count
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, created_at
    """, (
        student_id,
        student.get("full_name") or "Неизвестно",
        secretary_name,
        action_text,
        print_count, copy_count, notebook_count, ruler_count,
        corrector_count, pencil_count, eraser_sharpener_count,
        millimeter_count
    ))

    new_entry = cur.fetchone()
    conn.commit()

    messages_list = [
        "Выдача успешно сохранена",
        "🐯 Тигр успешно накормлен",
        "📚 Бумажная промышленность процветает",
        "⚡ Профком доволен вами",
        "🖨️ Печать пошла в бой",
        "🏆 +100 к уважению секретаря"
    ]

    message = (
        random.choice(messages_list)
        if random.randint(1, 10) == 1
        else "Выдача успешно сохранена"
    )

    cur.execute(
        "SELECT COUNT(*) as total FROM entries WHERE secretary = %s",
        (secretary_name,)
    )
    total_actions = cur.fetchone()["total"]

    achievement = None
    if total_actions == 100:
        achievement = "🏆 Достижение: 100 выдач!"
    elif total_actions == 500:
        achievement = "🐯 Легенда профкома!"
    elif total_actions == 1000:
        achievement = "👑 Верховный тигр!"

    # Юбилей — 10-я выдача студенту
    cur.execute(
        "SELECT COUNT(*) as cnt FROM entries WHERE student_id = %s",
        (student_id,)
    )
    student_total = cur.fetchone()["cnt"]

    if student_total == 10:
        name_short  = (student.get("full_name") or "Студент").split()[0]
        jubilee_msg = f"🎂 Тайная ачивка: Юбилей! {name_short} получает продукцию в 10-й раз!"
        achievement = (achievement + "||" + jubilee_msg) if achievement else jubilee_msg

    new_limits = {
        "prints":      LIMITS["prints"]      - (used["prints"]      + print_count),
        "copies":      LIMITS["copies"]      - (used["copies"]      + copy_count),
        "notebooks":   LIMITS["notebooks"]   - (used["notebooks"]   + notebook_count),
        "rulers":      LIMITS["rulers"]      - (used["rulers"]      + ruler_count),
        "correctors":  LIMITS["correctors"]  - (used["correctors"]  + corrector_count),
        "pencils":     LIMITS["pencils"]     - (used["pencils"]     + pencil_count),
        "erasers":     LIMITS["erasers"]     - (used["erasers"]     + eraser_sharpener_count),
        "millimeters": LIMITS["millimeters"] - (used["millimeters"] + millimeter_count)
    }

    cur.close()
    conn.close()

    return jsonify(
        ok          = True,
        message     = message,
        achievement = achievement,
        limits      = new_limits,
        entry       = {
            "id":           new_entry["id"],
            "student_name": student.get("full_name") or "Неизвестно",
            "secretary":    secretary_name,
            "student_id":   student_id,
            "action_text":  action_text,
            "created_at":   str(new_entry["created_at"])
        }
    )


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
        cur  = conn.cursor()
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

            roles = get_user_roles(user)

            # Сохраняем базовые данные сессии
            session["user"]  = user["name"]
            session["roles"] = roles
            session["uid"]   = user["id"]

            # Один человек — одна роль: сразу переходим
            if len(roles) == 1:
                return _apply_role(user, roles[0])

            # Несколько ролей — показываем выбор
            return redirect("/select_role")

        flash("Неверный пароль")

    return render_template("login.html")


def _apply_role(user, role):
    """Устанавливает роль в сессию и редиректит на нужную панель."""

    roles = get_user_roles(user)

    session["role"] = role

    if role == "bureau":
        # Определяем номер бюро для этой роли
        import json
        bureaus_raw = user.get("bureaus")
        bureau_num  = None

        if bureaus_raw:
            if isinstance(bureaus_raw, dict):
                nums = bureaus_raw.get("bureau", [])
                bureau_num = nums[0] if nums else None
            elif isinstance(bureaus_raw, str):
                try:
                    d = json.loads(bureaus_raw)
                    nums = d.get("bureau", [])
                    bureau_num = nums[0] if nums else None
                except Exception:
                    pass

        if bureau_num is None:
            bureau_num = user.get("bureau")

        session["bureau"] = bureau_num

    elif role in ("chairman", "vice_chairman", "secretary"):
        session["bureau"] = None

    return redirect(ROLE_REDIRECTS.get(role, "/dashboard"))


# ======================================================
# SELECT ROLE — экран выбора роли
# ======================================================

@app.route("/select_role", methods=["GET", "POST"])
def select_role():

    if "user" not in session:
        return redirect("/")

    if request.method == "POST":

        chosen_role = request.form.get("role")
        roles       = session.get("roles", [])

        if chosen_role not in roles:
            flash("Недопустимая роль")
            return redirect("/select_role")

        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT * FROM users WHERE name = %s", (session["user"],))
        user = cur.fetchone()
        cur.close()
        conn.close()

        return _apply_role(user, chosen_role)

    # GET — показываем страницу выбора
    roles = session.get("roles", [])

    # Собираем описания ролей для отображения
    role_options = []

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users WHERE name = %s", (session["user"],))
    user = cur.fetchone()
    cur.close()
    conn.close()

    import json

    for role in roles:
        label = ROLE_LABELS.get(role, role)
        extra = ""

        if role == "bureau":
            bureaus_raw = user.get("bureaus") if user else None
            if bureaus_raw:
                if isinstance(bureaus_raw, str):
                    try:
                        bureaus_raw = json.loads(bureaus_raw)
                    except Exception:
                        bureaus_raw = None
                if isinstance(bureaus_raw, dict):
                    nums = bureaus_raw.get("bureau", [])
                    if nums:
                        extra = f" №{nums[0]}"

        role_options.append({
            "role":  role,
            "label": label + extra,
        })

    return render_template(
        "role_select.html",
        user         = session["user"],
        role_options = role_options
    )


# ======================================================
# LOGOUT
# ======================================================

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ======================================================
# SWITCH ROLE — переключиться в другую роль без выхода
# ======================================================

@app.route("/switch_role")
@login_required
def switch_role():
    """Возвращает на экран выбора роли."""
    # Сбрасываем только текущую роль, оставляем пользователя
    session.pop("role", None)
    session.pop("bureau", None)
    return redirect("/select_role")


# ======================================================
# DASHBOARD — секретарь
# ======================================================

@app.route("/dashboard")
@login_required
@role_required("secretary")
def dashboard():

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM entries ORDER BY created_at DESC LIMIT 50")
    entries = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("dashboard.html", entries=entries)


# ======================================================
# BUREAU — панель профбюро
# ======================================================

@app.route("/bureau")
@login_required
@role_required("bureau")
def bureau_page():

    bureau_num = session.get("bureau")

    conn = get_db()
    cur  = conn.cursor()

    cur.execute("SELECT * FROM entries ORDER BY created_at DESC LIMIT 50")
    entries = cur.fetchall()

    cur.execute(
        "SELECT * FROM students WHERE bureau = %s ORDER BY student_id",
        (bureau_num,)
    )
    bureau_students = cur.fetchall()

    cur.execute(
        "SELECT COUNT(*) as count FROM students WHERE bureau = %s",
        (bureau_num,)
    )
    bureau_students_count = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) as count FROM entries")
    entries_count = cur.fetchone()["count"]

    cur.close()
    conn.close()

    return render_template(
        "bureau.html",
        entries               = entries,
        bureau_students       = bureau_students,
        bureau_num            = bureau_num,
        bureau_students_count = bureau_students_count,
        entries_count         = entries_count
    )


# ======================================================
# CHAIRMAN
# ======================================================

@app.route("/chairman")
@login_required
@role_required("chairman")
def chairman():
    return render_template("chairman.html", **get_admin_data())


# ======================================================
# VICE CHAIRMAN
# ======================================================

@app.route("/vice_chairman")
@login_required
@role_required("vice_chairman")
def vice_chairman():
    return render_template("vice_chairman.html", **get_admin_data())


# ======================================================
# ВЫДАЧА — secretary (AJAX)
# ======================================================

@app.route("/issue", methods=["POST"])
@login_required
@role_required("secretary")
def issue():

    data       = request.get_json()
    student_id = (data.get("student_id") or "").strip()

    if not student_id:
        return jsonify(ok=False, error="Введите ID студента")

    return do_issue(student_id, data, session.get("user") or "Секретарь")


# ======================================================
# ВЫДАЧА — bureau (AJAX)
# ======================================================

@app.route("/issue_bureau", methods=["POST"])
@login_required
@role_required("bureau")
def issue_bureau():

    data       = request.get_json()
    student_id = (data.get("student_id") or "").strip()

    if not student_id:
        return jsonify(ok=False, error="Введите ID студента")

    return do_issue(student_id, data, session.get("user") or "Профбюро")


# ======================================================
# UNDO — secretary и bureau
# ======================================================

@app.route("/undo/<int:entry_id>", methods=["POST"])
@login_required
@role_required("secretary", "bureau")
def undo(entry_id):

    conn = get_db()
    cur  = conn.cursor()

    cur.execute("SELECT * FROM entries WHERE id = %s", (entry_id,))
    entry = cur.fetchone()

    if not entry:
        cur.close()
        conn.close()
        return jsonify(ok=False, error="Запись не найдена")

    for label, field_name in FIELD_MAP.items():

        if field_name not in ALLOWED_FIELDS:
            continue

        amount = entry.get(field_name, 0) or 0

        if amount <= 0:
            continue

        cur.execute(f"""
            UPDATE students
            SET {field_name} = GREATEST({field_name} - %s, 0)
            WHERE student_id = %s
        """, (amount, entry["student_id"]))

    cur.execute("DELETE FROM entries WHERE id = %s", (entry_id,))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify(ok=True)


# ======================================================
# ADD USER — AJAX
# Если человек уже есть в базе — добавляем ему роль.
# Если нет — создаём новую запись.
# Поиск по базе студентов для подстановки ФИО.
# ======================================================

@app.route("/add_secretary", methods=["POST"])
@login_required
@role_required("chairman", "vice_chairman")
def add_secretary():

    data     = request.get_json()
    name     = (data.get("name")     or "").strip()
    password = (data.get("password") or "").strip()
    role     = (data.get("role")     or "secretary").strip()
    bureau   = data.get("bureau")

    if not name:
        return jsonify(ok=False, error="Введите ФИО")

    if role == "chairman":
        return jsonify(ok=False, error="Нельзя создать ещё одного председателя")

    if session["role"] == "vice_chairman" and role == "vice_chairman":
        return jsonify(ok=False, error="Недостаточно прав для назначения этой роли")

    if role == "bureau":
        if not bureau:
            return jsonify(ok=False, error="Укажите номер бюро")
        try:
            bureau = int(bureau)
        except (ValueError, TypeError):
            return jsonify(ok=False, error="Некорректный номер бюро")
    else:
        bureau = None

    conn = get_db()
    cur  = conn.cursor()

    # Проверяем — есть ли уже такой пользователь
    cur.execute("SELECT * FROM users WHERE name = %s", (name,))
    existing = cur.fetchone()

    if existing:

        # Пользователь существует — добавляем роль
        current_roles = get_user_roles(existing)

        if role in current_roles:
            cur.close()
            conn.close()
            return jsonify(ok=False, error=f"У {name} уже есть роль «{ROLE_LABELS.get(role, role)}»")

        new_roles = current_roles + [role]

        # Обновляем bureaus если добавляем роль bureau
        if role == "bureau":
            import json
            bureaus_raw = existing.get("bureaus")
            if bureaus_raw:
                if isinstance(bureaus_raw, str):
                    try:
                        bureaus_raw = json.loads(bureaus_raw)
                    except Exception:
                        bureaus_raw = {}
                bureaus = bureaus_raw if isinstance(bureaus_raw, dict) else {}
            else:
                bureaus = {}

            existing_bureaus = bureaus.get("bureau", [])
            if bureau not in existing_bureaus:
                existing_bureaus.append(bureau)
            bureaus["bureau"] = existing_bureaus

            cur.execute("""
                UPDATE users
                SET roles = %s, bureaus = %s
                WHERE id = %s
            """, (new_roles, json.dumps(bureaus), existing["id"]))
        else:
            cur.execute("""
                UPDATE users
                SET roles = %s
                WHERE id = %s
            """, (new_roles, existing["id"]))

        conn.commit()
        cur.close()
        conn.close()

        label = ROLE_LABELS.get(role, role)
        suffix = f" (бюро №{bureau})" if role == "bureau" else ""
        return jsonify(
            ok      = True,
            mode    = "updated",
            message = f"Роль «{label}{suffix}» добавлена пользователю {name}",
            user    = {
                "id":     existing["id"],
                "name":   name,
                "roles":  new_roles,
                "bureau": bureau
            }
        )

    else:

        # Новый пользователь — создаём
        if not password:
            cur.close()
            conn.close()
            return jsonify(ok=False, error="Задайте пароль для нового пользователя")

        import json

        bureaus = None
        if role == "bureau" and bureau:
            bureaus = json.dumps({"bureau": [bureau]})

        try:
            cur.execute("""
                INSERT INTO users (name, password, roles, bureaus)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (
                name,
                generate_password_hash(password),
                [role],
                bureaus
            ))
            new_id = cur.fetchone()["id"]
            conn.commit()

        except Exception as e:
            cur.close()
            conn.close()
            return jsonify(ok=False, error=str(e))

        cur.close()
        conn.close()

        label = ROLE_LABELS.get(role, role)
        suffix = f" (бюро №{bureau})" if role == "bureau" else ""
        return jsonify(
            ok      = True,
            mode    = "created",
            message = f"Создан новый пользователь {name} с ролью «{label}{suffix}»",
            user    = {
                "id":     new_id,
                "name":   name,
                "roles":  [role],
                "bureau": bureau
            }
        )


# ======================================================
# REMOVE ROLE FROM USER — AJAX
# Удаляет конкретную роль. Если ролей не осталось — удаляет пользователя.
# ======================================================

@app.route("/remove_role/<int:user_id>", methods=["POST"])
@login_required
@role_required("chairman", "vice_chairman")
def remove_role(user_id):

    data   = request.get_json()
    role   = (data.get("role") or "").strip()
    bureau = data.get("bureau")  # для удаления конкретного бюро

    conn = get_db()
    cur  = conn.cursor()

    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    target = cur.fetchone()

    if not target:
        cur.close()
        conn.close()
        return jsonify(ok=False, error="Пользователь не найден")

    if "chairman" in get_user_roles(target):
        cur.close()
        conn.close()
        return jsonify(ok=False, error="Нельзя удалить председателя")

    if session["role"] == "vice_chairman" and "vice_chairman" in get_user_roles(target):
        cur.close()
        conn.close()
        return jsonify(ok=False, error="Недостаточно прав")

    current_roles = get_user_roles(target)

    if role not in current_roles:
        cur.close()
        conn.close()
        return jsonify(ok=False, error="У пользователя нет этой роли")

    new_roles = [r for r in current_roles if r != role]

    import json

    # Обновляем bureaus если удаляем роль bureau
    bureaus = target.get("bureaus")
    if role == "bureau" and bureaus and bureau is not None:
        if isinstance(bureaus, str):
            try:
                bureaus = json.loads(bureaus)
            except Exception:
                bureaus = {}
        nums = bureaus.get("bureau", [])
        nums = [n for n in nums if n != bureau]
        if nums:
            bureaus["bureau"] = nums
        else:
            bureaus.pop("bureau", None)
        # Если в bureaus ничего не осталось — None
        bureaus = json.dumps(bureaus) if bureaus else None
    else:
        bureaus = json.dumps(target.get("bureaus")) if target.get("bureaus") else None

    if not new_roles:
        # Ролей не осталось — удаляем пользователя
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify(ok=True, deleted=True)

    cur.execute("""
        UPDATE users
        SET roles = %s, bureaus = %s
        WHERE id = %s
    """, (new_roles, bureaus, user_id))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify(ok=True, deleted=False, new_roles=new_roles)


# ======================================================
# DELETE USER COMPLETELY — AJAX
# ======================================================

@app.route("/delete_secretary/<int:user_id>", methods=["POST"])
@login_required
@role_required("chairman", "vice_chairman")
def delete_secretary(user_id):

    conn = get_db()
    cur  = conn.cursor()

    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    target = cur.fetchone()

    if not target:
        cur.close()
        conn.close()
        return jsonify(ok=False, error="Пользователь не найден")

    if "chairman" in get_user_roles(target):
        cur.close()
        conn.close()
        return jsonify(ok=False, error="Нельзя удалить председателя")

    if session["role"] == "vice_chairman" and "vice_chairman" in get_user_roles(target):
        cur.close()
        conn.close()
        return jsonify(ok=False, error="Недостаточно прав")

    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify(ok=True)


# ======================================================
# CHANGE PASSWORD — AJAX
# ======================================================

@app.route("/change_secretary_password/<int:user_id>", methods=["POST"])
@login_required
@role_required("chairman", "vice_chairman")
def change_secretary_password(user_id):

    data     = request.get_json()
    password = (data.get("password") or "").strip()

    if not password:
        return jsonify(ok=False, error="Пароль не может быть пустым")

    conn = get_db()
    cur  = conn.cursor()

    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    target = cur.fetchone()

    if not target:
        cur.close()
        conn.close()
        return jsonify(ok=False, error="Пользователь не найден")

    if "chairman" in get_user_roles(target):
        cur.close()
        conn.close()
        return jsonify(ok=False, error="Нельзя менять пароль председателя")

    if session["role"] == "vice_chairman" and "vice_chairman" in get_user_roles(target):
        cur.close()
        conn.close()
        return jsonify(ok=False, error="Недостаточно прав")

    cur.execute(
        "UPDATE users SET password = %s WHERE id = %s",
        (generate_password_hash(password), user_id)
    )
    conn.commit()
    cur.close()
    conn.close()

    return jsonify(ok=True)


# ======================================================
# CHANGE OWN PASSWORD
# ======================================================

@app.route("/change_password", methods=["POST"])
@login_required
@role_required("chairman", "vice_chairman")
def change_password():

    new_password = request.form["new_password"]

    conn = get_db()
    cur  = conn.cursor()

    cur.execute(
        "UPDATE users SET password = %s WHERE name = %s",
        (generate_password_hash(new_password), session["user"])
    )
    conn.commit()
    cur.close()
    conn.close()

    flash("Пароль изменён")

    return redirect("/chairman" if session["role"] == "chairman" else "/vice_chairman")


# ======================================================
# SAVE SCHEDULE
# ======================================================

@app.route("/save_schedule", methods=["POST"])
@login_required
@role_required("chairman", "vice_chairman")
def save_schedule():

    conn = get_db()
    cur  = conn.cursor()

    for day in ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"]:
        cur.execute(
            "UPDATE schedule SET secretary_name = %s WHERE day_name = %s",
            (request.form.get(day), day)
        )

    conn.commit()
    cur.close()
    conn.close()

    flash("Расписание сохранено")

    return redirect("/chairman" if session["role"] == "chairman" else "/vice_chairman")


# ======================================================
# EXPORT EXCEL
# ======================================================

@app.route("/export_excel")
@login_required
@role_required("chairman", "vice_chairman")
def export_excel():

    date_from = request.args.get("date_from")
    date_to   = request.args.get("date_to")
    secretary = request.args.get("secretary")

    conn = get_db()
    cur  = conn.cursor()

    query = """
        SELECT student_id, student_name, secretary, action_text,
               print_count, copy_count, notebook_count, ruler_count,
               corrector_count, pencil_count, eraser_sharpener_count,
               millimeter_count, created_at
        FROM entries WHERE 1=1
    """

    params = []
    if date_from: query += " AND DATE(created_at) >= %s"; params.append(date_from)
    if date_to:   query += " AND DATE(created_at) <= %s"; params.append(date_to)
    if secretary: query += " AND secretary = %s";          params.append(secretary)
    query += " ORDER BY created_at DESC"

    cur.execute(query, tuple(params))
    entries = cur.fetchall()
    cur.close()
    conn.close()

    data = [{
        "ID студента":     row["student_id"],
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

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(data).to_excel(writer, index=False, sheet_name="Отчет")
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="report.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ======================================================
# ADD STUDENT — AJAX
# ======================================================

@app.route("/add_student", methods=["POST"])
@login_required
@role_required("chairman", "vice_chairman", "bureau")
def add_student():

    data      = request.get_json()
    full_name = (data.get("name") or "").strip()

    if not full_name:
        return jsonify(ok=False, error="Введите ФИО")

    if session.get("role") == "bureau":
        bureau = session.get("bureau")
    else:
        try:
            bureau = int(data.get("bureau") or 0)
        except (ValueError, TypeError):
            bureau = 0
        if bureau not in range(1, 6):
            return jsonify(ok=False, error="Укажите номер бюро (1–5)")

    conn = get_db()
    cur  = conn.cursor()

    # Проверка дубликата
    cur.execute(
        "SELECT id FROM students WHERE full_name = %s AND bureau = %s",
        (full_name, bureau)
    )
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify(ok=False, error=f"Студент «{full_name}» уже есть в бюро №{bureau}")

    student_id = generate_student_id(cur, bureau)

    try:
        cur.execute(
            "INSERT INTO students (student_id, full_name, bureau) VALUES (%s, %s, %s)",
            (student_id, full_name, bureau)
        )
        conn.commit()
    except Exception as e:
        cur.close()
        conn.close()
        return jsonify(ok=False, error=str(e))

    cur.close()
    conn.close()

    return jsonify(ok=True, student_id=student_id, full_name=full_name, bureau=bureau)


# ======================================================
# DELETE STUDENT — AJAX
# ======================================================

@app.route("/delete_student/<student_id>", methods=["POST"])
@login_required
@role_required("chairman", "vice_chairman", "bureau")
def delete_student(student_id):

    conn = get_db()
    cur  = conn.cursor()

    if session.get("role") == "bureau":
        cur.execute(
            "SELECT bureau FROM students WHERE student_id = %s",
            (student_id,)
        )
        row = cur.fetchone()
        if not row or row["bureau"] != session.get("bureau"):
            cur.close()
            conn.close()
            return jsonify(ok=False, error="Нет доступа")

    cur.execute("DELETE FROM students WHERE student_id = %s", (student_id,))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify(ok=True)


# ======================================================
# UPLOAD STUDENTS
# ======================================================

@app.route("/upload_students", methods=["POST"])
@login_required
@role_required("chairman", "vice_chairman", "bureau")
def upload_students():

    file = request.files.get("file")
    role = session.get("role")
    back = (
        "/chairman"      if role == "chairman"      else
        "/vice_chairman" if role == "vice_chairman" else
        "/bureau"
    )

    if not file:
        flash("Файл не выбран")
        return redirect(back)

    raw     = file.read()
    content = None

    for encoding in ("utf-8-sig", "utf-8", "cp1251", "cp1252", "latin-1"):
        try:
            content = raw.decode(encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if content is None:
        flash("Не удалось определить кодировку файла.")
        return redirect(back)

    conn    = get_db()
    cur     = conn.cursor()
    added   = 0
    skipped = 0

    for line in content.splitlines():

        line = line.strip()
        if not line:
            continue

        parts     = [p.strip() for p in line.split(";")]
        full_name = parts[0] if parts else ""

        if not full_name:
            continue

        if role == "bureau":
            bureau = session.get("bureau")
        elif len(parts) >= 2 and parts[1]:
            try:
                bureau = int(parts[1])
            except ValueError:
                skipped += 1
                continue
            if bureau not in range(1, 6):
                skipped += 1
                continue
        else:
            skipped += 1
            continue

        cur.execute(
            "SELECT id FROM students WHERE full_name = %s AND bureau = %s",
            (full_name, bureau)
        )
        if cur.fetchone():
            skipped += 1
            continue

        student_id = generate_student_id(cur, bureau)

        try:
            cur.execute(
                "INSERT INTO students (student_id, full_name, bureau) VALUES (%s, %s, %s)",
                (student_id, full_name, bureau)
            )
            added += 1
        except Exception:
            skipped += 1
            continue

    conn.commit()
    cur.close()
    conn.close()

    flash(f"Добавлено: {added}, пропущено: {skipped}")
    return redirect(back)


# ======================================================
# SEARCH STUDENTS
# ======================================================

@app.route("/search_students")
@login_required
def search_students():

    query = request.args.get("q", "").strip()

    conn = get_db()
    cur  = conn.cursor()

    cur.execute("""
        SELECT student_id, full_name, bureau FROM students
        WHERE (
            LOWER(full_name) LIKE LOWER(%s)
            OR student_id LIKE %s
        )
        ORDER BY bureau, student_id
        LIMIT 15
    """, (f"%{query}%", f"%{query}%"))

    students = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify(students)


# ======================================================
# STUDENT LIMITS API
# ======================================================

@app.route("/student_limits/<student_id>")
@login_required
@role_required("bureau", "secretary")
def student_limits_api(student_id):

    conn = get_db()
    cur  = conn.cursor()

    cur.execute("""
        SELECT
            COALESCE(SUM(print_count),            0) AS prints,
            COALESCE(SUM(copy_count),             0) AS copies,
            COALESCE(SUM(notebook_count),         0) AS notebooks,
            COALESCE(SUM(ruler_count),            0) AS rulers,
            COALESCE(SUM(corrector_count),        0) AS correctors,
            COALESCE(SUM(pencil_count),           0) AS pencils,
            COALESCE(SUM(eraser_sharpener_count), 0) AS erasers,
            COALESCE(SUM(millimeter_count),       0) AS millimeters
        FROM entries
        WHERE student_id = %s
        AND DATE_TRUNC('month', created_at) = DATE_TRUNC('month', CURRENT_DATE)
    """, (student_id,))

    used = cur.fetchone()
    cur.close()
    conn.close()

    return jsonify({key: max(LIMITS[key] - used[key], 0) for key in LIMITS})


# ======================================================
# PING
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
