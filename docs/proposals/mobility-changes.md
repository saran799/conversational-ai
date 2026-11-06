# Proposal: Mobility Endpoints Alignment

## Overview
Worker 2 implemented the core mobility router in `backend/app/mobility/router.py`:
- `POST /api/mobility/routes/search`: Performs alias-based stop resolution, graph routing, enrichment (fare, distance, traffic advisories), and natural speech output in English/Tamil.
- `GET /api/mobility/stops/search`: Provides bilingual autocomplete for stops across bus, metro, and suburban train systems.
- `GET /api/mobility/diagnostics`: Admin diagnostics reporting dataset provenance, metadata, table counts, and integrity status.

## Shared File Changes Requested (for Integration Lead)
To expose these routes in the main application:
In `backend/app/main.py`:
```python
from backend.app.mobility.router import router as mobility_router

# In create_application():
app.include_router(mobility_router)
```

