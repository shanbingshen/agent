from functools import lru_cache

from arthra.config import Settings, get_settings
from arthra.industrial_data.adapters.mock_file import MockFileIndustrialDataAdapter
from arthra.industrial_data.adapters.thingsboard import ThingsBoardIndustrialDataAdapter
from arthra.industrial_data.adapters.timeseries_api import (
    TimeSeriesApiIndustrialDataAdapter,
)
from arthra.industrial_data.service import IndustrialDataService
from arthra.thingsboard import ThingsBoardClient


def build_industrial_data_service(settings: Settings) -> IndustrialDataService:
    if settings.industrial_data_provider == "mock":
        adapter = MockFileIndustrialDataAdapter(settings.industrial_data_mock_file)
    elif settings.industrial_data_provider == "timeseries_api":
        adapter = TimeSeriesApiIndustrialDataAdapter(
            base_url=settings.timeseries_api_url,
            token=settings.timeseries_api_token,
            timeout=settings.timeseries_api_timeout,
        )
    else:
        adapter = ThingsBoardIndustrialDataAdapter(ThingsBoardClient(settings=settings))
    return IndustrialDataService(adapter)


@lru_cache
def get_industrial_data_service() -> IndustrialDataService:
    return build_industrial_data_service(get_settings())
