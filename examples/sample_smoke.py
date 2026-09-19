"""공개 sample 키로 최소 endpoint만 확인하는 opt-in smoke 예제."""

from __future__ import annotations

import asyncio

from seoulgokr import SeoulOpenDataClient, SeoulOpenDataConfig


async def main() -> None:
    config = SeoulOpenDataConfig(
        api_key="sample",
        general_min_interval_seconds=0,
        realtime_min_interval_seconds=0,
        max_retries=0,
        timeout_seconds=15,
        allow_insecure_http=True,
    )
    async with SeoulOpenDataClient(config=config) as client:
        traffic = await client.traffic_info("1220003800")
        subway = await client.subway_arrivals("서울")
    if traffic.result_code != "INFO-000" or not traffic.items:
        raise RuntimeError("TrafficInfo sample smoke가 유효한 INFO-000 결과를 반환하지 않았습니다")
    if subway.result_code != "INFO-000" or not subway.items:
        raise RuntimeError("subway sample smoke가 유효한 INFO-000 결과를 반환하지 않았습니다")
    print("traffic", len(traffic.items), traffic.result_code)
    print("subway", len(subway.items), subway.result_code)


if __name__ == "__main__":
    asyncio.run(main())
