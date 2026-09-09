frappe.ui.form.on("Dagaar Motors Settings", {
  setup(frm) {
    const accountFields = [
      "rental_income_account",
      "extension_income_account",
      "late_return_income_account",
      "excess_mileage_income_account",
      "fuel_charge_income_account",
      "damage_recovery_income_account",
      "cleaning_charge_income_account",
      "cancellation_income_account",
      "driver_service_income_account",
      "delivery_income_account",
      "collection_income_account",
      "insurance_charge_income_account",
      "miscellaneous_rental_income_account",
      "deposit_liability_account",
      "deposit_clearing_account",
      "customer_receivable_account",
      "vehicle_operating_expense_account",
      "maintenance_expense_account",
      "repair_expense_account",
      "accident_expense_account",
      "insurance_expense_account",
      "registration_expense_account",
      "fuel_expense_account",
      "gain_on_vehicle_sale_account",
      "loss_on_vehicle_sale_account",
      "default_deposit_payment_account",
      "default_refund_payment_account",
    ];

    accountFields.forEach((fieldname) => {
      frm.set_query(fieldname, () => ({
        filters: {
          company: frm.doc.default_company || "",
          is_group: 0,
          disabled: 0,
        },
      }));
    });

    frm.set_query("default_branch", () => ({
      filters: { company: frm.doc.default_company || "", active: 1 },
    }));
    frm.set_query("default_cost_center", () => ({
      filters: { company: frm.doc.default_company || "", is_group: 0, disabled: 0 },
    }));
    frm.set_query("default_warehouse", () => ({
      filters: { company: frm.doc.default_company || "", is_group: 0, disabled: 0 },
    }));
  },

  refresh(frm) {
    frm.add_custom_button(__("Run Setup Health Check"), () => runHealthCheck(frm), __("Setup"));
    frm.add_custom_button(
      __("Open Command Center"),
      () => frappe.set_route("dagaar-motors-dashboard"),
      __("Setup")
    );
    renderStoredStatus(frm);
  },

  default_company(frm) {
    if (frm.doc.default_branch) {
      frm.set_value("default_branch", null);
    }
  },
});

function runHealthCheck(frm) {
  frappe.call({
    method: "dagaar_motors.api.setup.health_check",
    args: { update_settings: 1 },
    freeze: true,
    freeze_message: __("Validating Dagaar Motors configuration..."),
    callback: ({ message }) => {
      if (!message) return;
      frm.reload_doc().then(() => {
        renderReadiness(frm, message);
        showReadinessDialog(message);
      });
    },
  });
}

function renderStoredStatus(frm) {
  const wrapper = frm.fields_dict.setup_readiness_html?.$wrapper;
  if (!wrapper) return;
  const complete = Boolean(Number(frm.doc.setup_complete || 0));
  const lastRun = frm.doc.last_setup_validation
    ? frappe.datetime.str_to_user(frm.doc.last_setup_validation)
    : __("Not yet checked");
  wrapper.html(`
    <div class="dm-setup-status ${complete ? "is-ready" : "needs-work"}">
      <div>
        <div class="dm-setup-kicker">${__("SYSTEM READINESS")}</div>
        <h3>${complete ? __("Ready for operations") : __("Configuration check required")}</h3>
        <p>${frappe.utils.escape_html(frm.doc.setup_notes || __("Run the health check to validate required configuration."))}</p>
      </div>
      <div class="dm-setup-stamp">
        <strong>${complete ? __("READY") : __("REVIEW")}</strong>
        <span>${lastRun}</span>
      </div>
    </div>
  `);
}

function renderReadiness(frm, result) {
  frm.doc.setup_complete = result.ready ? 1 : 0;
  frm.doc.last_setup_validation = result.validated_on;
  frm.doc.setup_notes = result.summary;
  renderStoredStatus(frm);
}

function showReadinessDialog(result) {
  const rows = result.checks
    .map((row) => {
      const passed = row.status === "Pass";
      return `
        <div class="dm-health-row ${passed ? "pass" : "missing"}">
          <span class="dm-health-dot"></span>
          <div class="dm-health-copy">
            <strong>${frappe.utils.escape_html(row.label)}</strong>
            <span>${frappe.utils.escape_html(row.detail || "")}</span>
          </div>
          <span class="dm-health-tag">${passed ? __("Passed") : row.critical ? __("Required") : __("Recommended")}</span>
        </div>
      `;
    })
    .join("");

  const dialog = new frappe.ui.Dialog({
    title: __("Dagaar Motors Setup Health"),
    size: "large",
    fields: [{ fieldtype: "HTML", fieldname: "health_report" }],
    primary_action_label: result.ready ? __("Open Command Center") : __("Close"),
    primary_action() {
      dialog.hide();
      if (result.ready) frappe.set_route("dagaar-motors-dashboard");
    },
  });
  dialog.fields_dict.health_report.$wrapper.html(`
    <div class="dm-health-hero ${result.ready ? "is-ready" : "needs-work"}">
      <div>
        <span>${__("READINESS SCORE")}</span>
        <strong>${result.score}%</strong>
      </div>
      <p>${frappe.utils.escape_html(result.summary)}</p>
    </div>
    <div class="dm-health-list">${rows}</div>
  `);
  dialog.show();
}