# Data Import

## Status
Draft

## Summary
Allow users to import historical measurement data from CSV files without needing a physical scale present for each reading. This covers the helvetic export format (exact round-trip) and Fitbit's weight export format. The architecture is pluggable — adding a third source (e.g. Garmin, Google Fit) means creating one new module and one import line; nothing else changes.

## Assumptions
- User selects which of their registered scales to attribute imported measurements to — no virtual/import scale created
- Duplicates (same user + scale + timestamp) are silently skipped; count reported after import
- Weight unit in helvetic CSV is always kg; Fitbit CSV weight unit is user-selected on the form (kg or lbs)
- Dates without timezone info are treated as UTC
- Fitbit BMI column is present in the file but intentionally ignored — not stored
- File size is small (personal export); no chunked upload or async processing needed
- `bulk_create` is safe here — no `post_save` signals on `Measurement`

## Out of scope
- Creating a virtual/import scale (no model changes)
- Fitbit OAuth2 / direct API pull
- Google Fit, Garmin, MyFitnessPal import (architecture supports adding them; not planned now)
- Editing or deleting individual imported measurements (use the existing measurement list)
- Session/SSE-based real-time progress (imports complete in <1s on typical personal data)

## Approach

### Pluggable importer package

```
helvetic/importers/
    __init__.py          # imports parsers to fire @register decorators
    base.py              # CsvImporter ABC
    registry.py          # ImporterRegistry singleton
    helvetic_csv.py      # HelveticCsvImporter
    fitbit_csv.py        # FitbitCsvImporter
```

Each parser:
- Declares `label` (shown in form dropdown) and `sniff_fields` (frozenset of lowercase header names for auto-detection)
- Implements `parse(file_obj, **kwargs) -> list[dict]` returning `{when, weight_grams, body_fat}`
- Raises `ImportError` with a line-specific message on bad content

Auto-detect reads the first CSV row and checks `sniff_fields` against it. User can also select format explicitly. When Fitbit is selected (or detected), a weight-unit field appears via JS show/hide; server-side validation enforces the requirement.

Chosen over alternatives because: adding a new parser requires only a single new file + one import line; no registry list to maintain; consistent with existing Django patterns; no new pip dependencies.

### Progress bar

An indeterminate animated Bootstrap progress bar is shown on form submit via JS. When the user clicks Import, the button is disabled, a `<div class="progress">` becomes visible, and the form submits normally. On completion the server redirects — the progress bar disappears with the page navigation.

No polling endpoint or SSE needed. For personal CSV files this is appropriate; real-time granularity would require server-side streaming with no benefit for <1s imports.

## Changes required

### New files

| File | Purpose |
|------|---------|
| `helvetic/importers/__init__.py` | Package init; imports parsers so `@registry.register` decorators fire |
| `helvetic/importers/base.py` | `CsvImporter` ABC: `sniff()`, `parse()`, `_read_csv()` utility |
| `helvetic/importers/registry.py` | `ImporterRegistry`: `register()`, `choices()`, `get()`, `autodetect()` |
| `helvetic/importers/helvetic_csv.py` | `HelveticCsvImporter` — parses `date,weight_kg,body_fat_pct` |
| `helvetic/importers/fitbit_csv.py` | `FitbitCsvImporter` — parses `Date,Weight,BMI,Fat`; supports kg/lbs; handles ISO and US date formats |
| `helvetic/templates/helvetic/measurement_import.html` | Bootstrap 3 form; JS toggles Fitbit unit field and shows indeterminate progress bar on submit |

### Modified files

| File | Change |
|------|--------|
| `helvetic/forms.py` | Add `MeasurementImportForm`: `scale` (ModelChoiceField, filtered to `owner=user`), `format` (auto + registry choices), `file` (FileField), `fitbit_weight_unit`; `clean()` resolves format and validates Fitbit unit |
| `helvetic/views/webui.py` | Add `MeasurementImportView(LoginRequiredMixin, View)`: GET renders form; POST parses file, deduplicates with set lookup, `bulk_create`, redirects to `measurement_list` with success message |
| `helvetic/urls.py` | Add `re_path(r'^measurements/import/$', ..., name='measurement_import')` |
| `helvetic/templates/helvetic/measurement_list.html` | Add "Import CSV" button linking to `measurement_import` |
| `helvetic/tests.py` | ~30 new tests (see test plan) |

## Data model / API changes

None — no migration required. New URL only: `GET/POST /measurements/import/`

Duplicate detection: Python set of existing `(user, scale, when)` tuples fetched before insert.

## Test plan

### Parser unit tests (no DB, use `io.BytesIO`)

**`HelveticCsvImporterTest`**
- Valid row with and without body_fat
- Weight grams conversion (`70.500 kg → 70500 g`)
- Tz-naive date gets UTC; tz-aware date preserved
- Bad date / bad weight raises `ImportError`
- Empty file returns empty list
- Header sniff: correct headers match; wrong headers don't

**`FitbitCsvImporterTest`**
- Valid row in kg and lbs (conversion: `× 453.592`)
- BMI column present but result dict has no BMI key
- Empty Fat column → `None`
- ISO date format and US `MM/DD/YYYY` date format
- Bad weight_unit raises `ImportError`
- Header sniff: Fitbit headers match; helvetic headers don't

**`RegistryAutodetectTest`**
- Auto-detects helvetic file; Fitbit file; unknown → `None`; empty → `None`
- `choices()` includes both formats
- `get()` with unknown slug raises `ValueError`

### View integration tests (`TestCase` + `Client`)

**`MeasurementImportViewTest`**
- Unauthenticated redirects to login
- GET returns 200 with form
- Form scale dropdown contains only user's own scales (not another user's)
- POST auto-detect + helvetic CSV → correct Measurement created, redirect to list
- POST explicit Fitbit format kg + lbs
- POST Fitbit selected without weight_unit → re-renders with field error
- POST malformed CSV (parse raises `ImportError`) → re-renders with file field error
- POST with duplicate row → skipped, new rows created, success message includes counts
- POST with another user's scale → form invalid (not in queryset)
- Success message contains imported and skipped counts

Run: `cd helv_test && PYTHONPATH=/c/Users/bla/git/helvetic ../env/Scripts/python manage.py test helvetic`

## Open questions
None.

## Alternatives considered

| Alternative | Rejected because |
|-------------|-----------------|
| Auto-create virtual "import" scale per user | Pollutes the scale list; requires migration; special-cases needed throughout |
| Single-format import (helvetic CSV only) | Fitbit is the most common migration source for displaced Aria users |
| Per-row DB query for duplicate detection | N queries per import vs one set lookup; unnecessary for small personal exports |
| Global format auto-detect only (no explicit selector) | Some users may have ambiguous files; explicit override is cheap to add |
| Real-time progress via SSE or session polling | Imports complete in <1s on personal data; indeterminate bar gives sufficient feedback without a second endpoint or threading |
