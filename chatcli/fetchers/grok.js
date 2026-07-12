/**
 * Grok 对话页提取脚本（CDP 注入版）。
 *
 * 由 Python 端通过 Chrome DevTools Protocol 的 Runtime.evaluate 注入到
 * grok.com 对话页运行。提取 human / ai 消息后，把整个 payload 用
 * JSON.stringify 包成字符串返回，保证通过 CDP 序列化时不丢字段。
 *
 * 选择器与逻辑与原 Grok-Exporter 扩展的 content.js 保持一致，便于对照维护。
 *
 * 当 Python 端开了新标签再跳转到 URL 时，页面刚开始加载、消息还没渲染；
 * 配合 Runtime.evaluate 的 awaitPromise=True，本脚本可以异步轮询，等到
 * 至少抽出一条消息再返回。
 */

(function () {
  "use strict";

  const USER_SEL = '[data-testid="user-message"]';
  const AI_SEL = '[data-testid="assistant-message"]';
  const BOTH_SEL = USER_SEL + ", " + AI_SEL;
  const MD_SEL = ".response-content-markdown";
  const THINK_RE =
    /^(思考了\s*\d+\s*s|Thought for\s+\d+\s*s|Thinking(?:\s+for\s+\d+\s*s)?)\s*/i;

  // /json/new 后等待渲染的最长时间（毫秒）
  const MAX_WAIT_MS = 12000;
  const POLL_INTERVAL_MS = 300;

  function conversationIdFromUrl(href) {
    const m = String(href || "").match(/\/c\/([0-9a-fA-F-]{36})/);
    return m ? m[1] : null;
  }

  function cleanTitle(title) {
    return String(title || "")
      .replace(/\s*[-|]\s*Grok\s*$/i, "")
      .trim();
  }

  function extractThinkingLabel(el) {
    const btn = Array.from(el.querySelectorAll("button")).find((b) =>
      /思考了|Thought for|Thinking/i.test(b.innerText || "")
    );
    if (btn) return (btn.innerText || "").trim();
    const m = (el.innerText || "").match(
      /^(思考了\s*\d+\s*s|Thought for\s+\d+\s*s)/i
    );
    return m ? m[1] : null;
  }

  function extractMessages() {
    const nodes = Array.from(document.querySelectorAll(BOTH_SEL));
    return nodes.map((el, index) => {
      const testid = el.getAttribute("data-testid");
      const role = testid === "user-message" ? "human" : "ai";
      const md = el.querySelector(MD_SEL);
      let content = (md ? md.innerText : el.innerText || "").trim();
      let thinking_label = null;

      if (role === "ai") {
        thinking_label = extractThinkingLabel(el);
        if (thinking_label && content.startsWith(thinking_label)) {
          content = content.slice(thinking_label.length).replace(/^\n+/, "").trim();
        } else {
          content = content.replace(THINK_RE, "").trim();
        }
      }

      const msg = { index: index, role: role, content: content };
      if (role === "ai" && thinking_label) {
        msg.thinking_label = thinking_label;
      }
      return msg;
    });
  }

  function buildExportPayload() {
    const messages = extractMessages();
    const human_n = messages.filter((m) => m.role === "human").length;
    const ai_n = messages.filter((m) => m.role === "ai").length;
    return {
      conversation_id: conversationIdFromUrl(location.href),
      url: location.href.split("?")[0],
      title: cleanTitle(document.title),
      exported_at: new Date().toISOString(),
      message_count: messages.length,
      human_message_count: human_n,
      ai_message_count: ai_n,
      messages: messages,
    };
  }

  function ensureOnConversation() {
    // 在等待循环里也要校验，否则登录页 / about:blank 不会抛错
    if (!/\/c\/[0-9a-fA-F-]{36}/.test(location.pathname)) {
      return {
        ok: false,
        error: "当前不是对话页。请打开 https://grok.com/c/<id> 后再抓取。",
      };
    }
    return { ok: true };
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  // 入口：先确保 URL 正确，再轮询直到消息出现或超时。
  // 用 throw 而不是返回 {ok:false}，因为 CDP Runtime.evaluate 会把 throw
  // 自动包装成 exceptionDetails，Python 端 CDPEvalError 直接拿到错误信息。
  return (async function () {
    const deadline = Date.now() + MAX_WAIT_MS;
    let lastPayload = null;

    while (true) {
      const ok = ensureOnConversation();
      if (!ok.ok) {
        // 还没跳到对话页就继续等
        if (Date.now() >= deadline) {
          throw new Error(ok.error);
        }
        await sleep(POLL_INTERVAL_MS);
        continue;
      }
      const payload = buildExportPayload();
      if (payload.messages.length) {
        return JSON.stringify(payload);
      }
      lastPayload = payload;
      if (Date.now() >= deadline) {
        throw new Error(
          "未找到消息。请确认对话已加载完成，或向下/向上滚动后再试。"
        );
      }
      await sleep(POLL_INTERVAL_MS);
    }
  })();
})();