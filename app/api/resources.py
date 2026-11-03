from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

from app.api.dependencies import ok, session_for
from app.core.exceptions import BusinessError
from app.schemas import DriverCreate, ShiftCode, ShiftUpdate, UnavailabilityCreate, VehicleCreate
from app.services.resource_service import ResourceService

router = APIRouter(prefix='/api', tags=['车队资源'])


@router.get('/shifts')
def shifts(request: Request):
    with session_for(request) as db:
        return ok(ResourceService(db).shifts())


@router.put('/shifts/{code}')
def update_shift(code: ShiftCode, payload: ShiftUpdate, request: Request):
    with session_for(request, write=True) as db:
        return ok(ResourceService(db).update_shift(code, payload))


@router.get('/drivers')
def drivers(request: Request):
    with session_for(request) as db:
        return ok(ResourceService(db).drivers())


@router.get('/vehicles')
def vehicles(request: Request):
    with session_for(request) as db:
        return ok(ResourceService(db).vehicles())


@router.get('/drivers/available')
def available_drivers(
    request: Request, work_date: Annotated[date, Query(alias='date')], shift: ShiftCode | None = None
):
    with session_for(request) as db:
        return ok(ResourceService(db).available('driver', work_date, shift))


@router.get('/vehicles/available')
def available_vehicles(
    request: Request,
    work_date: Annotated[date, Query(alias='date')],
    shift: ShiftCode | None = None,
    task_mode: Literal['TAG', 'ROAD'] | None = None,
):
    with session_for(request) as db:
        return ok(ResourceService(db).available('vehicle', work_date, shift, task_mode))


@router.get('/drivers/{identifier}')
def driver(identifier: int, request: Request):
    with session_for(request) as db:
        row = next((r for r in ResourceService(db).drivers() if r['id'] == identifier), None)
        if row is None:
            raise BusinessError('NOT_FOUND', '司机不存在', 404)
        return ok(row)


@router.get('/vehicles/{identifier}')
def vehicle(identifier: int, request: Request):
    with session_for(request) as db:
        row = next((r for r in ResourceService(db).vehicles() if r['id'] == identifier), None)
        if row is None:
            raise BusinessError('NOT_FOUND', '车辆不存在', 404)
        return ok(row)


@router.post('/drivers', status_code=201)
def create_driver(payload: DriverCreate, request: Request):
    with session_for(request, write=True) as db:
        return ok(ResourceService(db).save_driver(payload))


@router.put('/drivers/{identifier}')
def update_driver(identifier: int, payload: DriverCreate, request: Request):
    with session_for(request, write=True) as db:
        return ok(ResourceService(db).save_driver(payload, identifier))


@router.post('/vehicles', status_code=201)
def create_vehicle(payload: VehicleCreate, request: Request):
    with session_for(request, write=True) as db:
        return ok(ResourceService(db).save_vehicle(payload))


@router.put('/vehicles/{identifier}')
def update_vehicle(identifier: int, payload: VehicleCreate, request: Request):
    with session_for(request, write=True) as db:
        return ok(ResourceService(db).save_vehicle(payload, identifier))


@router.get('/{kind}/{identifier}/unavailability')
def unavailability(kind: Literal['drivers', 'vehicles'], identifier: int, request: Request):
    with session_for(request) as db:
        return ok(
            ResourceService(db).unavailability('driver' if kind == 'drivers' else 'vehicle', identifier)
        )


@router.post('/{kind}/{identifier}/unavailability', status_code=201)
def add_unavailability(
    kind: Literal['drivers', 'vehicles'], identifier: int, payload: UnavailabilityCreate, request: Request
):
    with session_for(request, write=True) as db:
        return ok(
            ResourceService(db).add_unavailability(
                'driver' if kind == 'drivers' else 'vehicle', identifier, payload
            )
        )


@router.delete('/unavailability/{identifier}')
def remove_unavailability(identifier: int, request: Request):
    with session_for(request, write=True) as db:
        ResourceService(db).delete_unavailability(identifier)
        return ok({'deleted': True})
