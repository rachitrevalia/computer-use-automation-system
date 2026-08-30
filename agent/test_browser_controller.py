"""
Manual, scripted walkthrough of BrowserController - NO LLM involved.

"""
from browser_controller import BrowserController

TARGET = "http://127.0.0.1:5001"


def main():
    bc = BrowserController(headless=False).start()
    try:
        print("1. Navigating to login page...")
        bc.navigate(f"{TARGET}/login")
        state = bc.observe()
        print(state.to_prompt_text()[:600])
        print("...\n")

        print("2. Filling login form (tier test: no real <label> tags exist)...")
        bc.type_text("Username", "teller1")
        bc.type_text("Password", "pass123")
        print(f"   locator tier used: {bc.last_locator_tier}")

        print("3. Clicking 'Sign In'...")
        bc.click("Sign In")
        print(f"   locator tier used: {bc.last_locator_tier}")
        print(f"   now at: {bc.page.url}\n")

        print("4. Filling member search...")
        bc.type_text("Member ID", "12345")
        bc.click("Look Up")
        print(f"   now at: {bc.page.url}\n")

        print("5. Observing member detail page (checking iframe fallback)...")
        state = bc.observe()
        print(state.to_prompt_text())

        assert "Alice Johnson" in state.accessibility_tree, \
               "Expected to see Alice Johnson's name in the main ARIA tree"
        assert any("4210.55" in f["text"] for f in state.frames), \
               "Expected to see the balance inside the iframe's extracted text"

        print("\n✅ ALL CHECKS PASSED — perception + action layer works correctly.")
        bc.screenshot("test_walkthrough_success.png")
        print("Saved screenshot: test_walkthrough_success.png")

    finally:
        bc.close()


if __name__ == "__main__":
    main()