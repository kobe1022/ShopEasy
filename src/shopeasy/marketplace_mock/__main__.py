import uvicorn

from shopeasy.shared.config import MARKETPLACE_MOCK_PORT

if __name__ == "__main__":
    uvicorn.run(
        "shopeasy.marketplace_mock.app:app", port=MARKETPLACE_MOCK_PORT, reload=True
    )
