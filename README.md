# Centy POS (`centy_pos`)

Frappe app for Centy POS on **ERPNext v15**. Business logic stays in Python; Hub at **staging.centyhq.com** is the operator UI shell (see B2B Hub repo).

## Install (typical bench)

```bash
cd /path/to/frappe-bench
# copy or git clone this app into apps/centy_pos
bench get-app /path/to/centy_pos   # or clone from your git remote
bench --site <your_site> install-app centy_pos
bench --site <your_site> migrate
```

Requires **frappe** and **erpnext** on the bench (`hooks.py` `required_apps`). Add the **payments** app on the bench before enabling M-Pesa integrations (Phase 2).

## Phase 0 / 1 / 2 / 3 / 4 / 5 / 6

See [docs/CENTY_POS_PHASE0_PHASE1.md](./docs/CENTY_POS_PHASE0_PHASE1.md).

**First test deploy:** [docs/DEPLOY_TESTING_FIRST.md](./docs/DEPLOY_TESTING_FIRST.md) (ERP migrate → Hub migrate → build → smoke).

### Hub POS workspace (Phase 4–5)

On **`/centy-pos`**, the B2B Hub ships **register, shift, holds, returns**, and a **last-sale** strip (eTIMS + receipt queues) calling `centy_pos.api.*` via `POST /api/centy-pos/frappe` (`client/src/components/centy-pos/CentyPosWorkspace.tsx`).

### Phase 6 (in progress)

See **[docs/CENTY_POS_PHASE0_PHASE1.md](./docs/CENTY_POS_PHASE0_PHASE1.md)** — **Phase 6 — plan**, **implementation status**, and **execution checklist** (prioritized tickets P6-*). Landed: `centypos_erp_credentials`, Hub proxy resolution + `/api/centy-pos/erp-credentials/me`, `get_receipt_delivery_status`, client credential helpers. Next: P6-1b UI, P6-3a barcode, P6-2a tests, P6-4 runbooks.

### Hub → ERP proxy (B2B Hub repo)

- `POST /api/centy-pos/frappe` with JSON `{ "method": "centy_pos.api.cart.search_items", "kwargs": { "pos_profile": "...", "query": "..." } }`
- Env: `FRAPPE_BASE_URL`, and optional dedicated `CENTYPOS_ERP_API_KEY` / `CENTYPOS_ERP_API_SECRET`. When those are not both set, the Hub uses the same credential resolution as Centy HR (`hr_erp_credentials` then `HR_ERP_API_*`, subject to `HR_ERP_PREFER_ENV`).

### Site config (bench `site_config.json`) — Phase 3

- **Receipts / WhatsApp:** `centy_pos_receipt_webhook_url` (alias `centy_pos_n8n_receipt_webhook_url`), optional `centy_pos_receipt_webhook_secret`, `centy_pos_receipt_webhook_timeout`, `centy_pos_receipt_print_format`. Webhook receives JSON including `pdf_base64` when PDF generation succeeds; outbound `Authorization: Bearer <secret>` when a secret is set.
- **SMS:** optional `centy_pos_sms_webhook_url` (same receipt module).
- **eTIMS:** optional `centy_pos_etims_retry_callable` (dotted path to a callable `(pos_invoice_doc)`). Navari fields on the consolidated **Sales Invoice** are mirrored read-only onto the POS Invoice (`centy_pos_etims_qr_code`, `centy_pos_etims_control_unit_invoice_number` from `custom_qr_code` / `custom_qr_code_url` and `custom_scu_invoice_number`).

### Implemented APIs (`centy_pos.api.*`)

`cart`: `search_items`, `get_item_for_cart`, `price_cart`, `validate_coupon` · `shift`: `get_pos_profile_context`, `open_shift`, `close_shift`, `get_shift_summary`, `record_cash_movement` · `checkout`: `preview_invoice`, `submit_invoice` · `hold`: `save_hold`, `list_held`, `resume_hold`, `discard_hold` · `returns`: `get_returnable_items`, `create_return` · `receipt`: `get_receipt_delivery_status`, `send_whatsapp_receipt`, `send_sms_receipt` · `etims`: `get_etims_status`, `retry_etims_submission`.

## License

Proprietary — CentyHQ.
