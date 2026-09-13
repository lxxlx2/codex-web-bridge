"""Sanitized ChatGPT Web surface inspection for the standalone bridge.

The inspector intentionally returns only transport/readiness metadata. It does
not return conversation text, composer text, cookies, storage, account ids,
raw DOM, or raw conversation ids.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict
from urllib.parse import urlparse

from app.core import get_browser


_SURFACE_JS = r"""
return (function() {
  const visible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
    const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
    return (!style || (style.display !== 'none' && style.visibility !== 'hidden')) &&
      (!rect || (rect.width > 0 && rect.height > 0));
  };
  const norm = (value) => String(value || '').replace(/[\s\u200b-\u200d\ufeff]+/g, ' ').trim();
  const low = (value) => norm(value).toLowerCase();
  const selected = (el) => {
    const attr = (name) => low(el && el.getAttribute ? el.getAttribute(name) : '');
    const state = attr('data-state');
    return attr('aria-selected') === 'true' ||
      attr('aria-checked') === 'true' ||
      attr('aria-pressed') === 'true' ||
      attr('data-selected') === 'true' ||
      ['active', 'selected', 'checked', 'on'].includes(state) ||
      attr('aria-current') === 'page';
  };

  const prompt = document.querySelector('#prompt-textarea') ||
    document.querySelector('[role="textbox"][aria-label*="ChatGPT"]') ||
    document.querySelector('[contenteditable="true"][role="textbox"]');
  const composerText = prompt ? norm(
    prompt.innerText || prompt.textContent || prompt.value || ''
  ) : '';
  const send = document.querySelector('[data-testid="send-button"]') ||
    document.querySelector('button[aria-label*="Send" i]') ||
    document.querySelector('button[aria-label*="发送"]');

  const controls = Array.from(document.querySelectorAll(
    'button,a,[role="tab"],[role="button"],[aria-selected],[aria-pressed],'+
    '[aria-current],[data-state],[data-selected]'
  )).filter(visible);
  const controlRows = controls.map((el) => ({
    text: norm(el.innerText || el.textContent),
    aria: norm(el.getAttribute && el.getAttribute('aria-label')),
    selected: selected(el),
  }));
  const exactChat = new Set(['chat', '聊天']);
  const exactWork = new Set(['work', '工作']);
  const selectedChat = controlRows.some((row) => row.selected &&
    (exactChat.has(low(row.text)) || exactChat.has(low(row.aria))));
  const selectedWork = controlRows.some((row) => row.selected &&
    (exactWork.has(low(row.text)) || exactWork.has(low(row.aria))));
  const chatControlPresent = controlRows.some((row) =>
    exactChat.has(low(row.text)) || exactChat.has(low(row.aria)));
  const workControlPresent = controlRows.some((row) =>
    exactWork.has(low(row.text)) || exactWork.has(low(row.aria)));

  // Some current ChatGPT Work conversations expose the active mode as a
  // non-interactive badge next to the conversation title instead of a selected
  // tab/button. Treat that badge as conservative Work evidence. Only a boolean
  // leaves the page; no title or page text is returned.
  const modeLabels = Array.from(document.querySelectorAll('span,div,p'))
    .filter(visible)
    .filter((el) => !el.children || el.children.length === 0)
    .map((el) => low(el.innerText || el.textContent))
    .filter((value) => value.length > 0 && value.length <= 160);
  const workBadgePresent = modeLabels.some((value) =>
    exactWork.has(value) || /(?:^|[·•])\s*(?:work|工作)$/.test(value)
  );

  const statusNodes = Array.from(document.querySelectorAll(
    '[role="dialog"],[aria-modal="true"],[role="alert"],[role="status"],'+
    '[data-testid*="banner" i],[data-testid*="limit" i],[data-testid*="usage" i],'+
    '[class*="banner" i]'
  )).filter(visible);
  const statusText = low(
    statusNodes.map((el) => norm(el.innerText || el.textContent)).join(' | ')
  );

  const rateLimited =
    statusText.includes('too many requests') ||
    statusText.includes('making requests too quickly') ||
    statusText.includes('temporarily limited access to your conversations') ||
    statusText.includes('请求过于频繁') ||
    statusText.includes('暂时限制你访问对话记录');

  const workQuota =
    (statusText.includes('work usage') &&
      (statusText.includes('limit') || statusText.includes('reset'))) ||
    statusText.includes('used up work') ||
    (statusText.includes('工作用量') &&
      (statusText.includes('用完') || statusText.includes('重置')));

  const usageExhausted = !workQuota && (
    statusText.includes('usage limit') ||
    statusText.includes('reached your limit') ||
    (statusText.includes('you have reached') && statusText.includes('limit')) ||
    statusText.includes('使用上限') ||
    statusText.includes('用量已用完') ||
    (statusText.includes('已达到') && statusText.includes('上限'))
  );

  const authNodes = Array.from(
    document.querySelectorAll('a,button,[role="button"]')
  ).filter(visible);
  const authRequired = authNodes.some((el) => {
    const value = low(
      `${el.innerText || el.textContent || ''} ${
        el.getAttribute && el.getAttribute('aria-label') || ''
      }`
    );
    return ['log in', 'sign in', '登录'].includes(value);
  }) && !prompt;

  const challenge = !!document.querySelector(
    'iframe[src*="challenge" i],iframe[src*="captcha" i],'+
    '[data-testid*="challenge" i],[id*="challenge" i],[class*="captcha" i]'
  );

  return {
    host: String(location.hostname || ''),
    pathname: String(location.pathname || ''),
    prompt_present: !!prompt,
    composer_chars: composerText.length,
    send_control_present: !!(send && visible(send)),
    selected_chat: selectedChat,
    selected_work: selectedWork,
    chat_control_present: chatControlPresent,
    work_control_present: workControlPresent,
    work_badge_present: workBadgePresent,
    work_quota_exhausted: !!workQuota,
    usage_exhausted: !!usageExhausted,
    rate_limited: !!rateLimited,
    auth_required: !!authRequired,
    challenge_present: !!challenge,
  };
})();
"""


@dataclass(frozen=True)
class SurfaceSnapshot:
    target_count: int
    host_ok: bool
    pathname_class: str
    surface_kind: str
    prompt_present: bool
    composer_chars: int
    composer_empty: bool
    send_control_present: bool
    work_quota_exhausted: bool
    usage_exhausted: bool
    rate_limited: bool
    auth_required: bool
    challenge_present: bool
    surface_ready: bool
    blocking_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _tab_url(tab: Any) -> str:
    try:
        return str(getattr(tab, "url", "") or "")
    except Exception:
        return ""


def _is_chatgpt_url(url: str) -> bool:
    try:
        host = (urlparse(str(url or "")).hostname or "").lower()
    except Exception:
        host = ""
    return host in {"chatgpt.com", "www.chatgpt.com"}


def controlled_chatgpt_tabs() -> list[Any]:
    browser = get_browser(auto_connect=False)
    health = browser.health_check()
    if not isinstance(health, dict) or not health.get("connected"):
        return []
    return [
        tab
        for tab in list(browser.get_tabs() or [])
        if _is_chatgpt_url(_tab_url(tab))
    ]


def _pathname_class(pathname: str) -> str:
    value = str(pathname or "")
    if value in {"", "/"}:
        return "root"
    if value.startswith("/c/"):
        return "conversation"
    return "other"


def classify_surface_probe(
    raw: Dict[str, Any],
    *,
    target_count: int = 1,
) -> SurfaceSnapshot:
    data = dict(raw or {})
    host = str(data.get("host") or "").lower()
    host_ok = host in {"chatgpt.com", "www.chatgpt.com"}
    pathname_class = _pathname_class(str(data.get("pathname") or ""))
    prompt_present = bool(data.get("prompt_present"))
    try:
        composer_chars = max(0, int(data.get("composer_chars", 0) or 0))
    except (TypeError, ValueError):
        composer_chars = 0
    composer_empty = composer_chars == 0
    send_control_present = bool(data.get("send_control_present"))
    work_quota = bool(data.get("work_quota_exhausted"))
    usage = bool(data.get("usage_exhausted"))
    rate = bool(data.get("rate_limited"))
    auth = bool(data.get("auth_required"))
    challenge = bool(data.get("challenge_present"))
    selected_chat = bool(data.get("selected_chat"))
    selected_work = bool(data.get("selected_work"))
    chat_control = bool(data.get("chat_control_present"))
    work_control = bool(data.get("work_control_present"))
    work_badge = bool(data.get("work_badge_present"))

    # A visible Work badge is mode evidence even when the UI does not expose a
    # selected Work control. If Chat is simultaneously marked selected, fail
    # closed as an ambiguous/conflicting surface instead of guessing Chat.
    work_evidence = selected_work or work_badge
    if selected_chat and work_evidence:
        surface_kind = "unknown"
    elif work_evidence:
        surface_kind = "work"
    elif selected_chat:
        surface_kind = "chat"
    elif prompt_present and chat_control and not work_control:
        surface_kind = "chat"
    elif prompt_present and not chat_control and not work_control:
        surface_kind = "chat"
    else:
        surface_kind = "unknown"

    reason = "none"
    if target_count <= 0:
        reason = "target_missing"
    elif target_count > 1:
        reason = "target_ambiguous"
    elif not host_ok:
        reason = "unknown_surface"
    elif auth:
        reason = "auth_required"
    elif challenge:
        reason = "challenge"
    elif rate:
        reason = "rate_limited"
    elif work_quota:
        reason = "work_quota_exhausted"
    elif usage:
        reason = "usage_exhausted"
    elif surface_kind == "work":
        reason = "work_surface"
    elif surface_kind != "chat":
        reason = "unknown_surface"
    elif not prompt_present:
        reason = "prompt_missing"
    elif not composer_empty:
        reason = "composer_not_empty"
    elif not send_control_present:
        reason = "send_missing"

    return SurfaceSnapshot(
        target_count=int(target_count),
        host_ok=host_ok,
        pathname_class=pathname_class,
        surface_kind=surface_kind,
        prompt_present=prompt_present,
        composer_chars=composer_chars,
        composer_empty=composer_empty,
        send_control_present=send_control_present,
        work_quota_exhausted=work_quota,
        usage_exhausted=usage,
        rate_limited=rate,
        auth_required=auth,
        challenge_present=challenge,
        surface_ready=reason == "none",
        blocking_reason=reason,
    )


def inspect_chatgpt_surface(
    tab: Any | None = None,
    *,
    target_count: int | None = None,
) -> SurfaceSnapshot:
    if tab is None:
        tabs = controlled_chatgpt_tabs()
        count = len(tabs)
        if count != 1:
            return classify_surface_probe({}, target_count=count)
        tab = tabs[0]
        target_count = count
    count = 1 if target_count is None else int(target_count)
    try:
        result = tab.run_js(_SURFACE_JS)
    except Exception:
        result = {}
    return classify_surface_probe(
        result if isinstance(result, dict) else {},
        target_count=count,
    )


def sanitized_surface_status() -> Dict[str, Any]:
    """Return a safe health/status payload without page text or identifiers."""
    try:
        return inspect_chatgpt_surface().to_dict()
    except Exception:
        return {
            "target_count": 0,
            "host_ok": False,
            "pathname_class": "other",
            "surface_kind": "unknown",
            "prompt_present": False,
            "composer_chars": 0,
            "composer_empty": True,
            "send_control_present": False,
            "work_quota_exhausted": False,
            "usage_exhausted": False,
            "rate_limited": False,
            "auth_required": False,
            "challenge_present": False,
            "surface_ready": False,
            "blocking_reason": "surface_probe_failed",
        }


__all__ = [
    "SurfaceSnapshot",
    "classify_surface_probe",
    "controlled_chatgpt_tabs",
    "inspect_chatgpt_surface",
    "sanitized_surface_status",
]
