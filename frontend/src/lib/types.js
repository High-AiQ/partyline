/**
 * The shapes the server sends, written down once.
 *
 * These mirror the rows in `partyline/db.py` and the payloads in
 * `partyline/server.py`. They are JSDoc rather than TypeScript because this is
 * a JavaScript codebase, but they type-check the same and — more usefully —
 * they are the one place to read what a conversation or an attachment actually
 * contains without going and reading the Python.
 *
 * There is no runtime export here; importing this module is pointless. Refer to
 * the types with `import('./types.js').Attachment` in a JSDoc comment.
 */

/**
 * @typedef {object} Conversation
 * @property {string} id
 * @property {string} name
 * @property {string} [topic]      standing brief; agents get it when they join
 * @property {number} created_at   unix seconds
 * @property {number|null} [archived_at]
 */

/**
 * @typedef {"human"|"agent"|"system"} SenderType
 *
 * Decides how a body is rendered: processes get block markdown, people do not,
 * and system lines get neither. See `renderMessage`.
 */

/**
 * @typedef {object} Message
 * @property {string} id
 * @property {string} sender       the @handle, or "system"
 * @property {SenderType} sender_type
 * @property {string} body
 * @property {number} created_at   unix seconds
 */

/**
 * @typedef {"starting"|"running"|"exited"|"detached"} AttachmentStatus
 *
 * The four the schema defines — see the comment on `attachments.status` in
 * `partyline/db.py`. `starting` and `running` are *live*: the server will route
 * mentions to them. `exited` is a process that stopped on its own, `detached`
 * one that a person unplugged. Use `isLive` rather than comparing by hand, so
 * a fifth status added later cannot silently read as live.
 */

/**
 * @typedef {object} Attachment
 * @property {string} id
 * @property {string} name         the @handle this process answers to
 * @property {string} adapter      adapter id, e.g. "raw"
 * @property {string[]} command    argv of the spawned process
 * @property {string} cwd
 * @property {AttachmentStatus} status
 * @property {number} created_at   unix seconds
 * @property {string} [cli_session] the vendor CLI's own session id, when known
 */

/**
 * @typedef {object} Adapter
 * @property {string} id
 * @property {{resume?: boolean}} [capabilities]
 */

/**
 * @typedef {object} Preset
 * @property {string} [id]         absent on a preset that has not been saved
 * @property {string} title
 * @property {string} name
 * @property {string} adapter
 * @property {string} command
 */

/**
 * @typedef {object} RunningProcess
 * @property {string} name
 * @property {string} conversation  the line's name, not its id
 */

/**
 * A server event arriving over the wire. `type` selects the rest of the shape;
 * see `Room.#onWireEvent` for how each is handled.
 *
 * @typedef {object} WireEvent
 * @property {"hello"|"message"|"attachment"|"attention"|"conversation"|"conversation_archived"|"conversation_deleted"|"error"|"shutdown"} type
 * @property {string} [conversation_id]
 * @property {Attachment} [attachment]
 * @property {string} [attachment_id]
 * @property {Conversation} [conversation]
 * @property {Message|string} [message]
 *   Overloaded by the server, and worth knowing about: on a `message` event
 *   this is the `Message` itself, on an `error` event it is the human-readable
 *   reason. `Room` switches on `type` before touching it, which is the only
 *   thing that makes the overload safe.
 */

export {};
