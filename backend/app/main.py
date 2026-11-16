from fastapi import FastAPI

from .routers import admin, auth, profile, rides, wallet

app = FastAPI(title="Unaa API", version="0.1.0")
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(admin.router)
app.include_router(wallet.router)
app.include_router(rides.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True}
