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

**New files:**
| File | Purpose |
|------|---------|
| `helvetic/views/usermgmt.py` | `UserListView`, `UserCreateView`, `UserDeactivateView` |
| `helvetic/templates/helvetic/user_list.html` | Table with active/inactive badges; deactivate button |
| `helvetic/templates/helvetic/user_create.html` | Create user form |

**Modified files:**
| File | Change |
|------|--------|
| `helvetic/forms.py` | Add `UserCreateForm`: calls `set_password()` on save |
| `helvetic/urls.py` | Add `/users/`, `/users/create/`, `/users/<int:pk>/deactivate/` |
| `helvetic/templates/helvetic/base.html` | Add "Users" nav link, conditionally on `user.is_staff` |

**Access control:** `UserPassesTestMixin`, `test_func = lambda self: self.request.user.is_staff` on all three views.

**Key decisions:**
- Deactivation only (`user.is_active = False`), no deletion
- `UserDeactivateView`: POST-only; raises `PermissionDenied` if targeting self
- No user edit view — password reset via `/accounts/password_change/`

---

## Phase 4 — WiFi Setup UX

Browser-initiated AP config is not viable: `fetch()` cannot set `Cookie` on foreign origins, and the server is not on the scale's network. The existing curl flow is correct; only the UX needs improvement.

**Modified files:**
| File | Change |
|------|--------|
| `helvetic/templates/helvetic/registration/register_curl.html` | Show exact curl command with token pre-filled in copyable `<pre>`; one-click JS copy button |
| `helvetic/views/registration.py` | Add `RegistrationStatusView` |
| `helvetic/urls.py` | Add `/scales/register/status/` |

**Status page:** `<meta http-equiv="refresh" content="5">` polling page that checks `Scale.objects.filter(owner=request.user)` for newly added scales. Redirects to `/scales/` on first match. No WebSockets/Channels needed.

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

Split `tests.py` into a package before Phase 2:

```
helvetic/tests/__init__.py
helvetic/tests/test_models.py       ← move existing model tests
helvetic/tests/test_api.py          ← move existing API view tests
helvetic/tests/test_webui.py        ← move existing web UI tests
helvetic/tests/test_export.py       ← Phase 1
helvetic/tests/test_measurements.py ← Phase 2
helvetic/tests/test_usermgmt.py     ← Phase 3
helvetic/tests/test_registration.py ← Phase 4
```

New tests per phase:
- **Phase 1:** `ProfileViewTest` (no-profile → redirect, 200 with profile), `ProfileEditViewTest` (create, update, invalid POST), `MeasurementExportViewTest` (auth redirect, empty CSV, CSV with data)
- **Phase 2:** `MeasurementDataViewTest` (JSON structure, unit conversion, empty dataset), `ScaleEditViewTest` (owner edits, non-owner 403, M2M assignment)
- **Phase 3:** `UserListViewTest` (non-staff 403), `UserCreateViewTest` (password hashed), `UserDeactivateViewTest` (non-staff 403, self-deactivate 403)
- **Phase 4:** `RegistrationStatusViewTest` (no scale → refresh, scale found → redirect)

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
