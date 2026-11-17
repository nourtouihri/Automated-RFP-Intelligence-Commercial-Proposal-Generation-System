import pytest

from proposal.claims import unsupported

SUPPORT = ("Tender: Sonede needs a unified data platform. Requirement: ETL pipelines on Airflow. "
           "Asset PRJ-0003: Utility data hub for a water utility. Outcome: 56% fewer correction "
           "notices; handed over to internal IT. Employee_002 is a Data engineer with 7 years of "
           "experience and MuleSoft skills.")


def flags(text, support=SUPPORT, field="f"):
    return {(c["kind"], c["claim"]) for c in unsupported({field: text}, support)}


def test_invented_facts_of_every_kind_are_flagged():
    text = ("Cut churn by 18% in 2024 for Acme Corp, ISO 27001 certified, delivered in 6 weeks "
            "for €2.5 million.")
    got = flags(text)
    assert ("percentage", "18%") in got
    assert ("year", "2024") in got
    assert ("name", "Acme Corp") in got
    assert ("certification", "ISO 27001") in got
    assert ("status", "certified") in got
    assert ("status", "delivered") in got
    assert ("number", "6") in got
    assert ("money", "€2.5") in got


def test_claims_that_the_inputs_contain_are_not_flagged():
    text = ("A utility data hub with 56% fewer correction notices, built by a data engineer "
            "with 7 years of experience on Airflow for Sonede.")
    assert flags(text) == set()


def test_spelled_numbers_match_digits_both_ways():
    assert flags("Seven years of experience") == set()
    assert flags("Built over eight years", support="a platform used for 8 years") == set()
    assert ("number", "eight") in flags("Built over eight years")


def test_thousands_separators_and_decimals_are_the_same_number():
    assert flags("1,400 series", support="collects 1400 statistical series") == set()
    assert flags("3.2 million subscribers", support="3.2 million subscribers") == set()
    assert ("number", "1,500") in flags("1,500 series", support="1400 series")


def test_a_year_range_is_two_year_claims():
    assert flags("Phase 2, 2026–2028", support="the 2026 budget for phase 2") == {("year", "2028")}


def test_a_lone_capitalised_word_is_not_a_name_claim_but_a_run_of_them_is():
    assert flags("Seamless data. Trusted partners.") == set()
    # One capitalised word is not checked (a known miss: an invented one-word client).
    assert flags("We worked with Zeta last year.") == set()
    assert ("name", "Zeta Industries") in flags("We worked with Zeta Industries last year.")


def test_a_run_of_capitalised_words_is_fine_when_any_of_its_words_is_in_the_inputs():
    assert flags("Dear Sonede Team, thank you.") == set()
    assert flags("Deploy on Azure Kubernetes within 90 days.") == {("name", "Azure Kubernetes"),
                                                                    ("number", "90")}


def test_title_case_text_does_not_flag_ordinary_words():
    # Known blind spot: in a Title Case line an invented client name looks like any other word.
    assert flags("Secure Public Statistics Platform For Valdemar Citizens") == set()


def test_camel_case_and_acronyms_are_names_even_at_the_start():
    got = flags("BigQuery and GCP pipelines, plus SHAP explanations")
    assert {("name", "BigQuery"), ("name", "GCP"), ("name", "SHAP")} <= got
    assert flags("MuleSoft pipelines", support=SUPPORT) == set()


def test_names_are_matched_case_insensitively_and_with_plurals():
    assert flags("Utility Data Hubs on AIRFLOW") == set()


def test_unicode_names_are_checked_like_any_other():
    assert flags("Université de Tunis", support="L’Université de Tunis El Manar") == set()
    assert ("name", "Université Paris Cité") in flags("Welcome to Université Paris Cité")


def test_delivered_needs_the_word_in_the_inputs_but_delivery_is_not_a_claim():
    assert ("status", "delivered") in flags("Delivered a hub", support="a project proposed in 2023")
    assert flags("Delivered a hub", support="Delivered on schedule") == set()
    assert flags("Low-risk delivery with a working release at each phase") == set()


def test_certified_matches_its_stem_in_the_inputs():
    assert flags("Certified consultants", support="holds the Azure certification") == set()


def test_each_field_and_claim_is_reported_once():
    out = unsupported({"a": "Last spring we met Zeta Corp and later visited Zeta Corp again, 2031 and 2031", "b": "2031"}, "nothing")
    assert sorted((c["field"], c["claim"]) for c in out) == [("a", "2031"), ("a", "Zeta Corp"), ("b", "2031")]


def test_prompt_numbers_are_not_support_only_spelled_out_ones_are():
    from proposal.claims import support_text
    text = support_text("rules", "write three pillars, each at most 51 characters", {"A": "x"}, {})
    assert flags("Three pillars", support=text) == set()
    assert ("number", "51") in flags("51 pillars", support=text)


@pytest.mark.parametrize("text", ["", "   ", "Plain words only, nothing to check."])
def test_text_without_claims_is_never_flagged(text):
    assert flags(text) == set()


def test_ids_the_text_cites_are_not_read_as_numbers():
    text = "PRJ\u20110035 offline case handling"
    assert unsupported({"f": text}, "nothing") != []
    assert unsupported({"f": text}, "nothing", ignore=["PRJ-0035"]) == []
