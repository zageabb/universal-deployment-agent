#!/usr/bin/env python3
"""Generate a Caddy ingress configuration from explicitly published UDA apps."""
from __future__ import annotations
import argparse
from pathlib import Path
from urllib.parse import urlsplit
from deploy_agent import load_config

def render(config: dict) -> str:
    host=urlsplit(config['public_base_url']).hostname
    if not host: raise ValueError('public_base_url must contain a hostname')
    lines=[f'{host} {{','  encode zstd gzip']
    for app in config['applications']:
        if not app.get('enabled') or not app.get('proxy_enabled'): continue
        slug=app.get('proxy_slug') or app['name']; target=app.get('app_url') or app.get('health_url')
        parts=urlsplit(target or '')
        if parts.scheme not in ('http','https') or not parts.hostname: raise ValueError(f"{app['name']} needs a valid app_url")
        origin=f'{parts.scheme}://{parts.hostname}' + (f':{parts.port}' if parts.port else '')
        lines += [f'  redir /apps/{slug} /apps/{slug}/ 308',f'  handle_path /apps/{slug}/* {{',
          '    forward_auth 127.0.0.1:5048 {',f'      uri /auth/check',f'      header_up X-UDA-App {app["name"]}',
          '      copy_headers X-UDA-User X-UDA-Groups','    }',f'    reverse_proxy {origin} {{',
          f'      header_up X-Forwarded-Prefix /apps/{slug}','    }','  }']
    lines += ['  handle {','    reverse_proxy 127.0.0.1:5048','  }','}']
    return '\n'.join(lines)+'\n'

def main():
    p=argparse.ArgumentParser(); p.add_argument('--config',required=True,type=Path); p.add_argument('--output',required=True,type=Path); args=p.parse_args()
    content=render(load_config(args.config.expanduser())); args.output.parent.mkdir(parents=True,exist_ok=True)
    if not args.output.exists() or args.output.read_text()!=content: args.output.write_text(content)
if __name__=='__main__': main()
