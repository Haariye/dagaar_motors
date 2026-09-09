frappe.ui.form.on("Rental Reservation", {
  setup(frm) {
    set_rental_queries(frm);
  },

  async onload(frm) {
    if (frm.doc.customer) await dagaar_motors.forms.customer(frm);
    if (frm.doc.branch) await dagaar_motors.forms.branch(frm);
  },

  refresh(frm) {
    set_rental_queries(frm);
    if (frm.doc.pricing_breakdown?.length) {
      frm.add_custom_button(__("Pricing Breakdown"), () => dagaar_motors.ui.show_pricing(frm.doc), __("View"));
    }
    if (frm.is_new()) return;

    if (!["Cancelled", "No Show", "Completed", "Checked Out"].includes(frm.doc.status)) {
      frm.add_custom_button(__("Find Vehicle"), () => choose_vehicle(frm), __("Actions"));
      frm.add_custom_button(__("Confirm"), async () => {
        await dagaar_motors.ui.call("dagaar_motors.api.rental.confirm", { reservation: frm.doc.name });
        frm.reload_doc();
      }, __("Actions"));
    }
    if (["Confirmed", "Vehicle Assigned"].includes(frm.doc.status)) {
      frm.add_custom_button(__("Create Rental Agreement"), async () => {
        const result = await dagaar_motors.ui.call("dagaar_motors.api.rental.create_agreement", { reservation: frm.doc.name });
        frappe.set_route("Form", "Rental Agreement", result.name);
      }, __("Create"));
    }
  },

  async customer(frm) {
    await dagaar_motors.forms.customer(frm, { force: true });
    preview(frm);
  },

  async branch(frm) {
    await dagaar_motors.forms.branch(frm, { force: true });
    set_rental_queries(frm);
    preview(frm);
  },

  company: set_rental_queries,

  async requested_vehicle(frm) {
    if (!frm.doc.requested_vehicle) return;
    await dagaar_motors.forms.vehicle(frm, "requested_vehicle");
    set_rental_queries(frm);
    preview(frm);
  },

  async vehicle(frm) {
    if (!frm.doc.vehicle) return;
    await dagaar_motors.forms.vehicle(frm, "vehicle");
    set_rental_queries(frm);
    preview(frm);
  },

  pickup_datetime: preview,
  return_datetime: preview,
  rental_type: preview,
  vehicle_category: preview,
  discount_percent: preview,
  promo_code: preview,
  pickup_location: preview,
  return_location: preview,
  tax_template: preview,
});

frappe.ui.form.on("Rental Reservation Extra", {
  rental_extra: preview_parent,
  quantity: preview_parent,
  rate: preview_parent,
  extras_remove: preview_parent,
});

function preview(frm) {
  dagaar_motors.forms.previewPricing(frm, "pickup_datetime", "return_datetime");
}

function preview_parent(frm) {
  preview(frm);
}

function set_rental_queries(frm) {
  frm.set_query("branch", () => ({ filters: frm.doc.company ? { company: frm.doc.company, active: 1 } : { active: 1 } }));
  frm.set_query("requested_vehicle", vehicle_query(frm));
  frm.set_query("vehicle", vehicle_query(frm));
  if (frm.fields_dict.contact) {
    frm.set_query("contact", () => ({
      query: "frappe.contacts.doctype.contact.contact.contact_query",
      filters: { link_doctype: "Customer", link_name: frm.doc.customer },
    }));
  }
}

function vehicle_query(frm) {
  return () => ({
    filters: {
      company: frm.doc.company,
      branch: frm.doc.branch,
      category: frm.doc.vehicle_category,
      rentable: 1,
      status: ["in", ["Available", "Reserved"]],
    },
  });
}

async function choose_vehicle(frm) {
  if (!frm.doc.pickup_datetime || !frm.doc.return_datetime || !frm.doc.company) {
    frappe.msgprint(__("Enter the pickup and return dates first."));
    return;
  }
  const vehicles = await dagaar_motors.ui.call("dagaar_motors.api.availability.available_vehicles", {
    company: frm.doc.company,
    branch: frm.doc.branch,
    vehicle_category: frm.doc.vehicle_category,
    rental_type: frm.doc.rental_type,
    start_datetime: frm.doc.pickup_datetime,
    end_datetime: frm.doc.return_datetime,
  }, false);
  const dialog = new frappe.ui.Dialog({ title: __("Choose an Available Vehicle"), size: "large" });
  const rows = vehicles.map((vehicle) => `<div class="dm-op-row" data-vehicle="${dagaar_motors.ui.escape(vehicle.name)}"><div class="dm-op-avatar">${dagaar_motors.ui.initials(vehicle.license_plate)}</div><div><div class="dm-op-title">${dagaar_motors.ui.escape(vehicle.vehicle_title || vehicle.name)}</div><div class="dm-op-meta">${dagaar_motors.ui.escape([vehicle.license_plate, vehicle.category, vehicle.branch, `${format_number(vehicle.current_odometer || 0)} km`].filter(Boolean).join(" · "))}</div></div><div>${dagaar_motors.ui.badge(vehicle.status)}</div></div>`).join("");
  dialog.$body.html(`<div class="dm-op-list">${rows || `<div class="dm-empty">${__("No vehicles are free for this period.")}</div>`}</div>`);
  dialog.$body.on("click", "[data-vehicle]", async function () {
    await dagaar_motors.ui.call("dagaar_motors.api.rental.assign", { reservation: frm.doc.name, vehicle: this.dataset.vehicle });
    dialog.hide();
    frm.reload_doc();
  });
  dialog.show();
}
