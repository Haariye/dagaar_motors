frappe.pages["dagaar-motors-dashboard"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Motors"), single_column: true });
  page.set_primary_action(__("New Rental"), () => frappe.new_doc("Rental Agreement"), "add");
  page.add_menu_item(__("Add Vehicle"), () => frappe.new_doc("Motor Vehicle"));
  page.add_menu_item(__("Process Return"), () => frappe.new_doc("Rental Return"));
  page.add_menu_item(__("Vehicle Sale"), () => frappe.new_doc("Vehicle Sale"));
  page.add_menu_item(__("Maintenance"), () => frappe.new_doc("Vehicle Maintenance"));

  const state = { page, wrapper: $(wrapper).find(".layout-main-section") };
  state.company = page.add_field({
    fieldname: "company",
    label: __("Company"),
    fieldtype: "Link",
    options: "Company",
    default: frappe.defaults.get_default("Company"),
    change: () => {
      state.branch.set_value("");
      load(state);
    },
  });
  state.branch = page.add_field({
    fieldname: "branch",
    label: __("Branch"),
    fieldtype: "Link",
    options: "Motor Branch",
    change: () => load(state),
  });
  state.branch.get_query = () => ({ filters: { company: state.company.get_value(), active: 1 } });
  state.from_date = page.add_field({ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -1), change: () => load(state) });
  state.to_date = page.add_field({ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today(), change: () => load(state) });
  page.set_secondary_action(__("Refresh"), () => load(state), "refresh");
  load(state);
};

frappe.pages["dagaar-motors-dashboard"].on_page_show = function (wrapper) {
  const refresh = $(wrapper).find(".page-actions .btn-secondary");
  if (refresh.length) refresh.first().trigger("click");
};

async function load(state) {
  state.page.set_indicator(__("Refreshing"), "orange");
  try {
    const data = await frappe.xcall("dagaar_motors.api.dashboard.get_dashboard", {
      company: state.company.get_value(),
      branch: state.branch.get_value(),
      from_date: state.from_date.get_value(),
      to_date: state.to_date.get_value(),
    });
    render(state, data);
    state.page.set_indicator(__("Live"), "green");
  } catch (error) {
    state.page.set_indicator(__("Needs attention"), "red");
    state.wrapper.html(`<div class="dm-empty">${dagaar_motors.ui.escape(error.message || error)}</div>`);
  }
}

function render(state, data) {
  const k = data.kpis || {};
  const cards = [
    [__("Available"), k.available_vehicles, __("Vehicles ready now"), "check-circle", "Motor Vehicle", { status: "Available" }],
    [__("Active Rentals"), k.active_rentals, __("Currently on rent"), "car", "Rental Agreement", { status: ["in", ["Active", "Extended"]] }],
    [__("Overdue"), k.overdue_rentals, __("Needs follow-up"), "alert-triangle", "Rental Agreement", { status: "Overdue" }],
    [__("Maintenance"), k.maintenance_vehicles, __("In workshop / due"), "tool", "Vehicle Maintenance", { status: ["in", ["Due", "Scheduled", "In Progress"]] }],
  ];

  state.wrapper.html(`
    <div class="dm-dashboard dm-dashboard-simple">
      <section class="dm-hero dm-hero-simple">
        <div class="dm-hero-copy">
          <div class="dm-eyebrow">${__("RENT · MANAGE · MAINTAIN · SELL")}</div>
          <h1>${__("Everything important, without the clutter.")}</h1>
          <p>${__("Start a rental, add a vehicle, process a return, or sell a vehicle from one simple screen.")}</p>
        </div>
        <div class="dm-hero-actions">
          ${quickAction(__("New Rental"), __("Rent out a vehicle"), "car", "Rental Agreement")}
          ${quickAction(__("Add Vehicle"), __("Item and Asset auto-created"), "plus-circle", "Motor Vehicle")}
          ${quickAction(__("Process Return"), __("Finish an active rental"), "log-in", "Rental Return")}
          ${quickAction(__("Vehicle Sale"), __("Sell marked vehicles only"), "tag", "Vehicle Sale")}
        </div>
      </section>

      <section class="dm-kpi-grid dm-kpi-grid-simple">${cards.map(kpiCard).join("")}</section>

      <div class="dm-section-heading"><div><h2>${__("Today")}</h2><p>${__("Only the work that needs attention now.")}</p></div></div>
      <section class="dm-operations dm-operations-simple">
        ${operationCard(__("Pickups"), data.operations?.pickups, "pickup_datetime", "Rental Agreement")}
        ${operationCard(__("Returns"), data.operations?.returns, "expected_return_datetime", "Rental Agreement")}
        ${operationCard(__("Overdue"), data.operations?.overdue, "expected_return_datetime", "Rental Agreement")}
      </section>

      <section class="dm-card dm-simple-footer-card">
        <div class="dm-card-head"><h3>${__("Quick reports")}</h3><span>${__("Open only when you need detail")}</span></div>
        <div class="dm-quick-report-row">
          ${reportLink(__("Vehicle Profitability"), "Vehicle Profitability")}
          ${reportLink(__("Fleet Availability"), "Fleet Availability")}
          ${reportLink(__("Rental Revenue"), "Rental Revenue")}
          ${reportLink(__("Maintenance Due"), "Maintenance Due")}
        </div>
      </section>
    </div>`);

  state.wrapper.find("[data-new-doctype]").on("click", function () {
    frappe.new_doc(this.dataset.newDoctype);
  });
  state.wrapper.find("[data-route-target]").on("click", function () {
    frappe.route_options = JSON.parse(this.dataset.filters || "{}");
    frappe.set_route("List", this.dataset.routeTarget);
  });
  state.wrapper.find("[data-doctype][data-name]").on("click", function () {
    frappe.set_route("Form", this.dataset.doctype, this.dataset.name);
  });
  state.wrapper.find("[data-report]").on("click", function () {
    frappe.set_route("query-report", this.dataset.report);
  });
}

function quickAction(label, sub, icon, doctype) {
  return `<button class="dm-quick-action" data-new-doctype="${dagaar_motors.ui.escape(doctype)}"><span class="dm-quick-action-icon">${frappe.utils.icon(icon, "md")}</span><span><strong>${label}</strong><small>${sub}</small></span></button>`;
}

function kpiCard(card) {
  const [label, value, sub, icon, target, filters] = card;
  return `<article class="dm-kpi" data-route-target="${dagaar_motors.ui.escape(target)}" data-filters='${dagaar_motors.ui.escape(JSON.stringify(filters || {}))}'><div class="dm-kpi-top"><span>${label}</span><span class="dm-kpi-icon">${frappe.utils.icon(icon, "sm")}</span></div><div class="dm-kpi-value">${value ?? 0}</div><div class="dm-kpi-sub">${sub}</div></article>`;
}

function operationCard(title, rows = [], dateField, doctype) {
  const body = rows.map((row) => {
    const titleText = row.vehicle || row.customer || row.name;
    const meta = [row.customer, row.vehicle, row.status].filter(Boolean).join(" · ");
    return `<div class="dm-op-row" data-doctype="${doctype}" data-name="${dagaar_motors.ui.escape(row.name)}"><div class="dm-op-avatar">${dagaar_motors.ui.initials(titleText)}</div><div><div class="dm-op-title">${dagaar_motors.ui.escape(titleText)}</div><div class="dm-op-meta">${dagaar_motors.ui.escape(meta)}</div></div><div class="dm-op-time">${dagaar_motors.ui.escape(row[dateField] || "")}</div></div>`;
  }).join("") || `<div class="dm-empty">${__("Nothing waiting here.")}</div>`;
  return `<article class="dm-card dm-op-card"><div class="dm-card-head"><h3>${title}</h3><span>${rows.length}</span></div><div class="dm-op-list">${body}</div></article>`;
}

function reportLink(label, report) {
  return `<button class="btn btn-default btn-sm" data-report="${dagaar_motors.ui.escape(report)}">${label}</button>`;
}
