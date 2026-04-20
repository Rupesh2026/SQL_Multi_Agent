import asyncio
from dotenv import load_dotenv
load_dotenv()

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StdioConnectionParams
from mcp.client.stdio import StdioServerParameters
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


SYSTEM_PROMPT = """You are a helpful data analyst for an electronics store.
Answer questions by querying the database using the available tools.
Always run get_schema first if you are unsure about table structure.
Present results in a clear, concise way — use tables or bullet points where helpful.
Only use SELECT queries. Never guess data; always query for it.

If a SQL tool returns an error, analyze the error message carefully.
Use `get_schema` to verify column names and table structures before attempting to fix the query.
Do not repeat the same mistake; try a different approach if your previous attempt failed."""


async def create_agent():
    toolset = McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="python",
                args=["mcp_server.py"],
            )
        )
    )
    # Fixed: get_tools() is an async function, must be awaited
    tools = await toolset.get_tools()

    agent = LlmAgent(
        model="gemini-2.0-flash-lite",
        name="electronics_sql_agent",
        description="Text-to-SQL agent for the electronics store database",
        instruction=SYSTEM_PROMPT,
        tools=tools,
    )
    return agent, toolset


async def run_query(question: str):
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="electronics-agent",
        user_id="user",
    )

    agent, toolset = await create_agent()

    runner = Runner(
        agent=agent,
        app_name="electronics-agent",
        session_service=session_service,
    )

    print(f"\nQ: {question}")
    print("-" * 60)

    retry_count = 0
    max_retries = 3
    current_question = question

    while retry_count <= max_retries:
        error_found = False
        async for event in runner.run_async(
            user_id="user",
            session_id=session.id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=current_question)],
            ) if retry_count == 0 else None,
        ):
            if hasattr(event, 'content') and event.content:
                for part in event.content.parts:
                    if part.text and ("SQL Error:" in part.text or "SQL Syntax Error:" in part.text):
                        error_msg = part.text
                        retry_count += 1
                        if retry_count <= max_retries:
                            print(f"⚠️ SQL Error detected. Self-healing... (Attempt {retry_count}/{max_retries})")
                            current_question = f"The previous query failed with error: {error_msg}. Please analyze the schema and correct the query."
                            error_found = True
                            break

            if event.is_final_response() and event.content:
                for part in event.content.parts:
                    if part.text:
                        print(part.text)
                return

        if not error_found:
            break

    print("\n❌ Failed to resolve SQL error after maximum retries.")


async def main():
    questions = [
        "What are the top 5 best-selling products by total quantity sold?",
        "Which city generates the most revenue?",
        "Show monthly revenue trend for 2025.",
        "Which customers have placed more than 3 orders?",
        "What is the average order value per product category?",
    ]
    for q in questions:
        await run_query(q)


if __name__ == "__main__":
    asyncio.run(main())
