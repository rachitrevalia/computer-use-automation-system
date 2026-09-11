from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from playwright.sync_api import sync_playwright, Page, Browser, Playwright, TimeoutError as PWTimeout

MAX_TREE_CHARS = 6000  


@dataclass
class PageState:
    url: str
    accessibility_tree: str  
    frames: list[dict] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        lines = [f"CURRENT URL: {self.url}", "", "ACCESSIBILITY TREE (main frame, ARIA YAML):"]
        lines.append(self.accessibility_tree[:MAX_TREE_CHARS])
        if self.frames:
            lines.append("")
            lines.append(
                "EMBEDDED FRAMES (the ARIA tree does not cross into these; "
                "shown as extracted text instead):"
            )
            for f in self.frames:
                lines.append(f"  --- frame: {f['url']} ---")
                lines.append(f"  {f['text'][:800]}")
        return "\n".join(lines)


class LocatorFailure(Exception):
    """Raised when neither tier-1 nor tier-2 targeting can find the element."""


class BrowserController:
    """Thin wrapper around Playwright: launch once, observe/act repeatedly."""

    def __init__(self, headless: bool = False):
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.headless = headless
        self.last_locator_tier: Optional[str] = None  

    def start(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self.page = self._browser.new_page()
        return self

    def close(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    # ---------------- perception ----------------

    def observe(self) -> PageState:
        try:
            self.page.wait_for_load_state("load", timeout=5000)
        except PWTimeout:
            pass
        tree_yaml = self.page.aria_snapshot()
        frames = []
        for frame in self.page.frames:
            if frame == self.page.main_frame:
                continue
            try:
                text = frame.locator("body").inner_text(timeout=2000)
            except Exception:
                text = "(frame content unavailable)"
            frames.append({"url": frame.url, "text": text})
        return PageState(url=self.page.url, accessibility_tree=tree_yaml, frames=frames)

    def screenshot(self, path: str):
        self.page.screenshot(path=path, full_page=True)

    # ---------------- actions ----------------

    def navigate(self, url: str):
        self.page.goto(url)
        self.last_locator_tier = "navigate"

    # ---------------- replay-only: tier-direct actions ----------------
    # These skip straight to the tier already known to work from discovery
    # (recorded in the artifact's locator_strategy field), instead of
    # re-attempting the full tier1->tier2 fallback chain every time. That
    # fallback chain is right for discovery (which doesn't know the tier in
    # advance) but wastes a full timeout on tier 1 for every label-less
    # field during replay, when we already know which tier works.

    def click_via_tier(self, tier: str, target_text: str):
        try:
            if tier == "tier1_role_button":
                self.page.get_by_role("button", name=target_text).first.click(timeout=5000)
            elif tier == "tier1_role_link":
                self.page.get_by_role("link", name=target_text).first.click(timeout=5000)
            else:  # tier2_visible_text or unrecognized -- safest fallback
                self.page.get_by_text(target_text, exact=False).first.click(timeout=5000)
            self.last_locator_tier = tier
        except Exception as e:
            raise LocatorFailure(f"Could not click '{target_text}' via recorded tier '{tier}'") from e

    def type_text_via_tier(self, tier: str, label_text: str, value: str):
        try:
            if tier == "tier1_label":
                self.page.get_by_label(label_text).first.fill(value, timeout=5000)
            else:  # tier2_table_adjacent or unrecognized
                xpath = f"//td[normalize-space(text())='{label_text}']/following-sibling::td[1]//input"
                self.page.locator(xpath).first.fill(value, timeout=5000)
            self.last_locator_tier = tier
        except Exception as e:
            raise LocatorFailure(f"Could not fill field near '{label_text}' via recorded tier '{tier}'") from e

    def select_option_via_tier(self, tier: str, label_text: str, option_text: str):
        try:
            if tier == "tier1_label":
                self.page.get_by_label(label_text).first.select_option(label=option_text, timeout=5000)
            else:  # tier2_table_adjacent or unrecognized
                xpath = f"//td[normalize-space(text())='{label_text}']/following-sibling::td[1]//select"
                self.page.locator(xpath).first.select_option(label=option_text, timeout=5000)
            self.last_locator_tier = tier
        except Exception as e:
            raise LocatorFailure(f"Could not select option near '{label_text}' via recorded tier '{tier}'") from e

    # ---------------- discovery-only: tiered fallback actions ----------------

    def click(self, target_text: str):
        """Tier 1: role button/link by accessible name. Tier 2: any element by visible text."""
        try:
            self.page.get_by_role("button", name=target_text).first.click(timeout=3000)
            self.last_locator_tier = "tier1_role_button"
            return
        except (PWTimeout, Exception):
            pass
        try:
            self.page.get_by_role("link", name=target_text).first.click(timeout=3000)
            self.last_locator_tier = "tier1_role_link"
            return
        except (PWTimeout, Exception):
            pass
        try:
            self.page.get_by_text(target_text, exact=False).first.click(timeout=3000)
            self.last_locator_tier = "tier2_visible_text"
            return
        except (PWTimeout, Exception) as e:
            raise LocatorFailure(f"Could not find a clickable element matching '{target_text}'") from e

    def type_text(self, label_text: str, value: str):
        """Tier 1: real <label> association. Tier 2: table-adjacent-cell match."""
        try:
            self.page.get_by_label(label_text).first.fill(value, timeout=3000)
            self.last_locator_tier = "tier1_label"
            return
        except (PWTimeout, Exception):
            pass
        try:
            xpath = (
                f"//td[normalize-space(text())='{label_text}']"
                f"/following-sibling::td[1]//input"
            )
            self.page.locator(xpath).first.fill(value, timeout=3000)
            self.last_locator_tier = "tier2_table_adjacent"
            return
        except (PWTimeout, Exception) as e:
            raise LocatorFailure(f"Could not find an input field near label '{label_text}'") from e

    def select_option(self, label_text: str, option_text: str):
        """Tier 1: real <label> association. Tier 2: table-adjacent-cell match."""
        try:
            self.page.get_by_label(label_text).first.select_option(label=option_text, timeout=3000)
            self.last_locator_tier = "tier1_label"
            return
        except (PWTimeout, Exception):
            pass
        try:
            xpath = (
                f"//td[normalize-space(text())='{label_text}']"
                f"/following-sibling::td[1]//select"
            )
            self.page.locator(xpath).first.select_option(label=option_text, timeout=3000)
            self.last_locator_tier = "tier2_table_adjacent"
            return
        except (PWTimeout, Exception) as e:
            raise LocatorFailure(f"Could not find a dropdown near label '{label_text}'") from e