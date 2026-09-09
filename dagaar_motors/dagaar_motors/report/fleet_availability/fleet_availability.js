frappe.query_reports["Fleet Availability"] = {
  filters: [
    {
      fieldname: "company",
      label: "Company",
      fieldtype: "Link",
      options: "Company",
      reqd: 1,
      default: frappe.defaults.get_user_default("Company")
    },
    {
      fieldname: "branch",
      label: "Branch",
      fieldtype: "Link",
      options: "Motor Branch",
      get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } })
    },
    {
      fieldname: "status",
      label: "Status",
      fieldtype: "Select",
      options: "\nPreparation\nAvailable\nReserved\nRented\nInspection\nMaintenance\nBlocked\nIn Transit\nFor Sale\nSold\nRetired"
    },
    {
      fieldname: "vehicle",
      label: "Vehicle",
      fieldtype: "Link",
      options: "Motor Vehicle"
    },
    {
      fieldname: "vehicle_category",
      label: "Vehicle Category",
      fieldtype: "Link",
      options: "Vehicle Category"
    },
  ],
};
