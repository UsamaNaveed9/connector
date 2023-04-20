from __future__ import unicode_literals
import frappe, json
from frappe import _
from erpnext.accounts.utils import get_balance_on
from frappe.utils import cint, fmt_money,flt,cstr, getdate,add_days
from frappe.utils.pdf import get_pdf
import frappe.permissions
from six.moves import range
from erpnext.accounts.doctype.journal_entry.journal_entry import get_party_account_and_balance 

@frappe.whitelist()
def cron_sync_order():
	orders = frappe.db.sql("""select name as 'order' from `tabConnector Sales Order` where sync=0 and retry_limit>0 order by creation desc limit 20""",as_dict=1)
	sync_sales_order_multiple_cron(orders)

@frappe.whitelist()
def sync_sales_order_multiple_cron(names):
	msg = ""
	for name in names:
		try:
			sync = frappe.db.get_value("Connector Sales Order",name.order,"sync")
			if int(sync) == 0:
				sync_sales_order(name.order)
			else:
				msg += "Order Alredy Synced {0}".format(name.order) + "<br/>"
		except Exception as e:
			msg += "Something Wrong in sync order {0}".format(name.order) + "<br/>"
	if not msg == "":
		frappe.msgprint(msg)

@frappe.whitelist()
def sync_sales_order_multiple(names):
	names = json.loads(names)
	msg = ""
	for name in names:
		try:
			sync = frappe.db.get_value("Connector Sales Order",name,"sync")
			
			if int(sync) == 0:
				sync_sales_order(name)
			else:
				msg += "Order Alredy Synced {0}".format(name) + "<br/>"
		except Exception as e:
			msg += "Something Wrong in sync order {0}".format(name) + "<br/>"
			frappe.log_error(frappe.get_traceback())
	if not msg == "":
		frappe.msgprint(msg)

@frappe.whitelist()
def sync_sales_order(order_no):
	if frappe.db.get_value('Connector Sales Order',order_no,'order_type') in [ "store_account_payment","Store Account Payment"]:
		return False
	if frappe.db.get_value('Connector Sales Order', order_no, 'sync'):
		frappe.throw('Order already synced')
		return False
	frappe.db.sql(''' update `tabConnector Sales Order` set retry_limit=%s where name=%s ''',( frappe.db.get_value('Connector Sales Order', order_no, 'retry_limit')-1, order_no) )
	if frappe.db.get_value("Connector Setting","Connector Setting","sync_to") == "Sales Order":
		create_sales_order(order_no)
	else:
		create_sales_invoice(order_no)
	# if frappe.db.get_value('Connector Sales Order', order_no, 'pos_profile'):
 	#	create_sales_invoice(order_no)
	# 	return True
	# else:
	return True
	# return False

def create_sales_order(order_no):
	order_doc = frappe.get_doc("Connector Sales Order",order_no)
	if order_doc:
		customer_id = check_customer(order_doc)
		items = get_items(order_doc)
		taxes = get_taxes(order_doc)
		delivery_day = str(frappe.db.get_value("Connector Setting","Connector Setting","delivery_day"))
		submit_order = int(frappe.db.get_value("Connector Setting","Connector Setting","submit_order"))
		sales = get_sales_team(order_doc)
		so_doc = frappe.get_doc(dict(
			doctype = "Sales Order",
			customer = customer_id,
			items = items,
			transaction_date = order_doc.transaction_date,
			delivery_date = order_doc.transaction_date,
			taxes = taxes,
			connector_address_line1 = order_doc.address_line1,
			connector_address_line2 = order_doc.address_line2,
			connector_city = order_doc.city or 'NA',
			connector_state = order_doc.state,
			connector_email = order_doc.email,
			connector_mobile_no = order_doc.mobile_no,
			connector_country = order_doc.country,
			apply_discount_on = "Grand Total",
			additional_discount_percentage = order_doc.additional_discount_percentage,
			discount_amount = order_doc.discount_amount,
			sales_order_payment = get_payment_details(order_doc),
			reference_num = order_doc.reference_no,
			delivery_time = order_doc.delivery_time,
			sales_team = sales,
			notes = order_doc.notes,
			actual_delivery_date = order_doc.delivery_date,
		))
		so_doc.save(ignore_permissions = True)
		if so_doc.name:
			if int(submit_order):
				so_doc.submit()
			frappe.db.set_value("Connector Sales Order",order_no,"sync",1)
			frappe.db.set_value("Connector Sales Order", order_no, 'status', 'Synced')
			return True
		else:
			return False

def create_sales_invoice(order_no):
	order_doc = frappe.get_doc("Connector Sales Order",order_no)
	if order_doc:
		si = frappe.db.get_value('Sales Invoice',{"reference_number":order_doc.reference_no})
		if si:
			si_doc = frappe.get_doc('Sales Invoice',si)
			si_doc.reference_number = ""
			si_doc.save(ignore_permissions = True)
			si_doc.cancel()
		is_return = 0
		if not order_doc.set_warehouse:

			frappe.throw("No Source Warehouse is selected")
		if not order_doc.cost_center:
			frappe.throw("No Cost Center is selected")
		customer_id = check_customer(order_doc)
		if not customer_id:
			customer_id = 'Cash Customer'
		source_warehouse = frappe.db.get_value('Warehouse',{'warehouse_name':order_doc.set_warehouse})
		if not source_warehouse:
			frappe.throw("Warehouse - {0} not found".format(order_doc.set_warehouse))
		cost_center = frappe.db.get_value('Cost Center',{'cost_center_name':order_doc.cost_center})
		if order_doc.company:
			source_warehouse = frappe.db.get_value('Warehouse',{'warehouse_name':order_doc.set_warehouse,'company':order_doc.company})
			cost_center = frappe.db.get_value('Cost Center',{'cost_center_name':order_doc.cost_center,'company':order_doc.company})
		if not cost_center:
			frappe.throw("Cost Center - {0} not found".format(order_doc.cost_center))
		if order_doc.order_type in [ "store_account_payment","Store Account Payment"]:
			#create_journal_entry(order_doc)
			return False
		items= get_items(order_doc,source_warehouse,cost_center)
		write_off_amt = 0
#		if order_doc.order_type == "return":
#			is_return = 1
#			create_sales_return(order_doc,items,cost_center,source_warehouse)
#			return True
		if order_doc.order_type == "return":
			is_return = 1
#			create_sales_return(order_doc,items)
#			tl = 0
#			for row in order_doc.items:
#				tl = tl + (row.qty *row.rate)
#			order_doc.total = tl
#			tot_pay = 0
#			for pay in get_payment_details(order_doc):
#				tot_pay += pay['amount']
#			write_off_amt = "{0:.4f}".format(abs(order_doc.total - tot_pay))
		discount_amt = get_discount(order_doc)
		taxes = get_taxes(order_doc)
		sales = get_sales_team(order_doc)
		delivery_day = str(frappe.db.get_value("Connector Setting","Connector Setting","delivery_day"))
		submit_invoice = frappe.db.get_value("Connector Setting","Connector Setting","submit_invoice")
		si_doc = frappe.get_doc(dict(
			doctype = "Sales Invoice",
			customer = customer_id,
			is_return = is_return,
			items = items,
			update_stock = 1,
			is_pos = 1,
			connector_address_line1 = order_doc.address_line1,
			connector_address_line2 = order_doc.address_line2,
			connector_city = order_doc.city or 'NA',
			connector_state = order_doc.state,
			connector_email = order_doc.email,
			connector_mobile_no = order_doc.mobile_no,
			connector_country = order_doc.country,
			pos_profile = order_doc.pos_profile,
			cost_center = cost_center,
			set_warehouse = source_warehouse,
			set_posting_time = 1,
			posting_date = order_doc.transaction_date,
			due_date = order_doc.transaction_date,
			reference_number = order_doc.reference_no,
			taxes = taxes,
			sales_team = sales,
			apply_discount_on = "Grand Total",
			additional_discount_percentage = order_doc.additional_discount_percentage,
			discount_amount = discount_amt,
			payments = get_payment_details(order_doc),
			write_off_amount = -1*write_off_amt
		))
		si_doc.save(ignore_permissions = True)
		if si_doc.name:
			if si_doc.customer == "Cash Customer":
				si_doc.write_off_amount = si_doc.total - order_doc.total
				si_doc.outstanding_amount = 0
				si_doc.save(ignore_permissions = True)
			else:
				si_doc.write_off_amount = si_doc.total - order_doc.total
				si_doc.save(ignore_permissions = True)
			if si_doc.paid_amount:
				if si_doc.paid_amount > si_doc.grand_total:
					si_doc.write_off_amount = 0
					si_doc.save(ignore_permissions = True)
			if not si_doc.payments:
				si_doc.is_pos = 0
				si_doc.save(ignore_permissions = True)

			if int(submit_invoice):
				si_doc.submit()
			frappe.db.set_value("Connector Sales Order",order_no,"sync",1)
			frappe.db.set_value("Connector Sales Order", order_no, 'status', 'Synced')
			return True
	return False

def create_journal_entry(order_doc):
	customer_id = check_customer(order_doc)
	party_account = get_party_account_and_balance("Abdul Razzaq","Customer",customer_id,order_doc.cost_center)['account']
	if not party_account:
		frappe.throw("Party Account Cannot not found")
	doc = frappe.new_doc("Journal Entry")
	doc.posting_date = order_doc.transaction_date
	cr = 0
	for i in order_doc.items:
		cr += i.rate
	doc.append("accounts",{
		"account":party_account,
		"party_type":"Customer",
		"party":customer_id,
		"credit_in_account_currency":cr,
		"cost_center":frappe.db.get_value('Cost Center',{'cost_center_name':order_doc.cost_center}),
		"user_remark":order_doc.reference_no
	})
	for i in get_payment_details(order_doc):
		account = frappe.db.get_value("Mode of Payment Account",{"parent":i['mode_of_payment']},"default_account")
		doc.append("accounts",{
			"account":account,
			"debit_in_account_currency":i['amount']
		})
	doc.save(ignore_permissions = True)
	if doc.name:
		try:
			doc.submit()
			frappe.db.set_value("Connector Sales Order",order_doc.name,"sync",1)
			frappe.db.set_value("Connector Sales Order", order_doc.name, 'status', 'Synced')

		except:
			frappe.log_error(title = "Journal Entry Not Submit",message = frappe.get_traceback())
def create_sales_return(order_doc,items,cost_center,source_warehouse):
		if order_doc:
#			tl = 0
#			for row in order_doc.items:
#				tl = tl + (row.qty * row.rate)
#			write_off_amt = tl - order_doc.total
#			frappe.errprint(tl)
#			frappe.errprint(write_off_amt)
			customer_id = check_customer(order_doc)
			delivery_day = str(frappe.db.get_value("Connector Setting","Connector Setting","delivery_day"))
			discount_amt = get_discount(order_doc)
			taxes = get_taxes(order_doc)
			sales = get_sales_team(order_doc)
			si_doc = frappe.get_doc(dict(
                	        doctype = "Sales Invoice",
                        	customer = customer_id,
                        	is_return = 1,
                        	items = items,
                        	update_stock = 1,
                        	connector_address_line1 = order_doc.address_line1,
                        	connector_address_line2 = order_doc.address_line2,
                        	connector_city = order_doc.city or 'NA',
                        	connector_state = order_doc.state,
                        	connector_email = order_doc.email,
                        	connector_mobile_no = order_doc.mobile_no,
                        	connector_country = order_doc.country,
                        	set_posting_time = 1,
                        	posting_date = order_doc.transaction_date,
                        	due_date = order_doc.transaction_date,
                        	reference_number = order_doc.reference_no,
				cost_center = cost_center,
                        	set_warehouse = source_warehouse,
	                        taxes = taxes,
        	                sales_team = sales,
                	        apply_discount_on = "Grand Total",
                        	additional_discount_percentage = order_doc.additional_discount_percentage,
                        	discount_amount = discount_amt,
                	))
			si_doc.save(ignore_permissions = True)
			si_doc.is_pos = 1
			si_doc.pos_profile = order_doc.pos_profile
			paid_amt = 0
			for i in get_payment_details(order_doc):
				si_doc.append("payments",{
					"mode_of_payment":i['mode_of_payment'],
					"amount":i['amount']
				})
				paid_amt += i['amount']
			si_doc.paid_amount = paid_amt
			difference = si_doc.paid_amount + si_doc.write_off_amount
			si_doc.save(ignore_permissions = True)
			try:
				submit_invoice = frappe.db.get_value("Connector Setting","Connector Setting","submit_invoice")
				if int(submit_invoice):
					si_doc.submit()
				frappe.db.set_value("Connector Sales Order",order_no,"sync",1)
				frappe.db.set_value("Connector Sales Order", order_no, 'status', 'Synced')
			except:
				frappe.log_error(title  = "Sales Retun Not Synced", message = frappe.get_traceback())
def get_items(order_doc,warehouse=None,cost_center=None):
	items = []
	for row in order_doc.items:
		main_item = ""
		if row.item_code and row.item_code != "Discount":
			main_item = frappe.db.get_value("Item",row.item_code)
		if not main_item:
			if row.item_name and row.item_name != "Discount":
				main_item = frappe.db.get_value("Item",{"item_name":row.item_name})
				if not main_item:
					frappe.throw("Item - {0} not found".format(row.item_name))
			elif row.item_name != "Discount":
				frappe.throw("Item - {0} not found".format(row.item_code))
		item = dict(
			item_code = main_item,
			qty = row.qty,
			rate = row.rate,
			warehouse = warehouse,
			cost_center = cost_center,
			uom = row.uom
		)
		if row.item_code != "Discount":
			items.append(item)
	return items

def get_discount(order_doc):
	discount_amount = 0
	for row in order_doc.items:
		if row.item_code == "Discount":
			discount_amount = row.rate

	return discount_amount

def get_taxes(order_doc):
	taxes = []
	if order_doc.delivery_charges:
		tax = dict(
			charge_type = "Actual",
			account_head = frappe.db.get_value("Connector Setting","Connector Setting","delivery_account"),
			tax_amount = order_doc.delivery_charges,
			description = "Delivery Charges"
		)
		taxes.append(tax)
	if order_doc.total_taxes_and_charges:
		tax = dict(
			charge_type = "Actual",
			account_head = frappe.db.get_value("Connector Setting","Connector Setting","tax_account"),
			tax_amount = order_doc.total_taxes_and_charges,
			description = "Taxes"
		)
		taxes.append(tax)
	return taxes

def get_sales_person(sales):
	name = None
	if frappe.db.get_value('Sales Person', {'sales_person_name':sales.sales_person }):
		name = frappe.db.get_value('Sales Person', {'sales_person_name':sales.sales_person })
	else:
		doc = frappe.get_doc({
			'doctype': 'Sales Person',
			'sales_person_name':sales.sales_person,
		})
		doc.save()
		name = doc.name
	return name

def get_sales_team(self):
	sales_team = []
	for i in self.sales_team:
		sales_team.append(dict(
			sales_person = get_sales_person(i),
			contact_no = i.contact_no,
			allocated_percentage = i.allocated_percentage or 100,
			allocated_amount = i.allocated_amount,
			commission_rate = i.commission_rate,
			incentives = i.incentives
		))
	return sales_team

def get_payment_details(order_doc):
	payments = []
	bal_amount = 0
	for row in order_doc.connector_payment:
		if row.get('mode_of_payment') in [" ","",'',' ']:
			continue
		pay = dict(
			mode_of_payment = row.get('mode_of_payment'), #frappe.db.sql('''select mode_of_payment from `tabPOS Payment Method` where parent=%s and mapper_key=%s''',( order_doc.pos_profile, row.get('mode_of_payment')), as_dict=1)[0].mode_of_payment,
			amount = row.get('amount')
		)
		payments.append(pay)
	if not payments:
		return []
	return payments


def check_customer(order_doc):
	customer = ''
	address = ''
	customer_data = ''
	if order_doc.customer:
		customer_data= frappe.db.sql("""select name from `tabCustomer` where customer_name=%s""",(order_doc.customer),as_dict=1)
	else:
		if order_doc.mobile_no or order_doc.email:
			customer_data = frappe.db.sql("""select name from `tabCustomer` where email_id=%s and mobile_no=%s""",(order_doc.email,order_doc.mobile_no),as_dict=1)
			if not customer_data:
				customer = 'Cash Customer'
	if len(customer_data) >= 1:
		customer = customer_data[0].name
	if not order_doc.email and not order_doc.mobile_no and not order_doc.customer:
		customer = 'Cash Customer'
	elif not customer:
		customer = create_customer(order_doc)
	return customer

def check_address(order_doc,customer):
	address_data = frappe.db.sql("""select p.name as 'name' from `tabDynamic Link` as c inner join `tabAddress` as p on c.parent=p.name where c.link_doctype='Customer' and c.link_name=%s""",customer,as_dict=1)
	if len(address_data) >= 1:
		# frappe.errprint(address_data)
		address_doc = frappe.get_doc("Address",address_data[0].name)
		address_doc.address_line1 = order_doc.address_line1
		address_doc.address_line2 = order_doc.address_line2
		address_doc.city = order_doc.city or 'NA'
		address_doc.state = order_doc.state
		address_doc.country = order_doc.country
		address_doc.email_id = order_doc.email
		address_doc.phone = order_doc.mobile_no
		address_doc.save(ignore_permissions = True)
		return address_data[0].link_name
	else:
		return False


def create_address(order_doc,customer):
	if order_doc.address_line1:
		doc = frappe.get_doc(dict(
			doctype = "Address",
			address_line1 = order_doc.address_line1,
			address_line2 = order_doc.address_line2,
			city = order_doc.city or 'NA',
			state = order_doc.state,
			country = order_doc.country,
			email_id = order_doc.email,
			phone = order_doc.mobile_no
		))
		doc.append("links",{
			"link_doctype":"Customer",
			"link_name":customer
		})
		res = doc.insert(ignore_permissions=True)
		return res.name

def create_customer(order_doc):
	doc = frappe.get_doc(dict(
		doctype = "Customer",
		customer_name = order_doc.customer,
		email_id = order_doc.email,
		mobile_no = order_doc.mobile_no,
		customer_group = frappe.db.get_value("Connector Setting","Connector Setting","customer_group"),
		territory = frappe.db.get_value("Connector Setting","Connector Setting","territory")
	)).insert(ignore_permissions = True)
	return doc.name

def on_submit(self,method):
	for row in self.items:
		row.warehouse_bin = get_bin(row.item_code)

@frappe.whitelist()
def on_cancel(self,method):
	frappe.db.sql("""update `tabSales Invoice` set reference_number = null where name =%s """,(self.name))
	frappe.db.commit()

def get_bin(item_code):
	bin = frappe.db.sql("""select c.warehouse_bin as 'warehouse_bin' from `tabItem Warehouse Bin Item` as c inner join `tabItem Warehouse Bin` as p on c.parent=p.name where p.item_code=%s""",(item_code),as_dict=1)
	if bin:
		return bin[0].warehouse_bin

