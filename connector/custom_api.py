import frappe

@frappe.whitelist()
def get_sales_person():
	sp = frappe.db.sql('''select sales_person_name,name as id,parent as parent_sales_person from `tabSales Person` where enabled = 1''',as_dict =1)
	return sp
