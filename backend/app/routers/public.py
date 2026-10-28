"""Рецепт по публичной ссылке — без входа в аккаунт."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..app_settings import get_setting
from ..db import get_db
from ..images import image_url
from ..models import Recipe
from ..schemas import IngredientOut, SharedRecipeOut
from .recipes import _nutrition, _photo, _steps_out, _total

router = APIRouter(prefix="/api/public", tags=["public"])


def shared_recipe(db: Session, token: str) -> Recipe | None:
    if not token or len(token) > 32:
        return None
    return db.scalar(select(Recipe).where(Recipe.share_token == token))


@router.get("/recipes/{token}", response_model=SharedRecipeOut)
def get_shared(token: str, db: Session = Depends(get_db)) -> SharedRecipeOut:
    r = shared_recipe(db, token)
    if not r:
        raise HTTPException(404, "Ссылка не работает: её выключили или рецепт удалён")
    return SharedRecipeOut(
        title=r.title,
        description=r.description,
        image_url=image_url(r.image),
        category=r.category.name if r.category else None,
        tags=[t.name for t in r.tags],
        servings=r.servings,
        prep_minutes=r.prep_minutes,
        cook_minutes=r.cook_minutes,
        total_minutes=_total(r),
        difficulty=r.difficulty,
        author=r.author.display_name or r.author.username,
        source_url=r.source_url,
        nutrition=_nutrition(r),
        ingredients=[
            IngredientOut(id=i.id, product=i.product.name, amount=i.amount, unit=i.unit, note=i.note, group=i.group_name)
            for i in r.ingredients
        ],
        steps=_steps_out(r),
        photos=[_photo(p.image) for p in r.photos],
        site_name=get_setting(db, "site_name"),
    )
