# Centy POS Sprint Closure Checklist

## Done in this sprint

- [x] End-to-end UAT flow validated on staging (`Connect -> Shift -> Register -> Holds -> Returns`).
- [x] `create_return` reliability fix implemented (`paid_amount` synchronized before insert/submit).
- [x] Fix verified on staging with fresh records:
  - Sale: `ACC-PSINV-2026-00005`
  - Return: `ACC-PSINV-2026-00006` (against `00005`)
- [x] Source pushed to GitHub (`main`, commit `3011d54`).
- [x] Cashier-role audit performed for staging POS users in scope.

## Must close before sprint sign-off

- [ ] Deployment hardening: ensure ERP app deploy/restart runbook always reloads backend workers after Python code changes.
- [ ] Permission model decision: replace broad `Accounts User` dependency with explicit long-term DocPerm/role model for POS cashiers.
- [ ] Automated regression tests:
  - [ ] Submit invoice: permission + idempotency path.
  - [ ] Return flow: refund payment handling (`paid_amount` guard).
  - [ ] Return against submitted invoice end-to-end.
- [ ] Add lightweight post-deploy smoke script for staging:
  - [ ] Search item
  - [ ] Submit sale
  - [ ] Post return
- [ ] Release/rollback note:
  - [ ] What changed
  - [ ] Verification evidence (invoice IDs)
  - [ ] Rollback steps and owner

## Ownership suggestion

- **ERP/POS backend owner**: deployment runbook + regression tests.
- **ERP admin owner**: cashier role/DocPerm policy.
- **QA owner**: smoke script execution each deploy.
- **Release owner**: release + rollback notes for production handoff.
