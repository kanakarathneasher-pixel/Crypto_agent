"""Validate hosted settings, migrate PostgreSQL, then serve a single worker."""
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def hosted_settings(environ):
    # Do not allow Render's ephemeral filesystem to become the account database.
    from sqlalchemy.engine import make_url

    try:
        database = make_url(environ.get('DATABASE_URL', ''))
        if database.drivername not in {'postgres', 'postgresql', 'postgresql+psycopg'}:
            raise ValueError()
        if not database.host or not database.database or not database.username:
            raise ValueError()
    except Exception:
        raise ValueError('Set DATABASE_URL to an external PostgreSQL connection string.') from None
    database = database.set(drivername='postgresql+psycopg')
    if 'sslmode' not in database.query:
        database = database.update_query_dict({'sslmode': 'require'})
    if database.query.get('sslmode') not in {'require', 'verify-ca', 'verify-full'}:
        raise ValueError('DATABASE_URL must require TLS (sslmode=require or stronger).')
    origin = environ.get('ALLOWED_ORIGIN', '')
    try:
        parsed = urlsplit(origin)
        valid_origin = (parsed.scheme == 'https' and parsed.hostname
                        and not parsed.username and not parsed.password
                        and not parsed.path and not parsed.query and not parsed.fragment)
    except ValueError:
        valid_origin = False
    if not valid_origin:
        raise ValueError('Set ALLOWED_ORIGIN to the exact HTTPS dashboard origin, without a trailing slash.')
    return database.render_as_string(hide_password=False)


def main():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    try:
        os.environ['DATABASE_URL'] = hosted_settings(os.environ)
        port = int(os.environ.get('PORT', '10000'))
        if not 1 <= port <= 65535:
            raise ValueError('PORT must be between 1 and 65535.')
    except ValueError as error:
        print(f'Orbit configuration error: {error}', file=sys.stderr)
        return 1
    # Render Free has no pre-deploy command. Migrate before the server is ready.
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True)
    os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'backend.main:app',
                            '--host', '0.0.0.0', '--port', str(port), '--workers', '1'])


if __name__ == '__main__':
    raise SystemExit(main())
