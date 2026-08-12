from app.config import normalize_database_url


def test_normalize_render_postgres_url() -> None:
    assert (
        normalize_database_url("postgres://u:p@host:5432/db")
        == "postgresql+psycopg://u:p@host:5432/db"
    )
    assert (
        normalize_database_url("postgresql://u:p@host:5432/db")
        == "postgresql+psycopg://u:p@host:5432/db"
    )
    assert normalize_database_url("postgresql+psycopg://u:p@host/db").startswith(
        "postgresql+psycopg://"
    )
    assert normalize_database_url("sqlite:///./data/squadforge.db").startswith("sqlite:")


def test_normalize_supabase_adds_ssl() -> None:
    url = normalize_database_url(
        "postgresql://postgres.abc:secret@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
    )
    assert url.startswith("postgresql+psycopg://")
    assert "sslmode=require" in url
    assert "pooler.supabase.com" in url
