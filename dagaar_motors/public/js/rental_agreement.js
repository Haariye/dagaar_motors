frappe.ui.form.on("Rental Agreement", {
  setup(frm) {
    set_queries(frm);
  },

  async onload(frm) {
    if (frm.doc.customer) await dagaar_motors.forms.customer(frm, { suggestDriver: true });
    if (frm.doc.branch) await dagaar_motors.forms.branch(frm);
  },

  refresh(frm) {
    set_queries(frm);
    if (frm.doc.pricing_breakdown?.length) {
      frm.add_custom_button(__("Pricing Breakdown"), () => dagaar_motors.ui.show_pricing(frm.doc), __("View"));
    }
    if (frm.is_new()) return;

    if (frm.doc.docstatus === 0 && ["Ready for Pickup", "Reserved", "Awaiting Approval", "Draft"].includes(frm.doc.status)) {
      maybe_add_deposit_button(frm);
      frm.page.set_primary_action(__("Check Out Vehicle"), async () => {
        await dagaar_motors.ui.call("dagaar_motors.api.rental.checkout", { agreement: frm.doc.name });
        frm.reload_doc();
      }, "play");
    }
    if (frm.doc.docstatus === 1 && ["Active", "Extended", "Overdue"].includes(frm.doc.status)) {
      frm.add_custom_button(__("Extend Rental"), () => frappe.new_doc("Rental Extension", { rental_agreement: frm.doc.name }), __("Actions"));
      frm.add_custom_button(__("Process Return"), () => frappe.new_doc("Rental Return", { rental_agreement: frm.doc.name }), __("Actions"));
    }
    // Deposit collect/waive/refund actions (collect/waive only while in draft;
    // refund appears whenever there is an unused deposit balance).
    if (frm.doc.deposit_required) {
      maybe_add_deposit_button(frm);
    }
    if (frm.doc.current_invoice) {
      frm.add_custom_button(__("Open Rental Invoice"), () => frappe.set_route("Form", "Sales Invoice", frm.doc.current_invoice), __("View"));
    }
    if (frm.doc.deposit_payment_entry) {
      frm.add_custom_button(__("Open Deposit Payment"), () => frappe.set_route("Form", "Payment Entry", frm.doc.deposit_payment_entry), __("View"));
    }
    if (frm.doc.deposit_refund_payment_entry) {
      frm.add_custom_button(__("Open Refund Payment"), () => frappe.set_route("Form", "Payment Entry", frm.doc.deposit_refund_payment_entry), __("View"));
    }
    frm.add_custom_button(__("Account Statement"), () => show_account_statement(frm), __("View"));
  },

  async customer(frm) {
    await dagaar_motors.forms.customer(frm, { suggestDriver: true, force: true });
    preview(frm);
  },

  async branch(frm) {
    await dagaar_motors.forms.branch(frm, { force: true });
    set_queries(frm);
    preview(frm);
  },

  async vehicle(frm) {
    if (!frm.doc.vehicle) return;
    await dagaar_motors.forms.vehicle(frm, "vehicle");
    set_queries(frm);
    preview(frm);
  },

  pickup_datetime: preview,
  expected_return_datetime: preview,
  rental_type: preview,
  vehicle_category: preview,
  discount_percent(frm) {
    // A percentage overrides any manual amount; clear it so intent is clear.
    if (Number(frm.doc.discount_percent || 0)) frm.set_value("discount_amount", 0);
    preview(frm);
  },
  discount_amount(frm) {
    // Typing an amount clears the percentage so the amount is used as-is.
    if (Number(frm.doc.discount_amount || 0) && Number(frm.doc.discount_percent || 0)) {
      frm.set_value("discount_percent", 0);
    }
    preview(frm);
  },
  pickup_location: preview,
  return_location: preview,
  one_way: preview,
  tax_template: preview,
});

frappe.ui.form.on("Rental Agreement Charge", {
  quantity: charge_row_changed,
  rate: charge_row_changed,
  charge_type(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.quantity) row.quantity = 1;
    charge_row_changed(frm, cdt, cdn);
  },
  charges_remove: preview,
});

function charge_row_changed(frm, cdt, cdn) {
  const row = locals[cdt][cdn];
  row.amount = (Number(row.quantity || 0)) * (Number(row.rate || 0));
  frm.refresh_field("charges");
  preview(frm);
}

frappe.ui.form.on("Rental Agreement Driver", {
  drivers_add(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if ((frm.doc.drivers || []).length === 1) row.primary_driver = 1;
    frm.refresh_field("drivers");
  },

  primary_driver(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.primary_driver) return;
    (frm.doc.drivers || []).forEach((driver) => {
      if (driver.name !== row.name) driver.primary_driver = 0;
    });
    frm.refresh_field("drivers");
  },
});

frappe.ui.form.on("Rental Agreement Extra", {
  rental_extra: preview,
  quantity: preview,
  rate: preview,
  extras_remove: preview,
});

function preview(frm) {
  dagaar_motors.forms.previewPricing(frm, "pickup_datetime", "expected_return_datetime");
}

async function maybe_add_deposit_button(frm) {
  const required = Number(frm.doc.deposit_required || 0);
  if (!(required > 0)) return;

  let status;
  try {
    const r = await frappe.call({ method: "dagaar_motors.api.rental.deposit_status", args: { agreement: frm.doc.name } });
    status = r && r.message;
  } catch (e) {
    return;
  }
  if (!status) return;
  const outstanding = Number(status.outstanding || 0);

  if (status.waived) {
    frm.dashboard.set_headline_alert(__("Security deposit waived — you can check out the vehicle."), "blue");
  } else if (outstanding <= 0) {
    frm.dashboard.set_headline_alert(__("Security deposit collected — you can check out the vehicle."), "green");
  } else {
    frm.dashboard.set_headline_alert(
      __("Collect the security deposit of {0} before checkout.", [format_currency(outstanding, frm.doc.currency)]),
      "orange"
    );
    frm.add_custom_button(__("Collect Deposit"), () => open_deposit_dialog(frm, outstanding), __("Actions"));
    try {
      frm.change_custom_button_type(__("Collect Deposit"), __("Actions"), "primary");
    } catch (e) {
      // Older Frappe versions may not expose change_custom_button_type; ignore.
    }
    // Waiver button only for permitted users (roles set in Settings).
    frappe.call({ method: "dagaar_motors.api.rental.can_waive_deposit" }).then((r) => {
      if (r && r.message) {
        frm.add_custom_button(__("Waive Deposit"), () => open_waive_dialog(frm), __("Actions"));
      }
    });
  }

  // Refund button: return the unused deposit to the customer as a Payment Entry.
  if (Number(status.refundable || 0) > 0) {
    frm.add_custom_button(__("Refund Deposit"), () => open_refund_dialog(frm, Number(status.refundable)), __("Actions"));
  }
}

function open_refund_dialog(frm, refundable) {
  const dialog = new frappe.ui.Dialog({
    title: __("Refund Security Deposit"),
    fields: [
      { fieldname: "amount", label: __("Refund Amount"), fieldtype: "Currency", default: refundable, reqd: 1, options: "currency" },
      { fieldname: "currency", fieldtype: "Data", hidden: 1, default: frm.doc.currency },
      { fieldname: "payment_method", label: __("Mode of Payment"), fieldtype: "Link", options: "Mode of Payment" },
      { fieldname: "reference_number", label: __("Reference No"), fieldtype: "Data" },
    ],
    primary_action_label: __("Refund"),
    async primary_action(values) {
      dialog.hide();
      await dagaar_motors.ui.call("dagaar_motors.api.rental.refund_deposit", {
        agreement: frm.doc.name,
        amount: values.amount,
        payment_method: values.payment_method,
        reference_number: values.reference_number,
      });
      frappe.show_alert({ message: __("Deposit refunded."), indicator: "green" });
      frm.reload_doc();
    },
  });
  dialog.show();
}

function open_waive_dialog(frm) {
  frappe.prompt(
    [{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 }],
    async (values) => {
      await dagaar_motors.ui.call("dagaar_motors.api.rental.waive_deposit", { agreement: frm.doc.name, reason: values.reason });
      frappe.show_alert({ message: __("Security deposit waived."), indicator: "blue" });
      frm.reload_doc();
    },
    __("Waive Security Deposit"),
    __("Waive")
  );
}

async function show_account_statement(frm) {
  const res = await dagaar_motors.ui.call("dagaar_motors.api.rental.account_statement", { agreement: frm.doc.name }, false);
  if (!res) return;
  const cur = res.currency;
  const rows = (res.lines || []).map((l) => `
    <tr>
      <td>${frappe.datetime.str_to_user(l.date) || l.date || ""}</td>
      <td>${frappe.utils.escape_html(l.description || "")}</td>
      <td style="text-align:right">${l.debit ? format_currency(l.debit, cur) : ""}</td>
      <td style="text-align:right">${l.credit ? format_currency(l.credit, cur) : ""}</td>
    </tr>`).join("");
  const html = `
    <div class="dm-statement">
      <p><b>${__("Customer")}:</b> ${frappe.utils.escape_html(res.customer || "")}
         &nbsp;·&nbsp; <b>${__("Days accrued")}:</b> ${res.accrued_days}
         &nbsp;·&nbsp; <b>${__("Daily rate")}:</b> ${format_currency(res.daily_rate, cur)}</p>
      <table class="table table-bordered" style="font-size:12px">
        <thead><tr>
          <th>${__("Date")}</th><th>${__("Description")}</th>
          <th style="text-align:right">${__("Debit")}</th>
          <th style="text-align:right">${__("Credit")}</th>
        </tr></thead>
        <tbody>${rows}</tbody>
        <tfoot>
          <tr>
            <th colspan="2" style="text-align:right">${__("Totals")}</th>
            <th style="text-align:right">${format_currency(res.total_debit, cur)}</th>
            <th style="text-align:right">${format_currency(res.total_credit, cur)}</th>
          </tr>
          <tr>
            <th colspan="3" style="text-align:right">${__("Balance due")}</th>
            <th style="text-align:right">${format_currency(res.balance, cur)}</th>
          </tr>
        </tfoot>
      </table>
    </div>`;
  const dialog = new frappe.ui.Dialog({ title: __("Account Statement"), size: "large", fields: [{ fieldtype: "HTML", fieldname: "body", options: html }] });
  dialog.show();
}

function open_deposit_dialog(frm, outstanding) {
  const dialog = new frappe.ui.Dialog({
    title: __("Collect Security Deposit"),
    fields: [
      { fieldname: "amount", label: __("Amount"), fieldtype: "Currency", default: outstanding, reqd: 1, options: "currency" },
      { fieldname: "currency", fieldtype: "Data", hidden: 1, default: frm.doc.currency },
      { fieldname: "payment_method", label: __("Mode of Payment"), fieldtype: "Link", options: "Mode of Payment" },
      { fieldname: "reference_number", label: __("Reference No"), fieldtype: "Data" },
    ],
    primary_action_label: __("Collect"),
    async primary_action(values) {
      dialog.hide();
      await dagaar_motors.ui.call("dagaar_motors.api.rental.collect_deposit", {
        agreement: frm.doc.name,
        amount: values.amount,
        payment_method: values.payment_method,
        reference_number: values.reference_number,
      });
      frappe.show_alert({ message: __("Security deposit collected."), indicator: "green" });
      frm.reload_doc();
    },
  });
  dialog.show();
}

function set_queries(frm) {
  frm.set_query("branch", () => ({ filters: frm.doc.company ? { company: frm.doc.company, active: 1 } : { active: 1 } }));
  frm.set_query("vehicle", () => ({
    filters: {
      company: frm.doc.company,
      branch: frm.doc.branch,
      category: frm.doc.vehicle_category,
      rentable: 1,
      status: ["in", ["Available", "Reserved", "Rented"]],
    },
  }));
  if (frm.fields_dict.contact) {
    frm.set_query("contact", () => ({
      query: "frappe.contacts.doctype.contact.contact.contact_query",
      filters: { link_doctype: "Customer", link_name: frm.doc.customer },
    }));
  }
}
