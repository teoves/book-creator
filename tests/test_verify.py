import json

from bookcreator.verify import found, norm, verify_note

TEXT = ("The German people were told: “Russia has attacked us. We must defend our fatherland. "
        "At the same time we will go and liberate Russia from the toils of bureaucracy.” "
        "In France, the government found another explanation of the war for their people.")


def write(d, name, data):
    (d / name).mkdir(exist_ok=True)
    (d / name / "x.json").write_text(json.dumps(data), encoding="utf-8")


def test_found_ignores_quotes_case_and_joins_ellipses():
    tn = norm(TEXT)
    assert found("russia has attacked us", tn)
    assert found("“Russia has attacked us … liberate Russia from the toils of bureaucracy”", tn)
    assert not found("Russia is saving herself from the tsar", tn)


def test_paraphrase_error_is_caught_by_evidence_and_review(tmp_path):
    note = "Russia, she is told, is saving herself from the tsar."
    write(tmp_path, "evidence", [{"claim": "Russia is saving herself from the tsar",
                                  "quotes": ["Russia is saving herself from the tsar"]}])   # invented support
    write(tmp_path, "review", [{"sentence": note, "verdict": "wrong",
                                "problem": "It is Germany that promises to liberate Russia.",
                                "evidence": ["we will go and liberate Russia from the toils of bureaucracy"]}])
    r = verify_note("x", note, TEXT, tmp_path, require_review=True)
    assert any("evidence not found" in p for p in r.problems)
    assert len(r.flagged) == 1 and r.flagged[0]["verdict"] == "wrong"


def test_clean_note_passes(tmp_path):
    note = "Germany told its people “Russia has attacked us” and promised to free the Russians."
    write(tmp_path, "evidence", [
        {"claim": "Germany told its people Russia attacked first and promised to liberate Russia",
         "quotes": ["The German people were told: “Russia has attacked us.",
                    "we will go and liberate Russia from the toils of bureaucracy"]},
        {"claim": "The pamphlet was written during the First World War", "basis": "context"}])
    write(tmp_path, "review", [{"sentence": note, "verdict": "ok", "evidence": ["Russia has attacked us"]}])
    r = verify_note("x", note, TEXT, tmp_path, require_review=True)
    assert r.problems == [] and r.flagged == [] and r.claims == 1 and r.context_claims == 1


def test_missing_files_and_bad_review_evidence(tmp_path):
    r = verify_note("x", "A note.", TEXT, tmp_path, require_review=True)
    assert "no evidence file (evidence/<slug>.json)" in r.problems
    assert "no review file (review/<slug>.json)" in r.problems
    write(tmp_path, "evidence", [{"claim": "c", "quotes": ["In France, the government"]}])
    write(tmp_path, "review", [{"sentence": "s", "verdict": "ok", "evidence": ["made-up passage text"]}])
    r = verify_note("x", "A note.", TEXT, tmp_path, require_review=True)
    assert r.problems == ["review evidence not found in the work: “made-up passage text”"]


def test_declared_external_quotation_is_allowed(tmp_path):
    note = "The so-called “glass of water” theory was pinned on her."
    r = verify_note("x", note, TEXT, tmp_path, require_review=False)
    assert any("glass of water" in p for p in r.problems)
    write(tmp_path, "evidence", [{"claim": "A label attached to her by critics, not her words",
                                  "basis": "context", "external_quote": "glass of water"}])
    r = verify_note("x", note, TEXT, tmp_path, require_review=False)
    assert r.problems == []
