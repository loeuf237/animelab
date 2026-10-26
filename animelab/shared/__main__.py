"""Explicit shared-server entry point; never enables authentication implicitly."""
import argparse
import getpass
import os
from animelab.environment import getenv
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description='AnimeLab shared server and administrator recovery')
    parser.add_argument('--data-dir', type=Path,
        default=Path(os.getenv('ANIMELAB_SHARED_DIR', str(Path.home() / '.animelab-shared'))))
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create-admin', help='Create an administrator (password read securely)')
    create.add_argument('username')
    reset = commands.add_parser('reset-password', help='Local operator password recovery; revokes all sessions')
    reset.add_argument('username')
    serve = commands.add_parser('serve', help='Serve isolated account workspaces')
    serve.add_argument('--public-url', default=os.getenv('ANIMELAB_PUBLIC_URL', 'http://127.0.0.1:8080'))
    serve.add_argument('--host', default=getenv('ANIMAN_HOST', '127.0.0.1'))
    serve.add_argument('--port', type=int, default=int(getenv('ANIMAN_PORT', '8080')))
    serve.add_argument('--max-engines', type=int, default=int(os.getenv('ANIMELAB_MAX_ENGINES', '4')))
    serve.add_argument('--session-hours', type=int, default=12)
    serve.add_argument('--idle-minutes', type=int, default=30)
    from animelab.browser_settings import add_browser_arguments, apply_browser_arguments
    add_browser_arguments(serve)
    args = parser.parse_args()
    if args.command == 'serve': apply_browser_arguments(args)
    if getattr(sys, 'frozen', False):
        parser.error('Shared server is available from the Python source installation or Docker image')
    os.umask(0o077)
    from animelab.shared.accounts import Accounts
    store = Accounts(args.data_dir)
    try:
        if args.command == 'serve':
            import uvicorn
            from animelab.shared.gateway import SharedConfig, create_app
            config = SharedConfig(args.data_dir, args.public_url, args.max_engines, args.session_hours, args.idle_minutes)
            uvicorn.run(create_app(config, accounts=store), host=args.host, port=args.port,
                proxy_headers=False, access_log=False, timeout_graceful_shutdown=25)
            return
        password = getpass.getpass('Password (12–256 characters): ')
        if password != getpass.getpass('Confirm password: '):
            parser.error('Passwords do not match')
        if args.command == 'create-admin':
            store.create(args.username, password, admin=True)
            print('Administrator created.')
        else:
            user = next((user for user in store.users() if user['username'] == args.username.lower()), None)
            if not user:
                parser.error('Account not found')
            store.update(user['id'], password=password)
            print('Password updated; previous sessions revoked.')
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
