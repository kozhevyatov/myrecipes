"""Isolated database/API fixture that never imports real application settings."""
from __future__ import annotations

import contextlib
import importlib
import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace

from fastapi import Request


@contextlib.contextmanager
def environment(*, router: bool = True):
    """Use only inside a subprocess so synthetic modules cannot affect other tests."""
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    with tempfile.TemporaryDirectory(prefix="myrecipes-admin-test-") as directory:
        root = Path(directory)
        uploads = root / "uploads"
        uploads.mkdir()
        config = ModuleType("app.config")
        config.DATA_DIR = root
        config.UPLOAD_DIR = uploads
        config.settings = SimpleNamespace(database_url=None, static_dir=root / "static")
        sys.modules["app.config"] = config

        security = ModuleType("app.security")

        def get_current_user(request: Request):
            role = request.headers.get("X-Fixture-Role")
            if role is None:
                raise HTTPException(401, "Fixture authentication required")
            return SimpleNamespace(id=1 if role == "admin" else 2, is_admin=role == "admin", is_active=True)

        def require_admin(request: Request):
            user = get_current_user(request)
            if not user.is_admin:
                raise HTTPException(403, "Fixture administrator required")
            return user

        security.get_current_user = get_current_user
        security.require_admin = require_admin
        sys.modules["app.security"] = security

        db = importlib.import_module("app.db")
        models = importlib.import_module("app.models")
        engine = db.make_engine(f"sqlite:///{root / 'fixture.sqlite'}")
        db._engine = engine
        db._SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        db.Base.metadata.create_all(engine)
        with db._SessionLocal() as session:
            session.add_all([
                models.User(id=1, username="fixture-admin", email="admin@example.test", display_name="Fixture admin",
                            password_hash="synthetic-fixture-hash", is_admin=True, is_active=True),
                models.User(id=2, username="fixture-member", email="member@example.test", display_name="Fixture member",
                            password_hash="synthetic-fixture-hash", is_admin=False, is_active=True),
            ])
            session.commit()
        fixture = SimpleNamespace(root=root, db=db, models=models, engine=engine)
        try:
            if router:
                routes = importlib.import_module("app.routers.imports")
                app = FastAPI()
                app.include_router(routes.router)
                fixture.routes = routes
                fixture.app = app
                with TestClient(app) as client:
                    fixture.client = client
                    yield fixture
            else:
                yield fixture
        finally:
            engine.dispose()


ADMIN = {"X-Fixture-Role": "admin"}
MEMBER = {"X-Fixture-Role": "member"}
