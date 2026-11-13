/**
 * A fake LLM client that replays fixed tool calls and answers.
 * It never calls a provider and is used by the Node tests only.
 */
export class ScriptedModel {
  constructor(steps) {
    this.steps = steps;
    this.calls = [];
  }

  async chat(request) {
    this.calls.push({
      tools: Array.from(request.tools || []),
      messages: Array.from(request.messages || []),
    });
    const step = this.steps[this.calls.length - 1];
    if (step === undefined) {
      throw new Error(`ScriptedModel ran out of steps after ${this.steps.length} replies.`);
    }
    if (step.tool) {
      return {
        content: "",
        toolCalls: [
          {
            id: `call-${this.calls.length}`,
            type: "function",
            function: {
              name: step.tool,
              arguments: JSON.stringify(step.arguments || {}),
            },
          },
        ],
      };
    }
    return { content: step.text, toolCalls: [] };
  }

  toolNames(index) {
    return (this.calls[index]?.tools || []).map((tool) => tool.function.name);
  }

  toolResults(index) {
    const results = [];
    for (const message of this.calls[index]?.messages || []) {
      if (message.role === "tool") results.push(JSON.parse(message.content));
    }
    return results;
  }
}
