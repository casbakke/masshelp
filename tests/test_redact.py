from hypothesis import given
from hypothesis import strategies as st

from masshelp.util.redact import redact

safe_text = st.text(alphabet=st.characters(blacklist_categories=["Nd"], blacklist_characters="\x00"), max_size=40)


def test_examples():
    assert "123-45-6789" not in redact("my ssn is 123-45-6789 ok")
    assert "123456789" not in redact("ssn 123456789")
    assert "4111111111111111" not in redact("card 4111111111111111")
    assert "4111 1111 1111 1111" not in redact("card 4111 1111 1111 1111")
    assert "00012345678" not in redact("my account number is 00012345678")
    assert redact("I made $900 for 25 hours on 2026-11-30") == "I made $900 for 25 hours on 2026-11-30"
    assert redact("call 617-555-0101") == "call 617-555-0101"


@given(safe_text, st.from_regex(r"\d{3}-?\d{2}-?\d{4}", fullmatch=True), safe_text)
def test_ssn_removed(pre, ssn, post):
    digits = ssn.replace("-", "")
    if ssn.count("-") == 1:  # mixed separators are not SSN-shaped
        return
    out = redact(f"{pre} {ssn} {post}")
    assert digits not in out.replace("-", "")


@given(safe_text, st.from_regex(r"\d{13,19}", fullmatch=True), safe_text)
def test_card_removed(pre, card, post):
    assert card not in redact(f"{pre} {card} {post}")
