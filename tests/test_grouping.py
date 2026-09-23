import json

import pytest

import dashboard
import home
from deploy_agent import DeployError, load_config
from ui_groups import DEFAULT_GROUP, application_group, configured_groups, group_summary


def entry(**values):
    base = {
        'name': 'example-app', 'enabled': True, 'auto_deploy': False,
        'repo_path': '/tmp/example-app', 'branch': 'main',
        'restart_command': ['true'], 'health_url': 'http://127.0.0.1:5999/health',
    }
    base.update(values)
    return base


def auth(client):
    return (
        {'Authorization': 'Basic YWRtaW46c2VjcmV0'},
        {'csrf_token': client.application.config['CSRF_TOKEN']},
    )


def test_group_helpers_default_and_sort_other_last():
    applications = [entry(group='Tools'), entry(name='ai-app', group='AI & Knowledge'), entry(name='plain')]
    assert application_group(applications[-1]) == DEFAULT_GROUP
    assert group_summary(applications) == [
        {'name': 'AI & Knowledge', 'count': 1},
        {'name': 'Tools', 'count': 1},
        {'name': DEFAULT_GROUP, 'count': 1},
    ]


def test_managed_group_order_and_legacy_import():
    config = {'groups': ['Engineering', 'AI & Automation'], 'applications': [
        entry(group='AI & Automation'), entry(name='legacy', group='Legacy Tools'), entry(name='plain'),
    ]}
    assert configured_groups(config) == ['Engineering', 'AI & Automation', 'Legacy Tools']
    assert group_summary(config['applications'], configured_groups(config), include_empty=True) == [
        {'name': 'Engineering', 'count': 0},
        {'name': 'AI & Automation', 'count': 1},
        {'name': 'Legacy Tools', 'count': 1},
        {'name': DEFAULT_GROUP, 'count': 1},
    ]


def test_home_cards_expose_configured_group():
    cards = home.application_cards({'applications': [entry(group='Engineering')]}, 'server.local')
    assert cards[0]['group'] == 'Engineering'


def test_home_api_respects_managed_group_order(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'groups': ['Zulu', 'Alpha'], 'applications': [
        entry(name='zulu', group='Zulu'), entry(name='alpha', group='Alpha'),
    ]}))
    response = home.create_app(config, 'server.local').test_client().get('/api/applications')
    assert [group['name'] for group in response.get_json()['groups']] == ['Zulu', 'Alpha']


def test_invalid_group_is_rejected(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'applications': [entry(group='   ')]}))
    with pytest.raises(DeployError, match='Group name must be a non-empty single-line value'):
        load_config(config)


@pytest.mark.parametrize('groups, message', [
    ('not-a-list', 'groups must be a list'),
    (['Tools', 'tools'], 'Duplicate group name'),
    ([DEFAULT_GROUP], 'reserved for ungrouped applications'),
    (['other'], 'reserved for ungrouped applications'),
])
def test_invalid_managed_groups_are_rejected(tmp_path, groups, message):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'groups': groups, 'applications': [entry()]}))
    with pytest.raises(DeployError, match=message):
        load_config(config)


def test_dashboard_renders_group_navigation(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'dashboard_token': 'secret', 'groups': ['Engineering'], 'applications': [
        entry(enabled=False, group='Engineering'), entry(name='plain-app', enabled=False),
    ]}))
    client = dashboard.create_app(config).test_client()
    response = client.get('/', headers={'Authorization': 'Basic YWRtaW46c2VjcmV0'})
    assert response.status_code == 200
    assert b'All applications' in response.data
    assert b'Manage groups' in response.data
    assert b'data-app-group="Engineering"' in response.data
    assert b'data-app-group="Other"' in response.data


def test_group_manager_imports_legacy_groups_when_creating(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'dashboard_token': 'secret', 'applications': [
        entry(enabled=False, group='Legacy'),
    ]}))
    client = dashboard.create_app(config).test_client()
    headers, data = auth(client)

    page = client.get('/groups', headers=headers)
    assert page.status_code == 200
    assert b'Legacy' in page.data
    response = client.post('/groups/create', headers=headers, data=data | {'name': 'New Group'})

    assert response.status_code == 302
    saved = json.loads(config.read_text())
    assert saved['groups'] == ['Legacy', 'New Group']


def test_group_manager_lifecycle_and_app_assignment(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({
        'dashboard_token': 'secret',
        'groups': ['Tools', 'Engineering'],
        'applications': [
            entry(name='one', enabled=False, group='Tools'),
            entry(name='two', enabled=False),
        ],
    }))
    client = dashboard.create_app(config).test_client()
    headers, data = auth(client)

    assert client.post('/groups/create', headers=headers, data=data | {'name': 'AI'}).status_code == 302
    assert client.post('/applications/two/group', headers=headers,
                       data=data | {'group': 'AI'}).status_code == 302
    assert client.post('/groups/rename', headers=headers,
                       data=data | {'old_name': 'AI', 'name': 'AI & Automation'}).status_code == 302
    assert client.post('/groups/reorder', headers=headers,
                       data=data | {'name': 'AI & Automation', 'direction': 'up'}).status_code == 302

    saved = json.loads(config.read_text())
    assert saved['groups'] == ['Tools', 'AI & Automation', 'Engineering']
    assert next(app for app in saved['applications'] if app['name'] == 'two')['group'] == 'AI & Automation'

    assert client.post('/groups/delete', headers=headers,
                       data=data | {'name': 'Tools'}).status_code == 302
    saved = json.loads(config.read_text())
    assert saved['groups'] == ['AI & Automation', 'Engineering']
    assert 'group' not in next(app for app in saved['applications'] if app['name'] == 'one')


def test_group_manager_rejects_reserved_duplicate_and_unknown_assignment(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({
        'dashboard_token': 'secret',
        'groups': ['Tools'],
        'applications': [entry(enabled=False)],
    }))
    client = dashboard.create_app(config).test_client()
    headers, data = auth(client)

    assert client.post('/groups/create', headers=headers,
                       data=data | {'name': DEFAULT_GROUP}).status_code == 400
    assert client.post('/groups/create', headers=headers,
                       data=data | {'name': 'tools'}).status_code == 409
    assert client.post('/applications/example-app/group', headers=headers,
                       data=data | {'group': 'Missing'}).status_code == 400


def test_group_manager_requires_csrf(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'dashboard_token': 'secret', 'applications': [entry(enabled=False)]}))
    client = dashboard.create_app(config).test_client()
    headers = {'Authorization': 'Basic YWRtaW46c2VjcmV0'}
    assert client.post('/groups/create', headers=headers, data={'name': 'Tools'}).status_code == 403
