To build CLI tools that AI agents can use reliably and efficiently, follow these concise, actionable guidelines:

### 1. Standardize Input and Interaction
*   **Prioritize Flags over Arguments:** Use explicit flags (e.g., `--from source --to dest`) instead of positional arguments to ensure clarity and allow agents to provide input in any order.
*   **Eliminate Interactive Prompts:** Agents cannot answer prompts or navigate pagers. Implement `--yes`, `--no-confirm`, or `--force` flags to bypass confirmation steps.
*   **Support Environment Variables:** Use stable environment variables for global context (e.g., `NO_COLOR=true`) and document them in the `--help` section.

### 2. Ensure Machine-Readable Output
*   **JSON is Non-Negotiable:** Provide a `--json` flag for all commands to prevent silent parsing failures caused by changing table widths or text formatting.
*   **Separate Stdout and Stderr:** Emit only your "API contract" (structured data) to `stdout`; send all progress messages, warnings, and spinners to `stderr`.
*   **Maintain Schema Stability:** Treat structured output as a versioned API contract; breaking changes to field names or types can disrupt all downstream agent automation.

### 3. Design for Robust Execution
*   **Enforce Idempotency:** Ensure commands are safe to retry (e.g., a "create" command should not fail if the resource already exists) to prevent duplicate side effects during agent retries.
*   **Use Semantic Exit Codes:** Use specific, documented exit codes (e.g., 0 for success, distinct codes for "already exists" or "unauthorized") so agents can programmatically decide their next action.
*   **Provide Dry-Run Capabilities:** Include a `--dry-run` flag that outputs a structured "diff" of planned changes to allow agents to preview destructive actions before commitment.

### 4. Optimize for Agent Discovery
*   **Help Text is the Manual:** Agents rely on `--help` to understand your tool; keep it comprehensive, include realistic usage examples, and clearly mark required vs. optional flags.
*   **Narrow Tool Scope:** Follow the "One Concern Per Tool" principle; split monolithic tools into atomic, single-purpose operations (e.g., `copy_file`, `move_file`) to reduce ambiguity.
*   **Follow Noun-Verb Grammar:** Use hierarchical command structures (e.g., `docker container ls`) to allow agents to explore capabilities via deterministic tree searches in the help output.

### 5. Security and Governance
*   **Apply Least Privilege:** Ensure CLI tools require only the minimum necessary permissions for their task to limit the blast radius of potential agent errors.
*   **Isolate Auth from the Model:** Never expose raw credentials or login flows to the AI; handle authentication via secure backend logic or managed SSO platforms.