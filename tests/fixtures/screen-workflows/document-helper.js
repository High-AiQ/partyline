// A helper protocol peer backed by the live window-bench DOM.
async ({ token, line }) => {
  const address = new URL("/api/screen/helper", location.href);
  address.protocol = location.protocol === "https:" ? "wss:" : "ws:";
  address.searchParams.set("token", token);
  const socket = new WebSocket(address);
  const send = (message) => socket.send(JSON.stringify(message));
  const grant = "document-window";
  let counter = 0;
  const changed = () => {
    counter++;
    send({ type: "window_changed", grant_id: grant });
  };
  document.querySelector("#block-publishing").addEventListener("change", changed);

  function elements() {
    const result = [{ id: "document", control_type: "Document", name: "Document editor" }];
    const roots = "dialog[id], tr[id], [role=status][id]";
    const selector = `button[id], input[id], textarea[id], select[id], ${roots}`;
    const region = document.querySelector("#document-editor");
    for (const element of region.querySelectorAll(selector)) {
      if (element.closest("[hidden], dialog:not([open])")) continue;
      const parent = element.parentElement.closest(roots)?.id ?? "document";
      const name = element.getAttribute("aria-label") || element.labels?.[0]?.textContent.trim() ||
        element.textContent.trim();
      const [role, action] = {
        BUTTON: ["button", "invoke"],
        INPUT: element.type === "file" ? ["file_input", "set_files"] : ["textbox", "set_value"],
        TEXTAREA: ["textbox", "set_value"],
        SELECT: ["combobox", "select"],
        DIALOG: ["dialog", null],
        TR: ["row", null],
        P: ["status", null],
      }[element.tagName];
      result.push({
        id: element.id,
        parent,
        control_type: role,
        semantic_role: role,
        name,
        enabled: !element.disabled,
        value: element.value,
        file_count: element.files?.length,
        actions: action ? [action] : [],
        action_token: `token-${element.id}`,
      });
      if (role === "status" && element.textContent.trim()) {
        result.push({
          id: `${element.id}-text`,
          parent: element.id,
          control_type: "Text",
          name: element.textContent.trim(),
        });
      }
    }
    return result;
  }

  async function action(message) {
    const element = document.getElementById(message.element_id);
    if (!element || message.action_token !== `token-${element.id}`) {
      const error = new Error("Element action target changed");
      error.reason = "target_changed";
      throw error;
    }
    if ("workflow_document" in message &&
        (message.workflow_document !== "document:1" || message.workflow_counter !== counter)) {
      throw new Error("Workflow action did not use current evidence");
    }
    if (message.action === "invoke") element.click();
    else if (message.action === "set_files") {
      const transfer = new DataTransfer();
      for (const [index, file] of message.files.entries()) {
        const response = await fetch(`/api/screen/file-input/${message.file_ticket}/${index}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!response.ok) throw new Error("Could not read staged file");
        const content = await response.blob();
        transfer.items.add(new File([content], file.name, { type: content.type }));
      }
      element.files = transfer.files;
    } else {
      element.value = message.value;
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
    }
    changed();
    return {
      connected: element.isConnected,
      value: element.value,
      selected_count: element.tagName === "SELECT" ? element.selectedOptions.length : null,
      selected_option: element.tagName === "SELECT" && element.selectedOptions.length === 1 ?
        element.selectedOptions[0].label : null,
    };
  }

  await new Promise((resolve, reject) => {
    socket.addEventListener("error", reject, { once: true });
    socket.addEventListener("open", () => {
      send({
        type: "hello", protocol: 1, device_name: "Lab window", os: "test", helper_version: "1.11.0",
        monitors: [], windows: 2, chrome_dom: 6, window_access: true, workflow_actions: true,
      });
      send({ type: "list_share_targets", request_id: "targets" });
    });
    socket.addEventListener("message", async (event) => {
      const message = JSON.parse(event.data);
      const reply = { request_id: message.request_id, source: "cdp" };
      switch (message.type) {
        case "share_targets":
          send({
            type: "window_grant", request_id: "grant", targets_request_id: "targets",
            grant_id: grant, line_id: line, hwnd: 1, title: "Document editor", process: "editor",
          });
          break;
        case "window_grant_result":
          if (message.ok) resolve();
          else reject(new Error(message.error ?? "could not grant the lab window"));
          break;
        case "read_window_elements": {
          const response = {
            ...reply, type: "window_elements", event_counter: counter,
            subscription_live: true, events_supported: true,
          };
          if (!message.event_status) Object.assign(response, {
            elements: elements(), snapshot_id: message.request_id, workflow_document: "document:1",
            captured_event_counter: counter, action_identity_supported: true,
          });
          send(response);
          break;
        }
        case "window_element_action": {
          let status = "completed";
          let failure = {};
          let element;
          try {
            element = await action(message);
          } catch (error) {
            status = "failed";
            failure = { reason: error.reason, error: error.message };
            console.error(error);
          }
          send({ ...reply, type: "window_element_result", status, element, ...failure });
          break;
        }
        case "ping":
          send({ type: "pong" });
          break;
      }
    });
  });
}
