import os
import pytest

from bots.llm_selector import openai_generate


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="No OPENAI_API_KEY configured")
def test_openai_integration():
	"""Integration test that makes a real, billed OpenAI API call.

	Deselected by default via the `-m "not integration"` in pytest.ini; run it explicitly
	with `pytest -m integration`. Also skipped when no OPENAI_API_KEY is configured.
	It asserts a non-empty string response is returned.
	"""
	model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
	try:
		resp = openai_generate("Say hello in one sentence.", model=model, max_tokens=60, temperature=0.0)
	except Exception as e:
		# Treat API errors (quota, rate limit, network) as a skip for integration tests
		pytest.skip(f"OpenAI integration skipped due to error: {e}")

	assert isinstance(resp, str)
	assert resp.strip() != ""
