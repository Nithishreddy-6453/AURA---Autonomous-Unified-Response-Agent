from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(
    title="AURA Agent API",
    description="Autonomous Unified Response Agent API",
    version="0.1.0",
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "service": "aura-agent-api"},
    )
