// Copyright (c) 2020, Bhavesh Maheshwari and contributors
// For license information, please see license.txt

frappe.ui.form.on('Connector Sales Order', {
	refresh:function(frm){
		var msg = ""
		frappe.db.get_value('Connector Setting',
		'Connector Setting', 'sync_to')
			.then(r => {
			console.log(r.message)
			if (r.message.sync_to == "Sales Order") {
				 msg = "Create Sales Order"

			}
			else{
				msg = "Create Sales Invoice"
			}
			console.log(msg)
			frm.add_custom_button(__(msg), function(){
                        if(frm.doc.sync == 1){
                                frappe.msgprint('Order Already Created')
                                return
                        }
                        frappe.call({
                                'method': 'connector.api.sync_sales_order',
                                'args':{
                                'order_no': frm.doc.name
                                },
                                'callback':function(res){
                                        if(res.message){
                                                frappe.msgprint("Sales Invoice created")
                                        	}
                                	}
                        	})
                	})
		});
	}
});
