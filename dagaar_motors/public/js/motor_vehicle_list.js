frappe.listview_settings["Motor Vehicle"] = {
  add_fields: ["status", "license_plate", "category", "branch", "rentable", "sellable"],
  get_indicator(doc) {
    const map = {
      Available: [__("Available"), "green", "status,=,Available"],
      Reserved: [__("Reserved"), "blue", "status,=,Reserved"],
      Rented: [__("Rented"), "purple", "status,=,Rented"],
      Maintenance: [__("Maintenance"), "orange", "status,=,Maintenance"],
      Blocked: [__("Blocked"), "red", "status,=,Blocked"],
      "For Sale": [__("For Sale"), "yellow", "status,=,For Sale"],
      Sold: [__("Sold"), "gray", "status,=,Sold"],
    };
    return map[doc.status] || [__(doc.status || "Unknown"), "gray", `status,=,${doc.status}`];
  },
};