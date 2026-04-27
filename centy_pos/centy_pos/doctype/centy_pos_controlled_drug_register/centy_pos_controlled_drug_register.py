import frappe
from frappe import _
from frappe.model.document import Document


class CentyPOSControlledDrugRegister(Document):
	def validate(self):
		self._validate_item_is_controlled()
		self._validate_prescriber_for_schedule_ii()

	def _validate_item_is_controlled(self):
		if not self.item:
			return
		if not frappe.db.get_value("Item", self.item, "centy_pos_is_controlled_drug"):
			frappe.throw(_("Item {0} is not marked as a controlled drug.").format(self.item))

	def _validate_prescriber_for_schedule_ii(self):
		if self.drug_schedule == "II" and not (self.prescriber_reg_number or "").strip():
			frappe.throw(_("Prescriber registration number is required for Schedule II."))

