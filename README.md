# 🤖 SQL Agent: Natural Language to SQL Interface

An intelligent agent that allows users to interact with an electronics store database using natural language. It leverages a Large Language Model (LLM) to translate user queries into optimized SQL, executes them, and returns human-readable results.

## 🌟 Features

- **Natural Language Processing**: Ask questions in plain English (e.g., "Which products are in stock and cost less than $500?").
- **Dynamic SQL Generation**: Automatically generates accurate SQL queries based on the database schema.
- **MCP Server Integration**: Built with Model Context Protocol (MCP) for seamless tool integration.
- **ChatGPT-style Interactive Frontend**: A clean, modern light-themed web interface to query the database and view results instantly.
- **Self-Healing Queries**: Automatically detects SQL errors and prompts the agent to correct the query before presenting the final answer.
- **Pre-configured Dataset**: Comes with an electronics store database for immediate testing.

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- A valid LLM API Key (e.g., Anthropic or OpenAI)

### Installation
1. **Clone the repository**:
   ```bash
   git clone https://github.com/Rupesh2026/SQL_Multi_Agent.git
   cd SQL_Multi_Agent
   ```

2. **Set up a virtual environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**:
   Create a `.env` file in the root directory:
   ```env
   API_KEY=your_api_key_here
   # Add other necessary environment variables here
   ```

5. **Initialize the Database**:
   ```bash
   python setup_db.py
   ```

6. **Run the Server**:
   ```bash
   python server.py
   ```
   Open `index.html` in your browser or navigate to the local server address.

## 🛠️ Architecture

- **`agent.py`**: The core logic that handles LLM orchestration and SQL translation. It implements a high-reliability multi-agent pipeline:
    1. **Schema Specialist**: Prunes the full schema to only include relevant tables (reducing noise/token usage).
    2. **Security Agent**: Scans for PII leaks and SQL injection patterns.
    3. **SQL Agent**: Generates the optimized SQLite query.
    4. **Validator Agent**: Reviews the query and results for logical correctness.
    5. **Analysis Agent**: Converts raw data into business insights.
    6. **Critic Agent**: Ensures the analysis accurately answers the original user question.
    7. **Explanation Agent**: Formats the final answer into a polished, user-friendly response.

- **`server.py`**: The backend server managing API requests, session state, and the embedded ChatGPT-like frontend.
- **`mcp_server.py`**: Implements the Model Context Protocol for tool-calling capabilities (run_sql, get_schema).
- **`setup_db.py`**: Script to initialize the SQLite database with sample data.
- **`index.html`**: The user interface for interacting with the agent.

## 📁 Project Structure

```text
├── agent.py            # Core Agent logic and Multi-Agent Pipeline
├── server.py           # Backend Server and Embedded UI
├── mcp_server.py      # MCP Tool Server
├── setup_db.py        # Database initialization
├── electronics_store.db # SQLite Database
├── index.html         # Frontend UI
├── .env               # Configuration (ignored by git)
└── .gitignore         # Git ignore rules
```

## 🤝 Contributing

Contributions are welcome! Please submit a Pull Request.

## 📜 License

MIT License
