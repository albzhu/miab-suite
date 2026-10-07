## Description: <br>
Monitor and log MIAB transaction ledger events to a file. Requires miab-broker as a prerequisite. <br>

This skill is ready for commercial/non-commercial use. <br>

## Publisher: <br>
[albzhu](https://clawhub.ai/user/albzhu) <br>

### License/Terms of Use: <br>
MIT-0 <br>


## Use Case: <br>
Developers and agent operators use this skill to observe MIAB callback ledger activity, inspect queue status, and record human-readable transaction events to a local log. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: Local logs may preserve MIAB task and result details on disk. <br>
Mitigation: Keep secrets out of ledger task and result text, review the configured log path, and rotate or delete logs that may contain sensitive work details. <br>
Risk: The optional message sink sends closed-bottle summaries to a chat target, so the bottle id, task, result, reason, agent and model names and per-hop history leave the machine. None of it is redacted. <br>
Mitigation: The message sink is opt-in and cron-driven; the default log sink makes no network calls. Delivery fails closed unless CLAW_CLOSED_TARGET is explicitly set, and there is no default target. Ledger text is cleaned before it is posted (mentions and masked links are neutralised, control characters removed, every field and the whole message length-capped), but nothing is redacted, so keep secrets out of ledger task, result and reason text, review the configured target before enabling it, and run notify_closed_dryrun.py first to see exactly what would be sent. <br>
Risk: The message sink keeps a cursor over the ledger, and a lost or damaged cursor could re-post closed-bottle history to the chat target. <br>
Mitigation: A missing state file starts at the end of the ledger and posts nothing. A state file that exists but cannot be used, or a truncated ledger, makes the notifier exit 1 and deliver nothing instead of re-posting; a rotated ledger is recognised by a fingerprint and followed. <br>
Risk: The observer depends on miab-broker state and configurable filesystem paths. <br>
Mitigation: Verify miab-broker 2.0.0 or later is installed and initialized, then check CLAW_HOME, CLAW_LEDGER, CLAW_QUEUE_LOG, CLAW_QUEUE_STATE, CLAW_REGISTRY, LYRA_WORKSPACE, CLAW_CLOSED_TARGET, CLAW_CLOSED_STATE, and CLAW_CLOSED_ACCOUNT before enabling logging. <br>


## Reference(s): <br>
- [ClawHub skill page](https://clawhub.ai/albzhu/skills/miab-observer) <br>
- [Previous listing, published as `interagent-queue` through 1.3.0](https://clawhub.ai/albzhu/skills/interagent-queue) <br>


## Skill Output: <br>
**Output Type(s):** [Text, JSON, Shell commands, Configuration, Files] <br>
**Output Format:** [Markdown guidance with bash commands; script output is JSON status data and plain-text log entries.] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [Writes queue state and log files under configurable CLAW_* paths and requires an existing miab-broker ledger. The optional message sink also delivers unredacted closed-bottle summaries (neutralised for chat mentions and length-capped) to a chat target via `openclaw message send`.] <br>

## Skill Version(s): <br>
2.0.1 (current — message-sink hardening: fail-closed state, first run posts nothing, mention neutralisation) <br>
2.0.0 (renamed from `interagent-queue`) <br>
1.3.0 (published 2026-08-28 as `interagent-queue`; final under that name) <br>
1.2.0 (published 2026-07-22) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
