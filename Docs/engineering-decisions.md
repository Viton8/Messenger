# Engineering decisions

Record important behavior here when it changes: limits, privacy, account rules, and how chat decides what a member is allowed to do. Write in English. Keep each note short enough that the next change can update it in the same commit.

## Account email

New accounts stay inactive until the person opens the confirmation link. Sign-in does not say whether the username exists, the password is wrong, or the account is still inactive. The message is always "Incorrect username or password."

`ACCOUNT_EMAIL_CONFIRMATION_REQUIRED` defaults to true. Set it to false only for local testing: registration then creates an active account, sends no mail, and signs the person in. If `DEBUG` is false and the switch is false, Django refuses to start and `manage.py check` reports `accounts.E001`.

Until SMTP is configured, mail is printed in the `web` container logs (`EMAIL_BACKEND` defaults to the console backend). Real delivery needs `EMAIL_HOST` and `django.core.mail.backends.smtp.EmailBackend`.

Password reset and confirmation links expire after Django's `PASSWORD_RESET_TIMEOUT` (three days). A confirmation link stops working once the account is activated. Password reset mail is sent only to active accounts. Someone who has not confirmed yet uses the confirmation link, or the resend form. The resend answer is the same whether or not an account is waiting.

## Email request limit

Registration, the confirmation resend form, password reset, and the profile change-password button share one limit: `ACCOUNT_EMAIL_RATE_LIMIT` attempts per `ACCOUNT_EMAIL_RATE_WINDOW` seconds (defaults: 5 per hour). The same numbers apply to API registration, because it sends the same confirmation mail.

Each attempt counts against the caller IP (`REMOTE_ADDR`) and, when an address was submitted, against that address. The attempt is counted even when no account exists, so a rate-limit response does not reveal who is registered. A blocked call does not send mail and, for registration, does not create the account. The message is "Too many attempts. Try again later."

`X-Forwarded-For` is not trusted. A client can forge it. Behind a reverse proxy, the limit must be taught the real client address before it is useful.

The counters live in Redis (`REDIS_URL`, database 1, separate from Channels). If the cache cannot be reached, the request is allowed and a warning is logged, so a cache outage does not lock everyone out. Tests use a local memory cache and a high limit so the suite does not trip the cap.

## Passwords and usernames

Passwords are hashed by Django. They are never written to logs. New passwords must pass `AUTH_PASSWORD_VALIDATORS` and be at most 128 characters. The registration page shows those rules and does not block paste.

Usernames for new accounts are 3–30 characters and may contain only letters, digits, and underscore. Uniqueness ignores case (`accounts_user_username_ci`). Spaces, control characters, HTML markers, and web addresses are rejected. Reserved names such as `admin` and `support` cannot be registered; underscores do not bypass that (`Ad_min` is still reserved). Accounts created before these rules, including the existing `admin` user, keep their names and can still sign in.

Email addresses are stored in lower case and are unique. Older rows may have no email. Those accounts can sign in with a username, but password reset has nowhere to send mail until an address is set.

## Profile account changes

Changing an email on the profile requires the current password. The new address is stored immediately and is not confirmed by a second link.

Changing a password from the profile does not ask for the current password. The button emails the same reset link as the public password-reset form, to the address already stored on the account. The new password is chosen on that link. An account with no email cannot start this until an address is added. The request uses the shared email limit, and a blocked request does not send mail.

## Direct chat list and read mark

The chat list is every chat the signed-in user belongs to. Direct messages are their own folder. Group chats are listed under Group. The default order is newest message first. A chat with no messages sorts after those. The list can also be limited to unread chats, searched by chat name or another participant's username, or sorted by unread count or name. That search does not look inside message text.

`ChatParticipant.last_read_at` is how far that member has read. A message from someone else is unread when that mark is empty, or when the message is newer than the mark. The reader's own lines are never unread. The mark moves forward through `POST /api/chat/chats/<id>/read/` with the newest message the reader is caught up to. It does not move backward, it is not shown to the other person, and it does not record each message separately. The room moves it only while the reader is at the bottom of the open history. A text search inside a chat does not move the mark.

Username suggestions are `GET /api/chat/users/?q=`. The caller must be signed in. The query must be 2 to 150 characters. The response is at most eight active usernames that start with that text, plus initials and an avatar URL when one is stored. Email is not searched or returned. A direct chat still cannot be opened with yourself or an inactive account. Sending in a direct chat still stops when the other person has blocked the sender (`assert_can_send_message`). Group chats do not apply that block.

A signed-in member can open `/accounts/players/<username>/`. That page shows the username and avatar. It does not show email or password controls. Inactive accounts are not found. The Message button there opens or reuses the direct chat.

History is paged at 40 lines, and never more than 50. Older lines load with `before` set to a message id. `q` on the message list keeps lines whose text contains that string, at most 80 characters, and only for a member of that chat. A direct message saved over HTTP is published on the chat channel. A failed publish is logged and does not delete the saved line. This does not change who is allowed to post.

## Chat permissions

The browser is not trusted to decide who may read or post. HTTP and WebSocket handlers check that the caller is signed in and is a `ChatParticipant` of that chat. Anonymous sockets are closed. A non-member is refused.

`assert_can_send_message` in `chat/services.py` is the send rule. Direct chats refuse a post when the counterpart has blocked the sender (`accounts.Block`). Group chats ignore pairwise blocks. Membership is still required. This does not hide history already stored, and it does not implement moderation beyond that membership and block check.

A chat-room WebSocket is accepted only for the signed-in user, and only if that user is still a participant. There is no separate anti-abuse layer beyond those server checks.

## Group membership and roles

Group chats are `Chat.is_group`. Roles are `owner`, `admin`, and `member`. Checks live in `chat/group_services.py` and are applied by `/api/chat/groups/` and the group template views. Any member may read the group, list members, leave, and edit or delete their own user messages. Admin and owner may change name and description, add a member by username, remove a `member`, and create or revoke the invite token. Only the owner may set `member` ↔ `admin`. The owner cannot be removed and cannot be demoted through the role API. An admin cannot remove another admin or the owner.

When the owner leaves, the next owner is the earliest remaining admin (`joined_at`, then `id`), otherwise the earliest remaining member, in the same transaction. If no one is left, the `Chat` row is deleted (messages and participants cascade). `GROUP_MAX_MEMBERS` (default 50) is checked on add and join; a full group returns 400. This does not implement a ban list, multiple owners, or transferring ownership without leaving.

After a kick or leave, the next WebSocket `receive` on `ws/chat/<id>/` checks membership again and closes the socket when the `ChatParticipant` row is gone.

## Group invites and add rate

An invite is `Chat.invite_token` (`secrets.token_urlsafe(32)`). Admin or owner may rotate it (`POST /api/chat/groups/<id>/invite/`) or set it to null (`DELETE`). Join is `POST /api/chat/groups/join/` with `{token}` or the session form at `/chat/join/<token>/`. A revoked or unknown token is refused. Pairwise `accounts.Block` applies only to add: if the target has blocked the actor, add is 403. Join by token is a self-invite and does not consult that block. An existing blocker who is already a member stays. Inactive accounts are not added.

Add and join share `GROUP_MEMBER_RATE_LIMIT` per `GROUP_MEMBER_RATE_WINDOW` (defaults 20 per hour) but use separate cache keys per acting user (`add` vs `join`). The attempt is counted only after a successful add or join, matching the email limiter: a rights failure or a full group is not counted. The message is "Too many attempts. Try again later." Cache failures fail open and log a warning. Tests use a high limit.

## Message edit and delete

A member may `PATCH` or `DELETE` `/api/chat/chats/<id>/messages/<id>/` for their own user message. In a group, admin or owner may also delete another member's user line. The row is kept: `deleted_at` is set, clients receive the placeholder "Message deleted", and search does not match the original text. Edit sets `edited_at` and uses the same 1–10000 character body rule as create. System and board lines cannot be edited or deleted through this API. There is no time window. Edit and delete go through HTTP only; open rooms are updated with Channels events `message_updated` and `message_deleted`.

## Board metadata

Boards exist only on group chats (`Chat.is_group`). Any member may create a board and list boards (`POST`/`GET /api/chat/groups/<id>/boards/`). The creator (while still a member) or an admin/owner may rename or delete a board. Only admin/owner may set `is_locked`. Checks live in `boards/services.py`. Creating a board also stores a `Message` with `kind=board` and fans it out on the chat channel. Deleting the board row sets that card's `deleted_at`; clients see "Board deleted" and the `board` FK is cleared (`SET_NULL`). `BOARDS_MAX_PER_GROUP` (default 20) is enforced on create; a full group returns 400.

`seq` increases by one for each accepted ops WebSocket message on `ws/boards/<id>/`. A locked board (`is_locked`) refuses ops from anyone who is not admin or owner; init, presence, cursors, and transient frames still go through. There are no boards on direct chats.

## Board sync protocol

The drawing lives in `BoardObject` rows. The browser is not trusted: `boards/protocol.py` keeps a type whitelist (`rect`, `ellipse`, `line`, `path`, `textbox`, `arrow`, `sticker`) and drops unknown properties. Unknown types reject the whole ops message. There are no images or URLs. Path `points` are capped at 500; text at 2000 characters; numbers have fixed ranges. `fill`/`stroke` are `#RGB`, `#RRGGBB`, or `transparent`. Font families are a short list.

`BoardConsumer` accepts only a signed-in member of the board's group (close 4401 / 4403). Connect sends `{type: init, seq, objects, users}`. An ops message is applied in one transaction: `select_for_update` on `Board`, last-write-wins **per field** on patch, then `seq += 1` once. The fan-out `{type: ops, seq, user, ops, client_op_id}` includes the sender (that is the ack). Cursor and transient frames are not stored.

Limits (settings): 2000 live objects per board, 256 KiB per WebSocket frame, 30 ops messages per second per socket, 20 cursor and 20 transient messages per second per socket. Excess ops are an error and do not change `seq`. Removing a member or deleting the board sends `board_force_close` so sockets drop immediately, not on the next receive.

This does not implement OT/CRDT, server-side undo, or more than one seq bump per ops frame.

## Board editor

`/boards/<id>/` runs a local Fabric.js 7 editor (vendored ESM in `boards/static/boards/vendor/`, no CDN). Object JSON is built only through `serialize.js` against the same whitelist as `boards/protocol.py`. The in-memory `store.js` applies `add` / `patch` / `remove` / `z` so a later sync client can reuse the ops. Undo/redo is per tab.

The page sets `data-read-only="true"` when the board is locked and the viewer is not admin/owner (`boards/views.py`). The editor then disables selection and drawing; pan and zoom still work. The server still enforces the lock on ops. This does not open `ws/boards/<id>/`, load `BoardObject` rows, show remote cursors, or save the canvas.

## What this file is for

Add a short section when a change introduces or alters a limit, a privacy choice, an authentication rule, or a server-side chat rule. Do not paste implementation tours. State the rule, where it is enforced, and what it deliberately does not do.
