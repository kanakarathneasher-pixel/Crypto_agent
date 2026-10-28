import pytest
from sqlalchemy.engine import make_url
from scripts.render_start import hosted_settings


def settings(database='postgresql://orbit:example@db.example.com/orbit', **extra):
    return {'DATABASE_URL': database, 'ALLOWED_ORIGIN': 'https://orbit.example.com', **extra}


def test_postgres_driver_and_tls_preserve_connection_details():
    result = make_url(hosted_settings(settings('postgres://orbit:p%40ss@db.example.com:5432/orbit')))
    assert result.drivername == 'postgresql+psycopg'
    assert result.password == 'p@ss'
    assert result.port == 5432
    assert result.query['sslmode'] == 'require'


@pytest.mark.parametrize('database', ['', 'sqlite:///./crypto_agent.db', 'invalid',
                                    'postgresql:///orbit',
                                    'postgresql://orbit:secret@db.example.com/orbit?sslmode=disable'])
def test_ephemeral_or_invalid_database_is_rejected_without_disclosing_credentials(database):
    with pytest.raises(ValueError) as error:
        hosted_settings(settings(database))
    assert 'secret' not in str(error.value)


@pytest.mark.parametrize('origin', ['', 'http://localhost:3000', 'https://orbit.example.com/',
                                  'https://orbit.example.com/path', 'https://user:secret@orbit.example.com'])
def test_invalid_dashboard_origin_is_rejected(origin):
    with pytest.raises(ValueError):
        hosted_settings(settings(ALLOWED_ORIGIN=origin))
