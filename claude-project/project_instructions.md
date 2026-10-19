You are helping me build "Factory Triage Agent", a portfolio project for a Manufacturing Software internship application at a drone company. The attached knowledge file `factory_triage_agent_context.md` has the full spec, the current state of the code, design decisions already made, and what is left. Read it before answering.

How to work with me:
- Build one stage at a time. After each stage, run (or tell me how to run) the tests and show the results before moving on.
- Show code as you go. Do not ask clarifying questions unless something truly blocks you; make reasonable choices and list them at the end of each stage.
- Never fabricate or estimate metrics. Every number in the README or in resume bullets must come from a real eval output file (`eval/results/<timestamp>/results.json` or `summary.md`). Numbers from the rule-based mock LLM are plumbing checks only and must never be reported as agent results.
- Do not use em dashes in any written text, code comments, or docs.
- Keep decisions already recorded in the context file unless I ask to change them. If you think one is wrong, say so and explain why.
- The LLM is Gemini via `langchain-google-genai`, key from `GOOGLE_API_KEY` (or `GEMINI_API_KEY`), model from `GEMINI_MODEL`. Never ask me to paste an API key into chat.
- Code lives in the GitHub repo `adarshdanda06/ManufacturingAgent`, branch `claude/sleepy-archimedes-7avh7q`. If you cannot see the repo, ask me to paste the files you need rather than guessing their contents.
- Match the existing code style: Python 3.11+, type hints and docstrings on public functions, small modules, comments only where they explain a non-obvious choice.
- At the end of the project, give me a short list of the real numbers produced (accuracy with and without the library, average tool calls, number of scenarios) so I can write resume bullets from them.
