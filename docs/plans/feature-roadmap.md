# Helvetic Feature Roadmap

## Status
Approved

## Summary
Implement the missing user-facing features of helvetic in four phases, ordered by complexity and dependency. Phases 1–3 are standard Django CRUD. Phase 4 improves the existing curl-based WiFi registration flow — a browser-initiated approach is architecturally impossible (CORS + forbidden Cookie header). Google Fit integration is out of scope.

## Assumptions
- Bootstrap 3.3.7 stays — no upgrade, no npm, no bundler
- Chart.js via CDN; measurement data served via a dedicated JSON endpoint (not inlined in templates)
- User management restricted to `is_staff` users only
- Google Fit integration is out of scope
- No new pip dependencies for any phase
- WiFi setup = improve existing curl UX only
- Weight stored in grams; display/export always in kg
- Height stored in mm; forms use cm (×10 / ÷10 on save/init)

## Out of Scope
- Google Fit integration
- Browser-initiated WiFi AP configuration (CORS/forbidden-header constraints; server not on scale's network)
- Password/email change UI (use Django built-ins at `/accounts/password_change/`)
- Scale sharing between users who aren't the owner
- Background tasks (Celery etc.)

---

## Phase 1 — Profile Management + CSV Export

### Profile Management UI

**New files:**
| File | Purpose |
|------|---------|
| `helvetic/forms.py` | `UserProfileForm`: height in cm, ASCII validator on `short_name` |
| `helvetic/views/profile.py` | `ProfileView`, `ProfileEditView` |
| `helvetic/templates/helvetic/profile.html` | Shows profile data + latest measurement |
| `helvetic/templates/helvetic/profile_edit.html` | Bootstrap 3 horizontal form |

**Modified files:**
| File | Change |
|------|--------|
| `helvetic/urls.py` | Add `/profile/` and `/profile/edit/` |
| `helvetic/templates/helvetic/base.html` | Add "My Profile" nav link; fix `<title>{{ title }}</title>` → `<title>{% block title %}helvetic{% endblock %}</title>` |

**Key decisions:**
- `ProfileView` redirects to `/profile/edit/` if no `UserProfile` exists for the user yet
- `ProfileEditView`: a single `View` that handles both create and update — call `get_or_create` in `post()`, pass existing instance to form if present
- `short_name`: `RegexValidator(r'^[A-Za-z0-9 ]+$')` on the form field (not model); UI note about 20-char limit
- Height: `IntegerField(label='Height (cm)')` in form; convert ×10 on save, ÷10 in `__init__`

---

### CSV Export

**Modified files:**
| File | Change |
|------|--------|
| `helvetic/views/webui.py` | Add `MeasurementExportView` |
| `helvetic/urls.py` | Add `/measurements/export.csv` |

No template — response is `HttpResponse(content_type='text/csv')` with `Content-Disposition: attachment`.

Columns: `date` (ISO 8601), `weight_kg` (3dp), `body_fat_pct`

---

## Phase 2 — Graphs + Scale Configuration

### Measurement Graphs

**New files:**
| File | Purpose |
|------|---------|
| `helvetic/views/measurements.py` | `MeasurementListView`, `MeasurementGraphView`, `MeasurementDataView` |
| `helvetic/templates/helvetic/measurement_list.html` | Paginated list: date, weight (kg), body fat % |
| `helvetic/templates/helvetic/measurement_graph.html` | Loads Chart.js from CDN; fetches `/measurements/data.json` |

**Modified files:**
| File | Change |
|------|--------|
| `helvetic/urls.py` | Add `/measurements/`, `/measurements/graph/`, `/measurements/data.json` |

**JSON endpoint** (`MeasurementDataView`):
```json
{
  "labels": ["2026-01-01", "2026-01-02"],
  "weight": [70.5, 70.2],
  "body_fat": [18.3, 18.1]
}
```
- Last 365 data points for current user
- String labels (avoids Chart.js time-axis adapter dependency)
- Weight: grams → kg (÷1000); body_fat: Decimal → float

**Optional migration:** `Index(fields=['user', 'when'])` on `Measurement.Meta`.

---

### Scale Configuration UI

**New files:**
| File | Purpose |
|------|---------|
| `helvetic/templates/helvetic/scale_edit.html` | Edit form for unit + user assignment |

**Modified files:**
| File | Change |
|------|--------|
| `helvetic/forms.py` | Add `ScaleConfigForm`: `unit` radio, `users` M2M checkbox; queryset scoped to owner's profiles |
| `helvetic/views/webui.py` | Add `ScaleEditView(LoginRequiredMixin, UpdateView)` |
| `helvetic/urls.py` | Add `/scales/<int:pk>/edit/` |
| `helvetic/templates/helvetic/scale_list.html` | Show battery %, SSID, firmware; add Edit link for owner |

**Security:** `get_object()` raises `PermissionDenied` if `obj.owner != request.user`. M2M queryset: `UserProfile.objects.filter(user=request.user)` — owner cannot assign profiles that belong to other users.

---

## Phase 3 — User Management

**Decision: skipped.** The deployment has only 2 users; the Django admin (`/admin/`) covers all user management needs without additional code.

---

## Phase 4 — WiFi Setup UX

Browser-initiated AP config is not viable: `fetch()` cannot set `Cookie` on foreign origins, and the server is not on the scale's network. The existing curl flow is correct; only the UX needs improvement.

**Status: implemented.** 68 tests passing.

**Modified files:**
| File | Change |
|------|--------|
| `helvetic/templates/helvetic/registration/register_curl.html` | Rewritten: SSID/PSK inputs, curl command in `<pre class="well">` with `encodeURIComponent()` encoding, one-click Clipboard API copy button |
| `helvetic/templates/helvetic/registration/register_status.html` | New: "Waiting for Aria…" page with JS `setTimeout(location.reload, 5000)` auto-refresh; manual fallback link to `/scales/` |
| `helvetic/views/registration.py` | `CurlRegistrationView.post()` stores `request.session['initial_scale_count']`; new `RegistrationStatusView` polls scale count and redirects on increase |
| `helvetic/urls.py` | Added `/scales/register/status/` → `RegistrationStatusView` (name `register_status`) |
| `helvetic/tests.py` | 7 new tests: `RegistrationStatusViewTest` (5 cases), `CurlRegistrationViewSessionTest` (2 cases) |

**How the status flow works:**
1. User POSTs to `/scales/register/curl` → server deletes stale tokens, creates a fresh `AuthorisationToken`, stores current scale count in `request.session['initial_scale_count']`, renders the curl command page.
2. User runs the curl command against the scale's AP, reconnects to their home network.
3. Scale contacts `/scale/register` → server creates a new `Scale` record.
4. User navigates to `/scales/register/status/` (linked from step 1's page). The view compares current scale count to the session value. If greater, clears the session key and redirects to `/scales/`. Otherwise renders the waiting template which auto-reloads every 5 s via JS.

**Session key:** `initial_scale_count` (integer). Cleared on successful redirect.

**Why JS reload instead of `<meta http-equiv="refresh">`:** The base template has no `{% block head %}`, so a meta tag inserted from a child template's `{% block content %}` would be rendered in the body — valid HTML but non-standard. JS `setTimeout(function() { location.reload(); }, 5000)` at the bottom of `{% block content %}` is unambiguous.

---

## Data Model Changes

| Phase | Change | Migration |
|-------|--------|-----------|
| 1 | None | No |
| 2 (graphs) | Optional `Index(fields=['user','when'])` on `Measurement` | Yes (optional) |
| 2 (scale config) | None | No |
| 3 | None | No |
| 4 | None | No |

---

## Test Plan

Tests live in `helvetic/tests.py` (68 tests, all passing as of Phase 4).

Coverage by phase:
- **Pre-existing:** `AuthorisationTokenLookupTest`, `UserProfileAgeTest`, `UserProfileShortNameFormattedTest`, `UserProfileLatestMeasurementTest`, `ScaleUploadViewTest`, `ScaleRegisterViewTest`, `ScaleValidateViewTest`, `IndexViewTest`, `ScaleListViewTest`, `RegistrationViewTest`
- **Phase 1:** `ProfileViewTest`, `ProfileEditViewTest`, `MeasurementExportViewTest`
- **Phase 2:** `MeasurementListViewTest`, `MeasurementGraphViewTest`, `MeasurementDataViewTest`, `ScaleEditViewTest`
- **Phase 3:** skipped (Django admin used instead)
- **Phase 4:** `RegistrationStatusViewTest` (5 cases: unauthenticated redirect, no new scale, new scale → redirect, session cleared, existing scale not triggering redirect), `CurlRegistrationViewSessionTest` (2 cases: stores correct count with and without pre-existing scales)

Run:
```bash
cd helv_test
PYTHONPATH=/c/Users/bla/git/helvetic ../env/Scripts/python manage.py test helvetic
```

## Alternatives Considered

| Alternative | Rejected because |
|-------------|-----------------|
| Inline graph data in template | Couples backend to template; hard to paginate or filter later |
| Superuser-only user management | `is_staff` is the Django convention for management UIs |
| Browser-initiated WiFi AP config | `fetch()` cannot set `Cookie` on `192.168.240.1`; server not on scale network |
| Google Fit sync on upload trigger | Out of scope |
| Celery for background sync | Unnecessary infrastructure for a self-hosted personal project |
