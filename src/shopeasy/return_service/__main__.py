import uvicorn

from shopeasy.shared.config import RETURN_SERVICE_PORT

if __name__ == "__main__":
    uvicorn.run(
        "shopeasy.return_service.app:app", port=RETURN_SERVICE_PORT, reload=True
    )
