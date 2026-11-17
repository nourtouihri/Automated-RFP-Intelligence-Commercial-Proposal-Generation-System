"""Standalone app for the demo: uvicorn insights_agent.app:app --reload

Same envelope and X-Request-ID contract as the other services. To plug the
agent into the team's app instead, add one line there:
    from insights_agent.api import router; app.include_router(router)
"""

from dotenv import load_dotenv
from fastapi import FastAPI

from insights_agent.api import router
from shared.errors import install

load_dotenv()

app = FastAPI(title="OliveSoft Competitor & Budget Insights")
install(app)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(router)