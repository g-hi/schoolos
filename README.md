# SchoolOS

**Multi-tenant AI Operating System for International Schools**

SchoolOS is a backend platform that automates core school operations — timetabling, teacher substitution, parent communication, student pickup, social media monitoring — powered by AI and accessible through a single REST API.

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│                  Docker Compose                   │
│                                                   │
│  ┌─────────────┐  ┌──────────┐  ┌─────────────┐ │
│  │   gateway    │  │ postgres │  │    redis     │ │
│  │  FastAPI     │  │  16 +RLS │  │   7-alpine  │ │
│  │  :8000       │  │  :5432   │  │   :6379     │ │
│  └──────┬───────┘  └─────┬────┘  └─────────────┘ │
│         │                │                        │
│         └────────────────┘                        │
└──────────────────────────────────────────────────┘
```

| Layer | Technology |
|---|---|
| Web framework | FastAPI 0.135 + Uvicorn (async) |
| Database | PostgreSQL 16 with Row-Level Security |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| Cache/Queue | Redis 7 (reserved for future use) |
| AI/LLM | Groq (llama-3.1-8b-instant) via langchain-groq |
| Solver | Google OR-Tools CP-SAT for timetable optimization |
| PDF | fpdf2 for printable timetable export |
| Messaging | Twilio (WhatsApp/SMS) + SendGrid (email) |
| Runtime | Python 3.11, Docker Compose |

### Multi-Tenancy

Every request includes an `X-Tenant-Slug` header. PostgreSQL Row-Level Security ensures complete data isolation between schools. Each table has a `tenant_id` column with an RLS policy that filters rows automatically.

---

## Quick Start

### Prerequisites

- Docker Desktop
- Git

### 1. Clone and configure

```bash
git clone <repo-url> schoolos
cd schoolos
cp .env.example .env
# Edit .env — at minimum set GROQ_API_KEY for AI features
```

### 2. Start everything

```bash
docker compose up --build
```

This starts three containers:
- **schoolos_gateway** → `http://localhost:8000`
- **schoolos_postgres** → `localhost:5432`
- **schoolos_redis** → `localhost:6379`

### 3. Verify

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

### 4. Seed a tenant

The init SQL (`infra/postgres/init.sql`) creates the `greenwood` tenant automatically. Use `X-Tenant-Slug: greenwood` in all requests.

---

## API Endpoints

All endpoints require the `X-Tenant-Slug` header.

### System

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/tenant-info` | Tenant resolution test |
| GET | `/db-health` | Database connectivity test |

### Data Ingestion (`/ingest`)

| Method | Path | Description |
|---|---|---|
| POST | `/ingest/subjects` | Upload subjects CSV |
| POST | `/ingest/teachers` | Upload teachers CSV |
| POST | `/ingest/classes` | Upload classes CSV |
| POST | `/ingest/students` | Upload students CSV |
| POST | `/ingest/periods` | Upload periods CSV |

### Timetable (`/timetable`)

| Method | Path | Description |
|---|---|---|
| POST | `/timetable/upload` | Upload timetable entries CSV |
| GET | `/timetable/` | List timetable entries (filterable) |
| DELETE | `/timetable/{entry_id}` | Delete a timetable entry |
| POST | `/timetable/constraints` | Add a scheduling constraint |
| POST | `/timetable/constraints/nl` | Add constraint via natural language (Groq AI) |
| GET | `/timetable/constraints` | List all constraints |
| POST | `/timetable/generate` | Auto-generate timetable (OR-Tools solver) |
| GET | `/timetable/export/pdf` | Export timetable as PDF |
| GET | `/timetable/export/pdf/download` | Download timetable PDF |

### Teacher Substitution (`/substitution`)

| Method | Path | Description |
|---|---|---|
| POST | `/substitution/report` | Report absence → auto-find best substitute |
| GET | `/substitution/` | List substitution records |

Features: confidence scoring (0-100%), subject qualification matching, load balancing, dual-channel notifications (email + SMS).

### Parent Communication (`/communication`)

| Method | Path | Description |
|---|---|---|
| POST | `/communication/daily-digest` | Send daily digest to parents |
| POST | `/communication/broadcast` | Broadcast message to parents |
| GET | `/communication/log` | View message log |

Routes messages via each parent's preferred channel (WhatsApp, SMS, or email).

### Private Car Pickup (`/pickup`)

| Method | Path | Description |
|---|---|---|
| POST | `/pickup/request` | Request student pickup (GPS geofence validated) |
| POST | `/pickup/release/{request_id}` | Release student to parent |
| GET | `/pickup/log` | View pickup log |

GPS geofence validation — pickup requests outside the school radius are rejected.

### Dashboard (`/dashboard`)

| Method | Path | Description |
|---|---|---|
| GET | `/dashboard/summary` | Overview: teacher load, substitutions, pickups |
| GET | `/dashboard/teacher-load` | Per-teacher workload (flags >85% overloaded) |
| GET | `/dashboard/substitutions` | Substitution frequency by teacher and class |
| GET | `/dashboard/pickup-stats` | Pickup analytics by grade, avg release time |

### Audit Trail (`/audit`)

| Method | Path | Description |
|---|---|---|
| GET | `/audit/` | Browse immutable audit log |

Filters: `action`, `action_prefix`, `entity_type`, `entity_id`, `actor_id`, `actor_name`, `start_date`, `end_date`.

Tracked actions: `timetable.*`, `substitution.*`, `pickup.*`, `dashboard.viewed`, `social.*`.

### Social Media Analytics (`/social`)

| Method | Path | Description |
|---|---|---|
| POST | `/social/import` | Bulk import social mentions (JSON) |
| POST | `/social/analyze` | Run Groq AI sentiment + topic extraction |
| GET | `/social/report` | Weekly summary: sentiment, topics, trends, competitors |
| POST | `/social/crisis-check` | Detect negative spikes → alert leadership |
| GET | `/social/mentions` | Browse mentions (filter by platform, sentiment, competitor) |

---

## Project Structure

```
schoolos/
├── docker-compose.yml          # 3-container setup
├── pyproject.toml              # Python dependencies
├── .env.example                # Environment template
│
├── infra/
│   └── postgres/
│       └── init.sql            # Schema, RLS policies, seed data
│
├── shared/
│   ├── config.py               # Pydantic settings (reads .env)
│   ├── auth/
│   │   └── tenant.py           # X-Tenant-Slug → Tenant resolver
│   └── db/
│       ├── connection.py       # AsyncSession, set_tenant_context()
│       └── models.py           # 16 SQLAlchemy models
│
├── services/
│   └── gateway/
│       ├── Dockerfile
│       ├── main.py             # FastAPI app + 8 routers
│       ├── routers/
│       │   ├── ingest.py       # CSV data ingestion
│       │   ├── timetable.py    # Timetable CRUD + generation
│       │   ├── substitution.py # Teacher substitution engine
│       │   ├── communication.py# Parent messaging
│       │   ├── pickup.py       # Car pickup with geofence
│       │   ├── dashboard.py    # Principal analytics
│       │   ├── audit.py        # Audit log viewer
│       │   └── social.py       # Social media analytics
│       └── ai/
│           ├── constraint_parser.py  # NL → JSON constraints (Groq)
│           ├── solver.py             # OR-Tools CP-SAT scheduler
│           ├── pdf_export.py         # Timetable PDF generation
│           ├── notifier.py           # Teacher notifications (email/SMS)
│           ├── messenger.py          # Parent message routing
│           └── audit.py              # log_action() helper
│
├── samples/                    # Sample CSV files for testing
└── tests/                      # Test suite
```

## Data Models

16 models across the system:

| Model | Purpose |
|---|---|
| `Tenant` | School identity + settings (geofence config, etc.) |
| `User` | Parents, staff — with preferred communication channel |
| `Subject` | Academic subjects |
| `Teacher` | Staff with max weekly hours + max substitutions/week |
| `TeacherSubject` | Many-to-many: teacher qualifications |
| `Class` | Grade/section (e.g., "Grade 5A") |
| `Student` | Students linked to classes |
| `StudentParent` | Many-to-many: student-parent relationships |
| `Period` | Time slots (day + start/end time) |
| `TimetableEntry` | Scheduled class: teacher + subject + class + period |
| `TimetableConstraint` | Scheduling rules (no-teach windows, max hours, etc.) |
| `Substitution` | Absence records + assigned substitute + confidence score |
| `Message` | Communication log (all channels) |
| `PickupRequest` | Car pickup workflow with GPS coordinates |
| `AuditLog` | Immutable event trail |
| `SocialMention` | Social media posts with sentiment + topics |

---

## Environment Variables

Copy `.env.example` to `.env`. Key variables:

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `REDIS_URL` | No | Redis URL (default: `redis://localhost:6379/0`) |
| `GROQ_API_KEY` | For AI | Groq API key for NL constraints + sentiment analysis |
| `SECRET_KEY` | Production | JWT signing key |
| `TWILIO_ACCOUNT_SID` | For SMS | Twilio credentials |
| `TWILIO_AUTH_TOKEN` | For SMS | Twilio auth token |
| `SENDGRID_API_KEY` | For email | SendGrid API key |
| `APP_ENV` | No | `development` or `production` |

Messaging services degrade gracefully — if Twilio/SendGrid keys are missing, notifications log to stdout instead of failing.

---

## Common Commands

```bash
# Start
docker compose up --build

# Restart gateway (after code changes — hot-reload usually handles this)
docker compose restart gateway

# View logs
docker compose logs gateway --tail 50

# Access database
docker compose exec postgres psql -U schoolos_user -d schoolos

# Stop and wipe all data
docker compose down -v
```

---

## License

Private — all rights reserved.
