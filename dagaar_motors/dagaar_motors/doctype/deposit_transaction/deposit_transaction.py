import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from dagaar_motors.services.deposits import (
    post_transaction,
    prepare_transaction_identity,
    reverse_transaction,
    validate_transaction_document,
)


class DepositTransaction(Document):
    def before_insert(self):
        prepare_transaction_identity(self)

    def validate(self):
        validate_transaction_document(self)
        if not self.is_new() and self.docstatus == 0:
            immutable_fields = (
                "security_deposit",
                "transaction_type",
                "amount",
                "posting_date",
                "request_token",
                "idempotency_key",
            )
            immutable = frappe.db.get_value(
                "Deposit Transaction",
                self.name,
                list(immutable_fields),
                as_dict=True,
            )
            if immutable and any(
                str(self.get(fieldname)) != str(immutable.get(fieldname))
                for fieldname in immutable_fields
            ):
                frappe.throw(_("Deposit transaction identity and amount cannot be edited after creation."))
        if self.transaction_type == "Allocation":
            allocated = sum(flt(row.amount) for row in self.allocations)
            if self.allocations and abs(allocated - flt(self.amount)) > 0.005:
                frappe.throw(_("Deposit allocation rows must equal the transaction amount."))

    def on_submit(self):
        post_transaction(self)

    def on_cancel(self):
        reverse_transaction(self)

    def on_trash(self):
        if self.docstatus != 0:
            frappe.throw(_("Posted Deposit Transactions cannot be deleted."))
