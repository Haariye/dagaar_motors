frappe.ui.form.on("Motor Vehicle", {
  setup(frm) {
    set_vehicle_queries(frm);
  },

  async onload(frm) {
    if (frm.doc.branch) await dagaar_motors.forms.branch(frm);
    suggest_vehicle_name(frm);
  },

  refresh(frm) {
    set_vehicle_queries(frm);
    if (frm.is_new()) {
      frm.dashboard.set_headline_alert(__("Save once and Motors will create and link the ERP Item and Asset automatically."), "blue");
      return;
    }

    render_vehicle_strip(frm);
    frm.add_custom_button(__("Operational Summary"), async () => {
      const result = await dagaar_motors.ui.call("dagaar_motors.api.fleet.vehicle_summary", { vehicle: frm.doc.name }, false);
      show_vehicle_summary(result);
    }, __("View"));

    if (frappe.user.has_role(["Dagaar Motors Fleet Manager", "Dagaar Motors Administrator", "System Manager"])) {
      frm.add_custom_button(__("Mileage Correction"), () => mileage_dialog(frm), __("Actions"));
      frm.add_custom_button(__("Check Maintenance Due"), async () => {
        const created = await dagaar_motors.ui.call("dagaar_motors.api.fleet.generate_maintenance", { vehicle: frm.doc.name });
        frappe.show_alert({ message: created.length ? __("Created {0} maintenance record(s).", [created.length]) : __("No maintenance is due."), indicator: created.length ? "orange" : "green" });
        frm.reload_doc();
      }, __("Actions"));
    }

    if (frm.doc.rentable && !["Sold", "Retired"].includes(frm.doc.status)) {
      frm.add_custom_button(__("New Rental"), () => frappe.new_doc("Rental Agreement", { vehicle: frm.doc.name }), __("Create"));
    }
    if (frm.doc.sellable && !["Sold", "Retired"].includes(frm.doc.status)) {
      frm.add_custom_button(__("Vehicle Sale"), () => frappe.new_doc("Vehicle Sale", { vehicle: frm.doc.name }), __("Create"));
    }
  },

  async branch(frm) {
    await dagaar_motors.forms.branch(frm, { force: true });
    const branch = await frappe.xcall("dagaar_motors.api.forms.branch", { branch: frm.doc.branch });
    if (branch?.pickup_location && !frm.doc.current_location) await frm.set_value("current_location", branch.pickup_location);
    set_vehicle_queries(frm);
  },

  category(frm) {
    if (frm.doc.category && !frm.doc.rental_category) frm.set_value("rental_category", frm.doc.category);
  },

  model_year: suggest_vehicle_name,
  brand: suggest_vehicle_name,
  manufacturer: suggest_vehicle_name,
  model: suggest_vehicle_name,
  license_plate: suggest_vehicle_name,

  rentable(frm) {
    // A vehicle you no longer rent out is a candidate for sale; nudge the user.
    if (!frm.doc.rentable && frm.doc.status === "Available") {
      frappe.show_alert({ message: __("This vehicle is no longer rentable. Tick 'Available for Sale' to sell it."), indicator: "blue" });
    }
    frm.refresh_fields();
  },

  sellable(frm) {
    frm.refresh_fields();
  },
});

function set_vehicle_queries(frm) {
  frm.set_query("branch", () => ({ filters: frm.doc.company ? { company: frm.doc.company, active: 1 } : { active: 1 } }));
  frm.set_query("warehouse", () => ({ filters: { company: frm.doc.company } }));
  frm.set_query("cost_center", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
}

function suggest_vehicle_name(frm) {
  if (!frm.is_new()) return;
  const parts = [frm.doc.model_year, frm.doc.brand || frm.doc.manufacturer, frm.doc.model, frm.doc.license_plate].filter(Boolean);
  if (!parts.length) return;
  const suggestion = parts.join(" ");
  if (!frm.doc.vehicle_title || frm.doc.vehicle_title === frm.__motors_name_suggestion) {
    frm.__motors_name_suggestion = suggestion;
    frm.set_value("vehicle_title", suggestion);
  }
}

function render_vehicle_strip(frm) {
  const image = frm.doc.vehicle_image || "/assets/dagaar_motors/images/dagaar-motors-logo.svg";
  const html = `<div class="dm-vehicle-strip"><img src="${dagaar_motors.ui.escape(image)}"><div><h4>${dagaar_motors.ui.escape(frm.doc.vehicle_title || frm.doc.name)}</h4><p>${dagaar_motors.ui.escape([frm.doc.license_plate, frm.doc.vin, frm.doc.category].filter(Boolean).join(" · "))}</p><div style="margin-top:7px">${dagaar_motors.ui.badge(frm.doc.status)}</div></div><div class="dm-vehicle-metric"><span>${__("Odometer")}</span><strong>${format_number(frm.doc.current_odometer || 0)} km</strong></div><div class="dm-vehicle-metric"><span>${__("Utilization")}</span><strong>${Number(frm.doc.utilization_percent || 0).toFixed(1)}%</strong></div><div class="dm-vehicle-metric"><span>${__("Profit")}</span><strong>${dagaar_motors.ui.money(frm.doc.profit)}</strong></div></div>`;
  frm.dashboard.set_headline(html);
}

function mileage_dialog(frm) {
  const dialog = new frappe.ui.Dialog({
    title: __("Authorized Mileage Correction"),
    fields: [
      { fieldname: "current", label: __("Current Odometer"), fieldtype: "Float", default: frm.doc.current_odometer, read_only: 1 },
      { fieldname: "odometer", label: __("Corrected Odometer"), fieldtype: "Float", reqd: 1 },
      { fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 },
      { fieldname: "approved_by", label: __("Approved By"), fieldtype: "Link", options: "User", reqd: 1 },
    ],
    primary_action_label: __("Post Correction"),
    async primary_action(values) {
      await dagaar_motors.ui.call("dagaar_motors.api.fleet.correct_mileage", { vehicle: frm.doc.name, ...values });
      dialog.hide();
      frm.reload_doc();
    },
  });
  dialog.show();
}

function show_vehicle_summary(data) {
  const vehicle = data.vehicle || {};
  const rows = (data.future_reservations || []).map((row) => `<tr><td><a data-route="Rental Reservation|${dagaar_motors.ui.escape(row.name)}">${dagaar_motors.ui.escape(row.name)}</a></td><td>${dagaar_motors.ui.escape(row.customer)}</td><td>${dagaar_motors.ui.escape(row.pickup_datetime)}</td><td>${dagaar_motors.ui.escape(row.return_datetime)}</td></tr>`).join("");
  const dialog = new frappe.ui.Dialog({ title: __("Vehicle Summary"), size: "large" });
  dialog.$body.html(`<div class="dm-pricing-summary"><div class="dm-price-box"><span>${__("Rental Revenue")}</span><strong>${dagaar_motors.ui.money(vehicle.total_rental_revenue)}</strong></div><div class="dm-price-box"><span>${__("Operating Cost")}</span><strong>${dagaar_motors.ui.money(vehicle.operating_cost)}</strong></div><div class="dm-price-box"><span>${__("Maintenance")}</span><strong>${dagaar_motors.ui.money(vehicle.maintenance_cost)}</strong></div><div class="dm-price-box"><span>${__("Profit")}</span><strong>${dagaar_motors.ui.money(vehicle.profit)}</strong></div></div><table class="dm-price-lines"><thead><tr><th>${__("Reservation")}</th><th>${__("Customer")}</th><th>${__("Pickup")}</th><th>${__("Return")}</th></tr></thead><tbody>${rows || `<tr><td colspan="4">${__("No future reservations.")}</td></tr>`}</tbody></table>`);
  dialog.$body.on("click", "[data-route]", function () { const [doctype, name] = this.dataset.route.split("|"); dialog.hide(); frappe.set_route("Form", doctype, name); });
  dialog.show();
}
