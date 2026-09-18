const taskList = document.querySelector("#task-list");
const refreshState = document.querySelector("#refresh-state");

const labels = {
  queued: "等待中",
  running: "下载中",
  completed: "已完成",
  failed: "失败",
};

function formatBytes(value) {
  if (!value) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

function actionForm(taskId, action, label, danger = false) {
  const form = document.createElement("form");
  form.method = "post";
  form.action = `/tasks/${taskId}/${action}`;
  const csrf = document.createElement("input");
  csrf.type = "hidden";
  csrf.name = "csrf";
  csrf.value = taskList.dataset.csrf;
  const button = document.createElement("button");
  button.type = "submit";
  button.className = danger ? "small danger" : "small secondary";
  button.textContent = label;
  form.append(csrf, button);
  return form;
}

function render(tasks) {
  taskList.replaceChildren();
  if (!tasks.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "还没有任务";
    taskList.append(empty);
    return;
  }
  for (const task of tasks) {
    const card = document.createElement("article");
    card.className = "task-card";
    const info = document.createElement("div");
    info.className = "task-info";
    const title = document.createElement("strong");
    title.textContent = `JM${task.album_id}`;
    const message = document.createElement("p");
    message.textContent = task.message || labels[task.status] || task.status;
    const meta = document.createElement("small");
    meta.textContent = `${new Date(task.created_at).toLocaleString()}${task.zip_size ? ` · ${formatBytes(task.zip_size)}` : ""}`;
    info.append(title, message, meta);

    const controls = document.createElement("div");
    controls.className = "task-controls";
    const status = document.createElement("span");
    status.className = `status status-${task.status}`;
    status.textContent = labels[task.status] || task.status;
    controls.append(status);

    const actions = document.createElement("div");
    actions.className = "actions";
    if (task.status === "completed") {
      const download = document.createElement("a");
      download.href = `/tasks/${task.id}/download`;
      download.className = "small download";
      download.textContent = "下载 ZIP";
      actions.append(download);
    }
    if (task.status === "failed") {
      actions.append(actionForm(task.id, "retry", "重试"));
    }
    if (task.status !== "running") {
      actions.append(actionForm(task.id, "delete", "删除", true));
    }
    controls.append(actions);
    card.append(info, controls);
    taskList.append(card);
  }
}

async function refresh() {
  if (!taskList) return;
  try {
    const response = await fetch("/api/tasks", { credentials: "same-origin" });
    if (response.status === 401) {
      location.href = "/login";
      return;
    }
    if (!response.ok) throw new Error("refresh failed");
    render(await response.json());
    refreshState.textContent = `已更新 ${new Date().toLocaleTimeString()}`;
  } catch (_) {
    refreshState.textContent = "刷新失败，将自动重试";
  }
}

if (taskList) {
  refresh();
  setInterval(refresh, 3000);
}
