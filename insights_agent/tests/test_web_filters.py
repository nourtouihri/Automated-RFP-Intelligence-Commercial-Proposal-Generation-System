from insights_agent.tools.web_tools import is_valid_comparable, is_valid_competitor


def test_salary_is_not_a_comparable():
    assert not is_valid_comparable("a $100k developer's salary.")


def test_monthly_licence_is_not_a_comparable():
    assert not is_valid_comparable("Integration Starter | Est. $1,250 to $4,167+/mo")
    assert not is_valid_comparable("$50 per user per month")


def test_project_amount_is_a_comparable():
    assert is_valid_comparable("The HR integration project was awarded for $450,000.")


def test_platform_required_by_tender_is_not_a_competitor():
    tender = "We require an integration layer built on MuleSoft."
    assert not is_valid_competitor("MuleSoft", "https://example.com/blog", tender)


def test_case_study_customer_is_not_a_competitor():
    assert not is_valid_competitor("NZ Post", "https://www.mulesoft.com/case-studies", "tender text")


def test_real_competitor_is_kept():
    assert is_valid_competitor("Acme Integrators", "https://example.com/news", "tender text")


def test_software_vendor_is_not_a_competitor():
    assert not is_valid_competitor("Salesforce", "https://example.com/blog", "tender text")


def test_platform_sentence_is_rejected():
    sentence = "Some platforms like Gloroots integrate both capabilities in one system."
    assert not is_valid_competitor("Gloroots", "https://example.com/blog", "tender", evidence=sentence)


def test_integrator_sentence_is_kept():
    sentence = "Acme Integrators is a MuleSoft consulting partner delivering HR integrations."
    assert is_valid_competitor("Acme Integrators", "https://example.com/news", "tender", evidence=sentence)


def test_unknown_company_without_service_marker_is_rejected():
    sentence = "Zorbix launched a new dashboard last year."
    assert not is_valid_competitor("Zorbix", "https://example.com/news", "tender", evidence=sentence)

def test_annual_programme_cost_with_licences_is_not_a_comparable():
    s = "Total annual MuleSoft program cost, including licensing, builds, and support, above $70,000."
    assert not is_valid_comparable(s)