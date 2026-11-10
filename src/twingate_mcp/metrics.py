from prometheus_client import Counter, Histogram

TOOL_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 25, 50)

TOOL_CALLS = Counter("twingate_mcp_tool_calls", "MCP tool calls.", ["tool", "outcome"])
TOOL_DURATION = Histogram(
    "twingate_mcp_tool_call_duration_seconds",
    "MCP tool call duration.",
    ["tool"],
    buckets=TOOL_BUCKETS,
)
API_REQUESTS = Counter(
    "twingate_api_requests", "Twingate API requests, after retries.", ["operation", "outcome"]
)
API_DURATION = Histogram(
    "twingate_api_request_duration_seconds",
    "Twingate API request duration, including retries.",
    ["operation"],
    buckets=TOOL_BUCKETS,
)
