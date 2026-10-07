# AutoFlow

Backend for an automotive dealership and service management platform, built with
Django, Django REST Framework and PostgreSQL.

## Phase 1 – Core Domain & Database Layer

### Implemented

**Project structure**
- `config/` – Django settings, root URLconf, WSGI/ASGI entry points
- `apps/core/` – Modular monolith with separation of concerns:
  - `models/` – 13 domain models grouped by aggregate
  - `repositories/` – Database access layer (one class per aggregate)
  - `services/` – Business logic & transaction boundaries
  - `serializers/` – Request/response shapes & input validation
  - `views/` – Thin HTTP layer
  - `tests/` – Model, repository, service and API tests (109 total)

**Core domain models** (13)
| Model | Purpose |
|-------|---------|
| `Dealership` | Dealership locations |
| `Employee` | Staff (ADMIN, EMPLOYEE, TECHNICIAN) – ready for external auth via `external_user_id` |
| `TechnicianProfile` | Technician specialization & availability |
| `CustomerProfile` | Customers – no auth fields, ready for external auth |
| `CustomerVehicle` | Vehicle owned by a customer (registration, mileage, purchase date) |
| `Vehicle` | Dealership inventory (brand, model, variant, year, fuel, transmission, price, stock) |
| `Appointment` | Generic appointments (TEST_DRIVE, SERVICE, REPAIR, CONSULTATION) |
| `TestDrive` | Test-drive specifics linked to an Appointment + Vehicle |
| `ServiceRequest` | Service/repair work linked to a CustomerVehicle (and optional Appointment) |
| `TechnicianAssignment` | Technician → ServiceRequest with status lifecycle |
| `ServiceRecord` | Completed work record with parts/labor/total costs |
| `Invoice` | Invoice for a ServiceRecord (subtotal, tax, total, status) |
| `Feedback` | Customer rating (1–5) + comment per ServiceRecord |

**Database design**
- Proper FKs with `on_delete=PROTECT/CASCADE` for data integrity
- Unique constraints (inventory per dealership, registration numbers, one active assignment per technician, one invoice per service record, one feedback per customer+service record)
- Check constraints (non-negative prices/costs, rating 1–5, invoice total = subtotal + tax)
- Indexes on frequently queried columns (status+date, dealership+date, vehicle+date)
- DecimalField for all monetary values

**Repository layer** (7 classes)
- `DealershipRepository` – CRUD + active listing
- `CustomerRepository` / `CustomerVehicleRepository` – lookup by email/registration, listing by customer
- `VehicleRepository` – available listing with brand/dealership filters, CRUD
- `AppointmentRepository` / `TestDriveRepository` – listing by customer/status/date, test-drive lookup
- `TechnicianRepository` – available technicians by specialization
- `ServiceRequestRepository` / `TechnicianAssignmentRepository` / `ServiceRecordRepository` – status filtering, active assignment lookup
- `InvoiceRepository` / `FeedbackRepository` – lookup by number/service record/customer

**Service layer** (6 classes)
- `CustomerService` – register customer, register sale (reduces stock atomically)
- `VehicleService` – add inventory (unique constraint handling), get available
- `AppointmentService` – schedule/test-drive, state transitions (PENDING→CONFIRMED→IN_PROGRESS→COMPLETED/CANCELLED)
- `ServiceRequestService` – submit, confirm/cancel, assign/start/complete technician, complete with service record creation
- `InvoiceService` – generate (with tax calc), issue, mark paid
- `FeedbackService` – submit (validates ownership), list

**API endpoints**
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health/` | Liveness check → `{"status":"ok"}` |
| GET | `/api/vehicles/available/` | Inventory with `?brand=` and `?dealership=` filters |
| GET | `/api/appointments/` | Filter by `customer_id` or `status` (and `scheduled_date`) |
| POST | `/api/appointments/test-drives/` | Book a test drive (validates vehicle availability) |
| GET | `/api/service-requests/` | Filter by `status` |
| POST | `/api/service-requests/` | Raise a service request |
| GET | `/api/me/` | Current user context (role, dealership, `can_manage_inventory`) |
| GET | `/api/customer/vehicles/` | Customer's own `CustomerVehicle` records |
| POST | `/api/customer/vehicles/` | Register a customer-owned vehicle |
| GET | `/api/vehicles/` | Showroom inventory (OWNER/ADMIN), `?search=` |
| POST | `/api/vehicles/` | Add a showroom vehicle (OWNER/ADMIN) |
| GET | `/api/vehicles/<id>/` | Inventory vehicle detail (OWNER/ADMIN) |
| PATCH | `/api/vehicles/<id>/` | Update price/stock/availability/specs (OWNER/ADMIN) |
| DELETE | `/api/vehicles/<id>/` | Deactivate a showroom vehicle (OWNER/ADMIN) |

**Django Admin** – All 13 models registered with list_display, filters, search, and select_related

**Tests** – 109 tests covering:
- Model creation, relationships, constraints, cascade/protect behavior
- Repository query methods
- Service business logic, transitions, error handling
- API serialization, validation, error responses

---

## Phase 2 – Supabase Authentication + RBAC

### Implemented

**Authentication**
- Custom DRF authentication class: `SupabaseJWTAuthentication`
- Verifies Supabase JWT access tokens via JWKS endpoint
- Extracts `sub` claim and maps to local `CustomerProfile` or `Employee` via `external_user_id`
- Returns `SupabaseUser` context with role, profile, and dealership scoping

**Environment Configuration**
- `SUPABASE_URL` – Supabase project URL (used for issuer validation)
- `SUPABASE_JWKS_URL` – JWKS endpoint for JWT verification (e.g., `https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json`)

**RBAC Permission Classes**
| Permission | Allowed Roles |
|------------|---------------|
| `IsAuthenticated` | Any authenticated user |
| `IsCustomer` | CUSTOMER |
| `IsEmployee` | EMPLOYEE, TECHNICIAN, ADMIN |
| `IsTechnician` | TECHNICIAN |
| `IsAdmin` | ADMIN |
| `IsOwner` | OWNER |
| `IsOwnerOrAdmin` | OWNER, ADMIN |
| `IsEmployeeOrAdmin` | EMPLOYEE, TECHNICIAN, ADMIN, OWNER |
| `IsTechnicianOrAdmin` | TECHNICIAN, ADMIN |
| `IsCustomerOrEmployeeOrAdmin` | CUSTOMER, EMPLOYEE, TECHNICIAN, ADMIN |

**Object-Level Authorization**
- `CanAccessCustomerResource` – Customers access own resources; employees access dealership-scoped resources
- `IsDealershipMember` – Employee dealership scoping via query param
- `IsTechnicianAssigned` – Technicians access only assigned service requests
- `IsOwner` – Generic ownership checks

**API Protection**
- Public endpoints: `/api/health/`, `/api/vehicles/available/`
- Protected endpoints (require valid Supabase JWT):
  - `POST /api/appointments/test-drives/` – Customer only
  - `GET /api/appointments/` – Customer (own) or Employee (all)
  - `POST /api/service-requests/` – Customer only (own vehicles)
  - `GET /api/service-requests/` – Customer (own) or Employee/ADMIN (all)

**Role Mapping** (from Neon, not Supabase claims)
| Local Role | Source |
|------------|--------|
| CUSTOMER | `CustomerProfile.external_user_id` match |
| EMPLOYEE | `Employee.role=EMPLOYEE` |
| TECHNICIAN | `Employee.role=TECHNICIAN` (+ `TechnicianProfile`) |
| ADMIN | `Employee.role=ADMIN` |
| OWNER | `Employee.role=OWNER` (max one per dealership) |

Role is always resolved from the local database via the verified token `sub`.
Client-supplied `role`/`app_metadata`/`user_metadata` fields are ignored.

---

## Showroom Inventory & Owner Provisioning

### INR pricing
Prices are stored as `Decimal` numeric values, never formatted strings.
The frontend renders them with `Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' })`
through `formatMoney()` in `apps/core/static/js/common.js`.

### Seeding the showroom
Idempotent — safe to run repeatedly, never duplicates or overwrites existing rows:
```powershell
python manage.py seed_showroom_inventory
python manage.py seed_showroom_inventory --dealership-id 1
```
Seeds 25 variants across 20 Indian-market models (Wagon R, Swift, Brezza, Grand Vitara,
Punch, Nexon, Harrier, Safari, Creta, Verna, Venue, Thar, Scorpio-N, XUV700, Fortuner,
Innova HyCross, Seltos, Virtus, Slavia, Defender 110) with demo INR prices, varied
fuel/transmission/seating/year/stock. Demo pricing only — not official prices.

### Inventory management UI
`/inventory/` (AutoFlow app UI, separate from Django admin at `/admin/`).
Owner/Admin only: search, availability filter, add, edit, deactivate.
Backend enforces OWNER/ADMIN regardless of what the UI renders.

### Owner provisioning
There is no public "sign up as Owner" flow — public registration always creates a CUSTOMER.
The single Owner per dealership is created with:
```powershell
python manage.py create_owner --first-name Nikhil --last-name Sharma `
    --email owner@example.com --password <strong-password> --dealership-id 1
```
Or create the dealership at the same time:
```powershell
python manage.py create_owner --first-name Nikhil --last-name Sharma `
    --email owner@example.com --password <strong-password> `
    --dealership-name "AutoFlow Motors Baner" --address "21 Baner Road" `
    --city Pune --state Maharashtra --postal-code 411045 `
    --phone 9822001100 --dealership-email baner@example.com
```
Link an already-existing Supabase user instead of creating one:
```powershell
python manage.py create_owner --first-name Nikhil --last-name Sharma `
    --email owner@example.com --supabase-user-id <supabase-uuid>
```
The command refuses before touching Supabase when the dealership already has an owner
or the email is taken, and rolls the local row back if the Supabase signup fails.

**One-owner rule** is enforced twice:
- Database: partial unique constraint `uniq_owner_per_dealership` on `Employee(dealership)` where `role='OWNER'`
- Application: `EmployeeService.create_owner` checks and converts races to `409 Conflict`

### Role rules for inventory
| Role | Read available inventory | Read `/api/vehicles/` | Write `/api/vehicles/` |
|------|------------------------|----------------------|------------------------|
| CUSTOMER | yes | 403 | 403 |
| TECHNICIAN | yes | 403 | 403 |
| EMPLOYEE | yes | 403 | 403 |
| ADMIN | yes | yes | yes |
| OWNER | yes | yes | yes |

Customers register vehicles only as `CustomerVehicle` via `/api/customer/vehicles/`.
Test drives reference showroom `Vehicle`; service requests reference `CustomerVehicle`.

### Role rules for the dashboard
| Role | Dashboard data source | `/api/dashboard/` |
|------|------------------------|-------------------|
| CUSTOMER | own appointments, service requests and customer vehicles | 403 |
| EMPLOYEE | own dealership summary | 200 |
| TECHNICIAN | own dealership summary | 200 |
| ADMIN | own dealership summary | 200 |
| OWNER | own dealership summary | 200 |

`/api/dashboard/` is scoped to the caller's own dealership and returns showroom
inventory, in-stock count, upcoming appointments, upcoming test drives and the
eight most recent appointments for that dealership.

---

## Setup & Run Commands

### 1. Prerequisites
- Python 3.11+
- PostgreSQL database (external, e.g., Neon, Supabase, RDS)
- `DATABASE_URL` in `postgresql://user:pass@host/db?sslmode=require` format
- Supabase project for authentication

### 2. Create virtual environment & install dependencies
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
`requirements.txt`:
```
Django==6.0
djangorestframework==3.18.1
psycopg[binary]==3.3.6
dj-database-url==3.1.2
python-dotenv==1.2.3
python-jose[cryptography]==3.3.0
httpx==0.27.2
```

### 3. Configure environment
```powershell
Copy-Item .env.example .env
```
Edit `.env` with your values:
```
DEBUG=True
SECRET_KEY=your-django-secret-key
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
DATABASE_SSL=True
TIME_ZONE=UTC

SUPABASE_URL=https://your-project.supabase.co
SUPABASE_JWKS_URL=https://your-project.supabase.co/auth/v1/.well-known/jwks.json
```
> **Never commit `.env`** – it's in `.gitignore`.

Generate a secret key:
```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 4. Run database migrations
```powershell
python manage.py makemigrations core
python manage.py migrate
```
Verify no pending migrations:
```powershell
python manage.py makemigrations --check --dry-run
```

### 5. Link Supabase users to local profiles
Customers are auto-provisioned on first authenticated request, so public signup needs no manual step.

Staff and owners are provisioned explicitly. Employees via Django admin, or the single Owner per dealership via:
```powershell
python manage.py create_owner --first-name Nikhil --last-name Sharma `
    --email owner@example.com --password <strong-password> --dealership-id 1
```

For remaining roles, create the Supabase Auth user, then link it:
```python
# Employee
Employee.objects.create(
    external_user_id="supabase-user-uuid",
    dealership=dealership,
    email="staff@example.com",
    first_name="Jane",
    last_name="Smith",
    role=EmployeeRole.TECHNICIAN,
    ...
)
```

### 6. Run the development server
```powershell
python manage.py runserver
```
Server starts at `http://127.0.0.1:8000/`

### 7. Verify endpoints
```powershell
# Health check (public)
Invoke-RestMethod http://127.0.0.1:8000/api/health/

# Available vehicles (public)
Invoke-RestMethod "http://127.0.0.1:8000/api/vehicles/available/"

# Protected endpoints require Authorization: Bearer <supabase_access_token>
$headers = @{ Authorization = "Bearer $supabaseAccessToken" }

# Customer creates test drive
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/appointments/test-drives/" `
    -Headers $headers -Body (@{ dealership_id=1; vehicle_id=1; scheduled_date="2026-10-10"; scheduled_time="10:00:00" } | ConvertTo-Json) `
    -ContentType "application/json"

# Customer lists own appointments
Invoke-RestMethod -Headers $headers "http://127.0.0.1:8000/api/appointments/"

# Employee lists all appointments
Invoke-RestMethod -Headers $headers "http://127.0.0.1:8000/api/appointments/?status=PENDING"

# Dealership dashboard summary (EMPLOYEE, TECHNICIAN, ADMIN, OWNER)
Invoke-RestMethod -Headers $headers "http://127.0.0.1:8000/api/dashboard/"
```

### 8. Run the test suite
```powershell
python manage.py test
```
- 150 tests (109 Phase 1 + 41 Phase 2), runs against the configured PostgreSQL database
- Use `--keepdb` to reuse the test database between runs:
  ```powershell
  python manage.py test --keepdb
  ```

### 9. Static files (if needed later)
```powershell
python manage.py collectstatic
```

### 10. Code quality checks
```powershell
python -m pyflakes apps config manage.py
```

---

## YourSpinny – Dynamic AI Vehicle Assistant

A natural-language showroom assistant for customers. The user's question decides
what is queried and what is answered — there is no fixed list of hardcoded
questions or responses.

### Flow
```
User natural-language question
    ↓
Fast Path (query_matcher) — deterministic local matcher
    ↓ high-confidence?  ┌── no ──────────────┐
  yes ↓                 │  Gemini extracts structured intent + filters (JSON)
        │               ↓
        │      (also used when Fast Path can't resolve)
        ↓               ↓
Django validates the structure (intent_parser.validate_intent — SAME validator for both paths)
    ↓
VehicleRepository.search(...) → Django ORM → Neon
    ↓
Django determines the factual result (search / recommendation / comparison)
    ↓
Answer: Fast Path uses deterministic templates; Gemini generates a descriptive
answer from ONLY the verified result (fast-path results never call Gemini)
    ↓
Frontend renders the answer + matching vehicles / one pick / comparison
```

- **Two independent intent sources, one validated contract.** The Fast Path
  (`apps/core/services/query_matcher.py`) deterministically resolves common,
  high-confidence queries (**zero Gemini calls**): "car under 2000000",
  "20 lakh ke andar car", "Honda cars", "automatic cars", "3 or 5 seater",
  "cars between 10 and 15 lakh", "cheapest Honda", exclusions ("but not diesel"),
  brand/model names, availability and info questions. Everything it cannot
  resolve with confidence falls back to Gemini. Both emit the *same* canonical
  intent and both are validated by `intent_parser.validate_intent` before
  anything reaches the ORM — so the downstream service/repository pipeline is
  unchanged.
- **Cost & latency control.** Common queries perform zero Gemini calls and zero
  redundant DB queries. Inventory brand/model lookups are lazy and memoised;
  a pure-vocabulary query ("car under 20 lakh") never touches the inventory
  lookup at all.
- **Deterministic answers on the Fast Path.** Fast Path intents always render
  with fixed Django templates (or the small built-in FAQ for general questions),
  so a matched query can never produce an invented answer.
- **General knowledge, never inventory lies.** "What is ABS/CVT?" is answered
  from a built-in FAQ (or Gemini, when available) and never treated as an
  inventory search. A vehicle that is not in the showroom ("tell me about Maruti
  Ertiga") gets a truthful general answer — never "no vehicles found" and never
  a silent list of every other car.
- **Observability.** Every response includes `processing_path`
  (`fast_path` | `gemini_fallback`) and `intent_source` (`local` | `gemini`).
- **Gemini** understands language and explains results; it never supplies facts.
- **Django + Neon** own all data: every filter becomes an ORM lookup
  (`price__lte`, `seating_capacity`, `fuel_type`, `manufacturing_year`, ordering…).
- If Gemini fails (503/429/timeout/invalid JSON) *after* the Fast Path falls
  through, a deterministic fallback parser handles common expressions (price
  ranges, seating, fuel, transmission, year, cheapest/most expensive) so queries
  keep working. Fast Path queries keep working even when Gemini is fully offline.

### Supported dynamic filters
`price_min` / `price_max` (lakh–rupee conversion, ranges like "between 5 and 10 lakh"),
`brand`, `model`, `variant`, `manufacturing_year`, `year_min`/`year_max`,
`fuel_type` (PETROL/DIESEL/CNG/ELECTRIC/HYBRID),
`transmission` (MANUAL/AUTOMATIC/AMT/CVT/DCT) or `transmission_group` for generic
"automatic"/"manual", `seating_capacity` (exact), plus `sort` (`price_asc`/`price_desc`).
Explicit requirements are hard filters: a vehicle that violates one is never shown
as an exact match, and zero matches return an honest no-match answer instead of
unrelated vehicles.

### Intents
| Intent | Example | Response |
|--------|---------|----------|
| `SEARCH` | "cars under 10 lakh" | answer + all matching vehicles |
| `RECOMMENDATION` | "which car should I buy under 15 lakh?" | answer + ONE ranked pick |
| `COMPARISON` | "compare Honda City and Hyundai Verna" | comparison + table + ONE winner |
| `INFO` | "tell me about Honda City" | descriptive answer + that vehicle's records |
| `UNKNOWN` | greetings / off-topic | guidance message, no invented data |

Follow-ups ("only automatic") work statelessly: the frontend sends the previous
turn's filters as `context_filters`, Django validates and merges them per category
(`NEW_SEARCH` drops the old filters; `FOLLOW_UP` replaces only the category the
new utterance mentions). The response also reports `query_type`
(INVENTORY_SEARCH / RECOMMENDATION / COMPARISON / AVAILABILITY / VEHICLE_INFO /
GENERAL_INFO / GENERAL_COMPARISON / CLARIFICATION / OUT_OF_SCOPE),
`context_mode`, `processing_path`, `intent_source` and `exclusions`
(ORM `.exclude()`, never positive filters) — all additive to the existing
`intent` / `filters` / `results` contract.

### Endpoints (customer only, `IsAuthenticated` + `IsCustomer`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/yourspinny/ask/` | Unified dynamic query (intent, answer, results, recommendation, comparison) |
| POST | `/api/yourspinny/recommendations/` | Recommendations for a query (compat) |
| POST | `/api/yourspinny/query/` | Answer + matches for a query (compat) |
| POST | `/api/yourspinny/compare/` | Compare 2–3 selected vehicle ids (compat) |

Security: client-supplied `dealership_id`, roles, and Gemini output are never
trusted — Django validates every value before it reaches the ORM.

---

## Request Flow

### Authentication
```
HTTP Request
    → DRF Authentication Class (SupabaseJWTAuthentication)
    → Supabase JWT verification via JWKS
    → Local identity lookup (external_user_id)
    → SupabaseUser context attached to request.user
```

### Authorization
```
Request
    → Permission Class
    → Role / Ownership / Dealership checks
    → View
    → Serializer
    → Service
    → Repository
    → Django ORM → Neon PostgreSQL
```

**Rules enforced:**
- Views: HTTP concerns only, no business logic, no direct ORM
- Serializers: validation + (de)serialization only
- Services: business logic, transactions, coordinates repositories
- Repositories: all ORM queries, no business decisions
- Models: data + relationships, minimal methods

---

## Next Phases (not implemented yet)
- Phase 4: Employee/technician management, technician assignment UI, work orders
- Phase 5: Notifications, AI features, payments, advanced workflows
- Phase 6: Deployment (Render, CI/CD, monitoring)