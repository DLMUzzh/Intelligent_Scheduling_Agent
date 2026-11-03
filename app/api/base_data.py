from fastapi import APIRouter, Request

from app.api.foundation import identifier, query_fields
from app.core.responses import envelope
from app.schemas.base_data_queries import (
    CategoryQuery,
    DriverQuery,
    ResourceDateQuery,
    ResourceQuery,
    UnavailabilityQuery,
)
from app.services.base_data_queries import BaseDataQueries

router = APIRouter(prefix='/api/v1', tags=['基础资料'])


def list_response(request: Request, target_type: str, query_model):
    filters = query_model.model_validate(dict(request.query_params))
    result = BaseDataQueries(request.app.state.session_factory).list_records(target_type, filters)
    return envelope(request, data=result.data, revision=result.revision)


def detail_response(request: Request, target_type: str, object_id: str, *, dated: bool = False):
    work_date = None
    if dated:
        work_date = ResourceDateQuery.model_validate(dict(request.query_params)).work_date
    else:
        query_fields(request, set())
    result = BaseDataQueries(request.app.state.session_factory).detail(
        target_type, identifier(object_id), work_date
    )
    return envelope(request, data=result.data, revision=result.revision)


@router.get('/collection-categories')
def categories(request: Request):
    return list_response(request, 'CATEGORY', CategoryQuery)


@router.get('/drivers')
def drivers(request: Request):
    return list_response(request, 'DRIVER', DriverQuery)


@router.get('/drivers/{driver_id}')
def driver(request: Request, driver_id: str):
    return detail_response(request, 'DRIVER', driver_id, dated=True)


@router.get('/vehicles')
def vehicles(request: Request):
    return list_response(request, 'VEHICLE', ResourceQuery)


@router.get('/vehicles/{vehicle_id}')
def vehicle(request: Request, vehicle_id: str):
    return detail_response(request, 'VEHICLE', vehicle_id, dated=True)


@router.get('/resource-unavailability')
def unavailability_records(request: Request):
    return list_response(request, 'UNAVAILABILITY', UnavailabilityQuery)


@router.get('/resource-unavailability/{unavailability_id}')
def unavailability_record(request: Request, unavailability_id: str):
    return detail_response(request, 'UNAVAILABILITY', unavailability_id)
