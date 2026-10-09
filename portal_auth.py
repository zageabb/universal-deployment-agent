"""Local identity store for the authenticated UDA application portal."""
from __future__ import annotations
import hashlib, json, secrets, smtplib, sqlite3, time
from email.message import EmailMessage
from pathlib import Path
from werkzeug.security import check_password_hash, generate_password_hash

def connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path); db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS users (email TEXT PRIMARY KEY COLLATE NOCASE,
      password_hash TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0,
      groups_json TEXT NOT NULL DEFAULT '[]', is_admin INTEGER NOT NULL DEFAULT 0,
      token_digest TEXT, token_purpose TEXT, token_expires INTEGER, created_at INTEGER NOT NULL)""")
    db.commit(); return db

def normalize_email(value):
    email = value.strip().casefold()
    if len(email)>254 or email.count('@')!=1 or any(c.isspace() for c in email): raise ValueError('Enter a valid email address')
    local, domain = email.rsplit('@',1)
    if not local or '.' not in domain: raise ValueError('Enter a valid email address')
    return email

def user_for_email(db,email): return db.execute('SELECT * FROM users WHERE email=?',(normalize_email(email),)).fetchone()
def create_user(db,email,password,groups=(),admin=False,verified=False):
    email=normalize_email(email)
    if len(password)<12: raise ValueError('Password must be at least 12 characters')
    db.execute('INSERT INTO users VALUES (?,?,?,?,?,NULL,NULL,NULL,?)',(email,generate_password_hash(password),int(verified),json.dumps(list(groups)),int(admin),int(time.time())))
    db.commit(); return email
def authenticate(db,email,password):
    try: user=user_for_email(db,email)
    except ValueError: return None
    return user if user and user['verified'] and check_password_hash(user['password_hash'],password) else None
def issue_token(db,email,purpose,lifetime):
    token=secrets.token_urlsafe(32); digest=hashlib.sha256(token.encode()).hexdigest()
    db.execute('UPDATE users SET token_digest=?,token_purpose=?,token_expires=? WHERE email=?',(digest,purpose,int(time.time())+lifetime,normalize_email(email))); db.commit(); return token
def consume_token(db,token,purpose):
    digest=hashlib.sha256(token.encode()).hexdigest()
    user=db.execute('SELECT * FROM users WHERE token_digest=? AND token_purpose=? AND token_expires>=?',(digest,purpose,int(time.time()))).fetchone()
    if user: db.execute('UPDATE users SET token_digest=NULL,token_purpose=NULL,token_expires=NULL WHERE email=?',(user['email'],)); db.commit()
    return user
def groups(user): return set(json.loads(user['groups_json']))
def send_email(config,recipient,subject,body):
    password=config.get('smtp_password')
    if not password: raise RuntimeError('Email delivery is not configured')
    message=EmailMessage(); message['From']=config['smtp_from']; message['To']=recipient; message['Subject']=subject; message.set_content(body)
    with smtplib.SMTP(config.get('smtp_host','smtp.gmail.com'),int(config.get('smtp_port',587)),timeout=20) as smtp:
        smtp.starttls(); smtp.login(config.get('smtp_username',config['smtp_from']),password); smtp.send_message(message)
