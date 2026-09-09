from frappe.model.document import Document

from dagaar_motors.services.master_data import validate_document_requirement


class RentalDocumentRequirement(Document):
    def validate(self):
        validate_document_requirement(self)