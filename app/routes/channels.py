"""Alert channel CRUD + webhook test route."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..alerts import send_test_message
from ..auth import require_token
from ..database import get_db
from ..models import AlertChannel
from ..schemas import ChannelCreate, ChannelOut

router = APIRouter(prefix="/api/channels", tags=["channels"], dependencies=[Depends(require_token)])


@router.get("", response_model=list[ChannelOut])
def list_channels(db: Session = Depends(get_db)):
    return db.scalars(select(AlertChannel).order_by(AlertChannel.id)).all()


@router.post("", response_model=ChannelOut, status_code=201)
def create_channel(data: ChannelCreate, db: Session = Depends(get_db)):
    channel = AlertChannel(**data.model_dump())
    db.add(channel)
    db.commit()
    return channel


@router.delete("/{channel_id}", status_code=204)
def delete_channel(channel_id: int, db: Session = Depends(get_db)):
    channel = db.get(AlertChannel, channel_id)
    if channel is None:
        raise HTTPException(404, "channel not found")
    db.delete(channel)
    db.commit()


@router.post("/{channel_id}/test")
async def test_channel(channel_id: int, db: Session = Depends(get_db)):
    channel = db.get(AlertChannel, channel_id)
    if channel is None:
        raise HTTPException(404, "channel not found")
    ok = await send_test_message(channel)
    return {"ok": ok}
