from decimal import Decimal

from app.input import sample
from app.modules.intake.service import accept
from app.modules.runs.service import archive
from app.pipeline import evaluate


TICKET_HEADER = "ticket,tier,minutes,usd\n"


def ledger(sources):
    return evaluate(sources)["ledger"]


def ticketed(dirty, body):
    sources = dict(dirty)
    sources["invoice"] = TICKET_HEADER + body
    return sources


def test_tier_split_original_tickets_aggregate(dirty):
    result = ledger(ticketed(dirty, "A1,1,10,30\nA2,1,10,30\nB1,2,8,40\nB2,2,12,60\n"))
    first, second = result["rows"]
    assert first["code"] == "MATCH" and second["code"] == "MATCH"
    assert (first["invoice_lines"], first["gross_minutes"], first["net_usd"]) == ([2, 3], 20, "60.00")
    assert (second["net_minutes"], second["net_usd"]) == (20, "100.00")
    assert result["delta_usd"] == "0.00" and result["complete"] is True


def test_early_credit_ticket_cannot_turn_tier_negative(dirty):
    # 第 2 档只到红字票 -5/-25，原票尚未到。
    result = ledger(ticketed(dirty, "A1,1,20,60\nR1,2,-5,-25\n"))
    first, second = result["rows"]
    assert first["code"] == "MATCH"
    assert second["code"] == "RED_UNCOVERED"
    assert second["net_usd"] == "0.00" and second["net_minutes"] == 0
    assert (second["uncovered_red_usd"], second["uncovered_red_minutes"]) == ("25.00", 5)
    assert second["delta_usd"] is None and result["complete"] is False
    assert result["delta_usd"] is None
    # 可确认净额不被红字带成负数。
    assert Decimal(result["confirmed_net_usd"]) >= 0
    assert result["uncovered_red_usd"] == "25.00"


def test_late_original_tickets_recheck_then_match(dirty):
    partial = ticketed(dirty, "A1,1,20,60\nR1,2,-5,-25\n")
    assert ledger(partial)["rows"][1]["code"] == "RED_UNCOVERED"
    # 晚到的原票补齐：先到一张只覆盖红字，仍有差额；再补一张后分钟与金额齐。
    filled = ticketed(dirty, "A1,1,20,60\nR1,2,-5,-25\nB1,2,5,25\nB2,2,20,100\n")
    result = ledger(filled)
    second = result["rows"][1]
    assert (second["gross_minutes"], second["credit_minutes"], second["net_minutes"]) == (25, 5, 20)
    assert (second["gross_usd"], second["credit_usd"], second["net_usd"]) == ("125.00", "25.00", "100.00")
    assert second["code"] == "MATCH" and result["complete"] is True
    assert result["delta_usd"] == "0.00"


def test_credit_partially_covered_keeps_net_non_negative(dirty):
    # 原票 3/15 已到、红字 5/25 已到：净额按 0 封边，待冲 2/10。
    result = ledger(ticketed(dirty, "A1,1,20,60\nB1,2,3,15\nR1,2,-5,-25\n"))
    second = result["rows"][1]
    assert second["code"] == "RED_UNCOVERED"
    assert (second["net_usd"], second["net_minutes"]) == ("0.00", 0)
    assert (second["uncovered_red_usd"], second["uncovered_red_minutes"]) == ("10.00", 2)


def test_credit_against_sufficient_original_is_confirmed(dirty):
    # 原票 25/125，红字 5/25：净额 20/100，与应计相符。
    result = ledger(ticketed(dirty, "A1,1,20,60\nB1,2,25,125\nR1,2,-5,-25\n"))
    assert result["rows"][1]["code"] == "MATCH"
    assert result["delta_usd"] == "0.00" and result["uncovered_red_usd"] == "0.00"


def test_repeated_ticket_id_is_idempotent_not_double_offset(dirty):
    once = ticketed(dirty, "A1,1,20,60\nB1,2,25,125\nR1,2,-5,-25\n")
    twice = dict(once)
    twice["invoice"] += "R1,2,-5,-25\n"  # 同票号、完全一致的重跑行
    assert ledger(twice) == ledger(once)
    intake = accept(twice)
    invoice_dupes = [q for q in intake["isolated"] if q["source"] == "invoice" and q["code"] == "EXACT_DUPLICATE"]
    assert [q["line"] for q in invoice_dupes] == [5]
    assert ledger(twice)["rows"][1]["credit_usd"] == "25.00"


def test_conflicting_ticket_ids_isolate_whole_group(dirty):
    sources = ticketed(dirty, "A1,1,20,60\nB1,2,25,125\nR1,2,-5,-25\nR1,2,-4,-20\n")
    intake = accept(sources)
    conflicts = [q for q in intake["isolated"] if q["source"] == "invoice" and q["code"] == "KEY_CONFLICT"]
    assert {q["line"] for q in conflicts} == {4, 5}
    assert {q["tier"] for q in conflicts} == {2}
    result = ledger(sources)
    assert result["rows"][1]["code"] == "INVOICE_CONFLICT"
    assert result["rows"][1]["conflict_lines"] == [4, 5]
    assert result["complete"] is False


def test_mixed_sign_ticket_is_isolated(dirty):
    result = ledger(ticketed(dirty, "A1,1,20,60\nR1,2,-5,25\n"))
    intake = accept(ticketed(dirty, "A1,1,20,60\nR1,2,-5,25\n"))
    assert any(q["code"] == "TICKET_SIGN_MISMATCH" for q in intake["isolated"])
    assert result["rows"][1]["code"] == "INVOICE_MISSING"


def test_legacy_three_column_header_keeps_tier_dedupe(dirty):
    legacy = dict(dirty)
    legacy["invoice"] = "tier,minutes,usd\n1,20,60\n2,19,95\n2,19,95\n"
    intake = accept(legacy)
    invoice_dupes = [q for q in intake["isolated"] if q["source"] == "invoice"]
    assert [q["code"] for q in invoice_dupes] == ["EXACT_DUPLICATE"]
    result = ledger(legacy)
    assert result["rows"][1]["invoice_line"] == 3 and result["rows"][1]["code"] == "TIER_DIFFERENCE"


def test_legacy_negative_invoice_still_rejected(dirty):
    legacy = dict(dirty)
    legacy["invoice"] = "tier,minutes,usd\n1,20,60\n2,-5,-25\n"
    intake = accept(legacy)
    assert any(q["code"] == "INVALID_AMOUNT" for q in intake["isolated"])


def test_rerun_same_ticket_batch_archives_once(tmp_path, dirty):
    sources = ticketed(dirty, "A1,1,20,60\nB1,2,25,125\nR1,2,-5,-25\n")
    first, inserted_first = archive(tmp_path / "db", sources)
    again, inserted_again = archive(tmp_path / "db", sources)
    assert (inserted_first, inserted_again) == (True, False)
    assert first["run_id"] == again["run_id"]
    assert first["results"]["ledger"] == again["results"]["ledger"]


def test_uncovered_red_blocks_certificate_but_recovers(dirty, clean, tmp_path):
    from app.modules.evidence.service import certify
    from app.modules.runs.storage import commit
    from app.manifest import snapshot
    partial = ticketed(dirty, "A1,1,20,60\nR1,2,-5,-25\n")
    saved, _ = commit(tmp_path / "db", snapshot(partial, evaluate(partial), 0.0))
    assert certify(saved)["can_settle"] is False
    # 晚到原票补齐后，对账档恢复完整（分钟与金额齐）。
    filled = ticketed(dirty, "A1,1,20,60\nR1,2,-5,-25\nB1,2,5,25\nB2,2,20,100\n")
    filled_ledger = ledger(filled)
    assert filled_ledger["complete"] is True and filled_ledger["differences"] == 0
    # 无缺证的标准航次使用新式分票头，签发资格照常成立。
    settled = dict(clean)
    settled["invoice"] = TICKET_HEADER + "C1,1,0,0.00\nC2,2,0,0.00\n"
    whole, _ = archive(tmp_path / "db2", settled)
    assert certify(whole)["can_settle"] is True
