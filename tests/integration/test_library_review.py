"""An organize scan produces reviewable metadata without media mutations."""

import hashlib
import json

import pytest

from avo import cli
from library_fixtures import install_provider

pytestmark = pytest.mark.integration


def test_cli_scan_is_local_and_keeps_sources(tmp_path, monkeypatch, capsys):
    install_provider(tmp_path / "install")
    monkeypatch.setenv("AVO_ROOT", str(tmp_path / "install"))
    root = tmp_path / "footage"
    root.mkdir()
    source = root / "xpto-01.mp4"
    source.write_bytes(b"not-playable-but-must-remain-unchanged")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    assert (
        cli.main(
            ["organize", "scan", "--root", str(root), "--provider", "example", "--json"]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["refs"]["review"]["html"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert not (root / "edit/library/transcripts").exists()


def _browser_review(tmp_path):
    from avo.library.review import render_review

    proposal = {
        "proposalId": "browser",
        "revision": 1,
        "summary": {},
        "groups": [
            {
                "id": "g",
                "label": "xpto",
                "path": "xpto",
                "rationale": "Filename prefix",
                "evidence": [],
            }
        ],
        "actions": [
            {
                "actionId": str(i),
                "recordingId": str(i),
                "from": f"camera-a/day-01/recording-{i}.mp4",
                "to": f"xpto/project/camera-a/day-01/recording-{i}.mp4",
                "groupId": "g",
                "status": "move",
                "reason": "Filename",
                "sizeBytes": 100,
                "durationSeconds": 65.0 if i == 0 else None,
            }
            for i in range(250)
        ],
    }
    deep = "/".join(f"long-folder-{i}-" + "x" * 35 for i in range(20))
    proposal["actions"][1]["from"] = f"camera-a/day-01/{deep}/recording-1.mp4"
    proposal["actions"][1]["to"] = (
        f"xpto/project/camera-a/day-01/{deep}/recording-1.mp4"
    )
    context = {
        "root": str(tmp_path),
        "provider": "example",
        "libraryId": "lib",
        "headHash": "a" * 64,
        "proposalRef": {"id": "b" * 64, "sha256": "b" * 64},
    }
    return render_review(tmp_path, proposal, context)


def _check_nested_tree(page):
    assert page.locator("button.file").count() == 200
    nested = page.locator(
        '#current-tree > details.folder > .folder-children > details[data-path="camera-a"] > .folder-children > details[data-path="camera-a/day-01"]'
    )
    assert nested.count() == 1
    assert (
        page.locator(
            '#proposed-tree details[data-path="xpto"] > .folder-children > details[data-path="xpto/project"]'
        ).count()
        == 1
    )
    nested.locator(":scope > summary").focus()
    page.keyboard.press("Enter")
    assert nested.get_attribute("open") is None
    page.keyboard.press("Enter")
    assert nested.get_attribute("open") is not None


def _check_shown_metrics(page):
    root_summary = page.locator("#current-tree > details.folder > summary")
    assert "100 shown" in root_summary.inner_text()
    assert "99 unknown durations" in root_summary.inner_text()
    assert "1m 05s known" in root_summary.inner_text()
    assert "KiB" in root_summary.inner_text()
    assert "100 of 250" in page.locator("#page").inner_text()


def _check_keyboard_export(page):
    page.locator("button.file").first.focus()
    page.keyboard.press("Enter")
    assert "recording-0.mp4" in page.locator("#inspector").inner_text()
    assert "100 B" in page.locator("#inspector").inner_text()
    assert "1m 05s" in page.locator("#inspector").inner_text()
    page.get_by_role("button", name="Keep current location").click()
    assert "1 unsaved" in page.locator("#notice").inner_text()
    with page.expect_download() as event:
        page.get_by_role("button", name="Export requested changes").click()
    request = json.loads(event.value.path().read_text(encoding="utf-8"))
    assert request["edits"][0]["type"] == "keep-recording"
    assert "approved" not in request


def _check_mobile_layout(page, screenshot):
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.locator(".tree").evaluate_all(
        "elements => elements.every(element => element.scrollWidth <= element.clientWidth)"
    )
    page.screenshot(path=str(screenshot), full_page=True)


def test_browser_review_keyboard_export_and_narrow_layout(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    paths = _browser_review(tmp_path)
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(accept_downloads=True)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(paths["html"].as_uri())
        _check_nested_tree(page)
        _check_shown_metrics(page)
        _check_keyboard_export(page)
        page.screenshot(path=str(tmp_path / "review-desktop.png"), full_page=True)
        _check_mobile_layout(page, tmp_path / "review-mobile.png")
        assert not errors
        browser.close()
