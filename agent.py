import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Optional, List
from dotenv import load_dotenv
load_dotenv()

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StdioConnectionParams
from mcp.client.stdio import StdioServerParameters
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

@dataclass
class PipelineContext:
    user_question: str
    sql_query: Optional[str] = None
    sql_results: Any = None
    analysis: Optional[str] = None
    feedback: Optional[str] = None
    final_answer: Optional[str] = None
    metadata: dict = field(default_factory=dict)

class AgentFactory:
    @staticmethod
    def create_agent(role: str, tools: List = None) -> LlmAgent:
        prompts = {
            "schema_specialist": "You are a Schema Specialist. Your goal is 'Schema Pruning'. Analyze the full database schema and the user's question. Output ONLY the definitions of the tables and columns strictly necessary to answer the query. Remove all irrelevant tables to reduce noise.",
            "security_agent": "You are a Security Agent. Analyze the pruned schema and the user's intent. 1. Block access to PII (Personally Identifiable Information) like emails, passwords, or phone numbers. 2. Scan for SQL injection patterns. If a request is unsafe, output 'SECURITY_VIOLATION: [Reason]'. Otherwise, output 'SECURE'.",
            "sql_agent": "You are a SQL Expert. Using the provided pruned and secured schema, generate a precise SQLite query to answer the user's question. Only use SELECT queries. Do not guess data. If the schema is insufficient, state why.",
            "validator_agent": "You are a SQL Validator. Review the generated SQL and the resulting data. Check: 1. Does the SQL logically answer the question? 2. Are the results plausible? Output 'VALIDATED' if correct, or 'INVALID: [Reason]' if it needs correction.",
            "analysis_agent": "You are a Data Analyst. Transform raw SQL results into business insights. Focus on trends, totals, and direct answers to the user's query. Avoid technical jargon; focus on the business meaning of the data.",
            "critic_agent": "You are a Quality Critic. Compare the Analysis Agent's output against the original user question and the raw data. Does it miss any nuance? Is it accurate? Output 'APPROVED' if perfect, or 'REVISE: [Critique]' if changes are needed.",
            "explanation_agent": "You are a Communication Expert. Format the verified analysis into a polished, user-friendly response. Use professional tone, markdown tables for data, and a clear summary for the end-user."
        }

        return LlmAgent(
            model="gemini-2.0-flash-001",
            name=f"electronics_{role}_agent",
            description=f"Specialized agent for {role}",
            instruction=prompts.get(role, "You are a helpful assistant."),
            tools=tools if tools is not None else [],
        )

async def create_toolset():
    toolset = McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="python",
                args=["mcp_server.py"],
            )
        )
    )
    return toolset

class PipelineManager:
    def __init__(self, session_service: InMemorySessionService):
        self.session_service = session_service
        self.toolset = None
        self.tools = None

    async def __aenter__(self):
        self.toolset = await create_toolset()
        self.tools = await self.toolset.get_tools()
        self.schema_agent = AgentFactory.create_agent("schema_specialist")
        self.security_agent = AgentFactory.create_agent("security_agent")
        self.sql_agent = AgentFactory.create_agent("sql_agent", tools=self.tools)
        self.validator_agent = AgentFactory.create_agent("validator_agent")
        self.analysis_agent = AgentFactory.create_agent("analysis_agent")
        self.critic_agent = AgentFactory.create_agent("critic_agent")
        self.explanation_agent = AgentFactory.create_agent("explanation_agent")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def _run_agent(self, agent: LlmAgent, prompt: str, session_id: str, max_retries: int = 4):
        runner = Runner(agent=agent, app_name="electronics-agent", session_service=self.session_service)
        for attempt in range(max_retries):
            try:
                final_text = ""
                async for event in runner.run_async(
                    user_id="user",
                    session_id=session_id,
                    new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
                ):
                    if event.is_final_response() and event.content:
                        for part in event.content.parts:
                            if part.text:
                                final_text += part.text
                return final_text
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait = 60 * (attempt + 1)
                    print(f"Rate limit hit, waiting {wait}s before retry {attempt + 1}/{max_retries}...")
                    await asyncio.sleep(wait)
                    if attempt == max_retries - 1:
                        raise
                else:
                    raise

    async def run(self, question: str):
        session = await self.session_service.create_session(app_name="electronics-agent", user_id="user")
        ctx = PipelineContext(user_question=question)
        sid = session.id

        # 1. Schema Pruning
        # We use a temporary runner to call get_schema via the sql_agent's tools
        full_schema = await self._run_agent(self.sql_agent, "Call get_schema and return the full schema.", sid)
        ctx.metadata["full_schema"] = full_schema
        ctx.metadata["pruned_schema"] = await self._run_agent(self.schema_agent, f"Question: {question}\nSchema: {full_schema}", sid)

        # 2. Security Check
        sec_check = await self._run_agent(self.security_agent, f"Question: {question}\nPruned Schema: {ctx.metadata['pruned_schema']}", sid)
        if "SECURITY_VIOLATION" in sec_check:
            return f"Security Block: {sec_check}"

        # 3. SQL Loop
        max_sql_retries = 3
        for i in range(max_sql_retries):
            prompt = f"Question: {question}\nSchema: {ctx.metadata['pruned_schema']}\nFeedback: {ctx.feedback or 'None'}"
            runner = Runner(agent=self.sql_agent, app_name="electronics-agent", session_service=self.session_service)
            sql_response = ""
            async for event in runner.run_async(user_id="user", session_id=sid, new_message=types.Content(role="user", parts=[types.Part(text=prompt)])):
                if event.is_final_response() and event.content:
                    for part in event.content.parts:
                        if part.text: sql_response += part.text

            ctx.sql_query = sql_response
            # In a production system, we would execute the SQL here to get ctx.sql_results
            # For this implementation, we assume the agent provides the query and the result in its turn.

            val_prompt = f"Question: {question}\nSQL: {ctx.sql_query}\nResults: {ctx.sql_results}"
            validation = await self._run_agent(self.validator_agent, val_prompt, sid)
            if "VALIDATED" in validation:
                break
            ctx.feedback = validation

        # 4. Analysis Loop
        max_analysis_retries = 3
        for i in range(max_analysis_retries):
            analysis_prompt = f"Question: {question}\nResults: {ctx.sql_results}\nCritique: {ctx.feedback or 'None'}"
            ctx.analysis = await self._run_agent(self.analysis_agent, analysis_prompt, sid)

            critic_prompt = f"Question: {question}\nAnalysis: {ctx.analysis}\nResults: {ctx.sql_results}"
            critique = await self._run_agent(self.critic_agent, critic_prompt, sid)
            if "APPROVED" in critique:
                break
            ctx.feedback = critique

        # 5. Explanation
        expl_prompt = f"Question: {question}\nAnalysis: {ctx.analysis}"
        ctx.final_answer = await self._run_agent(self.explanation_agent, expl_prompt, sid)

        return ctx.final_answer

async def run_query(question: str):
    session_service = InMemorySessionService()
    async with PipelineManager(session_service) as manager:
        result = await manager.run(question)
        print(f"\nQ: {question}\n\nFinal Answer:\n{result}")

async def main():
    questions = [
        "What are the top 5 best-selling products by total quantity sold?",
        "Which city generates the most revenue?",
    ]
    for q in questions:
        await run_query(q)

if __name__ == "__main__":
    asyncio.run(main())
