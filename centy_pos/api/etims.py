import frappe
from frappe import _
from frappe.utils import cint

from centy_pos.utils.centy_pos_config import etims_retry_callable


def _read_navari_scu_from_si(si_name: str) -> tuple[str | None, str | None]:
	"""Read Navari kenya_compliance_via_slade fields from Sales Invoice (develop branch fieldnames)."""
	if not si_name or not frappe.db.exists("Sales Invoice", si_name):
		return None, None
	si = frappe.get_doc("Sales Invoice", si_name)
	qr = None
	for fn in ("custom_qr_code", "custom_qr_code_url"):
		v = getattr(si, fn, None)
		if v:
			qr = str(v)
			break
	cu = getattr(si, "custom_scu_invoice_number", None)
	cu = str(cu) if cu else None
	return qr, cu


@frappe.whitelist()
def mirror_etims_from_consolidated_sales_invoice(pos_invoice: str, persist: int | bool = 1):
	"""Copy Navari SCU / QR fields from linked Sales Invoice onto POS Invoice custom fields."""
	inv = frappe.get_doc("POS Invoice", pos_invoice)
	if not frappe.has_permission("POS Invoice", "write", doc=inv):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	si_name = getattr(inv, "consolidated_invoice", None)
	if not si_name:
		return {"ok": False, "message": _("No consolidated Sales Invoice on this POS Invoice.")}

	qr, cu = _read_navari_scu_from_si(si_name)
	if not qr and not cu:
		return {"ok": False, "message": _("Sales Invoice has no Navari SCU / QR data yet.")}

	persist_bool = bool(cint(persist)) if not isinstance(persist, bool) else persist
	if persist_bool:
		frappe.db.set_value(
			"POS Invoice",
			inv.name,
			{
				"centy_pos_etims_qr_code": qr or "",
				"centy_pos_etims_control_unit_invoice_number": cu or "",
			},
			update_modified=False,
		)
	return {"ok": True, "qr_code": qr, "control_unit_invoice_number": cu, "persisted": persist_bool}


@frappe.whitelist()
def get_etims_status(pos_invoice: str) -> dict:
	inv = frappe.get_doc("POS Invoice", pos_invoice)
	qr = getattr(inv, "centy_pos_etims_qr_code", None) or None
	cu = getattr(inv, "centy_pos_etims_control_unit_invoice_number", None) or None
	si_name = getattr(inv, "consolidated_invoice", None)
	if si_name and (not qr or not cu):
		si_qr, si_cu = _read_navari_scu_from_si(si_name)
		qr = qr or si_qr
		cu = cu or si_cu

	if qr:
		status = "submitted"
	elif not frappe.db.get_value("POS Profile", inv.pos_profile, "centy_pos_etims_enabled"):
		status = "disabled"
	else:
		status = "pending"
	return {
		"status": status,
		"qr_code": qr,
		"control_unit_invoice_number": cu,
		"last_attempt_at": None,
		"consolidated_sales_invoice": si_name,
	}


@frappe.whitelist()
def retry_etims_submission(pos_invoice: str) -> dict:
	inv = frappe.get_doc("POS Invoice", pos_invoice)
	if not frappe.has_permission("POS Invoice", "write", doc=inv):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	actions: list = []

	path = etims_retry_callable()
	if path:
		try:
			fn = frappe.get_attr(path)
			fn(inv)
			actions.append({"callable": path, "ok": True})
		except Exception as e:
			actions.append({"callable": path, "ok": False, "error": str(e)})

	if "kenya_compliance_via_slade" in frappe.get_installed_apps() and getattr(inv, "consolidated_invoice", None):
		try:
			frappe.get_attr(
				"kenya_compliance_via_slade.kenya_compliance_via_slade.overrides.server.sales_invoice.send_invoice_details"
			)(inv.consolidated_invoice)
			actions.append({"navari_resend_sales_invoice": inv.consolidated_invoice, "ok": True})
		except Exception as e:
			actions.append({"navari_resend_sales_invoice": False, "error": str(e)})

	actions.append(mirror_etims_from_consolidated_sales_invoice(pos_invoice, persist=True))

	return {"status": "pending", "actions": actions}
