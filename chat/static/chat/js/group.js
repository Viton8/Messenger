/**
 * Group info panel: add/remove members, roles, invite link, leave.
 */
(function () {
  "use strict";

  var panel = document.getElementById("chat-group-panel");
  if (!panel) return;
  var chatId = panel.getAttribute("data-chat-id");
  var error = document.getElementById("chat-group-error");
  var members = document.getElementById("chat-group-members");
  var inviteInput = document.getElementById("chat-group-invite-url");
  var addForm = document.getElementById("chat-group-add");
  var boardForm = document.getElementById("chat-group-board");

  function csrf() {
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function showError(text) {
    if (!error) return;
    if (!text) {
      error.hidden = true;
      error.textContent = "";
      return;
    }
    error.hidden = false;
    error.textContent = text;
  }

  function headers() {
    return {
      "Content-Type": "application/json",
      "X-CSRFToken": csrf(),
    };
  }

  function api(path, options) {
    options = options || {};
    return fetch("/api/chat/groups/" + chatId + path, {
      method: options.method || "GET",
      credentials: "same-origin",
      headers: headers(),
      body: options.body ? JSON.stringify(options.body) : undefined,
    }).then(function (response) {
      if (response.status === 204) return {};
      return response.json().then(function (data) {
        if (!response.ok) {
          var detail = data && data.detail;
          if (Array.isArray(detail)) detail = detail.join(" ");
          else if (detail && typeof detail === "object") detail = JSON.stringify(detail);
          throw new Error(detail || "Request failed.");
        }
        return data;
      });
    });
  }

  function setInvite(url) {
    var revoke = panel.querySelector('[data-group-action="revoke"]');
    if (!inviteInput) return;
    if (url) {
      inviteInput.value = url;
      inviteInput.hidden = false;
      if (revoke) revoke.hidden = false;
    } else {
      inviteInput.value = "";
      inviteInput.hidden = true;
      if (revoke) revoke.hidden = true;
    }
  }

  panel.addEventListener("click", function (event) {
    var button = event.target.closest("[data-group-action]");
    if (!button) return;
    var action = button.getAttribute("data-group-action");
    var userId = button.getAttribute("data-user-id");
    showError("");
    if (action === "leave") {
      if (!window.confirm("Leave this group?")) return;
      api("/leave/", { method: "POST" })
        .then(function () { window.location.href = "/chat/"; })
        .catch(function (failure) { showError(failure.message); });
      return;
    }
    if (action === "invite") {
      api("/invite/", { method: "POST" })
        .then(function (data) { setInvite(data.invite_url || ""); })
        .catch(function (failure) { showError(failure.message); });
      return;
    }
    if (action === "revoke") {
      api("/invite/", { method: "DELETE" })
        .then(function () { setInvite(""); })
        .catch(function (failure) { showError(failure.message); });
      return;
    }
    if (action === "remove" && userId) {
      api("/members/" + userId + "/", { method: "DELETE" })
        .then(function () {
          var row = members && members.querySelector('[data-user-id="' + userId + '"]');
          if (row) row.remove();
        })
        .catch(function (failure) { showError(failure.message); });
      return;
    }
    if (action === "promote" && userId) {
      api("/members/" + userId + "/role/", { method: "POST", body: { role: "admin" } })
        .then(function () { window.location.reload(); })
        .catch(function (failure) { showError(failure.message); });
      return;
    }
    if (action === "demote" && userId) {
      api("/members/" + userId + "/role/", { method: "POST", body: { role: "member" } })
        .then(function () { window.location.reload(); })
        .catch(function (failure) { showError(failure.message); });
    }
  });

  if (addForm) {
    addForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var field = document.getElementById("chat-group-add-username");
      var username = field ? String(field.value || "").trim() : "";
      if (!username) return;
      showError("");
      api("/members/", { method: "POST", body: { username: username } })
        .then(function () { window.location.reload(); })
        .catch(function (failure) { showError(failure.message); });
    });
  }

  if (boardForm) {
    boardForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var field = document.getElementById("chat-group-board-title");
      var title = field ? String(field.value || "").trim() : "";
      if (!title) return;
      showError("");
      api("/boards/", { method: "POST", body: { title: title } })
        .then(function () { window.location.reload(); })
        .catch(function (failure) { showError(failure.message); });
    });
  }
})();
