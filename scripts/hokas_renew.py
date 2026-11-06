#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hokas Container Auto-Renewal Script (Add 12 Hours & Add 24 Hours via ShrinkMe)
Follows the 16-screenshot workflow:
1. Sign in at https://hokas.net/sign-in
2. Open container dashboard: https://hokas.net/dashboard/main/98faaa0b83aa97ae0484611b70d94356
3. Record initial remaining time
4. Check & click "Add 12 Hours" -> complete Steps 1..12 (including optional Step 2 adblock modal)
5. Refresh container dashboard, verify time increased & button greyed out
6. Check & click "Add 24 Hours" -> complete Steps 1..12
7. Refresh container dashboard, verify time increased & button greyed out
8. Capture screenshots on any error and send detailed Telegram notification
"""

import os
import re
import sys
import time
import traceback
from datetime import datetime
import requests
from DrissionPage import ChromiumOptions, ChromiumPage


DEFAULT_SERVER_URL = "https://hokas.net/dashboard/main/98faaa0b83aa97ae0484611b70d94356"
SIGN_IN_URL = "https://hokas.net/sign-in"
SCREENSHOT_DIR = os.path.join(os.getcwd(), "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def log(msg: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def save_screenshot(page_or_tab, name: str) -> str:
    """Save a screenshot and return its file path."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}_{name}.png"
    filepath = os.path.join(SCREENSHOT_DIR, filename)
    try:
        page_or_tab.get_screenshot(path=filepath, full_page=False)
        log(f"Screenshot saved: {filepath}")
        return filepath
    except Exception as e:
        log(f"Failed to save screenshot ({name}): {e}")
        return ""


def get_requests_proxies() -> dict:
    is_proxy = os.environ.get("IS_PROXY", "false").lower() == "true"
    proxy_url = os.environ.get("PROXY_URL", "").strip()
    if is_proxy and proxy_url:
        # Telegram API works directly in GitHub Actions, so we don't need proxy for TG unless needed
        return {}
    return {}


def send_tg_message(text: str, photo_path: str = ""):
    """Send Telegram text notification and optional screenshot."""
    bot_token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        log("TG_BOT_TOKEN or TG_CHAT_ID not configured; skipping Telegram notification.")
        return

    try:
        if photo_path and os.path.isfile(photo_path):
            url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            with open(photo_path, "rb") as photo:
                resp = requests.post(
                    url,
                    data={"chat_id": chat_id, "caption": text[:1024], "parse_mode": "HTML"},
                    files={"photo": photo},
                    timeout=30,
                )
            if resp.status_code == 200:
                log("Telegram photo notification sent successfully.")
                return
            else:
                log(f"Telegram sendPhoto returned {resp.status_code}: {resp.text}")

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=30,
        )
        if resp.status_code == 200:
            log("Telegram text notification sent successfully.")
        else:
            log(f"Telegram sendMessage returned {resp.status_code}: {resp.text}")
    except Exception as e:
        log(f"Error sending Telegram message: {e}")


def parse_hms_to_seconds(hms: str) -> int:
    """Convert HH:MM:SS (or D:HH:MM:SS) string to total seconds."""
    if not hms:
        return -1
    parts = [int(p) for p in hms.strip().split(":") if p.strip().isdigit()]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 4:
        return parts[0] * 86400 + parts[1] * 3600 + parts[2] * 60 + parts[3]
    return -1


def format_duration_diff(diff_seconds: int) -> str:
    """Format seconds difference into human-readable Chinese string."""
    if diff_seconds <= 0:
        return "0小时0分0秒"
    hours = diff_seconds // 3600
    minutes = (diff_seconds % 3600) // 60
    seconds = diff_seconds % 60
    return f"{hours}小时{minutes}分{seconds}秒"


def create_browser() -> ChromiumPage:
    co = ChromiumOptions()
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-dev-shm-usage")
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--window-size=1920,1080")
    co.set_argument("--lang=en-US")

    is_proxy = os.environ.get("IS_PROXY", "false").lower() == "true"
    proxy_url = os.environ.get("PROXY_URL", "").strip()
    if is_proxy and proxy_url:
        log(f"Configuring browser with local proxy: {proxy_url}")
        co.set_argument(f"--proxy-server={proxy_url}")
    else:
        log("Configuring browser with direct connection (IS_PROXY=false)")

    page = ChromiumPage(co)
    return page


def login_hokas(page: ChromiumPage, email: str, password: str):
    """Step 0: Open https://hokas.net/sign-in, enter email & password, click Continue."""
    log(f"Navigating to login page: {SIGN_IN_URL}")
    page.get(SIGN_IN_URL)
    time.sleep(5)

    # Wait for email input
    email_input = (
        page.ele('css:input[name="identifier"]', timeout=15)
        or page.ele('css:input[type="email"]', timeout=5)
        or page.ele('css:input[placeholder*="email" i]', timeout=5)
        or page.ele("tag:input", timeout=5)
    )
    if not email_input:
        raise RuntimeError("登录页面未能找到邮箱输入框 (Email address input not found)")

    log("Entering email address...")
    email_input.clear()
    email_input.input(email)
    time.sleep(1)

    # Check if password input is already visible (as shown in 2026-11-05_21-41_1.png)
    pwd_input = page.ele('css:input[type="password"]', timeout=3) or page.ele(
        'css:input[name="password"]', timeout=2
    )
    if pwd_input and pwd_input.states.is_displayed:
        log("Entering password...")
        pwd_input.clear()
        pwd_input.input(password)
        time.sleep(1)

        continue_btn = (
            page.ele("xpath://button[contains(., 'Continue')]", timeout=5)
            or page.ele('css:button[type="submit"]', timeout=5)
        )
        if not continue_btn:
            raise RuntimeError("登录页面未能找到 Continue 按钮")
        log("Clicking Continue button to sign in...")
        continue_btn.click()
    else:
        # Two-step Clerk flow fallback: click Continue after email, then enter password
        continue_btn = (
            page.ele("xpath://button[contains(., 'Continue')]", timeout=5)
            or page.ele('css:button[type="submit"]', timeout=5)
        )
        if continue_btn:
            continue_btn.click()
            time.sleep(3)
        pwd_input = page.ele('css:input[type="password"]', timeout=10)
        if not pwd_input:
            raise RuntimeError("未能找到密码输入框 (Password input not found)")
        pwd_input.clear()
        pwd_input.input(password)
        time.sleep(1)
        continue_btn = (
            page.ele("xpath://button[contains(., 'Continue')]", timeout=5)
            or page.ele('css:button[type="submit"]', timeout=5)
        )
        if continue_btn:
            continue_btn.click()

    # Wait for login redirect away from /sign-in
    for _ in range(25):
        time.sleep(1)
        if "/sign-in" not in page.url:
            log(f"Login succeeded! Redirected to: {page.url}")
            return

    # Check if still on sign-in with an error
    raise RuntimeError(f"登录超时或失败，当前仍停留在: {page.url}")


def get_remaining_time(tab) -> str:
    """
    Extract remaining container time (e.g. '12:58:53' or '24:48:59') from the dashboard page.
    Matches screenshot 2026-11-05_21-43.png & 2026-11-05_21-53.png.
    """
    for _ in range(15):
        try:
            body_text = tab.html
            # Look specifically via JS near SERVER EXPIRING first
            hms = tab.run_js(
                """
                const allElements = Array.from(document.querySelectorAll('*'));
                for (const el of allElements) {
                    if (el.children.length === 0 && el.textContent) {
                        const txt = el.textContent.trim();
                        if (/^\\d{1,3}:\\d{2}:\\d{2}$/.test(txt)) {
                            return txt;
                        }
                    }
                }
                const bodyText = document.body ? document.body.innerText : '';
                const m = bodyText.match(/\\b(\\d{1,3}:\\d{2}:\\d{2})\\b/);
                return m ? m[1] : '';
                """
            )
            if hms and re.match(r"^\d{1,3}:\d{2}:\d{2}$", hms.strip()):
                return hms.strip()
        except Exception:
            pass
        time.sleep(1)
    return ""


def get_renew_button_state(tab, hours: int) -> tuple:
    """
    Find the 'Add 12 Hours' or 'Add 24 Hours' button and check if it is greyed out / disabled.
    Returns (button_element, is_clickable: bool, reason: str)
    """
    btn_text = f"Add {hours} Hours"
    btn = (
        tab.ele(f"xpath://button[contains(., '{btn_text}')]", timeout=8)
        or tab.ele(f"xpath://a[contains(., '{btn_text}')]", timeout=3)
        or tab.ele(f"text:{btn_text}", timeout=3)
    )
    if not btn:
        return None, False, f"未找到 {btn_text} 按钮"

    # Check via JS if button (or its clickable wrapper) is disabled / greyed out
    state_info = tab.run_js(
        """
        const btn = arguments[0].closest('button, a') || arguments[0];
        const style = window.getComputedStyle(btn);
        const parentStyle = btn.parentElement ? window.getComputedStyle(btn.parentElement) : style;
        const cls = (btn.className || '') + ' ' + (btn.parentElement ? btn.parentElement.className || '' : '');
        const bodyText = document.body ? document.body.innerText : '';
        const disabledAttr = btn.disabled || btn.getAttribute('disabled') !== null || btn.getAttribute('aria-disabled') === 'true';
        const lowOpacity = parseFloat(style.opacity) < 0.65 || parseFloat(parentStyle.opacity) < 0.65;
        const notAllowed = style.cursor === 'not-allowed' || style.pointerEvents === 'none' || cls.includes('disabled') || cls.includes('cursor-not-allowed') || cls.includes('opacity-50') || cls.includes('pointer-events-none');
        return {
            disabledAttr: Boolean(disabledAttr),
            lowOpacity: Boolean(lowOpacity),
            notAllowed: Boolean(notAllowed),
            opacity: style.opacity,
            cursor: style.cursor,
            className: cls,
            used12h: bodyText.includes('12h option used'),
            used24h: bodyText.includes('24h option used')
        };
        """,
        btn,
    )

    log(f"[{btn_text}] Button state inspect: {state_info}")

    if hours == 12 and state_info.get("used12h"):
        return btn, False, "按钮已灰色（页面提示 12h option used，未到续期时间）"
    if hours == 24 and state_info.get("used24h"):
        return btn, False, "按钮已灰色（页面提示 24h option used，未到续期时间）"
    if state_info.get("disabledAttr") or state_info.get("lowOpacity") or state_info.get("notAllowed"):
        return btn, False, "按钮处于灰色不可点击状态（未到续期时间）"

    return btn, True, "可点击"


def dismiss_adblock_popup_if_present(tab) -> bool:
    """
    Step 2 (2026-11-05_21-46.png):
    'Please turn off your ad blocker' -> click 'CONTINUE ANYWAY' if present.
    """
    try:
        clicked = tab.run_js(
            """
            const candidates = Array.from(document.querySelectorAll('a, button, span, div, p'));
            for (const el of candidates) {
                if (el.children.length === 0 && el.textContent) {
                    const txt = el.textContent.trim().toUpperCase();
                    if (txt === 'CONTINUE ANYWAY') {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            el.click();
                            return true;
                        }
                    }
                }
            }
            return false;
            """
        )
        if clicked:
            log("[Step 2] Detected 'Please turn off your ad blocker' popup -> Clicked 'CONTINUE ANYWAY'!")
            time.sleep(1.5)
            return True
    except Exception:
        pass
    return False


def ensure_tab_focus_spoof(tab):
    """Ensure countdown timers on ShrinkMe / blog don't pause due to visibility/focus checks."""
    try:
        tab.run_js(
            """
            try {
                Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });
                Object.defineProperty(document, 'hidden', { get: () => false, configurable: true });
                document.hasFocus = () => true;
                window.dispatchEvent(new Event('focus'));
                document.dispatchEvent(new Event('visibilitychange'));
            } catch (e) {}
            """
        )
    except Exception:
        pass


def try_pass_cloudflare_turnstile(tab):
    """
    Wait for Cloudflare Turnstile on shrinkme.click to pass automatically,
    or click the checkbox inside the widget if needed.
    """
    try:
        # Check if turnstile response input already has a token
        token = tab.run_js(
            """
            const inp = document.querySelector('input[name="cf-turnstile-response"], input[name="g-recaptcha-response"]');
            return inp ? inp.value : '';
            """
        )
        if token:
            return True

        # Try clicking the Turnstile iframe / widget box if present
        cf_iframe = tab.ele('css:iframe[src*="challenges.cloudflare.com"]', timeout=2)
        if cf_iframe:
            log("[Step 1] Clicking Cloudflare Turnstile checkbox...")
            try:
                rect = cf_iframe.rect
                tab.actions.move_to(cf_iframe, offset_x=-int(rect.size[0] / 2) + 32, offset_y=0).click()
            except Exception:
                try:
                    cf_iframe.click()
                except Exception:
                    pass
    except Exception:
        pass
    return False


def find_active_workflow_tab(page: ChromiumPage, dashboard_tab_id: str, current_tab):
    """
    If clicking a button on ShrinkMe/themezon opened a legitimate next-step tab or an ad popup tab,
    locate the tab that actually contains our renewal workflow (or returned to hokas.net).
    """
    try:
        all_tabs = page.get_tabs()
        # 1. Check if any new tab navigated back to hokas.net (Step 12 completed!)
        for t in all_tabs:
            if t.tab_id != dashboard_tab_id and "hokas.net" in (t.url or ""):
                return t

        # 2. Prefer a tab whose URL or content matches ShrinkMe / Step 1..12 markers
        for t in all_tabs:
            if t.tab_id == dashboard_tab_id:
                continue
            url = (t.url or "").lower()
            if any(k in url for k in ("shrinkme", "themezon", "#smg-next")):
                return t
            try:
                txt = t.run_js("return document.body ? document.body.innerText : '';") or ""
                if any(
                    marker in txt
                    for marker in (
                        "Click here to continue",
                        "CLICK TO VERIFY",
                        "STEP 1 OF 2",
                        "STEP 2 OF 2",
                        "CONTINUE NEXT",
                        "GENERATE LINK",
                        "CONTINUE TO YOUR LINK",
                        "YOUR LINK IS ALMOST READY",
                        "Get Link",
                        "Please turn off your ad blocker",
                    )
                ):
                    return t
            except Exception:
                pass
    except Exception:
        pass
    return current_tab


def complete_shrinkme_steps(page: ChromiumPage, dashboard_tab, hours: int) -> bool:
    """
    Executes Steps 1 through 12 in the newly opened ShrinkMe tab:
      Step 1 (2026-11-05_21-44 & 21-45): Wait for CF Turnstile -> Click 'Click here to continue'
      Step 2 (2026-11-05_21-46): Optional 'Please turn off your ad blocker' -> Click 'CONTINUE ANYWAY'
      Step 3 (2026-11-05_21-46_1): 'STEP 1 OF 2' -> Click 'CLICK TO VERIFY'
      Step 4 (2026-11-05_21-47): Wait countdown 'Please wait 7 seconds...'
      Step 5 (2026-11-05_21-47_1): Click 'Continue...' ('To scroll down, click Continue...')
      Step 6 (2026-11-05_21-48): Click green button 'CONTINUE NEXT'
      Step 7 (2026-11-05_21-48_1): 'STEP 2 OF 2' -> Click 'Continue...' ('Scroll down to Generate Link, or click Continue...')
      Step 8 (2026-11-05_21-48_2): Click blue button 'GENERATE LINK'
      Step 9 (2026-11-05_21-49): Wait countdown 'Your link will be ready in 6 seconds...'
      Step 10 (2026-11-05_21-51): Click green button 'CONTINUE TO YOUR LINK'
      Step 11 (2026-11-05_21-51_1): 'YOUR LINK IS ALMOST READY.' -> Wait 9s countdown ('Please wait...')
      Step 12 (2026-11-05_21-52): Click 'Get Link' -> Return to Hokas container page
    """
    dashboard_tab_id = dashboard_tab.tab_id

    # Wait for new tab to appear
    work_tab = None
    for _ in range(15):
        tabs = [t for t in page.get_tabs() if t.tab_id != dashboard_tab_id]
        if tabs:
            work_tab = tabs[0]
            break
        time.sleep(1)

    if not work_tab:
        # Check if current dashboard tab itself navigated away
        if "hokas.net/dashboard" not in dashboard_tab.url:
            work_tab = dashboard_tab
        else:
            log(f"[Add {hours}h] Clicking button did not open a new tab.")
            return False

    log(f"[Add {hours}h] Switched to renewal tab: {work_tab.url}")

    start_time = time.time()
    max_duration = 240  # 4 minutes max for the 12-step flow
    last_step_logged = ""

    while time.time() - start_time < max_duration:
        work_tab = find_active_workflow_tab(page, dashboard_tab_id, work_tab)
        try:
            page.activate_tab(work_tab)
        except Exception:
            pass

        cur_url = work_tab.url or ""

        # Check if we have already returned to hokas.net!
        if "hokas.net" in cur_url and work_tab.tab_id != dashboard_tab_id:
            log(f"[Step 12 Complete] Renewal tab returned to Hokas: {cur_url}")
            time.sleep(5)
            return True

        ensure_tab_focus_spoof(work_tab)

        # Always check & dismiss optional Step 2 adblock popup ('CONTINUE ANYWAY')
        dismiss_adblock_popup_if_present(work_tab)

        # Inspect page state via JS and perform the matching step action
        try:
            step_state = work_tab.run_js(
                """
                const bodyText = document.body ? document.body.innerText : '';

                function isVisible(el) {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 5 && rect.height > 5;
                }

                function findClickableByText(exactOrRegex) {
                    const els = Array.from(document.querySelectorAll('button, a, input[type="submit"], input[type="button"], div[role="button"], span'));
                    for (const el of els) {
                        const txt = (el.innerText || el.value || el.textContent || '').trim();
                        if (!txt) continue;
                        const matched = typeof exactOrRegex === 'string'
                            ? txt.toUpperCase() === exactOrRegex.toUpperCase()
                            : exactOrRegex.test(txt);
                        if (matched && isVisible(el)) {
                            return el;
                        }
                    }
                    return null;
                }

                // Step 12: 'Get Link' on shrinkme final page
                const getLinkBtn = findClickableByText(/^Get Link$/i);
                if (getLinkBtn) {
                    const href = getLinkBtn.getAttribute('href') || (getLinkBtn.closest('a') ? getLinkBtn.closest('a').getAttribute('href') : '');
                    getLinkBtn.click();
                    return { step: 'STEP_12_GET_LINK', href: href || '' };
                }

                // Step 11: 'YOUR LINK IS ALMOST READY' countdown ('Please wait...')
                if (/YOUR LINK IS ALMOST READY/i.test(bodyText) || findClickableByText(/^Please wait\\.{0,3}$/i)) {
                    return { step: 'STEP_11_WAIT_COUNTDOWN' };
                }

                // Step 10: 'CONTINUE TO YOUR LINK'
                const step10Btn = findClickableByText(/^CONTINUE TO YOUR LINK$/i);
                if (step10Btn) {
                    step10Btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                    step10Btn.click();
                    return { step: 'STEP_10_CONTINUE_TO_YOUR_LINK' };
                }

                // Step 9: 'Your link will be ready in X seconds...'
                if (/Your link will be ready in/i.test(bodyText)) {
                    return { step: 'STEP_9_WAIT_COUNTDOWN' };
                }

                // Step 8: 'GENERATE LINK'
                const step8Btn = findClickableByText(/^GENERATE LINK$/i);
                if (step8Btn) {
                    step8Btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                    step8Btn.click();
                    return { step: 'STEP_8_GENERATE_LINK' };
                }

                // Step 6: 'CONTINUE NEXT'
                const step6Btn = findClickableByText(/^CONTINUE NEXT$/i);
                if (step6Btn) {
                    step6Btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                    step6Btn.click();
                    return { step: 'STEP_6_CONTINUE_NEXT' };
                }

                // Step 5 or Step 7: 'Continue...' button
                const continueDotsBtn = findClickableByText(/^Continue\\.{2,3}$/i);
                if (continueDotsBtn) {
                    continueDotsBtn.scrollIntoView({ behavior: 'instant', block: 'center' });
                    continueDotsBtn.click();
                    const isStep2Of2 = /STEP 2 OF 2/i.test(bodyText) || /Scroll down to Generate Link/i.test(bodyText);
                    return { step: isStep2Of2 ? 'STEP_7_CONTINUE_STEP2' : 'STEP_5_CONTINUE_STEP1' };
                }

                // Step 4: 'Please wait X seconds...'
                if (/Please wait \\d+ seconds/i.test(bodyText)) {
                    return { step: 'STEP_4_WAIT_COUNTDOWN' };
                }

                // Step 3: 'CLICK TO VERIFY'
                const step3Btn = findClickableByText(/^CLICK TO VERIFY$/i);
                if (step3Btn) {
                    step3Btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                    step3Btn.click();
                    return { step: 'STEP_3_CLICK_TO_VERIFY' };
                }

                // Step 1: 'Click here to continue' (with Cloudflare Turnstile)
                const step1Btn = findClickableByText(/^Click here to continue$/i);
                if (step1Btn) {
                    const cfInput = document.querySelector('input[name="cf-turnstile-response"], input[name="g-recaptcha-response"]');
                    const cfToken = cfInput ? cfInput.value : '';
                    if (cfToken && cfToken.length > 10) {
                        step1Btn.click();
                        return { step: 'STEP_1_CF_PASSED_AND_CLICKED' };
                    }
                    // If there is no turnstile widget at all on the page, click directly
                    const hasCfWidget = Boolean(document.querySelector('iframe[src*="cloudflare"], .cf-turnstile, [data-sitekey]'));
                    if (!hasCfWidget) {
                        step1Btn.click();
                        return { step: 'STEP_1_CLICKED_NO_CF' };
                    }
                    return { step: 'STEP_1_WAITING_CF' };
                }

                return { step: 'WAITING_PAGE', url: window.location.href };
                """
            )
        except Exception as e:
            step_state = {"step": f"JS_ERR: {e}"}

        step_name = step_state.get("step", "UNKNOWN")
        if step_name != last_step_logged:
            log(f"[Add {hours}h] Flow status -> {step_name} (URL: {cur_url})")
            last_step_logged = step_name

        if step_name == "STEP_1_WAITING_CF":
            # Give CF a few seconds to auto-verify; if not, click the turnstile checkbox
            if int(time.time() - start_time) % 5 == 0:
                try_pass_cloudflare_turnstile(work_tab)

        elif step_name in ("STEP_5_CONTINUE_STEP1", "STEP_7_CONTINUE_STEP2"):
            # Scroll down slightly in case the next button is further down the article
            time.sleep(1.5)
            try:
                work_tab.scroll.down(600)
            except Exception:
                pass

        elif step_name == "STEP_12_GET_LINK":
            href = step_state.get("href", "")
            log(f"[Step 12] Clicked 'Get Link' (href={href}). Waiting for redirect to Hokas...")
            time.sleep(4)
            # Check if any tab returned to hokas.net, or if href is a valid non-javascript link we can navigate to
            for t in page.get_tabs():
                if t.tab_id != dashboard_tab_id and "hokas.net" in (t.url or ""):
                    log(f"[Step 12] Successfully redirected to Hokas: {t.url}")
                    time.sleep(4)
                    return True
            if href and href.startswith("http") and "hokas.net" in href:
                work_tab.get(href)
                time.sleep(5)
                return True

        time.sleep(1.5)

    # Timeout reached — capture screenshot right at the stuck place before closing tab!
    err_shot = save_screenshot(work_tab, f"ERROR_add_{hours}h_step_timeout")
    send_tg_message(
        f"⚠️ <b>Hokas +{hours}小时续期卡住超时</b>\n"
        f"• 最后状态: <code>{last_step_logged}</code>\n"
        f"• 当前页面: <code>{work_tab.url}</code>",
        photo_path=err_shot,
    )
    return False


def cleanup_extra_tabs(page: ChromiumPage, dashboard_tab):
    """Close all tabs except the main container dashboard tab."""
    for t in page.get_tabs():
        if t.tab_id != dashboard_tab.tab_id:
            try:
                t.close()
            except Exception:
                pass
    try:
        page.activate_tab(dashboard_tab)
    except Exception:
        pass


def perform_single_renewal(page: ChromiumPage, dashboard_tab, server_url: str, hours: int) -> dict:
    """
    Attempt renewal for +12 Hours or +24 Hours.
    Returns a dict with:
      - hours: 12 or 24
      - status: 'SUCCESS' | 'GREYED_OUT' | 'FAILED'
      - before_time: str
      - after_time: str
      - added_str: str
      - detail: str
    """
    log(f"========== Checking Add {hours} Hours ==========")
    dashboard_tab.get(server_url)
    time.sleep(5)

    before_hms = get_remaining_time(dashboard_tab)
    before_sec = parse_hms_to_seconds(before_hms)
    log(f"[Add {hours}h] Remaining time before renewal: {before_hms} ({before_sec}s)")

    btn, is_clickable, reason = get_renew_button_state(dashboard_tab, hours)
    if not is_clickable:
        log(f"[Add {hours}h] Skipping click: {reason}")
        return {
            "hours": hours,
            "status": "GREYED_OUT",
            "before_time": before_hms,
            "after_time": before_hms,
            "added_str": "0小时0分0秒",
            "detail": reason,
        }

    log(f"[Add {hours}h] Button is active! Clicking 'Add {hours} Hours'...")
    btn.click()
    time.sleep(3)

    try:
        flow_ok = complete_shrinkme_steps(page, dashboard_tab, hours)
    finally:
        cleanup_extra_tabs(page, dashboard_tab)

    # Refresh the container dashboard page to check updated remaining time and button grey state
    log(f"[Add {hours}h] Returning to container page and refreshing...")
    dashboard_tab.get(server_url)
    time.sleep(4)
    dashboard_tab.refresh()
    time.sleep(6)

    after_hms = get_remaining_time(dashboard_tab)
    after_sec = parse_hms_to_seconds(after_hms)
    _, after_clickable, after_reason = get_renew_button_state(dashboard_tab, hours)

    log(f"[Add {hours}h] Remaining time after renewal: {after_hms} ({after_sec}s), Button clickable={after_clickable}")

    diff_sec = after_sec - before_sec if (after_sec > 0 and before_sec > 0) else 0
    # Consider renewal successful if remaining time increased by at least 10 minutes (600s)
    if diff_sec > 600:
        added_str = format_duration_diff(diff_sec)
        grey_note = "按钮已变回灰色" if not after_clickable else "按钮状态未变灰"
        return {
            "hours": hours,
            "status": "SUCCESS",
            "before_time": before_hms,
            "after_time": after_hms,
            "added_str": added_str,
            "detail": f"续期成功！剩余时间 {before_hms} -> {after_hms}（增加了 {added_str}，{grey_note}）",
        }
    else:
        return {
            "hours": hours,
            "status": "FAILED",
            "before_time": before_hms,
            "after_time": after_hms,
            "added_str": "0小时0分0秒",
            "detail": f"未成功增加时间（续期前 {before_hms}，刷新后 {after_hms}，flow_ok={flow_ok}）",
        }


def main():
    email = os.environ.get("HOKAS_EMAIL", "").strip()
    password = os.environ.get("HOKAS_PASSWORD", "").strip()
    server_url = os.environ.get("HOKAS_SERVER_URL", "").strip() or DEFAULT_SERVER_URL

    if not email or not password:
        log("ERROR: HOKAS_EMAIL or HOKAS_PASSWORD environment variable is missing!")
        send_tg_message("❌ <b>Hokas 自动续期失败</b>\n未配置 <code>HOKAS_EMAIL</code> 或 <code>HOKAS_PASSWORD</code> 密钥。")
        sys.exit(1)

    page = None
    try:
        page = create_browser()

        # 1. Login
        login_hokas(page, email, password)

        # 2. Go to container page and record initial time
        log(f"Opening container page: {server_url}")
        page.get(server_url)
        time.sleep(6)

        initial_time = get_remaining_time(page)
        initial_sec = parse_hms_to_seconds(initial_time)
        log(f"Initial container remaining time: {initial_time}")
        save_screenshot(page, "01_initial_dashboard")

        if not initial_time:
            raise RuntimeError("进入容器页面后未能读取到剩余时间，请检查页面状态")

        # 3. Run +12 Hours renewal first
        res_12 = perform_single_renewal(page, page, server_url, 12)
        save_screenshot(page, "02_after_12h")

        # 4. Run +24 Hours renewal next (if +12h succeeded or was already greyed out)
        res_24 = perform_single_renewal(page, page, server_url, 24)
        final_shot = save_screenshot(page, "03_after_24h_final")

        final_time = get_remaining_time(page) or res_24.get("after_time") or res_12.get("after_time")
        final_sec = parse_hms_to_seconds(final_time)
        total_diff = final_sec - initial_sec if (final_sec > 0 and initial_sec > 0) else 0
        total_added_str = format_duration_diff(total_diff) if total_diff > 60 else "0小时0分0秒"

        def fmt_status(r: dict) -> str:
            st = r["status"]
            icon = "✅ 成功" if st == "SUCCESS" else ("⏳ 未到时间(已灰色)" if st == "GREYED_OUT" else "❌ 失败")
            return (
                f"<b>+{r['hours']}小时续期</b>: {icon}\n"
                f"  • 增加时间: <code>{r['added_str']}</code>\n"
                f"  • 详情: {r['detail']}"
            )

        summary_msg = (
            f"🖥 <b>Hokas 容器自动续期报告</b>\n\n"
            f"⏱ <b>初始剩余时间</b>: <code>{initial_time}</code>\n"
            f"⏱ <b>最终剩余时间</b>: <code>{final_time}</code>\n"
            f"➕ <b>本次累计增加</b>: <code>{total_added_str}</code>\n\n"
            f"{fmt_status(res_12)}\n\n"
            f"{fmt_status(res_24)}"
        )

        log("========== Renewal Summary ==========")
        log(summary_msg)
        send_tg_message(summary_msg, photo_path=final_shot)

    except Exception as e:
        err_trace = traceback.format_exc()
        log(f"FATAL ERROR during workflow:\n{err_trace}")

        err_shot = ""
        if page:
            try:
                # Capture screenshot of whichever tab was currently active when error occurred
                active_tab = page.get_tab()
                err_shot = save_screenshot(active_tab, "ERROR_screenshot")
            except Exception:
                err_shot = save_screenshot(page, "ERROR_screenshot")

        err_msg = (
            f"⚠️ <b>Hokas 自动续期工作流异常中断</b>\n\n"
            f"❌ <b>错误信息</b>: <code>{str(e)}</code>\n"
            f"📸 已在出错位置自动截图（见附图或 Actions Artifact）。"
        )
        send_tg_message(err_msg, photo_path=err_shot)
        sys.exit(1)

    finally:
        if page:
            try:
                page.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()
