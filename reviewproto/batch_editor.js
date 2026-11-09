/* Offline drafts only. The CLI validates and applies every downloaded decision. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const data = JSON.parse($("batch-data").textContent);
  const envelope = data.envelope;
  const drafts = new Map();
  const status = message => { $("save-status").textContent = message; };
  const updateAlternatives = () => {
    $("alternative").replaceChildren();
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "请选择具体修改方案";
    $("alternative").append(empty);
    const variants = data.alternatives[$("issue").value] || [];
    for (const variant of variants) {
      if (variant.alternative_id === "retain") continue;
      const option = document.createElement("option");
      option.value = variant.alternative_id;
      option.textContent = variant.alternative_id + " · " + variant.label;
      $("alternative").append(option);
    }
    $("alternative").disabled = $("action").value !== "change" || !variants.length;
  };
  const updateCases = () => {
    $("case-source").replaceChildren();
    for (const source of data.issue_cases[$("issue").value] || []) {
      const option = document.createElement("option");
      option.value = source;
      option.textContent = source;
      $("case-source").append(option);
    }
    $("case-source").disabled = $("decision-type").value !== "case_decision";
  };
  $("issue").addEventListener("change", updateCases);
  $("issue").addEventListener("change", updateAlternatives);
  $("action").addEventListener("change", updateAlternatives);
  $("decision-type").addEventListener("change", updateCases);
  updateCases();
  updateAlternatives();
  $("queue").addEventListener("click", () => {
    const row = {issue_id: $("issue").value, decision_type: $("decision-type").value,
      case_source_id: $("decision-type").value === "case_decision" ? $("case-source").value : null,
      action: $("action").value, reason: $("decision-reason").value};
    const variants = data.alternatives[row.issue_id] || [];
    if (variants.length && row.action === "change") {
      if (!$("alternative").value) return status("请选择具体修改方案；尚未应用。");
      row.alternative_id = $("alternative").value;
    }
    if (!row.issue_id || !row.reason.trim()) return status("请选择问题并填写本项理由；尚未应用。");
    drafts.set(row.issue_id + ":" + row.decision_type + ":" + row.case_source_id, row);
    $("draft-list").replaceChildren();
    for (const [key, value] of drafts) {
      const li = document.createElement("li");
      li.textContent = value.issue_id + " · " + value.decision_type + " · " + (value.case_source_id || "通用条款讨论") + " · " + value.action + " · " + (value.alternative_id || "无具体修改方案") + "：" + value.reason;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "移出队列";
      remove.addEventListener("click", () => { drafts.delete(key); li.remove(); status("队列已更新；尚未应用。"); });
      li.append(" ", remove);
      $("draft-list").append(li);
    }
    status("已加入 " + drafts.size + " 项草稿；尚未应用。");
  });
  $("download").addEventListener("click", () => {
    if (!drafts.size || !$("actor").value.trim() || !$("reason").value.trim()) {
      return status("须填写操作者、审核说明并加入至少一项决定；尚未应用。");
    }
    const patch = {...envelope, actor: $("actor").value, reason: $("reason").value, decisions: [...drafts.values()]};
    const url = URL.createObjectURL(new Blob([JSON.stringify(patch, null, 2) + "\n"], {type: "application/json"}));
    const a = document.createElement("a");
    a.href = url;
    a.download = "batch-decisions.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status("补丁已下载，尚未应用；请通过本机 batch-apply 校验保存后重开。");
  });
})();
