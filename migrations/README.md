# Schema changes

Run from the project root: `.\.venv\Scripts\python.exe -m alembic upgrade head`.

The initial migration freezes explicit table/index creation. Application startup does not recreate tables. Future changes require a new reviewed revision, not edits to 0001. Back up the database before upgrading. Preserve the `Money` storage contract (signed integer units of 1e-8) when changing types. Migration downgrades delete data; do not run them on a personal database without a backup and an explicit reason.

For future revisions use `alembic revision --autogenerate -m description` or author a numbered revision with `upgrade`/`downgrade` functions directly. Test upgrades on both an empty database and a copy of the prior schema before applying them to account data.
