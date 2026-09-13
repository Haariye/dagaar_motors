from __future__ import annotations

import frappe

from dagaar_motors.api.permissions import enforce_document_scope, enforce_vehicle_scope
from dagaar_motors.services.extensions import approve_and_submit_extension
from dagaar_motors.services.rental import (
    assign_vehicle,
    checkout_agreement,
    confirm_reservation,
    convert_quotation_to_reservation,
    create_agreement_from_reservation,
)
from dagaar_motors.services.returns import complete_return


@frappe.whitelist()
def convert_quotation(quotation):
    enforce_document_scope("Rental Quotation", quotation)
    return convert_quotation_to_reservation(quotation).as_dict()


@frappe.whitelist()
def confirm(reservation):
    enforce_document_scope("Rental Reservation", reservation)
    return confirm_reservation(reservation).as_dict()


@frappe.whitelist()
def assign(reservation, vehicle):
    enforce_document_scope("Rental Reservation", reservation)
    enforce_vehicle_scope(vehicle)
    return assign_vehicle(reservation, vehicle).as_dict()


@frappe.whitelist()
def create_agreement(reservation):
    enforce_document_scope("Rental Reservation", reservation)
    return create_agreement_from_reservation(reservation).as_dict()


@frappe.whitelist()
def checkout(agreement):
    enforce_document_scope("Rental Agreement", agreement)
    return checkout_agreement(agreement).as_dict()


@frappe.whitelist()
def approve_extension(extension):
    enforce_document_scope("Rental Extension", extension)
    return approve_and_submit_extension(extension).as_dict()


@frappe.whitelist()
def finalize_return(rental_return):
    enforce_document_scope("Rental Return", rental_return)
    return complete_return(rental_return).as_dict()