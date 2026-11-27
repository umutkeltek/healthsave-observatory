"""GET ``/api/v2/owners`` — who this Observatory holds data for.

One Observatory per coach or clinic, one key per participant (migration
029). The web shell reads this to decide whether to show a participant
switcher (only when there is more than one owner) and what to call each
person. Admin only: ``server.api.access`` keeps it off participant keys
because it names every participant.

Additive v2 read — no v1 surface touched. SQL lives in
``storage.timescale.api_keys``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from storage.timescale.api_keys import list_owners

from .deps import get_session, verify_api_key

router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_api_key)])


class OwnerView(BaseModel):
    id: str
    label: str | None
    is_default: bool
    active: bool
    scopes: list[str]
    created_at: datetime | None
    last_ingest_at: datetime | None


class OwnersResponse(BaseModel):
    count: int
    owners: list[OwnerView]


@router.get("/owners", response_model=OwnersResponse)
async def owners(session: Any = Depends(get_session)) -> OwnersResponse:
    """The default owner first (``label`` null), then one entry per participant.

    A participant whose keys are all revoked stays listed with
    ``active: false``: revoking a key stops new data, it does not delete the
    person's history.
    """

    rows = await list_owners(session)
    return OwnersResponse(count=len(rows), owners=[OwnerView(**row) for row in rows])
