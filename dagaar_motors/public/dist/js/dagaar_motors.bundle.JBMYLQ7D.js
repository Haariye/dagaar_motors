(() => {
  // ../dagaar_motors/dagaar_motors/public/js/dagaar_motors.bundle.js
  frappe.provide("dagaar_motors");
  frappe.provide("dagaar_motors.ui");
  Object.assign(dagaar_motors.ui, {
    escape(value) {
      return frappe.utils.escape_html(String(value != null ? value : ""));
    },
    money(value, currency) {
      return format_currency(Number(value || 0), currency || frappe.boot.sysdefaults.currency);
    },
    async call(method, args = {}, freeze = true) {
      return frappe.xcall(method, args, freeze ? { freeze: true, freeze_message: __("Processing\u2026") } : {});
    },
    badge(status) {
      const danger = ["Overdue", "Failed", "Unsafe", "Blocked", "Cancelled", "Expired"];
      const warning = ["Pending", "Due", "Awaiting Approval", "Partially Collected", "Maintenance", "Inspection"];
      const success = ["Available", "Active", "Completed", "Closed", "Paid", "Held", "Passed"];
      const info = ["Reserved", "Extended", "Invoiced", "In Transit", "For Sale"];
      const tone = danger.includes(status) ? "danger" : warning.includes(status) ? "warning" : success.includes(status) ? "success" : info.includes(status) ? "info" : "neutral";
      return `<span class="dm-badge ${tone}">${this.escape(status || __("Unknown"))}</span>`;
    },
    show_pricing(doc) {
      const rows = (doc.pricing_breakdown || []).map((row) => `
      <tr>
        <td>${this.escape(row.component)}</td>
        <td>${this.escape(row.description || "")}</td>
        <td>${this.escape(row.quantity || 0)} \xD7 ${this.money(row.rate, doc.currency)}</td>
        <td>${this.money(row.amount, doc.currency)}</td>
      </tr>`).join("");
      const body = `
      <div class="dm-pricing-summary">
        <div class="dm-price-box"><span>${__("Base")}</span><strong>${this.money(doc.base_amount, doc.currency)}</strong></div>
        <div class="dm-price-box"><span>${__("Extras")}</span><strong>${this.money(doc.extras_amount, doc.currency)}</strong></div>
        <div class="dm-price-box"><span>${__("Discount")}</span><strong>${this.money(doc.discount_amount, doc.currency)}</strong></div>
        <div class="dm-price-box"><span>${__("Grand Total")}</span><strong>${this.money(doc.grand_total, doc.currency)}</strong></div>
      </div>
      <table class="dm-price-lines"><thead><tr><th>${__("Component")}</th><th>${__("Explanation")}</th><th>${__("Calculation")}</th><th>${__("Amount")}</th></tr></thead><tbody>${rows || `<tr><td colspan="4">${__("Save the document to calculate pricing.")}</td></tr>`}</tbody></table>`;
      const dialog = new frappe.ui.Dialog({ title: __("Transparent Pricing Breakdown"), size: "large" });
      dialog.$wrapper.addClass("dm-pricing-dialog");
      dialog.$body.html(body);
      dialog.show();
    },
    route(doctype, name) {
      if (doctype && name)
        frappe.set_route("Form", doctype, name);
    },
    initials(value) {
      return String(value || "DM").split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
    }
  });
  frappe.router.on("change", () => {
    document.body.classList.toggle("dagaar-motors-route", frappe.get_route_str().includes("dagaar-motors"));
  });
  frappe.provide("dagaar_motors.forms");
  Object.assign(dagaar_motors.forms, {
    async customer(frm, { suggestDriver = false, force = false } = {}) {
      if (!frm.doc.customer)
        return {};
      const values = await frappe.xcall("dagaar_motors.api.forms.customer", { customer: frm.doc.customer });
      if ((values == null ? void 0 : values.contact) && (force || !frm.doc.contact))
        await frm.set_value("contact", values.contact);
      if (suggestDriver && frm.fields_dict.drivers && !(frm.doc.drivers || []).length) {
        const row = frm.add_child("drivers");
        row.full_name = (values == null ? void 0 : values.contact_name) || (values == null ? void 0 : values.customer_name) || frm.doc.customer;
        row.phone = (values == null ? void 0 : values.phone) || "";
        row.email = (values == null ? void 0 : values.email) || "";
        row.primary_driver = 1;
        row.source_contact = (values == null ? void 0 : values.contact) || "";
        row.source_customer = frm.doc.customer;
        row.suggested_from_customer = 1;
        frm.refresh_field("drivers");
      }
      return values || {};
    },
    async branch(frm, { force = false } = {}) {
      if (!frm.doc.branch)
        return {};
      const values = await frappe.xcall("dagaar_motors.api.forms.branch", { branch: frm.doc.branch });
      const mapping = {
        company: "company",
        currency: "currency",
        pickup_location: "pickup_location",
        return_location: "return_location",
        warehouse: "warehouse",
        cost_center: "cost_center"
      };
      for (const [source, target] of Object.entries(mapping)) {
        if (frm.fields_dict[target] && (values == null ? void 0 : values[source]) && (force || !frm.doc[target])) {
          await frm.set_value(target, values[source]);
        }
      }
      return values || {};
    },
    async vehicle(frm, fieldname = "vehicle") {
      const vehicle = frm.doc[fieldname] || frm.doc.vehicle || frm.doc.requested_vehicle;
      if (!vehicle)
        return {};
      const values = await frappe.xcall("dagaar_motors.api.forms.vehicle", { vehicle });
      const mapping = {
        company: "company",
        branch: "branch",
        currency: "currency",
        vehicle_category: "vehicle_category",
        category: "category",
        warehouse: "warehouse",
        cost_center: "cost_center"
      };
      for (const [source, target] of Object.entries(mapping)) {
        if (frm.fields_dict[target] && (values == null ? void 0 : values[source]) && frm.doc[target] !== values[source]) {
          await frm.set_value(target, values[source]);
        }
      }
      return values || {};
    },
    async agreement(frm, fieldname = "rental_agreement") {
      const agreement = frm.doc[fieldname];
      if (!agreement)
        return {};
      const values = await frappe.xcall("dagaar_motors.api.forms.agreement", { agreement });
      const fields = [
        "company",
        "branch",
        "customer",
        "contact",
        "vehicle",
        "vehicle_category",
        "rental_type",
        "currency",
        "checkout_odometer",
        "checkout_fuel_level",
        "pickup_location",
        "return_location"
      ];
      for (const fieldname2 of fields) {
        if (frm.fields_dict[fieldname2] && (values == null ? void 0 : values[fieldname2]) != null && !frm.doc[fieldname2]) {
          await frm.set_value(fieldname2, values[fieldname2]);
        }
      }
      return values || {};
    },
    previewPricing(frm, startField, endField) {
      clearTimeout(frm.__motors_pricing_timer);
      frm.__motors_pricing_timer = setTimeout(async () => {
        const start = frm.doc[startField];
        const end = frm.doc[endField];
        if (!start || !end || !frm.doc.customer || !frm.doc.rental_type || !frm.doc.vehicle_category)
          return;
        if (frm.__motors_pricing_running)
          return;
        frm.__motors_pricing_running = true;
        try {
          const context = {
            pickup_datetime: start,
            return_datetime: end,
            company: frm.doc.company,
            branch: frm.doc.branch,
            currency: frm.doc.currency,
            vehicle: frm.doc.vehicle || frm.doc.requested_vehicle,
            vehicle_category: frm.doc.vehicle_category,
            rental_type: frm.doc.rental_type,
            customer: frm.doc.customer,
            booking_channel: frm.doc.reservation_source,
            promo_code: frm.doc.promo_code,
            pickup_location: frm.doc.pickup_location,
            return_location: frm.doc.return_location,
            one_way: Boolean(frm.doc.one_way) || Boolean(frm.doc.pickup_location && frm.doc.return_location && frm.doc.pickup_location !== frm.doc.return_location),
            discount_percent: Number(frm.doc.discount_percent || 0),
            fixed_discount: Number(frm.doc.discount_percent || 0) ? 0 : Number(frm.doc.discount_amount || 0),
            additional_charges: (frm.doc.charges || []).reduce((sum, row) => sum + Number(row.quantity || 0) * Number(row.rate || 0), 0),
            extras: (frm.doc.extras || []).map((row) => ({ rental_extra: row.rental_extra, quantity: row.quantity || 1, rate: row.rate || 0 }))
          };
          const result = await frappe.xcall("dagaar_motors.api.pricing.preview", { context: JSON.stringify(context) });
          const mapping = {
            base_rate: "base_rate",
            base_amount: "base_amount",
            extras_amount: "extras_amount",
            user_discount: "discount_amount",
            net_amount: "net_amount",
            tax_amount: "tax_amount",
            grand_total: "grand_total",
            deposit_required: "deposit_required",
            pricing_rule: "pricing_rule",
            billable_units: "duration_units",
            duration_label: "duration_label"
          };
          for (const [source, target] of Object.entries(mapping)) {
            if (frm.fields_dict[target] && (result == null ? void 0 : result[source]) !== void 0) {
              frm.doc[target] = result[source];
              frm.refresh_field(target);
            }
          }
        } catch (error) {
          console.debug("Motors live pricing preview skipped", error);
        } finally {
          frm.__motors_pricing_running = false;
        }
      }, 350);
    }
  });
})();
//# sourceMappingURL=dagaar_motors.bundle.JBMYLQ7D.js.map
