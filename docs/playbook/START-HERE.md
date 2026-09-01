# START HERE — Full-Source Playbook v2.2

This package was rebuilt directly from the uploaded **Master Playbook v2.2 DOCX** because the previous Copilot package reduced each chat to a short summary.

## Authority order

1. `00-master/00-UPGRADE-LAYERS-v2.0-v2.2.md`
2. `00-master/01-MASTER-COPILOT-IMPLEMENTATION-BOOTSTRAP.md`
3. Relevant full Chat file(s) under `01-specification/`
4. `00-master/MASTER-PLAYBOOK-v2.2-COMPLETE.md` when cross-checking or resolving ambiguity
5. Approved ADRs/contracts created during implementation

## Important

- The Chat files under `01-specification/` are **full source-derived sections**, not summaries.
- Do not load all 13 chats into one coding prompt. Read the constitution/bootstrap first, then only the chat(s) relevant to the current issue.
- If a generated implementation artifact conflicts with the full source, the full source wins.
- Preserve the 13-chat structure. Do not create Chat 14.
- Do not simplify features merely to reduce implementation effort.

## Recommended first implementation action

Perform repository discovery only. Do not write application code until the repository discovery report is reviewed by the human owner.
