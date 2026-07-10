---
name: schedule-meeting
description: Schedule meetings, calls, or events on the calendar. Use when the user wants to book, plan, schedule, or set up a meeting or appointment with someone at a time.
---

## How to schedule well

1. Resolve relative dates ("next Tuesday", "tomorrow morning") into ISO 8601
   using today's date from the system prompt. Morning = 09:00, afternoon =
   14:00, evening = 18:00 unless the user says otherwise.
2. Check memory context for the attendee's preferences (e.g. "prefers morning
   meetings") and apply them — mention it when you do ("since Alex prefers
   mornings, I booked 9am").
3. Call `create_event` with a short, specific title: "Coffee with Alex", not
   "Meeting".
4. If the user mentioned an agenda or context, put it in `notes`.
5. After creating, confirm in one sentence: what, when, with whom.

## Edge cases

| Situation | Do |
|---|---|
| No time given | Ask one clarifying question, don't guess a day |
| Past date requested | Point it out, suggest the next occurrence |
| Attendee unknown to memory | Schedule anyway; offer to `save_note` who they are |
