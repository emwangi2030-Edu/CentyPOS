# Verify Centy POS (`centy_pos`) on ERPNext production / staging

Use this after `bench install-app centy_pos` (or equivalent Docker `bench`) on the site bound to your Hub’s `FRAPPE_BASE_URL`.

## 1. App installed and importable

```bash
bench --site <yoursite> execute frappe.get_installed_apps
```

Expect `centy_pos` in the list.

```bash
bench --site <yoursite> console
```

```python
import centy_pos  # noqa: F401
import centy_pos.api.cart as c  # noqa: F401
```

No `ModuleNotFoundError`.

## 2. Whitelisted API reachable (token auth)

From any machine with the integration user’s API key:

```bash
curl -sS -X POST "https://<erp-host>/api/method/centy_pos.api.shift.get_pos_profile_context" \
  -H "Authorization: token <api_key>:<api_secret>" \
  -H "Content-Type: application/json" \
  -d '{"kwargs": {"pos_profile": "YOUR_POS_PROFILE_NAME"}}'
```

Expect HTTP 200 and JSON with `message` containing `pos_profile`, `company`, `payment_modes`.

## 3. Custom fields on core DocTypes

In Desk: **POS Profile**, **POS Invoice**, **Item**, **Customer**, **Employee** — confirm Centy POS custom fields exist (from `centy_pos/fixtures/custom_field.json` after migrate).

## 4. Pay Hub proxy

With Hub session cookie (browser) or integration test: `POST /api/centy-pos/frappe` body `{"method":"centy_pos.api.shift.get_pos_profile_context","kwargs":{"pos_profile":"..."}}` → 200 and same shape as step 2.

## 5. Post-deploy smoke (optional)

1. Hub **Settings → Centy POS**: save per-user API key/secret (or rely on `CENTYPOS_ERP_*` / HR creds).
2. Hub **`/centy-pos`**: Connect → load profile → Shift → Open shift → Register → Preview → Submit (test item).

Record POS Profile name, company, and integration user in your environment matrix (`CENTY_POS_PHASE0_PHASE1.md` §6.0).
