# Regression: ISSUE-019 — Landing page rendering and CSS tag encapsulation
# Value: prevents CSS rules from rendering as raw text on the landing page and verifies proper layout container

import os
import tempfile
from founder_signal.app import create_app
from founder_signal.config import Config


def test_landing_page_rendering_and_styles_encapsulation():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        config = Config(ledger_backend="sqlite", ledger_sqlite_path=db_path)
        app = create_app(config)
        app.config["TESTING"] = True
        client = app.test_client()

        res = client.get("/")
        assert res.status_code == 200
        html = res.text

        # All CSS must be strictly within <style> and </style> inside <head>
        assert "<head>" in html and "</head>" in html
        head = html.split("</head>")[0]
        assert head.count("<style>") == 1
        assert head.count("</style>") == 1

        style_content = head.split("<style>")[1].split("</style>")[0]
        assert "/* ===== Landing Page Styles ===== */" in style_content
        assert ".landing-hero" in style_content
        assert ".hero-inner" in style_content

        # Content after </style> and before </head> must not contain raw CSS rules
        post_style_head = head.split("</style>")[1].strip()
        assert post_style_head == ""

        # Check landing container class and key landing elements
        assert 'class="container-landing"' in html
        assert "Founder Signal" in html
        assert "Commitment Ledger" in html
        assert "Built for Founders" in html
        assert "How It Works" in html
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)
