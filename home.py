#!/usr/bin/env python3
"""Read-only application launcher backed by the existing UDA registry."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from urllib.parse import urlsplit, urlunsplit

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from deploy_agent import DeployError, load_config
from portal_auth import authenticate, connect, consume_token, create_user, groups as memberships, issue_token, send_email, user_for_email
from ui_groups import application_group, configured_groups, group_summary

LOCAL_HOSTS = {'localhost', '127.0.0.1', '0.0.0.0', '::1', '::'}


def application_url(entry: dict, public_host: str) -> str | None:
    explicit = entry.get('app_url')
    raw = explicit or entry.get('health_url')
    if not isinstance(raw, str) or not raw or any(c.isspace() for c in raw):
        return None
    try:
        parts = urlsplit(raw)
        if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
            return None
        host = parts.hostname
        port = parts.port
        if host in LOCAL_HOSTS:
            host = public_host
        authority = f'[{host}]' if ':' in host else host
        if port is not None:
            authority += f':{port}'
        # A health path is never a safe guess at the application's front door.
        return urlunsplit((parts.scheme, authority, parts.path or '/' if explicit else '/',
                           parts.query if explicit else '', parts.fragment if explicit else ''))
    except ValueError:
        return None


def application_cards(config: dict, public_host: str, user_groups: set[str] | None = None) -> list[dict]:
    cards = []
    for entry in config['applications']:
        if not entry.get('enabled') or entry.get('kind') == 'library' or entry.get('show_on_home') is False:
            continue
        allowed = set(entry.get('allowed_groups') or [])
        if user_groups is not None and '*' not in user_groups:
            if application_group(entry) not in user_groups:
                continue
            if entry.get('proxy_enabled') and (not allowed or user_groups.isdisjoint(allowed)):
                continue
        if entry.get('proxy_enabled') and config.get('public_base_url'):
            slug = entry.get('proxy_slug') or entry['name']
            url = config['public_base_url'].rstrip('/') + f'/apps/{slug}/'
        else:
            url = application_url(entry, public_host)
        if not url:
            continue
        title = entry.get('display_name') or re.sub(r'[-_]+', ' ', entry['name']).title()
        words = title.split()
        cards.append({'name': entry['name'], 'title': title, 'url': url,
                      'initials': ''.join(word[0] for word in words[:2]).upper(),
                      'address': urlsplit(url).netloc,
                      'group': application_group(entry)})
    return sorted(cards, key=lambda card: card['title'].casefold())


def create_app(config_path: Path, public_host: str | None = None) -> Flask:
    app = Flask(__name__)
    try: initial = load_config(config_path)
    except DeployError: initial = {}
    app.secret_key = os.environ.get('UDA_PORTAL_SECRET') or initial.get('portal_secret_key') or secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_NAME='uda_session', SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=str(initial.get('public_base_url','')).startswith('https://'))
    app.jinja_env.filters['from_json'] = json.loads

    def identity_config():
        cfg=load_config(config_path); cfg['smtp_password']=os.environ.get('UDA_SMTP_PASSWORD',''); return cfg
    def database():
        return connect(Path(identity_config().get('identity_db','~/.local/state/deployment-agent/identity.db')).expanduser())
    def csrf(): session.setdefault('csrf',secrets.token_urlsafe(24)); return session['csrf']
    def require_csrf():
        if not secrets.compare_digest(session.get('csrf',''),request.form.get('csrf','')): abort(400)
    def current_user():
        return user_for_email(database(),session['user']) if session.get('user') else None
    def auth_enabled(): return bool(initial.get('portal_auth_enabled',False))

    def directory():
        host = public_host or urlsplit(request.host_url).hostname
        cfg = load_config(config_path)
        user=current_user()
        allowed=None if not auth_enabled() else ({'*'} if user and user['is_admin'] else (memberships(user) if user else set()))
        return application_cards(cfg, host, allowed), configured_groups(cfg)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.get('/')
    def index():
        if auth_enabled() and not current_user(): return redirect(url_for('login'))
        try:
            applications, groups = directory()
            return render_template('home.html', applications=applications, user=current_user(), csrf=csrf(), auth_enabled=auth_enabled(),
                                   groups=group_summary(applications, groups), error=False)
        except DeployError:
            app.logger.warning('Application registry unavailable')
            return render_template('home.html', applications=[], groups=[], error=True), 503

    @app.get('/api/applications')
    def applications():
        if auth_enabled() and not current_user(): return jsonify(error='Authentication required'),401
        try:
            listed, groups = directory()
            return jsonify(applications=listed, groups=group_summary(listed, groups))
        except DeployError:
            return jsonify(error='The application list is temporarily unavailable.'), 503

    @app.get('/health')
    def health():
        try:
            directory()
            return jsonify(ok=True)
        except DeployError:
            return jsonify(ok=False), 503

    @app.route('/login',methods=['GET','POST'])
    def login():
        if request.method=='POST':
            require_csrf(); user=authenticate(database(),request.form.get('email',''),request.form.get('password',''))
            if user:
                session.clear(); session['user']=user['email']; csrf(); return redirect(url_for('index'))
            flash('Invalid email, password, or unverified account.','error')
        return render_template('portal_form.html',mode='login',csrf=csrf())

    @app.route('/register',methods=['GET','POST'])
    def register():
        cfg=identity_config()
        if not cfg.get('registration_enabled',True): abort(404)
        if request.method=='POST':
            require_csrf()
            try:
                email=create_user(database(),request.form.get('email',''),request.form.get('password',''),cfg.get('registration_groups',[]))
                token=issue_token(database(),email,'verify',86400); link=cfg['public_base_url']+url_for('verify',token=token)
                send_email(cfg,email,'Verify your UDA account',f'Verify your account:\n\n{link}\n'); flash('Check your email to verify the account.','success'); return redirect(url_for('login'))
            except sqlite3.IntegrityError: flash('That account already exists.','error')
            except (ValueError,RuntimeError) as exc: flash(str(exc),'error')
        return render_template('portal_form.html',mode='register',csrf=csrf())

    @app.get('/verify/<token>')
    def verify(token):
        db=database(); user=consume_token(db,token,'verify')
        if not user: abort(400)
        db.execute('UPDATE users SET verified=1 WHERE email=?',(user['email'],)); db.commit(); flash('Email verified. You can now sign in.','success'); return redirect(url_for('login'))

    @app.route('/forgot-password',methods=['GET','POST'])
    def forgot_password():
        if request.method=='POST':
            require_csrf(); cfg=identity_config()
            try:
                user=user_for_email(database(),request.form.get('email',''))
                if user:
                    token=issue_token(database(),user['email'],'reset',3600); link=cfg['public_base_url']+url_for('reset_password',token=token)
                    send_email(cfg,user['email'],'Reset your UDA password',f'Reset your password:\n\n{link}\n')
            except (ValueError,RuntimeError): pass
            flash('If that account exists, a reset link has been sent.','success'); return redirect(url_for('login'))
        return render_template('portal_form.html',mode='forgot',csrf=csrf())

    @app.route('/reset-password/<token>',methods=['GET','POST'])
    def reset_password(token):
        if request.method=='POST':
            require_csrf(); password=request.form.get('password','')
            if len(password)<12: flash('Password must be at least 12 characters.','error')
            else:
                db=database(); user=consume_token(db,token,'reset')
                if not user: abort(400)
                from werkzeug.security import generate_password_hash
                db.execute('UPDATE users SET password_hash=? WHERE email=?',(generate_password_hash(password),user['email'])); db.commit(); flash('Password changed.','success'); return redirect(url_for('login'))
        return render_template('portal_form.html',mode='reset',csrf=csrf())

    @app.post('/logout')
    def logout(): require_csrf(); session.clear(); return redirect(url_for('login'))

    @app.get('/auth/check')
    def auth_check():
        user=current_user()
        if not user: return '',401
        name=request.headers.get('X-UDA-App',''); cfg=identity_config(); entry=next((x for x in cfg['applications'] if x['name']==name),None)
        allowed=set(entry.get('allowed_groups') or []) if entry else set(); user_groups={'*'} if user['is_admin'] else memberships(user)
        if not entry or (allowed and '*' not in user_groups and user_groups.isdisjoint(allowed)): return '',403
        response=app.response_class('',204); response.headers['X-UDA-User']=user['email']; response.headers['X-UDA-Groups']=','.join(sorted(user_groups)); return response

    @app.route('/admin/users',methods=['GET','POST'])
    def admin_users():
        actor=current_user()
        if not actor or not actor['is_admin']: abort(403)
        db=database(); cfg=identity_config()
        if request.method=='POST':
            require_csrf(); email=request.form.get('email',''); selected=request.form.getlist('groups')
            if not set(selected).issubset(set(configured_groups(cfg))): abort(400)
            db.execute('UPDATE users SET groups_json=?,verified=? WHERE email=?',(json.dumps(selected),int(request.form.get('verified')=='1'),email)); db.commit()
            flash(f'Updated {email}.','success'); return redirect(url_for('admin_users'))
        users=db.execute('SELECT email,verified,groups_json,is_admin,created_at FROM users ORDER BY email').fetchall()
        access=[]
        for group in configured_groups(cfg):
            apps=[entry.get('display_name') or re.sub(r'[-_]+',' ',entry['name']).title()
                  for entry in cfg['applications'] if entry.get('enabled') and entry.get('proxy_enabled')
                  and group in (entry.get('allowed_groups') or [])]
            access.append({'name':group,'applications':apps})
        return render_template('portal_users.html',users=users,groups=access,csrf=csrf())

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', default=5048, type=int)
    parser.add_argument('--public-host', help='Hostname or IP used in place of loopback links')
    args = parser.parse_args()
    create_app(args.config.expanduser(), args.public_host).run(host=args.host, port=args.port)


if __name__ == '__main__':
    main()
