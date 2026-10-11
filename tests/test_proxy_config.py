from proxy_config import render

def test_only_explicitly_published_apps_are_routed():
    config={'public_base_url':'https://tanyaanne.ddns.net','applications':[
      {'name':'catmanager','enabled':True,'proxy_enabled':True,'app_url':'http://127.0.0.1:5088/'},
      {'name':'tender-designer','enabled':True,'app_url':'http://127.0.0.1:5050/'}]}
    output=render(config)
    assert '/apps/catmanager/' in output and '127.0.0.1:5088' in output
    assert 'tender-designer' not in output

def test_prefix_can_be_preserved_for_base_path_aware_apps():
    config={'public_base_url':'https://tanyaanne.ddns.net','applications':[
      {'name':'next-app','enabled':True,'proxy_enabled':True,'proxy_preserve_prefix':True,
       'proxy_slug':'next-app','app_url':'http://127.0.0.1:5077/'}]}
    output=render(config)
    assert '  handle /apps/next-app/* {' in output
    assert '  handle_path /apps/next-app/* {' not in output

def test_selected_asset_paths_can_strip_an_app_prefix():
    config={'public_base_url':'https://tanyaanne.ddns.net','applications':[
      {'name':'next-app','enabled':True,'proxy_enabled':True,'proxy_preserve_prefix':True,
       'proxy_strip_prefix_paths':['assets'],'proxy_slug':'next-app','app_url':'http://127.0.0.1:5077/'}]}
    output=render(config)
    asset_handler='  handle /apps/next-app/assets/* {'
    app_handler='  handle /apps/next-app/* {'
    assert asset_handler in output
    assert output.index(asset_handler) < output.index(app_handler)
    assert '    uri strip_prefix /apps/next-app' in output

def test_strip_prefix_paths_reject_caddy_syntax():
    config={'public_base_url':'https://tanyaanne.ddns.net','applications':[
      {'name':'unsafe','enabled':True,'proxy_enabled':True,
       'proxy_strip_prefix_paths':['assets/* { respond 200 }'],
       'app_url':'http://127.0.0.1:5077/'}]}
    try:
        render(config)
    except ValueError as exc:
        assert 'invalid proxy_strip_prefix_paths' in str(exc)
    else:
        raise AssertionError('unsafe proxy path was accepted')
