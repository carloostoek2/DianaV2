# DianaV2 Changelog

Highlights of what's new and fixed in Diana, from her early releases through the latest agent-evolution work.

## Agent Evolution (Shadow) — 2026-08-07

*Observation-only: this new layer runs in shadow mode, so it measures how Diana would act without changing her live responses yet.*

### ✨ New Features
- **Shadow agent-evolution engine**: a complete observational layer now watches how Diana handles each conversation — emotional signals, turn-by-turn self-assessment, mood, and per-VIP trust — and records it all for analysis.
- **Emotional signal detection**: Diana now spots emotional cues in incoming messages with a lightweight local heuristic (no external AI calls).
- **Automatic profile refresh**: when a VIP's conversation shows strong signals, Diana can now trigger a profile synthesis on her own, keeping VIP profiles current without a manual action.
- **Turn-by-turn self-classification**: for every turn, Diana records how she would have handled it autonomously and her confidence in that call.
- **Three-axis mood engine**: Diana now tracks her emotional tone across conversations to keep her delivery consistent.
- **Trust budget per VIP**: Diana keeps a running trust score per VIP based on how consistently she handles their conversations, with configurable thresholds and a status card.
- **Correction events**: behavior that needs recalibration is captured as a structured correction event in the trust system.
- **Automatic data housekeeping**: agent-evolution records are purged automatically on a schedule (TTL) so the system stays bounded.

### 🔧 Improvements
- **Hardened shadow layer**: several review rounds fixed event-hook safety, deterministic behavior, database-write guards, and in-flight-turn handling.
- **Live tuning**: shadow behavior can be overridden at runtime per environment without redeploys.
- **Sensitive-content priority**: the classifier weighs sensitive or personal content first when assessing a turn.

## ✨ New Features
- **Automatic memory**: Diana now saves relevant details from conversations (preferences, dates, topics) and recalls them later, without being asked.
- **VIP profiles**: Diana builds a profile for each VIP from their chat history and a dedicated profile action, so preferences stay up to date across the whole bot.
- **Attention channel for non-VIP chats**: a dedicated flow for non-VIP conversations, including a real escalation path where unresolved questions reach the owner with a resolution workflow.
- **VIP freeze and pause**: freeze or unfreeze a VIP (1 day, 1 week, or indefinitely), with reminders when a frozen VIP keeps writing.
- **Redesigned menu**: the VIP profile now offers direct actions, a sandbox activation wizard, back buttons, in-place edits, and registering a VIP simply by forwarding their message.
- **Owner review queue (staging)**: Diana's example replies can be staged and approved or discarded by the owner before they are used.
- **Owner dashboard**: weekly summary and metrics commands (`/resumen`, `/metricas`) with trend tracking, plus a way to flag wrong answers for recalibration.
- **Traceability**: the owner can inspect, step by step, how Diana reasoned through a conversation and how long each step took.
- **Re-engagement for non-VIPs**: when a non-VIP asks for more information, Diana opens a 30-day attention cycle and can schedule follow-up messages.
- **Autonomous follow-ups**: after an initial reply, Diana can send follow-up messages on her own, with natural pacing instead of a single immediate answer.
- **Handles edited messages**: if a VIP edits their message, Diana aborts the in-flight work and restarts with the corrected text.
- **Resilient recovery**: after a restart, Diana picks up missed messages and unfinished turns so nothing is lost.
- **Owner sandbox**: test Diana's behavior in a safe sandbox before enabling real delivery.

## 🔧 Improvements
- **Faster history**: long conversations now load quickly and reliably, even with many messages.
- **More human delivery**: replies are paced with natural delays and typing, varying by mode (supervised vs. autonomous) to match Diana's original cadence.
- **More natural Spanish voice**: Diana now uses neutral Spanish consistently, with an emotion-sensitive tone and no dialect-locked or slang-heavy phrasing.
- **Better conversation flow**: bursts of messages are grouped instead of answered one by one, and repeated questions are recognized and handled better.

## 🐛 Fixes
- Fixed memory summaries repeating old facts instead of showing the most recent ones.
- Fixed history pagination errors in long conversations.
- Fixed a crash when saving a memory without text (the error no longer exposes the raw message).
- Fixed timezone and day-boundary issues so Diana's daily behavior aligns with the Mexico City day.
- Fixed message-loss gaps during recovery after restarts.
- Fixed orphaned approvals and stale timers that could block a VIP's turn.
- Corrected several Spanish accent and wording issues in the interface.

## 🔒 Security
- **Personal data protection**: memory errors and logs no longer expose raw message content; stored facts are kept out of logs with an explicit data disclaimer.
- **Input hardening**: incoming messages are sanitized so they cannot break out of Diana's prompts.
- **Admin access control**: owner-only gates on all admin surfaces, and attention-channel access fails closed on errors.

## ⚠️ Breaking Changes
- The attention channel is now live only for chats that received the promo and stays open for a 30-day cycle (payment closes it). Chats without the promo are not admitted.
