from prefect import flow


@flow(name="market-daily", retries=2, retry_delay_seconds=30)
def market_daily() -> None:
    return None
