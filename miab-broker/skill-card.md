## Description:

Operates the Message-in-a-Bottle (MIAB) LIFO callback stack for async inter-agent delegation, callback routing, wake registration, returns, resolution, and reaping. As of 2.0.0 it also enforces which agent is entitled to act on a bottle, and guards delegation chains against cycles and unbounded depth.

This skill is ready for commercial/non-commercial use.

## Publisher:

[albzhu](https://clawhub.ai/user/albzhu)

### License/Terms of Use:

MIT-0

## Use Case:

Developers and agent operators use this skill to coordinate local multi-agent task delegation without polling. It provides command guidance and scripts for creating, forwarding, returning, resolving, listing, and reaping file-backed callback envelopes.

### Deployment Geography for Use:

Global

## Known Risks and Mitigations:

Risk: 1.3.0 shipped a Discord notifier inside a package that declared no network access, which ClawScan marked suspicious. That script could send callback history off the machine, and it defaulted its delivery target to a Discord channel belonging to the publisher's deployment. An install that ran the notifier without setting CLAW_CLOSED_TARGET therefore sent its own callback summaries — which carry task and result text — to that channel, using its own Discord credentials.

Mitigation: Resolved in 2.0.0. The notifier and its dry-run companion are no longer part of this skill; they moved to the companion `miab-observer` skill (published as `interagent-queue` at the time), which declares that egress explicitly. The hardcoded default is gone: CLAW_CLOSED_TARGET is required and the notifier fails closed when it is unset, so an unconfigured install sends nothing rather than sending somewhere unintended. This package now makes no network calls of any kind, and its `network: []` declaration covers everything in it with nothing scoped out in prose. If you installed 1.3.0 and ran the notifier unconfigured, check what it sent and treat that content as disclosed to a third party. The channel id itself is an identifier rather than a credential — no token, webhook, or account shipped with it — so the exposure is misdirected delivery, not access.

Risk: Callback task, summary, result, and resume fields are written to local state and can be copied into dispatch messages.

Mitigation: Do not place secrets in callback fields; reference non-sensitive locations only when needed. State is written `0600` under a `0700` root, but it is plaintext and is never pruned.

Risk: The broker authorises actions but does not authenticate identity. As of 2.0.0 `--from` is checked against the envelope — `forward` and `return` require the current holder, `resolve` requires the originating agent and an empty stack — but `--from` itself remains an unverified assertion.

Mitigation: Use it only with trusted local agents and keep CLAW_HOME private with restrictive permissions. Every authority check accepts `--force`, which proceeds and records an `authority-override` ledger event naming the actor, the action, and the agent that was entitled to it; review that event type if you rely on the checks.

Risk: Envelopes are unsigned plain JSON with no concurrency locking, so a local process can tamper with a bottle's wake target or resume steps, and concurrent writes to one bottle can corrupt it.

Mitigation: Corruption is detected and quarantined rather than silently skipped, but the data is lost. Treat the callback root as trusted local state and do not share it across untrusted processes. See SECURITY.md for the full enforced/limitations breakdown.

## Reference(s):

- [ClawHub skill page](https://clawhub.ai/albzhu/skills/miab-broker)
- [Publisher profile](https://clawhub.ai/user/albzhu)

## Skill Output:

**Output Type(s):** [guidance, shell commands, configuration, code]

**Output Format:** [Markdown guidance with inline shell commands and JSON command output from bundled scripts]

**Output Parameters:** [1D]

**Other Properties Related to Output:** [Produces local callback state under CLAW_HOME and may emit dispatch messages for agent wake routing. Makes no network calls.]

## Skill Version(s):

2.0.0 (current) — behaviour-breaking: calls that previously succeeded silently are now refused. See CHANGELOG.md "What will now fail" before upgrading.
1.3.0 (published 2026-08-08)

## Ethical Considerations:

Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment.
