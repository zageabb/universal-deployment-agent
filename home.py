#!/usr/bin/env python3
"""Read-only application launcher backed by the existing UDA registry."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

from flask import Flask, jsonify, render_template, request
from deploy_agent import DeployError, load_config

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


def application_cards(config: dict, public_host: str) -> list[dict]:
    cards = []
    for entry in config['applications']:
        if not entry.get('enabled') or entry.get('kind') == 'library' or entry.get('show_on_home') is False:
            continue
        url = application_url(entry, public_host)
        if not url:
            continue
        title = entry.get('display_name') or re.sub(r'[-_]+', ' ', entry['name']).title()
        words = title.split()
        cards.append({'name': entry['name'], 'title': title, 'url': url,
                      'initials': ''.join(word[0] for word in words[:2]).upper(),
                      'address': urlsplit(url).netloc})
    return sorted(cards, key=lambda card: card['title'].casefold())


def create_app(config_path: Path, public_host: str | None = None) -> Flask:
    app = Flask(__name__)

    def cards():
        host = public_host or urlsplit(request.host_url).hostname
        return application_cards(load_config(config_path), host)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        return response

    @app.get('/')
    def index():
        try:
            return render_template('home.html', applications=cards(), error=False)
        except DeployError:
            app.logger.warning('Application registry unavailable')
            return render_template('home.html', applications=[], error=True), 503

    @app.get('/api/applications')
    def applications():
        try:
            return jsonify(applications=cards())
        except DeployError:
            return jsonify(error='The application list is temporarily unavailable.'), 503

    @app.get('/health')
    def health():
        try:
            cards()
            return jsonify(ok=True)
        except DeployError:
            return jsonify(ok=False), 503

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
