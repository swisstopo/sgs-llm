#!/usr/bin/env python3
"""Run the documented customer queries through the real local browser UI.

This is deliberately an end-to-end harness: it types into the Lit chat
component, observes the browser WebSocket protocol, and inspects the rendered
map controls.  It does not call the agent or MCP directly.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


BASE_URL = "http://127.0.0.1:5174/"
ARTIFACT = Path("/tmp/sgs-local-customer-acceptance.json")


CASES: list[dict[str, Any]] = [
    {
        "id": "T01-search_layers",
        "lang": "en",
        "turns": ["What official Swiss datasets are available about avalanche hazards?"],
    },
    {
        "id": "T02-geocode_location",
        "lang": "en",
        "turns": [
            "Find the exact coordinates of Seftigenstrasse 264, 3084 Wabern.",
            "Show me on the map.",
        ],
    },
    {
        "id": "T03-describe_layer",
        "lang": "en",
        "turns": [
            "Describe the layer ch.swisstopo-vd.stand-oerebkataster, including its fields, owner, map service, legend, and download options."
        ],
    },
    {
        "id": "T04-identify_at_point",
        "lang": "en",
        "turns": [
            "At Seftigenstrasse 264, Wabern, return the complete ÖREB record, EGRID, PDF extract, online extract, and prepare the exact parcel polygon for the map."
        ],
    },
    {
        "id": "T05-search_locations",
        "lang": "en",
        "turns": ["Find the canton of Zug and show me which administrative level was selected."],
    },
    {
        "id": "T06-display_division",
        "lang": "en",
        "turns": ["Show the boundary of the canton of Zug on the map."],
    },
    {
        "id": "T07-filter_then_T09-analyze",
        "lang": "en",
        "turns": [
            "Find every municipality inside the true boundary of the canton of Zug, not merely inside its bounding rectangle.",
            "For the municipalities fetched in canton Zug, calculate the count, total area, total boundary length, extent, and numeric area statistics.",
        ],
    },
    {
        "id": "T08-display_catalog_layer",
        "lang": "en",
        "turns": [
            "Make the current flood warning map available to add to the map, focused on Valais, at 70% opacity."
        ],
    },
    {
        "id": "T10-display_layer",
        "lang": "en",
        "turns": [
            "Find all municipalities in canton Zug and prepare the personalized result for the map with a blue fill at 60% opacity."
        ],
    },
    {
        "id": "WA-address-followup",
        "lang": "en",
        "turns": [
            "Find the exact coordinates of Seftigenstrasse 264, 3084 Wabern.",
            "Show me on the map.",
        ],
    },
    {
        "id": "WB-oereb-both-layer-types",
        "lang": "en",
        "turns": [
            "Locate Seftigenstrasse 264, 3084 Wabern; return the EGRID, official PDF extract, online extract, and responsible authority. Prepare the exact parcel result for the map and offer the official nationwide ÖREB availability layer separately."
        ],
    },
    {
        "id": "WC-flood-Valais",
        "lang": "en",
        "turns": [
            "For canton Valais, compare the current flood warning map, measurement-station danger levels, surface-runoff hazards, and Aquaprotect flood scenarios. Show the canton boundary and make every recommended official layer available to add to the map."
        ],
    },
    {
        "id": "WD-Zug-analysis",
        "lang": "en",
        "turns": [
            "Find every municipality in canton Zug. Tell me the exact count, total area, total boundary length, minimum/maximum/average municipality area, and show both the municipalities and canton boundary on the map."
        ],
    },
    {
        "id": "WE-structured-filter",
        "lang": "en",
        "turns": [
            "In canton Zug, find municipality features whose canton field equals ZG and whose official area is greater than 1,000 hectares. Count them, calculate their combined area, and show the filtered result on the map."
        ],
    },
    {
        "id": "WF-current-map-view",
        "lang": "en",
        "turns": [
            "In the area currently visible on the map, find all municipality features, count them, calculate their total area, and show the result as a personalized layer."
        ],
    },
    {
        "id": "WG-en",
        "lang": "en",
        "turns": ["Show me flood hazards in Valais."],
    },
    {
        "id": "WG-de",
        "lang": "de",
        "turns": ["Zeige mir Hochwassergefahren im Wallis."],
    },
    {
        "id": "WG-fr",
        "lang": "fr",
        "turns": ["Montre-moi les dangers de crues en Valais."],
    },
    {
        "id": "WG-it",
        "lang": "it",
        "turns": ["Mostrami i pericoli di piena in Vallese."],
    },
    {
        "id": "WG-rm",
        "lang": "rm",
        "turns": ["Mussa ma ils privels d'inundaziun en il Vallais."],
    },
    {
        "id": "WH-no-match",
        "lang": "en",
        "turns": [
            "Find an official Swiss geodata layer containing historical Bitcoin prices for Atlantis and show it on the map."
        ],
    },
]


class BrowserAudit:
    def __init__(self, page: Page):
        self.page = page
        self.sent: list[dict[str, Any]] = []
        self.received: dict[str, list[dict[str, Any]]] = {}
        page.on("websocket", self._on_websocket)

    def _on_websocket(self, socket: Any) -> None:
        socket.on("framesent", self._on_sent)
        socket.on("framereceived", self._on_received)

    def _on_sent(self, frame: Any) -> None:
        payload = frame if isinstance(frame, str) else frame.get("payload", "")
        try:
            data = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            return
        if data.get("type") == "user_message":
            self.sent.append(data)

    def _on_received(self, frame: Any) -> None:
        payload = frame if isinstance(frame, str) else frame.get("payload", "")
        try:
            data = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            return
        message_id = data.get("message_id")
        if message_id:
            self.received.setdefault(message_id, []).append(data)

    def open_chat(self) -> None:
        button = self.page.locator("sgs-nav-rail > button").nth(0)
        if button.get_attribute("aria-pressed") != "true":
            button.click()
        self.page.locator("sgs-composer textarea").wait_for(state="visible")

    def clear_chat(self) -> None:
        if self.page.locator("sgs-layer-info-dialog").count():
            self.page.keyboard.press("Escape")
        self.open_chat()
        self.page.locator("button.chat-new").click()
        self.page.wait_for_function("() => document.querySelectorAll('sgs-chat-message').length === 0")

    def select_language(self, lang: str) -> None:
        toggle = self.page.locator("sgs-nav-rail button.lang-toggle")
        if self.page.locator("html").get_attribute("lang") == lang:
            return
        toggle.click()
        self.page.locator("sgs-nav-rail .lang-list button", has_text=lang).click()
        self.page.wait_for_function(
            "lang => document.documentElement.lang === lang", arg=lang
        )

    def send_turn(self, query: str) -> dict[str, Any]:
        self.open_chat()
        sent_before = len(self.sent)
        textarea = self.page.locator("sgs-composer textarea")
        textarea.fill(query)
        started = time.monotonic()
        textarea.press("Enter")
        deadline = time.monotonic() + 10
        while len(self.sent) <= sent_before and time.monotonic() < deadline:
            self.page.wait_for_timeout(100)
        if len(self.sent) <= sent_before:
            raise RuntimeError("The browser did not send a user_message WebSocket frame")
        outbound = self.sent[-1]
        message_id = outbound["id"]

        deadline = time.monotonic() + 105
        while time.monotonic() < deadline:
            events = self.received.get(message_id, [])
            if any(event.get("type") == "done" for event in events):
                break
            self.page.wait_for_timeout(200)
        else:
            raise TimeoutError(f"No done event for {message_id}")

        events = self.received.get(message_id, [])
        final = next((event for event in events if event.get("type") == "final"), None)
        error = next((event for event in events if event.get("type") == "error"), None)
        intermediate = [event for event in events if event.get("type") == "intermediate"]
        assistant = self.page.locator("sgs-chat-message").last
        markdown = assistant.locator(".markdown").inner_text() if assistant.locator(".markdown").count() else ""
        ui = {
            "markdown_rendered": bool(markdown),
            "inline_official_buttons": assistant.locator("button.inline-catalog-layer").count(),
            "personalized_cards": assistant.locator("sgs-layer-result-card").count(),
            "fallback_official_cards": assistant.locator("sgs-catalog-layer-card").count(),
        }
        return {
            "query": query,
            "lang_sent": outbound.get("lang"),
            "map_context": outbound.get("map_context"),
            "message_id": message_id,
            "duration_seconds": round(time.monotonic() - started, 2),
            "progress": intermediate,
            "final": final,
            "error": error,
            "rendered_text": markdown,
            "ui": ui,
        }

    def smoke_personalized_layer(self) -> dict[str, Any]:
        assistant = self.page.locator("sgs-chat-message").last
        card = assistant.locator("sgs-layer-result-card").first
        if card.count() == 0:
            return {"available": False}
        button = card.locator("button")
        before = button.inner_text()
        button.click()
        try:
            self.page.wait_for_function(
                "el => el.disabled === true", arg=button.element_handle(), timeout=10_000
            )
        except PlaywrightTimeoutError:
            pass
        after = button.inner_text()
        maps_button = self.page.locator("sgs-nav-rail > button").nth(1)
        badge = maps_button.locator(".badge").inner_text() if maps_button.locator(".badge").count() else "0"
        maps_button.click()
        remove = self.page.locator("sgs-displayed-maps sgs-layer-item button[aria-label]").filter(has_text="")
        active_rows = self.page.locator("sgs-displayed-maps sgs-layer-item").count()
        if active_rows:
            self.page.locator(
                'sgs-displayed-maps sgs-layer-item button[aria-label*="Remove"]'
            ).last.click()
        self.open_chat()
        return {
            "available": True,
            "button_before": before,
            "button_after": after,
            "map_badge_after_add": badge,
            "active_rows_after_add": active_rows,
            "removed_from_displayed_maps": active_rows > 0,
        }

    def smoke_official_layer(self, test_details: bool = False) -> dict[str, Any]:
        assistant = self.page.locator("sgs-chat-message").last
        inline = assistant.locator("button.inline-catalog-layer").first
        if inline.count():
            inline.click()
            dialog = assistant.locator(".layer-choice")
            dialog.wait_for(state="visible")
            data = {
                "available": True,
                "presentation": "inline-tooltip",
                "title": dialog.locator(".title").inner_text(),
                "metadata": dialog.locator(".metadata").inner_text(),
                "has_close_x": dialog.locator("button.close").count() == 1,
                "actions": dialog.locator(".actions button").all_inner_texts(),
            }
            first = dialog.locator(".actions button").first
            before = first.inner_text()
            first.click()
            self.page.wait_for_timeout(1_000)
            after = first.inner_text() if first.count() else ""
            data["add_label"] = before
            data["remove_label"] = after
            if first.count():
                first.click()
            if test_details:
                inline.click()
                dialog.locator(".actions button").nth(1).click()
                try:
                    self.page.locator("sgs-layer-info-dialog dialog[open]").wait_for(timeout=15_000)
                    data["details_opened"] = True
                    self.page.locator("sgs-layer-info-dialog header button").click()
                except PlaywrightTimeoutError:
                    data["details_opened"] = False
                    # Do not let a test-only modal block the remaining suite.
                    self.page.keyboard.press("Escape")
            return data

        card = assistant.locator("sgs-catalog-layer-card").first
        if card.count():
            actions = card.locator("button")
            before = actions.first.inner_text()
            actions.first.click()
            self.page.wait_for_timeout(1_000)
            after = actions.first.inner_text()
            actions.first.click()
            return {
                "available": True,
                "presentation": "fallback-card",
                "actions": actions.all_inner_texts(),
                "add_label": before,
                "remove_label": after,
            }
        return {"available": False}


def main() -> None:
    selected = {
        value.strip()
        for value in os.environ.get("SGS_CASE_IDS", "").split(",")
        if value.strip()
    }
    cases = [case for case in CASES if not selected or case["id"] in selected]
    results: list[dict[str, Any]] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        audit = BrowserAudit(page)
        page.goto(BASE_URL, wait_until="domcontentloaded")
        audit.open_chat()

        personalized_smoked = False
        official_smoked = False
        for index, case in enumerate(cases, start=1):
            print(f"[{index:02d}/{len(cases)}] {case['id']}", flush=True)
            audit.clear_chat()
            audit.select_language(case["lang"])
            case_result = {"id": case["id"], "lang": case["lang"], "turns": []}
            for query in case["turns"]:
                try:
                    turn = audit.send_turn(query)
                    final = turn.get("final") or {}
                    print(
                        "  "
                        f"{turn['duration_seconds']:>6.2f}s "
                        f"error={bool(turn['error'])} "
                        f"steps={len(turn['progress'])} "
                        f"data={len(final.get('layers', []))} "
                        f"official={len(final.get('catalog_layers', []))}",
                        flush=True,
                    )
                    if final.get("layers") and not personalized_smoked:
                        try:
                            turn["personalized_map_smoke"] = audit.smoke_personalized_layer()
                        except Exception as exc:
                            turn["personalized_map_smoke"] = {
                                "harness_error": f"{type(exc).__name__}: {exc}"
                            }
                        personalized_smoked = True
                    if final.get("catalog_layers") and not official_smoked:
                        try:
                            turn["official_map_smoke"] = audit.smoke_official_layer(
                                test_details=True
                            )
                        except Exception as exc:
                            turn["official_map_smoke"] = {
                                "harness_error": f"{type(exc).__name__}: {exc}"
                            }
                        official_smoked = True
                    case_result["turns"].append(turn)
                except Exception as exc:  # keep the suite sequential after one failure
                    print(f"  HARNESS FAILURE: {type(exc).__name__}: {exc}", flush=True)
                    case_result["turns"].append(
                        {"query": query, "harness_error": f"{type(exc).__name__}: {exc}"}
                    )
            results.append(case_result)
            ARTIFACT.write_text(
                json.dumps(
                    {
                        "base_url": BASE_URL,
                        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "cases": results,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        page.screenshot(path="/tmp/sgs-local-customer-acceptance-final.png", full_page=True)
        browser.close()
    print(f"Artifact: {ARTIFACT}", flush=True)


if __name__ == "__main__":
    main()
