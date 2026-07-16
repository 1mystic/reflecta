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


def test_span_progress_fills_declare_block_display():
    """Regression: .bar-fill and .gap-fill are <span> elements sized via an inline
    `width: NN%` style set in JS (see app.js). A <span> is `display: inline` by default,
    and CSS width has NO effect on inline elements — the fill silently renders as a
    hairline regardless of the computed percentage. Both selectors must declare a
    non-inline display (block/inline-block/flex) for the width to actually apply."""
    css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    for selector in (".bar-fill", ".gap-fill"):
        rule = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert rule, f"{selector} rule not found in styles.css"
        assert re.search(r"display\s*:\s*(block|inline-block|flex)", rule.group(1)), (
            f"{selector} has no block-level display — its JS-set width:% will be ignored "
            "because <span> is display:inline by default"
        )


def test_hero_cta_wins_specificity_over_btn_primary_full_width():
    """Regression: .btn-primary sets `width: 100%` for full-width form buttons. The hero
    CTA also carries the .btn-primary class (for its base color/shape), but must render
    at its natural (auto) width, not stretched full-width like a form button. Relying on
    CSS declaration order for this is fragile — whichever rule appears LATER in the file
    wins when specificity is equal, so a later edit to .btn-primary silently broke the
    hero CTA's width once already. The fix is a higher-specificity selector that wins
    regardless of order: .btn.w-cta (two classes) beats .btn-primary (one class)."""
    css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    assert re.search(r"\.btn\.w-cta\s*\{[^}]*width:\s*auto", css), (
        ".w-cta's width:auto must be declared on a selector with specificity >= "
        "0,2,0 (e.g. `.btn.w-cta`) so it beats .btn-primary's `width: 100%` "
        "regardless of which rule appears later in the stylesheet"
    )


def test_no_em_dashes_in_frontend_pages():
    """User-requested style rule: no em dashes (U+2014) anywhere in the rendered pages."""
    for name in ("index.html", "app.js", "styles.css", "privacy.html"):
        text = (FRONTEND / name).read_text(encoding="utf-8")
        assert "—" not in text, f"em dash found in {name}"


def test_sidebar_has_no_api_docs_nav_item():
    """User-requested: the 'API & Help' / API docs link was removed from the sidebar nav
    (the landing page footer's separate API docs link is unaffected)."""
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    sidebar = html.split('<nav class="nav">')[1].split("</nav>")[0]
    assert "/docs" not in sidebar
    assert "API" not in sidebar


def test_new_screens_and_nav_items_exist_and_are_registered():
    """The Cognitive Vitals and Model Lab screens are shown/hidden by app.js's show(),
    which iterates the SCREENS array and calls $(`screen-${s}`) on each. A nav item whose
    screen id or SCREENS entry is missing throws (null.classList) and breaks ALL nav. Guard
    both the markup ids and the JS registration together."""
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    js = (FRONTEND / "app.js").read_text(encoding="utf-8")
    for view in ("vitals", "lab"):
        assert f'id="screen-{view}"' in html, f"#screen-{view} section missing"
        assert f'data-view="{view}"' in html, f"nav item for {view} missing"
        # must be in the SCREENS array or show() throws on the missing element
        assert re.search(rf'SCREENS\s*=\s*\[[^\]]*"{view}"', js), (
            f'"{view}" not registered in the SCREENS array - show() would crash on it')


def test_vitals_face_and_meters_have_target_elements():
    """The live tick (app.js tickVitals -> renderVitals) writes into specific ids after
    every answer. If the markup ids drift, the face silently stops updating."""
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    for el_id in ("qz-face", "qz-emotion", "qz-certainty", "qz-theta",
                  "vt-face", "vt-emotion", "vt-theta", "vt-concepts"):
        assert f'id="{el_id}"' in html, f"vitals element #{el_id} missing from markup"
