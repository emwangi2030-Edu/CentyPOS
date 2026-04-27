import base64

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from centy_pos.utils.centy_pos_config import (
	receipt_print_format,
	receipt_webhook_secret,
	receipt_webhook_timeout,
	receipt_webhook_url,
	sms_webhook_url,
)
from centy_pos.utils.customer_phone import resolve_customer_mobile


def _update_whatsapp_status(pos_invoice: str, status: str):
	frappe.db.set_value("POS Invoice", pos_invoice, "centy_pos_whatsapp_status", status, update_modified=False)
	if status == "Sent":
		frappe.db.set_value(
			"POS Invoice",
			pos_invoice,
			"centy_pos_whatsapp_sent_at",
			now_datetime(),
			update_modified=False,
		)


def _build_pos_invoice_pdf_bytes(doc) -> bytes | None:
	pf = receipt_print_format()
	try:
		return frappe.get_print("POS Invoice", doc.name, print_format=pf or None, as_pdf=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "centy_pos_pdf_generation")
		return None


def _post_json_webhook(url: str, payload: dict, secret: str | None) -> tuple[int, str]:
	try:
		import requests
	except ImportError:
		frappe.log_error("requests package missing for Centy POS webhook", "centy_pos_receipt")
		return 0, "requests not installed"

	headers = {"Content-Type": "application/json", "Accept": "application/json"}
	if secret:
		headers["Authorization"] = f"Bearer {secret}"
	try:
		r = requests.post(url, json=payload, headers=headers, timeout=receipt_webhook_timeout())
		return r.status_code, (r.text or "")[:2000]
	except Exception as e:
		return 0, str(e)


def _send_whatsapp_job(pos_invoice: str, override_number: str | None = None):
	try:
		doc = frappe.get_doc("POS Invoice", pos_invoice)
		phone = resolve_customer_mobile(doc.customer, override_number)
		if not phone:
			_update_whatsapp_status(pos_invoice, "Skipped")
			return

		url = receipt_webhook_url()
		if not url:
			frappe.logger().info(
				f"[centy_pos] WhatsApp receipt skipped (no centy_pos_receipt_webhook_url): {pos_invoice} phone={phone}"
			)
			_update_whatsapp_status(pos_invoice, "Sent")
			return

		pdf_bytes = _build_pos_invoice_pdf_bytes(doc)
		pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8") if pdf_bytes else ""

		company_name = frappe.db.get_value("Company", doc.company, "company_name") or doc.company
		etims_url = None
		qr = getattr(doc, "centy_pos_etims_qr_code", None) or ""
		if qr and (qr.startswith("http://") or qr.startswith("https://")):
			etims_url = qr
		elif qr:
			etims_url = None

		payload = {
			"pos_invoice": doc.name,
			"customer_phone": phone,
			"customer_name": doc.customer_name or doc.customer,
			"grand_total": flt(doc.grand_total),
			"currency": doc.currency or "KES",
			"pdf_base64": pdf_b64,
			"business_name": company_name,
			"etims_qr_url": etims_url or "",
		}

		status_code, body = _post_json_webhook(url, payload, receipt_webhook_secret())
		if 200 <= status_code < 300:
			_update_whatsapp_status(pos_invoice, "Sent")
		else:
			frappe.log_error(
				message=f"Webhook HTTP {status_code}: {body}",
				title="centy_pos_whatsapp_webhook",
			)
			_update_whatsapp_status(pos_invoice, "Failed")
	except Exception:
		frappe.log_error(frappe.get_traceback(), "centy_pos_whatsapp_receipt")
		_update_whatsapp_status(pos_invoice, "Failed")


@frappe.whitelist()
def get_receipt_delivery_status(pos_invoice: str) -> dict:
	"""Read-only status for Hub / ops (no webhook secrets)."""
	if not frappe.db.exists("POS Invoice", pos_invoice):
		frappe.throw(_("POS Invoice not found"))
	if not frappe.has_permission("POS Invoice", "read", doc=pos_invoice):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	row = frappe.db.get_value(
		"POS Invoice",
		pos_invoice,
		[
			"docstatus",
			"grand_total",
			"currency",
			"centy_pos_whatsapp_status",
			"centy_pos_whatsapp_sent_at",
			"pos_profile",
		],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("POS Invoice not found"))
	prof = None
	if row.get("pos_profile"):
		prof = frappe.db.get_value(
			"POS Profile",
			row.pos_profile,
			["centy_pos_receipt_via_whatsapp", "centy_pos_receipt_via_sms"],
			as_dict=True,
		)
	sent = row.get("centy_pos_whatsapp_sent_at")
	return {
		"pos_invoice": pos_invoice,
		"docstatus": row.get("docstatus"),
		"grand_total": flt(row.get("grand_total")),
		"currency": row.get("currency"),
		"whatsapp_status": row.get("centy_pos_whatsapp_status"),
		"whatsapp_sent_at": str(sent) if sent else None,
		"profile_receipt_via_whatsapp": int(prof.get("centy_pos_receipt_via_whatsapp") or 0) if prof else 0,
		"profile_receipt_via_sms": int(prof.get("centy_pos_receipt_via_sms") or 0) if prof else 0,
		"sms_webhook_configured": bool(sms_webhook_url()),
		"whatsapp_webhook_configured": bool(receipt_webhook_url()),
	}


@frappe.whitelist()
def send_whatsapp_receipt(pos_invoice: str, override_number: str | None = None) -> dict:
	doc = frappe.get_doc("POS Invoice", pos_invoice)
	if doc.docstatus != 1:
		frappe.throw(_("POS Invoice must be submitted."))
	phone = resolve_customer_mobile(doc.customer, override_number)
	if not phone:
		_update_whatsapp_status(pos_invoice, "Skipped")
		return {"status": "skipped_no_number", "queue_id": None}
	frappe.enqueue(_send_whatsapp_job, queue="default", pos_invoice=pos_invoice, override_number=override_number)
	return {"status": "queued", "queue_id": pos_invoice}


def _send_sms_job(pos_invoice: str, override_number: str | None = None):
	doc = frappe.get_doc("POS Invoice", pos_invoice)
	url = sms_webhook_url()
	if not url:
		return
	phone = resolve_customer_mobile(doc.customer, override_number)
	if not phone:
		return
	payload = {
		"pos_invoice": doc.name,
		"customer_phone": phone,
		"grand_total": flt(doc.grand_total),
		"currency": doc.currency or "KES",
	}
	_post_json_webhook(url, payload, receipt_webhook_secret())


@frappe.whitelist()
def send_sms_receipt(pos_invoice: str, override_number: str | None = None) -> dict:
	doc = frappe.get_doc("POS Invoice", pos_invoice)
	if doc.docstatus != 1:
		frappe.throw(_("POS Invoice must be submitted."))
	if not sms_webhook_url():
		return {"status": "skipped", "message": _("centy_pos_sms_webhook_url not configured")}
	frappe.enqueue(_send_sms_job, queue="default", pos_invoice=pos_invoice, override_number=override_number)
	return {"status": "queued"}


def queue_receipt_on_submit(doc):
	"""Called from POS Invoice on_submit hook."""
	row = frappe.db.get_value(
		"POS Profile",
		doc.pos_profile,
		["centy_pos_receipt_via_whatsapp", "centy_pos_receipt_via_sms"],
		as_dict=True,
	)
	if not row:
		return
	if row.get("centy_pos_receipt_via_whatsapp"):
		frappe.enqueue(_send_whatsapp_job, queue="default", pos_invoice=doc.name)
	if row.get("centy_pos_receipt_via_sms"):
		frappe.enqueue(_send_sms_job, queue="default", pos_invoice=doc.name)


def retry_failed_whatsapp_deliveries():
	"""Hourly: retry recent failures (max 3 comments per invoice)."""
	since = frappe.utils.add_days(frappe.utils.today(), -1)
	rows = frappe.get_all(
		"POS Invoice",
		filters={
			"docstatus": 1,
			"centy_pos_whatsapp_status": "Failed",
			"modified": (">", since),
		},
		pluck="name",
		limit=50,
	)
	for name in rows or []:
		retries = frappe.db.sql(
			"""
			SELECT COUNT(*) FROM `tabComment`
			WHERE reference_doctype = 'POS Invoice' AND reference_name = %s
			AND comment_type = 'Comment' AND content LIKE %s
			""",
			(name, "%[centy_pos_whatsapp_retry]%"),
		)[0][0]
		if retries >= 3:
			continue
		doc = frappe.get_doc("POS Invoice", name)
		doc.add_comment("Comment", "[centy_pos_whatsapp_retry] " + _("Scheduled WhatsApp retry"))
		frappe.enqueue(_send_whatsapp_job, queue="default", pos_invoice=name)
