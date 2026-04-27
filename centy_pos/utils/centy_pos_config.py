"""Site config keys (bench `site_config.json`) for Centy POS."""

import frappe


def get_conf(key: str, default=None):
	return frappe.conf.get(key, default)


def receipt_webhook_url() -> str | None:
	v = get_conf("centy_pos_receipt_webhook_url") or get_conf("centy_pos_n8n_receipt_webhook_url")
	return (v or "").strip() or None


def receipt_webhook_secret() -> str | None:
	v = get_conf("centy_pos_receipt_webhook_secret") or get_conf("centy_pos_n8n_receipt_webhook_secret")
	return (v or "").strip() or None


def receipt_webhook_timeout() -> int:
	return int(get_conf("centy_pos_receipt_webhook_timeout") or 30)


def receipt_print_format() -> str | None:
	v = get_conf("centy_pos_receipt_print_format")
	return (v or "").strip() or None


def sms_webhook_url() -> str | None:
	v = get_conf("centy_pos_sms_webhook_url")
	return (v or "").strip() or None


def etims_retry_callable() -> str | None:
	"""Dotted path e.g. my_app.api.etims.retry_pos_invoice — optional."""
	v = get_conf("centy_pos_etims_retry_callable")
	return (v or "").strip() or None
