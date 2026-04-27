# Deploy for testing (first pass)

Order: **ERPNext site first** (data + APIs), then **Pay Hub** (proxy + DB migration). Use a **non-production** site until smoke checks pass.

---

## 1. ERPNext (Frappe bench)

On the host that runs the ERP site (e.g. `erp.tarakilishicloud.com`):

1. **Backup** the site (snapshot or `bench --site <site> backup`).
2. **Update app code** for `centy_pos` (git pull in `apps/centy_pos` or install from your artifact).
3. **Migrate** (applies DocTypes, fixtures, new API methods such as `get_receipt_delivery_status`, `get_pos_profile_context`):

   ```bash
   bench --site <your_site> migrate
   ```

4. **Restart** workers / web as you usually do (`bench restart` or supervisor).

5. **Smoke (Desk or curl)**  
   - Confirm **POS Profile** and custom fields load.  
   - Optional API check (replace token and site):

   ```bash
   curl -sS -X POST "https://<erp-host>/api/method/centy_pos.api.shift.get_pos_profile_context" \
     -H "Authorization: token <api_key>:<api_secret>" \
     -H "Content-Type: application/json" \
     --data '{"pos_profile":"<POS Profile name>"}' | head -c 500
   ```

---

## 2. Pay Hub (B2B Hub repo)

On the Node host that serves the Hub (e.g. staging Pay Hub):

1. **Env** (minimum for POS proxy):
   - `FRAPPE_BASE_URL` — same origin as step 1 (no trailing slash).
   - Either **both** `CENTYPOS_ERP_API_KEY` and `CENTYPOS_ERP_API_SECRET`, **or** rely on `hr_erp_credentials` / `HR_ERP_API_*` per existing HR pattern.
   - After first DB migration below, company admins can save **per-user** keys via `PUT /api/centy-pos/erp-credentials/me` (no need to put cashier keys in `.env`).

2. **Pull code** and install deps if needed:

   ```bash
   cd /path/to/b2b-staging-wt
   npm ci   # or npm install
   ```

3. **Database migration** (creates `centypos_erp_credentials`):

   ```bash
   npm run db:migrate
   ```

   If you apply SQL manually instead, run `migrations/0096_centypos_erp_credentials.sql` against the Hub Postgres and keep Drizzle journal in sync with your process.

4. **Build and start**:

   ```bash
   npm run build
   npm run start
   ```

   Or use your existing PM2 / Docker / K8s rollout; artifact is `dist/index.cjs` + `dist/public/`.

5. **Smoke (browser)**  
   - Log in as a **company admin**.  
   - Open DevTools → Application → confirm session cookie for your domain.  
   - Optional: call credential status (must be admin for Centy POS visibility rules):

   ```text
   GET /api/centy-pos/erp-credentials/me
   ```

   - Optional: proxy smoke (after login, same session cookie; adjust method/kwargs):

   ```bash
   curl -sS -X POST "https://<hub-host>/api/centy-pos/frappe" \
     -H "Cookie: session_token=<value_from_browser>" \
     -H "Content-Type: application/json" \
     --data '{"method":"centy_pos.api.shift.get_pos_profile_context","kwargs":{"pos_profile":"<name>"}}' | head -c 800
   ```

---

## 3. Quick verification checklist

| # | Check |
|---|--------|
| 1 | ERP `bench migrate` completed without fixture errors |
| 2 | Hub `npm run db:migrate` applied; table `centypos_erp_credentials` exists |
| 3 | Hub `POST /api/centy-pos/frappe` returns 200 for `get_pos_profile_context` (with valid keys) |
| 4 | `GET /api/centy-pos/erp-credentials/me` returns JSON (403 for non-admin is expected) |
| 5 | If using per-user keys: admin **PUT** keys then repeat (3) in browser as that user |

---

## 4. Rollback (testing only)

- **Hub:** redeploy previous image/commit; DB table can remain empty (safe) or drop `centypos_erp_credentials` only if you are sure nothing depends on it.
- **ERP:** restore backup or `bench migrate` down is not standard — prefer restore from backup taken in §1.

---

## References

- Phase checklist: [CENTY_POS_PHASE0_PHASE1.md](./CENTY_POS_PHASE0_PHASE1.md) (Phase 6 execution checklist).
- Hub env hints: `b2b-staging-wt/.env.example` (Centy POS + HR Frappe sections).
