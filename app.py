import sqlite3
import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "my_student_project_key"
placement_db = "placement_portal.db"

def get_db():
    
    db = sqlite3.connect(placement_db)
    db.row_factory = sqlite3.Row
    return db

def initialize_database_with_defaults():
    db = get_db()
    
    db.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT,
        is_approved INTEGER DEFAULT 0,
        is_blacklisted INTEGER DEFAULT 0
    )''')

    db.execute('''CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        full_name TEXT,
        email TEXT,
        contact TEXT,
        dept TEXT,
        cgpa REAL,
        resume TEXT
    )''')

    db.execute('''CREATE TABLE IF NOT EXISTS companies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        website TEXT
    )''')

    db.execute('''CREATE TABLE IF NOT EXISTS drives (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id INTEGER,
        title TEXT,
        description TEXT,
        criteria TEXT,
        deadline TEXT,
        status TEXT DEFAULT 'Pending'
    )''')

    db.execute('''CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        drive_id INTEGER,
        status TEXT DEFAULT 'Applied',
        UNIQUE(student_id, drive_id)
    )''')

    #Admin login is created here automatically, if it is not present

    check = db.execute("SELECT * FROM users WHERE username = 'admin'").fetchone()
    if check is None:
        p_hash = generate_password_hash("admin123")
        db.execute("INSERT INTO users (username, password, role, is_approved) VALUES ('admin', ?, 'admin', 1)", (p_hash,))
    
    db.commit()
    db.close()
initialize_database_with_defaults()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class UserAccount(UserMixin):
    def __init__(self, uid, name, role, approved, blocked):
        self.id = uid
        self.username = name
        self.role = role
        self.is_approved = approved
        self.is_blacklisted = blocked

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")
        
        db = get_db()
        user_row = db.execute("SELECT * FROM users WHERE username = ?", (u,)).fetchone()
        db.close()
        
        if user_row and check_password_hash(user_row['password'], p):
            if user_row['is_blacklisted'] == 1:
                flash("Your account is blocked.", "danger")
            elif user_row['role'] != 'admin' and user_row['is_approved'] == 0:
                flash("Wait for Admin approval.", "warning")
            else:
                user_obj = UserAccount(user_row['id'], user_row['username'], user_row['role'], 
                                     user_row['is_approved'], user_row['is_blacklisted'])
                login_user(user_obj)
                return redirect(url_for("dashboard"))
        else:
            flash("Invalid login", "danger")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        role = request.form.get("role")
        u = request.form.get("username")
        p = generate_password_hash(request.form.get("password"))
        
        approved = 1 if role == "student" else 0
        
        db = get_db()
        # manual error handling for whether a profile exists or not
        try:
            cursor = db.cursor()
            cursor.execute("INSERT INTO users (username, password, role, is_approved) VALUES (?, ?, ?, ?)", (u, p, role, approved))
            new_id = cursor.lastrowid
            
            if role == "student":
                n = request.form.get("full_name")
                e = request.form.get("email")
                cursor.execute("INSERT INTO students (user_id, full_name, email) VALUES (?, ?, ?)", (new_id, n, e))
            else:
                cn = request.form.get("company_name")
                web = request.form.get("website")
                cursor.execute("INSERT INTO companies (user_id, name, website) VALUES (?, ?, ?)", (new_id, cn, web))
            
            db.commit()
            flash("Success! Please Login.", "success")
            return redirect(url_for("login"))
        except:
            flash("Username exists", "danger")
        finally:
            db.close()
    return render_template("register.html")

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    if current_user.role == "admin":
        s_count = db.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        c_count = db.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        d_count = db.execute("SELECT COUNT(*) FROM drives").fetchone()[0]
        a_count = db.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        
        p_companies = db.execute("SELECT u.id, c.name FROM users u JOIN companies c ON u.id = c.user_id WHERE u.is_approved = 0").fetchall()
        p_drives = db.execute("SELECT d.id, d.title, c.name FROM drives d JOIN companies c ON d.company_id = c.id WHERE d.status = 'Pending'").fetchall()
        db.close()
        return render_template("admin_dashboard.html", stats={'s':s_count, 'c':c_count, 'd':d_count, 'a':a_count}, 
                               p_comp=p_companies, p_drive=p_drives)

    elif current_user.role == "company":
        prof = db.execute("SELECT * FROM companies WHERE user_id = ?", (current_user.id,)).fetchone()
        my_drives = db.execute("SELECT d.*, (SELECT COUNT(*) FROM applications a WHERE a.drive_id = d.id) as count FROM drives d WHERE company_id = ?", (prof['id'],)).fetchall()
        db.close()
        return render_template("company_dashboard.html", company=prof, drives=my_drives)

    else: # Student
        prof = db.execute("SELECT * FROM students WHERE user_id = ?", (current_user.id,)).fetchone()
        open_drives = db.execute("SELECT d.*, c.name FROM drives d JOIN companies c ON d.company_id = c.id WHERE d.status = 'Approved'").fetchall()
        my_status = db.execute("SELECT a.status, d.title, c.name FROM applications a JOIN drives d ON a.drive_id = d.id JOIN companies c ON d.company_id = c.id WHERE a.student_id = ?", (prof['id'],)).fetchall()
        db.close()
        return render_template("student_dashboard.html", drives=open_drives, apps=my_status)

@app.route("/admin/approve/<int:uid>")
@login_required
def approve_comp(uid):
    db = get_db()
    db.execute("UPDATE users SET is_approved = 1 WHERE id = ?", (uid,))
    db.commit()
    db.close()
    return redirect(url_for("dashboard"))

@app.route("/admin/approve_drive/<int:did>")
@login_required
def approve_drive(did):
    db = get_db()
    db.execute("UPDATE drives SET status = 'Approved' WHERE id = ?", (did,))
    db.commit()
    db.close()
    return redirect(url_for("dashboard"))

@app.route("/admin/manage")
@login_required
def manage():
    find = f"%{request.args.get('search', '')}%"
    db = get_db()
    s_list = db.execute("SELECT s.*, u.is_blacklisted, u.id as user_id FROM students s JOIN users u ON s.user_id = u.id WHERE s.full_name LIKE ?", (find,)).fetchall()
    c_list = db.execute("SELECT c.*, u.is_blacklisted, u.id as user_id FROM companies c JOIN users u ON c.user_id = u.id WHERE c.name LIKE ?", (find,)).fetchall()
    db.close()
    return render_template("manage_users.html", students=s_list, companies=c_list)

@app.route("/admin/block/<int:uid>")
@login_required
def toggle_block(uid):
    db = get_db()
    db.execute("UPDATE users SET is_blacklisted = NOT is_blacklisted WHERE id = ?", (uid,))
    db.commit()
    db.close()
    return redirect(url_for("manage"))

@app.route("/company/create", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        db = get_db()
        comp_id = db.execute("SELECT id FROM companies WHERE user_id = ?", (current_user.id,)).fetchone()['id']
        t = request.form.get("title")
        des = request.form.get("description")
        crit = request.form.get("criteria")
        date = request.form.get("deadline")
        
        db.execute("INSERT INTO drives (company_id, title, description, criteria, deadline) VALUES (?, ?, ?, ?, ?)", (comp_id, t, des, crit, date))
        db.commit()
        db.close()
        return redirect(url_for("dashboard"))
    return render_template("create_drive.html")

@app.route("/company/applicants/<int:did>")
@login_required
def applicants(did):
    db = get_db()
    drive = db.execute("SELECT * FROM drives WHERE id = ?", (did,)).fetchone()
    app_list = db.execute('''SELECT a.id as aid, a.status, s.full_name, s.email, s.cgpa, s.resume 
                             FROM applications a JOIN students s ON a.student_id = s.id 
                             WHERE a.drive_id = ?''', (did,)).fetchall()
    db.close()
    return render_template("view_applicants.html", d=drive, apps=app_list)

@app.route("/company/status/<int:aid>", methods=["POST"])
@login_required
def status(aid):
    s = request.form.get("status")
    db = get_db()
    db.execute("UPDATE applications SET status = ? WHERE id = ?", (s, aid))
    did = db.execute("SELECT drive_id FROM applications WHERE id = ?", (aid,)).fetchone()['drive_id']
    db.commit()
    db.close()
    return redirect(url_for("applicants", did=did))

@app.route("/student/apply/<int:did>")
@login_required
def apply(did):
    db = get_db()
    sid = db.execute("SELECT id FROM students WHERE user_id = ?", (current_user.id,)).fetchone()['id']
    try:
        db.execute("INSERT INTO applications (student_id, drive_id) VALUES (?, ?)", (sid, did))
        db.commit()
        flash("Application sent!", "success")
    except:
        flash("Already applied", "warning")
    db.close()
    return redirect(url_for("dashboard"))

@app.route("/student/profile", methods=["GET", "POST"])
@login_required
def profile():
    db = get_db()
    if request.method == "POST":
        db.execute('''UPDATE students SET full_name=?, email=?, contact=?, dept=?, cgpa=?, resume=? 
                      WHERE user_id=?''', 
                   (request.form.get("name"), request.form.get("email"), request.form.get("phone"), 
                    request.form.get("dept"), request.form.get("cgpa"), request.form.get("resume"), current_user.id))
        db.commit()
        db.close()
        return redirect(url_for("dashboard"))
    p = db.execute("SELECT * FROM students WHERE user_id = ?", (current_user.id,)).fetchone()
    db.close()
    return render_template("student_profile.html", profile=p)

@login_manager.user_loader
def load_user(uid):
    db = get_db()
    res = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    db.close()
    if res:
        return UserAccount(res['id'], res['username'], res['role'], res['is_approved'], res['is_blacklisted'])
    return None

@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)