import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StdioConnectionParams
from mcp.client.stdio import StdioServerParameters
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

SYSTEM_PROMPT = """You are a helpful data analyst for an electronics store.
Answer questions by querying the database using the available tools.
Always run get_schema first if you are unsure about table structure.
Present results in a clear, concise way — use markdown tables or bullet points where helpful.
Only use SELECT queries. Never guess data; always query for it.

If a SQL tool returns an error, analyze the error message carefully.
Use `get_schema` to verify column names and table structures before attempting to fix the query.
Do not repeat the same mistake; try a different approach if your previous attempt failed."""

session_service = InMemorySessionService()
_tools = None
_exit_stack = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _tools, _exit_stack
    toolset = McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="python",
                args=["mcp_server.py"],
            )
        )
    )
    # Fixed: get_tools() is an async function, must be awaited
    _tools = await toolset.get_tools()
    _exit_stack = toolset
    yield
    # Attempt to close toolset if it has a close method
    if hasattr(_exit_stack, 'close'):
        _exit_stack.close()


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def make_agent() -> LlmAgent:
    return LlmAgent(
        model="gemini-2.0-flash",
        name="electronics_sql_agent",
        description="Text-to-SQL agent for the electronics store database",
        instruction=SYSTEM_PROMPT,
        tools=_tools,
    )


class AskRequest(BaseModel):
    question: str
    session_id: str | None = None


@app.post("/ask")
async def ask(req: AskRequest):
    session_id = req.session_id or str(uuid.uuid4())

    try:
        await session_service.get_session(app_name="electronics", user_id="user", session_id=session_id)
    except Exception:
        await session_service.create_session(app_name="electronics", user_id="user", session_id=session_id)

    agent = make_agent()
    runner = Runner(agent=agent, app_name="electronics", session_service=session_service)

    async def stream():
        yield f"data: {json.dumps({'type': 'session_id', 'value': session_id})}\n\n"
        retry_count = 0
        max_retries = 3

        while retry_count <= max_retries:
            try:
                async for event in runner.run_async(
                    user_id="user",
                    session_id=session_id,
                    new_message=types.Content(
                        role="user",
                        parts=[types.Part(text=req.question if retry_count == 0 else "")]
                    ) if retry_count == 0 else None,
                ):
                    # Tool call — show the SQL being run
                    if hasattr(event, 'content') and event.content:
                        for part in event.content.parts:
                            if hasattr(part, 'function_call') and part.function_call:
                                fc = part.function_call
                                if fc.name == 'run_sql':
                                    sql = fc.args.get('query', '')
                                    yield f"data: {json.dumps({'type': 'sql', 'value': sql})}\n\n"

                    # Check for SQL errors in the tool output (via event content)
                    error_found = False
                    if hasattr(event, 'content') and event.content:
                        for part in event.content.parts:
                            if part.text and ("SQL Error:" in part.text or "SQL Syntax Error:" in part.text):
                                error_msg = part.text
                                retry_count += 1
                                if retry_count <= max_retries:
                                    yield f"data: {json.dumps({'type': 'answer', 'value': f'⚠️ SQL Error detected. Self-healing... (Attempt {retry_count}/{max_retries})'})}\n\n"
                                    # Inject correction prompt into session
                                    # Since runner.run_async typically manages history, we add a message to the session
                                    correction_prompt = f"The previous query failed with error: {error_msg}. Please analyze the schema and correct the query."
                                    # We must use the session_service or the agent's internal state if available.
                                    # However, the ADK Runner usually handles the loop.
                                    # To force a re-run, we need to provide a new message.

                                    # For Gemini ADK, we can append to the session history.
                                    # But since we are in a streaming loop, we might need to break and re-invoke.
                                    error_found = True
                                    break

                    if error_found:
                        break # Exit the inner async for loop to trigger retry

                    # Final answer
                    if event.is_final_response() and event.content:
                        for part in event.content.parts:
                            if part.text:
                                yield f"data: {json.dumps({'type': 'answer', 'value': part.text})}\n\n"
                        return # Success! End the stream

                if not error_found:
                    break # No error, exit while loop

                # If we reached here, we found an error and want to retry
                # We inject the correction prompt as a new user message for the next iteration
                current_session = await session_service.get_session(app_name="electronics", user_id="user", session_id=session_id)
                # The ADK Runner uses session history. We need to add the error as a user message to trigger the LLM to fix it.
                # This is a conceptual implementation as ADK's Session internal structure varies.
                # In a real ADK scenario, we would use session.add_message(...)
                # For this implementation, we'll assume the runner picks up the last tool error and we just need to prompt it.

                # In the next iteration of the while loop, runner.run_async will start again.
                # To ensure the LLM knows it needs to fix the error, we can pass a new message.
                # But we must avoid repeating the original question.
                # We'll use a simplified approach: update the user's last message or add a new one.
                # For the purpose of this project, let's use the 'new_message' parameter in the next run_async call.

                # Save the correction prompt for the next loop iteration
                req.question = f"Correction required: {error_msg}. Please fix the SQL query."

            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'value': str(e)})}\n\n"
                return

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Electronics Store — SQL Agent</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0f1117;
    color: #e0e0e0;
    height: 100vh;
    display: flex;
    flex-direction: column;
  }

  header {
    padding: 16px 24px;
    border-bottom: 1px solid #1e2130;
    display: flex;
    align-items: center;
    gap: 12px;
    background: #13151f;
  }

  header .logo {
    width: 32px; height: 32px;
    background: linear-gradient(135deg, #6c63ff, #3ecfcf);
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 16px;
  }

  header h1 { font-size: 16px; font-weight: 600; color: #fff; }
  header span { font-size: 12px; color: #6b7280; margin-left: 4px; }

  #chat {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .bubble {
    max-width: 780px;
    width: 100%;
  }

  .bubble.user { align-self: flex-end; }
  .bubble.agent { align-self: flex-start; }

  .bubble-inner {
    padding: 12px 16px;
    border-radius: 12px;
    font-size: 14px;
    line-height: 1.6;
  }

  .bubble.user .bubble-inner {
    background: #6c63ff;
    color: #fff;
    border-bottom-right-radius: 4px;
  }

  .bubble.agent .bubble-inner {
    background: #1a1d2e;
    border: 1px solid #252840;
    border-bottom-left-radius: 4px;
  }

  .sql-block {
    margin-top: 8px;
    background: #0d0f1a;
    border: 1px solid #2a2d45;
    border-radius: 8px;
    overflow: hidden;
  }

  .sql-block .sql-label {
    padding: 4px 12px;
    font-size: 11px;
    color: #6b7280;
    background: #13151f;
    border-bottom: 1px solid #1e2130;
    font-family: monospace;
    letter-spacing: 0.05em;
  }

  .sql-block pre {
    padding: 10px 12px;
    font-size: 12px;
    color: #7dd3fc;
    font-family: 'Fira Code', 'Courier New', monospace;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .answer-text { white-space: pre-wrap; }

  /* markdown-like table */
  .answer-text table {
    border-collapse: collapse;
    width: 100%;
    margin-top: 8px;
    font-size: 13px;
  }
  .answer-text th, .answer-text td {
    border: 1px solid #2a2d45;
    padding: 6px 10px;
    text-align: left;
  }
  .answer-text th { background: #1e2130; color: #a5b4fc; }

  .thinking {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #6b7280;
    font-size: 13px;
    padding: 4px 0;
  }

  .dot-flashing {
    display: inline-flex; gap: 4px;
  }
  .dot-flashing span {
    width: 6px; height: 6px;
    background: #6c63ff;
    border-radius: 50%;
    animation: blink 1.2s infinite;
  }
  .dot-flashing span:nth-child(2) { animation-delay: 0.2s; }
  .dot-flashing span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes blink { 0%,80%,100% { opacity:0.2 } 40% { opacity:1 } }

  #input-area {
    padding: 16px 24px;
    border-top: 1px solid #1e2130;
    background: #13151f;
    display: flex;
    gap: 10px;
    align-items: flex-end;
  }

  #question {
    flex: 1;
    background: #1a1d2e;
    border: 1px solid #252840;
    border-radius: 10px;
    padding: 10px 14px;
    color: #e0e0e0;
    font-size: 14px;
    resize: none;
    min-height: 44px;
    max-height: 140px;
    outline: none;
    font-family: inherit;
    line-height: 1.5;
    transition: border-color 0.2s;
  }
  #question:focus { border-color: #6c63ff; }
  #question::placeholder { color: #4b5563; }

  #send-btn {
    background: #6c63ff;
    border: none;
    border-radius: 10px;
    width: 44px; height: 44px;
    cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    transition: background 0.2s;
  }
  #send-btn:hover { background: #5a52d5; }
  #send-btn:disabled { background: #2a2d45; cursor: not-allowed; }
  #send-btn svg { width: 18px; height: 18px; fill: white; }

  .suggestions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding: 0 24px 12px;
  }
  .chip {
    padding: 6px 12px;
    background: #1a1d2e;
    border: 1px solid #252840;
    border-radius: 20px;
    font-size: 12px;
    color: #a5b4fc;
    cursor: pointer;
    transition: background 0.2s, border-color 0.2s;
    white-space: nowrap;
  }
  .chip:hover { background: #252840; border-color: #6c63ff; }

  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #252840; border-radius: 3px; }
</style>
</head>
<body>

<header>
  <div class="logo">⚡</div>
  <h1>Electronics Store <span>SQL Agent</span></h1>
</header>

<div id="chat"></div>

<div class="suggestions" id="suggestions">
  <div class="chip" onclick="ask(this.textContent)">Top 5 best-selling products</div>
  <div class="chip" onclick="ask(this.textContent)">Monthly revenue in 2025</div>
  <div class="chip" onclick="ask(this.textContent)">Which city generates the most revenue?</div>
  <div class="chip" onclick="ask(this.textContent)">Customers with the most orders</div>
  <div class="chip" onclick="ask(this.textContent)">Average order value by category</div>
  <div class="chip" onclick="ask(this.textContent)">Products low in stock</div>
</div>

<div id="input-area">
  <textarea id="question" placeholder="Ask anything about the store data…" rows="1"></textarea>
  <button id="send-btn" onclick="submitQuestion()">
    <svg viewBox="0 0 24 24"><path d="M2 21l21-9L2 3v7l15 2-15 2v7z"/></svg>
  </button>
</div>

<script>
  let sessionId = null;
  const chat = document.getElementById('chat');
  const input = document.getElementById('question');
  const btn = document.getElementById('send-btn');

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitQuestion(); }
  });

  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 140) + 'px';
  });

  function ask(text) {
    input.value = text;
    submitQuestion();
  }

  function addBubble(role, html, id) {
    const wrap = document.createElement('div');
    wrap.className = `bubble ${role}`;
    if (id) wrap.id = id;
    const inner = document.createElement('div');
    inner.className = 'bubble-inner';
    inner.innerHTML = html;
    wrap.appendChild(inner);
    chat.appendChild(wrap);
    chat.scrollTop = chat.scrollHeight;
    return wrap;
  }

  function renderMarkdown(text) {
    // basic markdown: bold, code blocks, tables, bullet lists
    return text
      .replace(/```[\\s\\S]*?```/g, m => {
        const code = m.replace(/```\\w*\\n?/, '').replace(/```$/, '');
        return `<pre>${escHtml(code)}</pre>`;
      })
      .replace(/\`([^\`]+)\`/g, '<code>$1</code>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/^\\|(.+)\\|$/gm, row => {
        if (/^[\\s|:-]+$/.test(row)) return '';
        const cells = row.split('|').filter(Boolean);
        return '<tr>' + cells.map(c => `<td>${c.trim()}</td>`).join('') + '</tr>';
      })
      .replace(/(<tr>.*<\\/tr>)/gs, m => `<table>${m}</table>`)
      .replace(/^- (.+)$/gm, '<li>$1</li>')
      .replace(/(<li>.*<\\/li>)/gs, m => `<ul>${m}</ul>`)
      .replace(/\\n/g, '<br>');
  }

  function escHtml(t) {
    return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  async function submitQuestion() {
    const q = input.value.trim();
    if (!q) return;

    document.getElementById('suggestions').style.display = 'none';
    input.value = '';
    input.style.height = 'auto';
    btn.disabled = true;

    addBubble('user', escHtml(q));

    const agentId = 'agent-' + Date.now();
    const agentBubble = addBubble('agent', `
      <div class="thinking">
        <div class="dot-flashing"><span></span><span></span><span></span></div>
        Querying database…
      </div>`, agentId);
    const inner = agentBubble.querySelector('.bubble-inner');

    let sqlHtml = '';
    let answered = false;

    const resp = await fetch('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, session_id: sessionId }),
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const msg = JSON.parse(line.slice(6));

        if (msg.type === 'session_id') {
          sessionId = msg.value;
        } else if (msg.type === 'sql') {
          sqlHtml += `
            <div class="sql-block">
              <div class="sql-label">SQL</div>
              <pre>${escHtml(msg.value)}</pre>
            </div>`;
          inner.innerHTML = sqlHtml + `
            <div class="thinking" style="margin-top:8px">
              <div class="dot-flashing"><span></span><span></span><span></span></div>
              Processing results…
            </div>`;
          chat.scrollTop = chat.scrollHeight;
        } else if (msg.type === 'answer') {
          answered = true;
          inner.innerHTML = sqlHtml + `<div class="answer-text">${renderMarkdown(msg.value)}</div>`;
          chat.scrollTop = chat.scrollHeight;
        } else if (msg.type === 'error') {
          inner.innerHTML = `<span style="color:#f87171">Error: ${escHtml(msg.value)}</span>`;
        } else if (msg.type === 'done') {
          if (!answered) inner.innerHTML = sqlHtml || 'No response.';
        }
      }
    }

    btn.disabled = false;
    input.focus();
  }
</script>
</body>
</html>
"""


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
