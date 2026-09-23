import json

import pytest

import dashboard
import home
from deploy_agent import DeployError, load_config
from ui_groups import application_group, group_summary


def entry(**values):
    base = {
        'name': 'example-app', 'enabled': True, 'auto_deploy': False,
        'repo_path': '/tmp/example-app', 'branch': 'main',
        'restart_command': ['true'], 'health_url': 'http://127.0.0.1:5999/health',
    }
    base.update(values)
    return base


def test_group_helpers_default_and_sort_other_last():
    applications = [entry(group='Tools'), entry(name='ai-app', group='AI & Knowledge'), entry(name='plain')]
    assert application_group(applications[-1]) == 'Other'
    assert group_summary(applications) == [
        {'name': 'AI & Knowledge', 'count': 1},
        {'name': 'Tools', 'count': 1},
        {'name': 'Other', 'count': 1},
    ]


def test_home_cards_expose_configured_group():
    cards = home.application_cards({'applications': [entry(group='Engineering')]}, 'server.local')
    assert cards[0]['group'] == 'Engineering'


def test_invalid_group_is_rejected(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'applications': [entry(group='   ')]}))
    with pytest.raises(DeployError, match='group must be a non-empty string'):
        load_config(config)


def test_dashboard_renders_group_navigation(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'dashboard_token': 'secret', 'applications': [
        entry(enabled=False, group='Engineering'), entry(name='plain-app', enabled=False),
    ]}))
    client = dashboard.create_app(config).test_client()
    response = client.get('/', headers={'Authorization': 'Basic YWRtaW46c2VjcmV0'})
    assert response.status_code == 200
    assert b'All applications' in response.data
    assert b'data-app-group="Engineering"' in response.data
    assert b'data-app-group="Other"' in response.data
