import json
from pathlib import Path

import pytest

import home


def entry(**values):
    return {'name': 'context-studio', 'enabled': True, 'repo_path': '/private/app', 'branch': 'main',
            'restart_command': ['true'], 'health_url': 'http://127.0.0.1:8074/api/health', **values}


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'https://user:secret@example.com/',
                                'file:///etc/passwd', 'http://example.com:bad/', '//example.com/',
                                'http://example.com/a b'])
def test_unsafe_links_are_omitted(url):
    assert home.application_url(entry(app_url=url), 'server.local') is None


def test_explicit_frontend_link_wins_over_backend_health():
    assert home.application_url(entry(app_url='http://127.0.0.1:5075/work?x=1'), 'server.local') == 'http://server.local:5075/work?x=1'


def test_fallback_removes_health_path_and_query():
    assert home.application_url(entry(health_url='http://localhost:5050/api/health?token=secret'), '192.168.1.249') == 'http://192.168.1.249:5050/'


def test_external_links_remain_external():
    assert home.application_url(entry(app_url='https://apps.example.org/tool/'), 'server.local') == 'https://apps.example.org/tool/'


def test_ipv6_loopback_is_rewritten():
    assert home.application_url(entry(app_url='http://[::1]:5075/'), '2001:db8::1') == 'http://[2001:db8::1]:5075/'


def test_directory_excludes_disabled_hidden_and_libraries():
    config = {'applications': [entry(), entry(name='disabled', enabled=False),
                               entry(name='hidden', show_on_home=False), entry(name='library', kind='library')]}
    assert [app['name'] for app in home.application_cards(config, 'server.local')] == ['context-studio']


def test_live_registry_and_secret_filtering(tmp_path):
    path = tmp_path / 'config.json'
    value = {'dashboard_token': 'never-display-this', 'applications': [entry()]}
    path.write_text(json.dumps(value))
    client = home.create_app(path, 'server.local').test_client()
    response = client.get('/api/applications')
    assert response.status_code == 200
    assert b'never-display-this' not in response.data
    assert b'/private/app' not in response.data
    assert b'restart_command' not in response.data
    value['applications'].append(entry(name='another-app'))
    path.write_text(json.dumps(value))
    assert len(client.get('/api/applications').json['applications']) == 2
    html = client.get('/').data
    assert b'target="_blank"' in html and b'rel="noopener noreferrer"' in html
    assert b'Another App' in html
    assert client.post('/api/applications').status_code == 405


def test_registry_failure_returns_generic_error(tmp_path):
    path = tmp_path / 'missing.json'
    client = home.create_app(path).test_client()
    for route in ['/', '/health', '/api/applications']:
        response = client.get(route)
        assert response.status_code == 503
        assert str(path).encode() not in response.data


def test_empty_registry_and_escaped_titles(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'applications': []}))
    client = home.create_app(path).test_client()
    assert b'No applications are listed yet.' in client.get('/').data
    path.write_text(json.dumps({'applications': [entry(display_name='<script>bad()</script>')]}))
    assert b'<script>bad()</script>' not in client.get('/').data
