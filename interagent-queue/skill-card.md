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
Risk: The observer depends on miab-broker state and configurable filesystem paths. <br>
Mitigation: Verify miab-broker 2.0.0 or later is installed and initialized, then check CLAW_HOME, CLAW_LEDGER, CLAW_QUEUE_LOG, CLAW_QUEUE_STATE, CLAW_REGISTRY, and LYRA_WORKSPACE before enabling logging. <br>


## Reference(s): <br>
- [ClawHub skill page](https://clawhub.ai/albzhu/skills/interagent-queue) <br>


## Skill Output: <br>
**Output Type(s):** [Text, JSON, Shell commands, Configuration, Files] <br>
**Output Format:** [Markdown guidance with bash commands; script output is JSON status data and plain-text log entries.] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [Writes queue state and log files under configurable CLAW_* paths and requires an existing miab-broker ledger.] <br>

## Skill Version(s): <br>
1.3.0 (current) <br>
1.2.0 (published 2026-07-22) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
