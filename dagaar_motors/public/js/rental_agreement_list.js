frappe.listview_settings["Rental Agreement"] = {
  add_fields: ["status", "vehicle", "customer", "expected_return_datetime", "grand_total"],
  get_indicator(doc) {
    const map = {
      Active: [__("Active"), "green", "status,=,Active"],
      Extended: [__("Extended"), "blue", "status,=,Extended"],
      Overdue: [__("Overdue"), "red", "status,=,Overdue"],
      "Ready for Pickup": [__("Ready for Pickup"), "orange", "status,=,Ready for Pickup"],
      Completed: [__("Completed"), "gray", "status,=,Completed"],
      Closed: [__("Closed"), "gray", "status,=,Closed"],
      Cancelled: [__("Cancelled"), "red", "status,=,Cancelled"],
    };
    return map[doc.status] || [__(doc.status || "Draft"), "gray", `status,=,${doc.status}`];
  },
};