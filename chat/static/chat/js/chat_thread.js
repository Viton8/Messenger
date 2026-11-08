/**
 * Shared chat history: grouping, stick-to-bottom, older pages, and read marks.
 * Direct and group chats share this so the thread UI matches.
 */
(function () {
  "use strict";

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var GROUP_MS = 5 * 60 * 1000;
  var readTimer = 0;
  var readPending = null;

  function pad(value) {
    return value < 10 ? "0" + value : String(value);
  }

  function formatSentAt(value) {
    var date = new Date(value);
    if (isNaN(date.getTime())) return "";
    var time = pad(date.getHours()) + ":" + pad(date.getMinutes());
    var now = new Date();
    if (date.toDateString() === now.toDateString()) return time;
    var stamp = MONTHS[date.getMonth()] + " " + date.getDate();
    if (date.getFullYear() !== now.getFullYear()) stamp += ", " + date.getFullYear();
    return stamp + " " + time;
  }

  function csrf() {
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function profileHref(name) {
    if (!name || !/^[A-Za-z0-9_]{3,30}$/.test(name)) return "";
    return "/accounts/players/" + encodeURIComponent(name) + "/";
  }

  function normalize(message) {
    var kind = message.kind || "user";
    var name = kind === "system" ? "System" : (message.username || message.sender || "User");
    var deleted = !!message.deleted;
    var boardId = message.board_id == null ? "" : String(message.board_id);
    var content;
    if (deleted && kind === "board") content = "Board deleted";
    else if (deleted) content = "Message deleted";
    else content = message.content || "";
    return {
      id: message.id == null ? "" : String(message.id),
      senderId: message.sender_id == null ? "" : String(message.sender_id),
      name: name,
      kind: kind,
      sent: message.sent_at || "",
      content: content,
      deleted: deleted,
      edited: !deleted && !!message.edited_at,
      boardId: boardId,
      boardUrl: message.board_url || (boardId ? "/boards/" + boardId + "/" : ""),
    };
  }

  function selfId(options) {
    if (typeof options.selfId === "function") return String(options.selfId() || "");
    return String(options.selfId || "");
  }

  function findLine(log, id) {
    var key = String(id);
    var rows = log.querySelectorAll("[data-message-id]");
    for (var i = 0; i < rows.length; i += 1) {
      if (rows[i].getAttribute("data-message-id") === key) return rows[i];
    }
    return null;
  }

  function createLine(message, options) {
    var row = normalize(message);
    var mine = row.kind !== "system" && row.kind !== "board" && row.senderId && row.senderId === selfId(options);
    var line = document.createElement("div");
    line.className = "chat-msg";
    if (row.kind === "system") line.classList.add("chat-msg--system");
    else if (row.kind === "board") line.classList.add("chat-msg--board");
    else if (mine) line.classList.add("is-mine");
    if (row.deleted) line.classList.add("is-deleted");
    line.setAttribute("data-message-id", row.id);
    line.setAttribute("data-sender-id", row.senderId);
    line.setAttribute("data-sent-at", row.sent);
    line.setAttribute("data-kind", row.kind);
    line.setAttribute("data-deleted", row.deleted ? "1" : "0");
    if (row.boardId) line.setAttribute("data-board-id", row.boardId);
    var meta = document.createElement("p");
    meta.className = "chat-msg__meta";
    var name;
    var href = row.kind === "system" ? "" : profileHref(row.name);
    if (href) {
      name = document.createElement("a");
      name.href = href;
    } else {
      name = document.createElement("span");
    }
    name.className = "chat-msg__name";
    name.textContent = row.name;
    meta.appendChild(name);
    if (row.sent) {
      var time = document.createElement("time");
      time.dateTime = row.sent;
      time.textContent = formatSentAt(row.sent);
      meta.appendChild(time);
    }
    if (row.edited) {
      var edited = document.createElement("span");
      edited.className = "chat-msg__edited";
      edited.textContent = "edited";
      meta.appendChild(edited);
    }
    line.appendChild(meta);
    if (row.kind === "board") {
      var card = document.createElement("div");
      card.className = "chat-board-card";
      var preview = document.createElement("div");
      preview.className = "chat-board-card__preview";
      preview.setAttribute("aria-hidden", "true");
      card.appendChild(preview);
      var title = document.createElement("p");
      title.className = "chat-board-card__title";
      title.textContent = row.content;
      card.appendChild(title);
      if (row.sent) {
        var updated = document.createElement("time");
        updated.className = "chat-board-card__updated";
        updated.dateTime = row.sent;
        updated.textContent = formatSentAt(row.sent);
        card.appendChild(updated);
      }
      if (!row.deleted && row.boardUrl) {
        var open = document.createElement("a");
        open.className = "btn";
        open.href = row.boardUrl;
        open.appendChild(document.createTextNode("Open board"));
        card.appendChild(open);
      }
      line.appendChild(card);
      return line;
    }
    var body = document.createElement("p");
    body.className = "chat-msg__body";
    body.textContent = row.content;
    line.appendChild(body);
    if (!row.deleted && row.kind !== "system") {
      var canEdit = mine;
      var canDelete = mine || !!options.canModerate;
      if (canEdit || canDelete) {
        var actions = document.createElement("p");
        actions.className = "chat-msg__actions";
        if (canEdit) {
          var editBtn = document.createElement("button");
          editBtn.type = "button";
          editBtn.setAttribute("data-msg-action", "edit");
          editBtn.textContent = "Edit";
          actions.appendChild(editBtn);
        }
        if (canDelete) {
          var deleteBtn = document.createElement("button");
          deleteBtn.type = "button";
          deleteBtn.setAttribute("data-msg-action", "delete");
          deleteBtn.textContent = "Delete";
          actions.appendChild(deleteBtn);
        }
        line.appendChild(actions);
      }
    }
    return line;
  }

  function dayKey(date) {
    if (isNaN(date.getTime())) return "";
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate());
  }

  function formatDayLabel(date) {
    var now = new Date();
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var then = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    var diff = (today.getTime() - then.getTime()) / 86400000;
    if (diff === 0) return "Today";
    if (diff === 1) return "Yesterday";
    var stamp = MONTHS[date.getMonth()] + " " + date.getDate();
    if (date.getFullYear() !== now.getFullYear()) stamp += ", " + date.getFullYear();
    return stamp;
  }

  function paintGroups(log) {
    log.querySelectorAll(".chat-day").forEach(function (el) { el.remove(); });
    var previous = null;
    var previousDay = "";
    log.querySelectorAll("[data-message-id]").forEach(function (line) {
      var kind = line.getAttribute("data-kind") || "user";
      var name = line.querySelector(".chat-msg__name");
      line.classList.remove("is-grouped");
      if (name) name.classList.remove("visually-hidden");
      var sent = new Date(line.getAttribute("data-sent-at") || "");
      var sender = line.getAttribute("data-sender-id") || "";
      var key = dayKey(sent);
      if (key && key !== previousDay) {
        var sep = document.createElement("p");
        sep.className = "chat-day";
        sep.textContent = formatDayLabel(sent);
        line.parentNode.insertBefore(sep, line);
      }
      if (key) previousDay = key;
      var grouped = previous
        && kind !== "system"
        && kind !== "board"
        && previous.kind !== "system"
        && previous.kind !== "board"
        && sender
        && sender === previous.sender
        && !isNaN(sent.getTime())
        && !isNaN(previous.sent.getTime())
        && dayKey(sent) === dayKey(previous.sent)
        && sent.getTime() - previous.sent.getTime() < GROUP_MS
        && sent.getTime() >= previous.sent.getTime();
      if (grouped) {
        line.classList.add("is-grouped");
        var keepNames = log.closest('[data-is-group="1"]');
        if (name && !keepNames) name.classList.add("visually-hidden");
      }
      previous = { kind: kind, sender: sender, sent: sent };
    });
  }

  function nearBottom(log) {
    return log.scrollHeight - log.scrollTop - log.clientHeight < 48;
  }

  function following(options, log) {
    if (typeof options.isFollowing === "function" && !options.isFollowing()) return false;
    return nearBottom(log);
  }

  function lineCount(log) {
    return log.querySelectorAll("[data-message-id]").length;
  }

  function oldestId(log) {
    var first = log.querySelector("[data-message-id]");
    return first ? first.getAttribute("data-message-id") : "";
  }

  function newestLine(log) {
    var rows = log.querySelectorAll("[data-message-id]");
    return rows.length ? rows[rows.length - 1] : null;
  }

  function newestPayload(log) {
    var line = newestLine(log);
    if (!line) return null;
    return { id: line.getAttribute("data-message-id") };
  }

  /**
   * Attach scroll, grouping, and the new-messages control to one log.
   * @param {Object} options
   * @return {Object}
   */
  function bind(options) {
    var log = options.log;
    var jump = options.jump || null;
    var hasOlder = !!options.hasOlder;
    var loading = false;
    var unseen = 0;

    function notifyCount() {
      if (options.onCount) options.onCount(lineCount(log));
    }

    function paintJump() {
      if (!jump) return;
      if (!unseen) {
        jump.hidden = true;
        jump.textContent = "New messages";
        return;
      }
      jump.hidden = false;
      jump.textContent = "New messages";
      jump.setAttribute(
        "aria-label",
        unseen === 1 ? "1 new message" : unseen + " new messages"
      );
    }

    function clearUnseen() {
      unseen = 0;
      paintJump();
      if (options.onUnseen) options.onUnseen(0);
    }

    function bumpUnseen() {
      unseen += 1;
      paintJump();
      if (options.onUnseen) options.onUnseen(unseen);
    }

    function seenNewest() {
      var payload = newestPayload(log);
      if (payload && options.onSeen) options.onSeen(payload);
    }

    function scrollToEnd() {
      log.scrollTop = log.scrollHeight;
      clearUnseen();
      seenNewest();
    }

    function paintLine(message) {
      var row = normalize(message);
      var existing = findLine(log, row.id);
      if (!existing) return false;
      var next = createLine(message, options);
      existing.parentNode.replaceChild(next, existing);
      paintGroups(log);
      return true;
    }

    function append(message, force) {
      var row = normalize(message);
      if (!row.id) return false;
      if (findLine(log, row.id)) {
        paintLine(message);
        return false;
      }
      var stick = !!force || following(options, log);
      log.appendChild(createLine(message, options));
      paintGroups(log);
      notifyCount();
      if (stick) {
        log.scrollTop = log.scrollHeight;
        clearUnseen();
        if (options.onSeen) options.onSeen(row);
      } else {
        bumpUnseen();
      }
      return true;
    }

    function prepend(messages) {
      var previousHeight = log.scrollHeight;
      var previousTop = log.scrollTop;
      var fragment = document.createDocumentFragment();
      (messages || []).forEach(function (message) {
        var row = normalize(message);
        if (!row.id || findLine(log, row.id)) return;
        fragment.appendChild(createLine(message, options));
      });
      var anchor = log.firstChild;
      if (anchor) log.insertBefore(fragment, anchor);
      else log.appendChild(fragment);
      paintGroups(log);
      log.scrollTop = log.scrollHeight - previousHeight + previousTop;
      notifyCount();
    }

    function replace(messages) {
      while (log.firstChild) log.removeChild(log.firstChild);
      (messages || []).forEach(function (message) {
        var row = normalize(message);
        if (!row.id) return;
        log.appendChild(createLine(message, options));
      });
      paintGroups(log);
      notifyCount();
    }

    function noteCatchUp(rows) {
      log.scrollTop = log.scrollHeight;
      if (!rows.length) return;
      unseen = rows.length;
      paintJump();
      if (options.onUnseen) options.onUnseen(unseen);
    }

    function syncLatest(messages, older, forceScroll) {
      var newest = newestLine(log);
      var rows = messages || [];
      var stick = !!forceScroll || following(options, log);
      if (!newest) {
        replace(rows);
        hasOlder = !!older;
        if (stick) scrollToEnd();
        else noteCatchUp(rows);
        return;
      }
      var known = -1;
      var current = newest.getAttribute("data-message-id");
      for (var i = 0; i < rows.length; i += 1) {
        if (String(rows[i].id) === current) known = i;
      }
      if (known === -1) {
        replace(rows);
        hasOlder = !!older;
        if (stick) scrollToEnd();
        else noteCatchUp(rows);
        return;
      }
      for (var j = known + 1; j < rows.length; j += 1) append(rows[j], !!forceScroll);
    }

    function loadOlder() {
      if (loading || !hasOlder || !options.fetchOlder) return;
      if (typeof options.isFollowing === "function" && !options.isFollowing()) return;
      if (log.scrollTop > 48) return;
      var before = oldestId(log);
      if (!before) return;
      loading = true;
      log.setAttribute("aria-busy", "true");
      options.fetchOlder(before).then(function (page) {
        loading = false;
        log.removeAttribute("aria-busy");
        if (!page) return;
        hasOlder = !!page.has_older;
        prepend(page.messages || []);
      }).catch(function () {
        loading = false;
        log.removeAttribute("aria-busy");
      });
    }

    log.addEventListener("scroll", function () {
      if (following(options, log)) {
        clearUnseen();
        seenNewest();
      }
      loadOlder();
    });

    if (jump) {
      jump.addEventListener("click", function () {
        scrollToEnd();
        if (options.input) options.input.focus();
      });
    }

    paintGroups(log);
    notifyCount();

    return {
      append: append,
      prepend: prepend,
      replace: replace,
      update: paintLine,
      syncLatest: syncLatest,
      scrollToEnd: scrollToEnd,
      setHasOlder: function (value) { hasOlder = !!value; },
      unseen: function () { return unseen; },
      setChatId: function (id) { options.chatId = id; },
      chatId: function () { return options.chatId || ""; },
    };
  }

  function markRead(chatId, messageId) {
    if (!chatId || !messageId) return;
    readPending = { chatId: String(chatId), messageId: String(messageId) };
    window.clearTimeout(readTimer);
    readTimer = window.setTimeout(function () {
      var pending = readPending;
      readPending = null;
      if (!pending) return;
      fetch("/api/chat/chats/" + pending.chatId + "/read/", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrf(),
        },
        body: JSON.stringify({ message_id: pending.messageId }),
      }).catch(function () {});
    }, 400);
  }

  window.ChatThread = {
    formatSentAt: formatSentAt,
    bind: bind,
    markRead: markRead,
    paintGroups: paintGroups,
  };
})();
