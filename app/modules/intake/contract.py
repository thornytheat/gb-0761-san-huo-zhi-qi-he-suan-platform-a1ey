HEADERS = {
    "events": "event_id,kind,time,party",
    "stops": "stop_id,kind,start,end",
    "terms": "version,start,end,priority,wait_min,allow_min,tier1_min,rate1_usd_min,rate2_usd_min",
    "invoice": "tier,minutes,usd",
}

# 新分票样式：同档可拆成多张原票，红字票以负数列示并携带票号；旧式分档账单仍是三列。
INVOICE_TICKET_HEADER = "ticket,tier,minutes,usd"
OPTIONAL_HEADERS = {"invoice": (HEADERS["invoice"], INVOICE_TICKET_HEADER)}
