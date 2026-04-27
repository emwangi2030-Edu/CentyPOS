from . import __version__ as app_version

app_name = "centy_pos"
app_title = "Centy POS"
app_publisher = "CentyHQ"
app_description = "Point of Sale for East African SMEs, built on ERPNext"
app_email = "edwin@getcenty.com"
app_license = "Proprietary"
app_version = app_version

required_apps = ["frappe", "erpnext"]

after_install = "centy_pos.install.after_install"

fixtures = [
	"role.json",
	"custom_field.json",
]

doc_events = {
	"POS Invoice": {
		"validate": "centy_pos.overrides.pos_invoice.validate",
		"on_submit": "centy_pos.overrides.pos_invoice.on_submit",
		"on_cancel": "centy_pos.overrides.pos_invoice.on_cancel",
	},
	"POS Opening Entry": {
		"on_submit": "centy_pos.api.shift.on_opening_submit",
	},
}

scheduler_events = {
	"hourly": [
		"centy_pos.api.receipt.retry_failed_whatsapp_deliveries",
	],
}
