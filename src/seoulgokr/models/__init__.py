"""서울 provider typed models."""

from .citydata import CityData
from .common import SeoulApiResult
from .parking import ParkingLot, ParkingRealtime
from .subway import SubwayArrival, SubwayPosition
from .traffic import TrafficInfo

__all__ = [
    "CityData",
    "ParkingLot",
    "ParkingRealtime",
    "SeoulApiResult",
    "SubwayArrival",
    "SubwayPosition",
    "TrafficInfo",
]
