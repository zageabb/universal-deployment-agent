from pathlib import Path
from portal_auth import authenticate, connect, consume_token, create_user, groups, issue_token

def test_user_password_groups_and_one_time_token(tmp_path: Path):
    db=connect(tmp_path/'identity.db')
    create_user(db,'Alice@Example.com','correct horse battery',groups=['Cat Managers'],verified=True)
    user=authenticate(db,'alice@example.com','correct horse battery')
    assert user and groups(user)=={'Cat Managers'}
    assert authenticate(db,'alice@example.com','wrong') is None
    token=issue_token(db,user['email'],'reset',60)
    assert consume_token(db,token,'reset')['email']=='alice@example.com'
    assert consume_token(db,token,'reset') is None
