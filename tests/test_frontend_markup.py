"""Static checks on the frontend markup for defect classes that unit/API tests can't see —
these are DOM/browser-semantics bugs, not backend bugs, so pytest is the wrong layer to
catch them at runtime; this file guards the markup invariants that prevent them.
"""
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def test_segmented_control_values_have_matching_select_options():
    """Regression: the question-count segmented buttons write into a hidden <select> via
    `select.value = "8"`. Per the HTML spec, setting .value to a string with no matching
    <option> silently resets it to "" — not an error, not a console warning. That produced
    `n_questions: NaN` -> JSON.stringify(NaN) -> null -> a confusing 422 from the API
    ("Input should be a valid integer") for any question count except whichever one
    happened to have a literal <option> in the markup. Every button's data-n must have a
    corresponding <option value=...> or this silently breaks again.
    """
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    seg_values = set(re.findall(r'data-n="(\d+)"', html))
    select_block = re.search(r'<select id="nq"[^>]*>(.*?)</select>', html, re.S).group(1)
    option_values = set(re.findall(r'<option value="(\d+)"', select_block))
    assert seg_values, "no segmented control values found — markup structure changed"
    assert seg_values == option_values, (
        f"segmented buttons {seg_values} and <select id=nq> options {option_values} "
        "are out of sync — clicking a button with no matching option resets the "
        "select's value to '', which fails integer validation on submit"
    )


def test_start_quiz_never_sends_nan_n_questions():
    """Defense in depth alongside the markup check above: even if the <select> options
    and buttons drift out of sync again, app.js must not forward a NaN/empty value to the
    API — `parseInt(...) || 12` is the required fallback pattern."""
    js = (FRONTEND / "app.js").read_text(encoding="utf-8")
    assert "n_questions: parseInt($(\"nq\").value, 10) || 12" in js, (
        "startQuiz() must fall back to a valid default when parseInt() yields NaN "
        "(happens when the <select>'s value doesn't match any <option>)"
    )


def test_api_base_url_is_same_origin_not_port_heuristic():
    """Regression: the API base URL used to be selected via `location.port === "8000"`,
    which silently misroutes every request whenever the frontend is opened through any
    server other than our own backend (a bundler dev server, VS Code Live Server, etc.) —
    those requests go to that *other* server, which usually can't handle POST and returns
    404/405. The frontend is served BY the same process as the API, so same-origin is
    always correct except when opened as a raw file."""
    js = (FRONTEND / "app.js").read_text(encoding="utf-8")
    assert 'location.port === "8000"' not in js, (
        "port-based origin heuristic reintroduced — this misroutes API calls whenever "
        "the frontend isn't opened through :8000 specifically"
    )
    assert 'location.protocol === "file:"' in js
