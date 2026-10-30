"""Opportunity Navigator (Group Scalar prototype). Flask + SQLite. Fictional data only."""
import os, re, sqlite3, secrets
from datetime import date
from functools import wraps
from flask import (Flask, g, render_template, request, redirect, url_for,
                   session, flash, abort)
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "navigator.db")
app = Flask(__name__)
# Secret key comes from the environment, never from the code.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

FIELDS = ["STEM", "Business", "Arts", "Humanities", "Social Impact", "Leadership"]
TYPES = ["Competition", "Research programme", "Conference", "Scholarship", "Programme"]
AIDS = ["Need blind", "Need aware", "Full aid", "Partial aid", "No aid"]
CHOICES = {"field": FIELDS, "type": TYPES, "aid": AIDS}
TEXT = ("title", "provider", "field", "type", "aid", "eligibility", "location",
        "deadline", "description", "link")
NUMS = ("age_min", "age_max", "duration_weeks")
LABELS = {"title": "Name", "provider": "Provider", "field": "Field", "type": "Type",
          "aid": "Financial aid", "eligibility": "Eligibility", "location": "Location",
          "deadline": "Deadline", "description": "Description", "link": "Application link",
          "age_min": "Minimum age", "age_max": "Maximum age",
          "duration_weeks": "Duration in weeks"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  pw TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('student','staff','approver')));
CREATE TABLE IF NOT EXISTS opportunities(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, provider TEXT NOT NULL,
  field TEXT NOT NULL, type TEXT NOT NULL, aid TEXT NOT NULL, eligibility TEXT NOT NULL,
  age_min INTEGER NOT NULL, age_max INTEGER NOT NULL, duration_weeks INTEGER NOT NULL,
  location TEXT NOT NULL, deadline TEXT NOT NULL, description TEXT NOT NULL,
  link TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK(status IN ('pending','published','rejected','archived')),
  created_by INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS wishlist(
  user_id INTEGER NOT NULL REFERENCES users(id),
  opp_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  PRIMARY KEY(user_id, opp_id));
"""

# title, provider, field, type, aid, eligibility, age_min, age_max, weeks, location, days to deadline, status
SAMPLES = [
    ("Savanna STEM Summer Lab", "Baobab Science Institute", "STEM", "Research programme", "Full aid", "Strong maths and science results", 15, 19, 6, "Nairobi, Kenya", 35, "published"),
    ("Pan African Robotics Challenge", "Kora Robotics Network", "STEM", "Competition", "Partial aid", "Teams of two to four students", 14, 19, 1, "Online", 9, "published"),
    ("Young Founders Pitch Day", "Lumen Enterprise Hub", "Business", "Competition", "No aid", "A business idea to present", 15, 20, 1, "Johannesburg, South Africa", 5, "published"),
    ("Voices of Tomorrow Writing Fellowship", "Nile Letters Foundation", "Humanities", "Programme", "Need blind", "Writes in English or French", 16, 19, 12, "Online", 48, "published"),
    ("Community Impact Leadership Scholarship", "Ubuntu Futures Trust", "Leadership", "Scholarship", "Full aid", "Proven community service", 16, 18, 52, "Accra, Ghana", 60, "published"),
    ("Climate Action Youth Conference", "Green Horizon Alliance", "Social Impact", "Conference", "Partial aid", "Open to all high school students", 14, 19, 1, "Kigali, Rwanda", 21, "published"),
    ("Digital Arts Residency", "Mosaic Creative Centre", "Arts", "Programme", "Need aware", "Portfolio of three works", 16, 20, 8, "Cape Town, South Africa", 75, "published"),
    ("Data Science Bootcamp for Beginners", "Kilimanjaro Tech Academy", "STEM", "Programme", "Need blind", "No coding experience needed", 15, 19, 4, "Online", -10, "published"),
    ("Global Health Research Internship", "Sahel Health Collective", "STEM", "Research programme", "Full aid", "Interest in public health", 17, 20, 10, "Dakar, Senegal", 90, "pending"),
    ("Model Parliament Youth Summit", "Agora Civic Forum", "Social Impact", "Conference", "No aid", "Interest in policy", 15, 19, 1, "Lagos, Nigeria", 120, "pending"),
]


def init_db():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    if not con.execute("SELECT 1 FROM users").fetchone():
        print("Fictional demo accounts. Random passwords are shown once, note them now:")
        ids = {}
        for role in ("student", "staff", "approver"):
            pw = secrets.token_urlsafe(8)
            cur = con.execute("INSERT INTO users(email,name,pw,role) VALUES(?,?,?,?)",
                              (f"{role}@example.test", f"Sample {role.capitalize()}",
                               generate_password_hash(pw), role))
            ids[role] = cur.lastrowid
            print(f"  {role}: {role}@example.test / {pw}")
        for i, (t, p, f, ty, aid, el, a1, a2, w, loc, days, st) in enumerate(SAMPLES, 1):
            dl = date.fromordinal(date.today().toordinal() + days).isoformat()
            desc = (f"{t} is a sample record offered by {p}. Participants build skills in "
                    f"{f.lower()} and connect with other students. Eligibility: {el}.")
            con.execute("""INSERT INTO opportunities(title,provider,field,type,aid,eligibility,
                age_min,age_max,duration_weeks,location,deadline,description,link,status,created_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (t, p, f, ty, aid, el, a1, a2, w, loc, dl, desc,
                         f"https://example.org/opportunities/{i}", st, ids["staff"]))
    con.commit()
    con.close()


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


def label(deadline):
    """Status in words: Open, Closing soon (14 days or less) or Closed."""
    days = (date.fromisoformat(deadline) - date.today()).days
    if days < 0:
        return "Closed", "closed"
    return ("Closing soon", "soon") if days <= 14 else ("Open", "open")


def num(v):
    v = (v or "").strip()
    return int(v) if v.isdigit() else None


def isodate(v):
    try:
        return date.fromisoformat(v).isoformat()
    except (ValueError, TypeError):
        return None


def login_required(*roles):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            if "uid" not in session:
                return redirect(url_for("login"))
            if roles and session["role"] not in roles:
                abort(403)
            return f(*a, **k)
        return wrapper
    return deco


@app.before_request
def csrf_check():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    if request.method == "POST" and request.form.get("csrf") != session["csrf"]:
        abort(400)


def get_opp(oid):
    o = db().execute("SELECT * FROM opportunities WHERE id=?", (oid,)).fetchone()
    if not o:
        abort(404)
    return o


def can_edit(o):
    return session.get("role") == "approver" or (
        o["created_by"] == session.get("uid") and o["status"] in ("pending", "rejected"))


app.jinja_env.globals.update(label=label, can_edit=can_edit, labels=LABELS,
                             csrf_token=lambda: session.get("csrf", ""))


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
def problem(e):
    msg = {400: "That request was not valid.", 403: "You do not have access to this page.",
           404: "We could not find that page."}[e.code]
    return render_template("error.html", msg=msg), e.code


@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = db().execute("SELECT * FROM users WHERE email=?",
                         (request.form.get("email", "").strip().lower(),)).fetchone()
        if u and check_password_hash(u["pw"], request.form.get("password", "")):
            session.clear()
            session.update(uid=u["id"], role=u["role"], name=u["name"],
                           csrf=secrets.token_hex(16))
            return redirect(url_for("home"))
        flash("Email or password is incorrect.")
    return render_template("auth.html", mode="login")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        if not name or len(name) > 80:
            flash("Enter your name (80 characters or fewer).")
        elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            flash("Enter a valid email address.")
        elif len(pw) < 8:
            flash("Password must have at least 8 characters.")
        else:
            try:
                db().execute("INSERT INTO users(email,name,pw,role) VALUES(?,?,?, 'student')",
                             (email, name, generate_password_hash(pw)))
                db().commit()
                flash("Account created. Please log in.")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That email is already registered.")
    return render_template("auth.html", mode="signup")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/home")
@login_required()
def home():
    if session["role"] != "student":
        return redirect(url_for("manage"))
    a = request.args
    today = date.today().isoformat()
    sql, p = "SELECT * FROM opportunities WHERE status='published'", []
    q = a.get("q", "").strip()
    if q:
        sql += " AND (title LIKE ? OR provider LIKE ? OR description LIKE ? OR field LIKE ?)"
        p += [f"%{q}%"] * 4
    for col in ("field", "type", "aid"):
        vals = [v for v in a.getlist(col) if v in CHOICES[col]]
        if vals:
            sql += f" AND {col} IN ({','.join('?' * len(vals))})"
            p += vals
    if a.get("location", "").strip():
        sql += " AND location LIKE ?"
        p.append(f"%{a['location'].strip()}%")
    if isodate(a.get("from")):
        sql += " AND deadline >= ?"
        p.append(a["from"])
    if isodate(a.get("to")):
        sql += " AND deadline <= ?"
        p.append(a["to"])
    if num(a.get("age")) is not None:
        sql += " AND age_min <= ? AND age_max >= ?"
        p += [num(a["age"])] * 2
    if num(a.get("dmin")) is not None:
        sql += " AND duration_weeks >= ?"
        p.append(num(a["dmin"]))
    if num(a.get("dmax")) is not None:
        sql += " AND duration_weeks <= ?"
        p.append(num(a["dmax"]))
    if a.get("hide"):
        sql += " AND deadline >= ?"
        p.append(today)
    sql += " ORDER BY deadline < ?, deadline"
    p.append(today)
    saved = {r[0] for r in db().execute("SELECT opp_id FROM wishlist WHERE user_id=?",
                                        (session["uid"],))}
    return render_template("home.html", opps=db().execute(sql, p).fetchall(),
                           saved=saved, a=a, choices=CHOICES)


@app.route("/opportunity/<int:oid>")
@login_required()
def detail(oid):
    o = get_opp(oid)
    if o["status"] != "published" and not (
            session["role"] == "approver" or o["created_by"] == session["uid"]):
        abort(404)
    saved = db().execute("SELECT 1 FROM wishlist WHERE user_id=? AND opp_id=?",
                         (session["uid"], oid)).fetchone() is not None
    return render_template("detail.html", o=o, saved=saved)


@app.route("/wishlist")
@login_required("student")
def wishlist():
    rows = db().execute("""SELECT o.* FROM opportunities o JOIN wishlist w ON w.opp_id=o.id
        WHERE w.user_id=? AND o.status='published' ORDER BY o.deadline""",
                        (session["uid"],)).fetchall()
    return render_template("wishlist.html", opps=rows)


@app.route("/wishlist/<int:oid>", methods=["POST"])
@login_required("student")
def save(oid):
    o = get_opp(oid)
    if request.form.get("do") == "remove":
        db().execute("DELETE FROM wishlist WHERE user_id=? AND opp_id=?", (session["uid"], oid))
    elif o["status"] == "published":
        db().execute("INSERT OR IGNORE INTO wishlist(user_id,opp_id) VALUES(?,?)",
                     (session["uid"], oid))
    db().commit()
    nxt = request.form.get("next", "")
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("home"))


@app.route("/manage")
@login_required("staff", "approver")
def manage():
    sql, p = "SELECT o.*, u.name AS owner FROM opportunities o LEFT JOIN users u ON u.id=o.created_by", []
    if session["role"] == "staff":
        sql += " WHERE o.created_by=?"
        p.append(session["uid"])
    rows = db().execute(sql + " ORDER BY o.status='pending' DESC, o.deadline", p).fetchall()
    return render_template("manage.html", opps=rows)


def clean(f):
    d = {k: f.get(k, "").strip() for k in TEXT + NUMS}
    err = [f"{LABELS[k]} is required." for k, v in d.items() if not v]
    for k in NUMS:
        if d[k] and num(d[k]) is None:
            err.append(f"{LABELS[k]} must be a whole number.")
    for k in ("field", "type", "aid"):
        if d[k] and d[k] not in CHOICES[k]:
            err.append(f"Choose a valid {LABELS[k].lower()}.")
    if d["deadline"] and not isodate(d["deadline"]):
        err.append("Deadline must be a valid date.")
    if d["link"] and not re.match(r"^https?://[^\s/]+\.[^\s]+$", d["link"]):
        err.append("Application link must start with http:// or https://.")
    a1, a2, w = num(d["age_min"]), num(d["age_max"]), num(d["duration_weeks"])
    if a1 is not None and a2 is not None and a1 > a2:
        err.append("Minimum age cannot be above maximum age.")
    if w is not None and w < 1:
        err.append("Duration must be at least 1 week.")
    if len(d["title"]) > 120 or len(d["description"]) > 2000:
        err.append("Name (120) or description (2000) is too long.")
    return d, err


@app.route("/opportunity/new", defaults={"oid": None}, methods=["GET", "POST"])
@app.route("/opportunity/<int:oid>/edit", methods=["GET", "POST"])
@login_required("staff", "approver")
def form(oid):
    o = get_opp(oid) if oid else None
    if o and not can_edit(o):
        abort(403)
    v, errors = (dict(o) if o else {}), []
    if request.method == "POST":
        v, errors = clean(request.form)
        if not errors:
            cols = list(v)
            if session["role"] == "approver":
                status = o["status"] if o else "published"
            else:
                status = "pending"
            if o:
                db().execute(f"UPDATE opportunities SET {','.join(c + '=?' for c in cols)},status=? WHERE id=?",
                             [*v.values(), status, oid])
            else:
                db().execute(f"INSERT INTO opportunities({','.join(cols)},status,created_by) "
                             f"VALUES({','.join('?' * len(cols))},?,?)",
                             [*v.values(), status, session["uid"]])
            db().commit()
            flash("Opportunity saved." if session["role"] == "approver"
                  else "Opportunity saved and sent for approval.")
            return redirect(url_for("manage"))
    return render_template("form.html", v=v, errors=errors, o=o, choices=CHOICES)


@app.route("/opportunity/<int:oid>/act", methods=["POST"])
@login_required("staff", "approver")
def act(oid):
    o, do = get_opp(oid), request.form.get("do")
    new = {"approve": "published", "reject": "rejected", "archive": "archived"}
    if do == "delete" and can_edit(o):
        db().execute("DELETE FROM opportunities WHERE id=?", (oid,))
    elif do in new and session["role"] == "approver":
        db().execute("UPDATE opportunities SET status=? WHERE id=?", (new[do], oid))
    else:
        abort(403)
    db().commit()
    flash("Updated.")
    return redirect(url_for("manage"))


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=False)
