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


def test_published_app_card_uses_protected_proxy_route():
    config = {'public_base_url': 'https://tanyaanne.ddns.net', 'applications': [
        entry(name='catmanager', proxy_enabled=True, proxy_slug='catmanager',
              app_url='http://127.0.0.1:5088/')
    ]}
    card = home.application_cards(config, 'server.local')[0]
    assert card['url'] == 'https://tanyaanne.ddns.net/apps/catmanager/'
    assert card['address'] == 'tanyaanne.ddns.net'


def test_authenticated_basic_user_sees_assigned_groups_and_proxy_entitlements():
    config = {'public_base_url': 'https://example.test', 'applications': [
        entry(name='legacy-lan-app', group='Personal'),
        entry(name='published-without-policy', proxy_enabled=True),
        entry(name='catmanager', group='WEB Access', proxy_enabled=True,
              allowed_groups=['WEB Access']),
    ]}
    assert [card['name'] for card in home.application_cards(config, 'server', {'WEB Access'})] == ['catmanager']
    assert sorted(card['name'] for card in home.application_cards(config, 'server', {'*'})) == [
        'catmanager', 'legacy-lan-app', 'published-without-policy']
    assert [card['name'] for card in home.application_cards(config, 'server', {'Personal'})] == [
        'legacy-lan-app']


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


def test_session_cookie_security_follows_the_effective_request_scheme(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'portal_auth_enabled': True, 'applications': []}))

    local_response = home.create_app(path).test_client().get('/login')
    public_response = home.create_app(path).test_client().get(
        '/login', headers={'X-Forwarded-Proto': 'https'})

    assert 'Secure' not in local_response.headers['Set-Cookie']
    assert 'HttpOnly' in local_response.headers['Set-Cookie']
    assert 'Secure' in public_response.headers['Set-Cookie']
    assert 'HttpOnly' in public_response.headers['Set-Cookie']


def admin_client(tmp_path):
    identity = tmp_path / 'identity.db'
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({
        'portal_auth_enabled': True,
        'portal_secret_key': 'test-secret',
        'identity_db': str(identity),
        'groups': ['Personal', 'Development'],
        'applications': [entry(name='allocraft', display_name='Allocraft',
                               group='Personal', proxy_enabled=True,
                               allowed_groups=['Personal'])],
    }))
    db = home.connect(identity)
    db.executemany(
        'INSERT INTO users(email,password_hash,verified,groups_json,is_admin,created_at) VALUES (?,?,?,?,?,?)',
        [
            ('admin@example.com', 'unused', 1, '["Personal"]', 1, 1),
            ('member@example.com', 'unused', 1, '[]', 0, 2),
        ],
    )
    db.commit()
    app = home.create_app(config)
    client = app.test_client()
    with client.session_transaction() as session:
        session['user'] = 'admin@example.com'
    return client, identity


def test_admin_user_list_links_to_separate_detail_pages(tmp_path):
    client, _ = admin_client(tmp_path)
    listing = client.get('/admin/users')

    assert listing.status_code == 200
    assert b'admin@example.com' in listing.data
    assert b'member@example.com' in listing.data
    assert b'href="/admin/users/member@example.com"' in listing.data
    assert b'Allowed UDA groups' not in listing.data

    detail = client.get('/admin/users/member@example.com')
    assert detail.status_code == 200
    assert b'Back to users' in detail.data
    assert b'member@example.com' in detail.data
    assert b'admin@example.com' not in detail.data
    assert b'Allowed UDA groups' in detail.data
    assert b'Allocraft' in detail.data


def test_admin_user_detail_updates_only_selected_user(tmp_path):
    client, identity = admin_client(tmp_path)
    client.get('/admin/users/member@example.com')
    with client.session_transaction() as session:
        csrf = session['csrf']
    response = client.post('/admin/users/member@example.com', data={
        'csrf': csrf,
        'verified': '1',
        'groups': ['Personal'],
    })

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/admin/users/member@example.com')
    user = home.connect(identity).execute(
        'SELECT verified,groups_json FROM users WHERE email=?', ('member@example.com',)
    ).fetchone()
    assert user['verified'] == 1
    assert json.loads(user['groups_json']) == ['Personal']


def test_admin_user_pages_require_an_administrator(tmp_path):
    client, _ = admin_client(tmp_path)
    with client.session_transaction() as session:
        session['user'] = 'member@example.com'
    assert client.get('/admin/users').status_code == 403
    assert client.get('/admin/users/admin@example.com').status_code == 403
