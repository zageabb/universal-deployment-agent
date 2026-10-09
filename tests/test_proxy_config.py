from proxy_config import render

def test_only_explicitly_published_apps_are_routed():
    config={'public_base_url':'https://tanyaanne.ddns.net','applications':[
      {'name':'catmanager','enabled':True,'proxy_enabled':True,'app_url':'http://127.0.0.1:5088/'},
      {'name':'tender-designer','enabled':True,'app_url':'http://127.0.0.1:5050/'}]}
    output=render(config)
    assert '/apps/catmanager/' in output and '127.0.0.1:5088' in output
    assert 'tender-designer' not in output
