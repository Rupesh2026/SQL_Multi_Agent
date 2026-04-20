# 🤖 SQL Agent: Natural Language to SQL Interface

An intelligent agent that allows users to interact with an electronics store database using natural language. It leverages a Large Language Model (LLM) to translate user queries into optimized SQL, executes them, and returns human-readable results.

## 🌟 Features

- **Natural Language Processing**: Ask questions in plain English (e.g., "Which products are in stock and cost less than $500?").
- **Dynamic SQL Generation**: Automatically generates accurate SQL queries based on the database schema.
- **MCP Server Integration**: Built with Model Context Protocol (MCP) for seamless tool integration.
- **Interactive Frontend**: A clean web interface to query the database and view results instantly.
- **Pre-configured Dataset**: Comes with an electronics store database for immediate testing.

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- A valid LLM API Key (e.g., Anthropic or OpenAI)

### Installation
1. **Clone the repository**:
   ```bash
   git clone https://github.com/Rupesh2026/SQL_Agent.git
   cd SQL_Agent
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

- **`agent.py`**: The core logic that handles LLM orchestration and SQL translation.
- **`server.py`**: The backend server managing API requests and database connections.
- **`mcp_server.py`**: Implements the Model Context Protocol for tool-calling capabilities.
- **`setup_db.py`**: Script to initialize the SQLite database with sample data.
- **`index.html`**: The user interface for interacting with the agent.

## 📁 Project Structure

```text
├── agent.py            # Core Agent logic
├── server.py           # Backend Server
├── mcp_server.py      # MCP Tool Server
├── setup_db.py        # Database initialization
├── electronics_store.db # SQLite Database
├── index.html         # Frontend UI
├── .env               # Configuration (ignored by git)
└── .gitignore         # Git ignore rules
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📜 License

MIT License
