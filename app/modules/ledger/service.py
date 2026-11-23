from decimal import Decimal

from .rates import tier_costs


def _conflict_lines(quarantined, tier):
    return sorted(q["line"] for q in quarantined
                  if q["source"] == "invoice" and q["code"] == "KEY_CONFLICT"
                  and (q.get("tier") == tier or q.get("key") == tier))


def compare(notice, clock, invoice, quarantined):
    tickets = {}
    for item in invoice:
        tickets.setdefault(item["tier"], []).append(item)
    rows = []
    for tier in tier_costs(notice["term"], clock["overtime_min"]):
        number = tier["tier"]
        disputed = _conflict_lines(quarantined, number)
        if disputed:
            rows.append({**tier, "code": "INVOICE_CONFLICT", "invoice_line": None, "invoice_lines": [],
                         "conflict_lines": disputed, "actual_usd": None, "actual_minutes": None,
                         "gross_usd": None, "credit_usd": None, "net_usd": None,
                         "gross_minutes": None, "credit_minutes": None, "net_minutes": None,
                         "uncovered_red_usd": None, "uncovered_red_minutes": None, "delta_usd": None})
            continue
        seen = tickets.get(number)
        if not seen:
            rows.append({**tier, "code": "INVOICE_MISSING", "invoice_line": None, "invoice_lines": [],
                         "conflict_lines": [], "actual_usd": None, "actual_minutes": None,
                         "gross_usd": None, "credit_usd": None, "net_usd": None,
                         "gross_minutes": None, "credit_minutes": None, "net_minutes": None,
                         "uncovered_red_usd": None, "uncovered_red_minutes": None, "delta_usd": None})
            continue
        gross_usd = sum((Decimal(item["usd"]) for item in seen if item["kind"] == "ORIGINAL"), Decimal())
        credit_usd = sum((-Decimal(item["usd"]) for item in seen if item["kind"] == "CREDIT"), Decimal())
        gross_minutes = sum(item["minutes"] for item in seen if item["kind"] == "ORIGINAL")
        credit_minutes = sum(-item["minutes"] for item in seen if item["kind"] == "CREDIT")
        # 月末只交代能确认的净额：先到的红字票若超过已到原票，超出部分另列待冲，不把档位冲成负数。
        net_usd = max(Decimal(), gross_usd - credit_usd)
        net_minutes = max(0, gross_minutes - credit_minutes)
        uncovered_usd = max(Decimal(), credit_usd - gross_usd)
        uncovered_minutes = max(0, credit_minutes - gross_minutes)
        if uncovered_usd or uncovered_minutes:
            code = "RED_UNCOVERED"
            delta_usd = None
        else:
            delta = Decimal(tier["expected_usd"]) - net_usd
            delta_usd = f"{delta:.2f}"
            code = "MATCH" if not delta and tier["minutes"] == net_minutes else "TIER_DIFFERENCE"
        lines = sorted(item["line"] for item in seen)
        legacy = len(lines) == 1 and "ticket" not in seen[0]
        rows.append({**tier, "code": code,
                     "invoice_line": lines[0] if legacy else None,
                     "invoice_lines": lines, "conflict_lines": [],
                     "actual_usd": f"{net_usd:.2f}", "actual_minutes": net_minutes,
                     "gross_usd": f"{gross_usd:.2f}", "credit_usd": f"{credit_usd:.2f}",
                     "net_usd": f"{net_usd:.2f}",
                     "gross_minutes": gross_minutes, "credit_minutes": credit_minutes, "net_minutes": net_minutes,
                     "uncovered_red_usd": f"{uncovered_usd:.2f}",
                     "uncovered_red_minutes": uncovered_minutes,
                     "delta_usd": delta_usd})
    complete = all(r["delta_usd"] is not None for r in rows)
    expected = sum(Decimal(r["expected_usd"]) for r in rows)
    seen_total = sum(Decimal(r["net_usd"]) for r in rows if r["net_usd"] is not None)
    uncovered_total = sum(Decimal(r["uncovered_red_usd"]) for r in rows if r["uncovered_red_usd"] is not None)
    return {"expected_usd": f"{expected:.2f}", "seen_invoice_usd": f"{seen_total:.2f}",
            "confirmed_net_usd": f"{seen_total:.2f}",
            "uncovered_red_usd": f"{uncovered_total:.2f}",
            "delta_usd": f"{expected - seen_total:.2f}" if complete else None,
            "complete": complete, "differences": sum(r["code"] != "MATCH" for r in rows), "rows": rows}
