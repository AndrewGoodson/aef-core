"use strict";

const nodes = {
  retrieve: ["CONTEXT", "Bring relevant context into the run.", "The memory-backed retriever supplies context through injected services. Retrieved lessons remain fallible evidence; they cannot grant permissions or override the owner's instructions."],
  prompt: ["REASONING", "Give reasoning an explicit boundary.", "The prompt-agent node calls the configured provider and is declared nondeterministic. Native persona settings are reported, not automatically obeyed. Tools and containment still require explicit target wiring and verification."],
  reflect: ["FEEDBACK", "Inspect the outcome before keeping advice.", "Rule-based reflection is implemented. Optional LLM-backed reflection is off by default and has not shown task gains in existing trials. A critique is evidence to evaluate, not proof that the next answer will improve."],
  consolidate: ["KNOWLEDGE", "Make useful context available for later work.", "The consolidation node updates knowledge through injected services. It does not train model weights or create a knowledge graph. Persistent storage and cross-run reuse depend on the target's service configuration."]
};

document.querySelectorAll("[data-node]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-node]").forEach((item) => {
      const active = item === button;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    const [tag, title, description] = nodes[button.dataset.node];
    document.getElementById("node-tag").textContent = tag;
    document.getElementById("node-title").textContent = title;
    document.getElementById("node-description").textContent = description;
  });
});

const target = document.getElementById("target");
const harness = document.getElementById("harness");
const command = document.getElementById("command");
const status = document.getElementById("command-status");
const copy = document.getElementById("copy");

function updateCommand() {
  const path = target.value;
  // Native skill invocation, not a shell command. Reject ambiguous quoting
  // and control characters rather than promising parser-specific escaping.
  const valid = path.startsWith("/") && !/^\/+$/.test(path) && !/[\x00-\x1f\x7f"\\]/.test(path);
  target.setAttribute("aria-invalid", String(!valid));
  copy.disabled = !valid;
  command.textContent = valid ? `${harness.value === "codex" ? "$" : "/"}target-repo "${path}"` : "Enter an absolute directory to preview the command.";
  status.textContent = valid ? "Run in a coding-agent session opened in your AEF checkout." : "Use an absolute directory other than /. This preview does not support quotes, backslashes or control characters.";
}
target.addEventListener("input", updateCommand);
harness.addEventListener("change", updateCommand);
copy.addEventListener("click", async () => {
  const copiedCommand = command.textContent;
  try {
    await navigator.clipboard.writeText(copiedCommand);
    if (command.textContent === copiedCommand) status.textContent = "Copied. Paste into your coding agent, not a shell.";
  } catch {
    if (command.textContent === copiedCommand) status.textContent = "Clipboard unavailable. Select and copy the command above.";
  }
});
updateCommand();
