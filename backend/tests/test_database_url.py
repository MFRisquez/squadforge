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
