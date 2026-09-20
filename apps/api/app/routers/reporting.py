from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from app.services.reporting import collect_weekly, interval

router = APIRouter(prefix='/reporting', tags=['reporting'])


@router.get('/weekly-status')
def weekly_status(
    since: datetime = Query(description='Inclusive ISO-8601 timestamp with timezone'),
    until: datetime | None = Query(default=None, description='Exclusive end, defaults to now; maximum interval 31 days'),
):
    try:
        start, end = interval(since, until)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return jsonable_encoder(collect_weekly(start, end))
