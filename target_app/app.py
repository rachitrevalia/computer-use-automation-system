"""
Mock Targeted App
"""
import time
import uuid
from flask import Flask, request, redirect, url_for, make_response, render_template

from data import get_member, open_sub_account

app = Flask(__name__)

SESSIONS ={}
SESSIONS_TTL_SECONDS = 120
NOTICE_ACK = set()

def current_session_id():
    return request.cookies.get("lb_session")

def session_is_valid(force_expired=False):
    sid = current_session_id()
    if not sid or sid not in SESSIONS:
        return False
    if force_expired:
        return False
    age = time.time() - SESSIONS[sid]["created_at"]
    return age < SESSIONS_TTL_SECONDS


@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    username = request.form.get("username","").strip()
    password = request.form.get("password", "").strip()
    if not username or not password:
        return render_template("login.html", error="username and password is required")
    sid = str(uuid.uuid4())
    SESSIONS[sid] = {"created_at": time.time()}
    resp = make_response(redirect(url_for("search")))
    resp.set_cookie("lb_session",sid)
    return resp

@app.route("/search", methods = ["GET", "POST"])
def search():
    simulate = request.args.get("simulate", "")
    if not session_is_valid(force_expired=(simulate == "timeout")):
        return render_template("session_expired.html"), 200
    if request.method == "GET":
        return render_template("search.html")
    member_id = request.form.get("member_id", "").strip()
    return redirect(url_for("member_detail", member_id=member_id, simulate=simulate))

@app.route("/member/<member_id>")
def member_detail(member_id):
    simulate = request.args.get("simulate","")
    
    if not session_is_valid(force_expired=(simulate == "timeout")):
        return render_template("session_expired.html"), 200
    
    if simulate == "not_found":
        return render_template("not_found.html", member_id=member_id), 200
    
    member = get_member(member_id)
    
    if member is None:
        return render_template("not_found.html", member_id = member_id), 200
    
    if member["locked"] or simulate == "permission_denied":
        return render_template("permission_denied.html", member_id=member_id),200
    
    return render_template("member_detail.html", member=member, simulate=simulate)
    

@app.route("/member/<member_id>/balance_frame")
def balance_frame(member_id):
    member = get_member(member_id)
    if member is None:
        return render_template("not_found.html", member_id = member_id), 200
    return render_template("balance_frame.html", member=member)

@app.route("/member/<member_id>/new_subaccount", methods=["GET","POST"])
def new_subaccount(member_id):
    simulate = request.args.get("simulate","")
    if not session_is_valid(force_expired=(simulate == "timeout")):
        return render_template("session_expired.html"), 200
    
    member = get_member(member_id)
    if member is None:
        return render_template("not_found.html", member_id=member_id), 200
    
    sid = current_session_id()
    if simulate == "interstitial" and sid not in NOTICE_ACK:
        return render_template("notice_interstitial.html", member_id=member_id)
    
    if request.method == "GET":
        return render_template("new_subaccount.html", member=member, simulate=simulate)
    
    account_type = request.form.get("account_type","").strip()
    deposit_raw = request.form.get("initial_deposit", "").strip()
    
    error = None
    if simulate == "validation_error":
        error = "Initial deposit must be a positive amount."
    elif not account_type:
        error = "Account type is required."
    else:
        try:
            deposit = float(deposit_raw)
            if deposit <= 0:
                error = "Initial deposit must be a positive amount."
        except ValueError:
            error = "Initial deposit must be a number."
    
    if error:
        return render_template("new_subaccount.html", member=member,error=error, simulate=simulate)
    
    record = open_sub_account(member_id, account_type, float(deposit_raw))
    return render_template("confirmation.html", member=member, record=record)


@app.route("/member/<member_id>/new_subaccount/ack", methods=["POST"])
def ack_notice(member_id):
    sid = current_session_id()
    if sid:
        NOTICE_ACK.add(sid)
    return redirect(url_for("new_subaccount", member_id=member_id))

@app.route("/")
def index():
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)    