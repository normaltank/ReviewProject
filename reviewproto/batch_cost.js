/* Same explicit settle/show/pause/attempt mechanism as the source editor.
   This sidecar describes observation only; it never changes or applies a patch. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const envelope = JSON.parse($('batch-data').textContent).envelope;
  let costSession = null, costPhase = 'idle', costTick = 0;
  const costStatus = $('cost-status');
  function settleCost() {
    if (!costSession || costPhase === 'finished') return;
    const now = performance.now(), elapsed = Math.max(0, now - costTick);
    if (costPhase === 'active') costSession.active_elapsed_ms += elapsed;
    else if (costPhase === 'paused') costSession.paused_elapsed_ms += elapsed;
    costTick = now;
  }
  function showCost() {
    settleCost();
    $('cost-elapsed').textContent = '活动 ' + ((costSession?.active_elapsed_ms || 0) / 1000).toFixed(1) +
      ' 秒；暂停 ' + ((costSession?.paused_elapsed_ms || 0) / 1000).toFixed(1) + ' 秒';
  }
  function countAttempt(name) {
    if (costSession && costPhase !== 'finished') costSession.attempt_counts[name]++;
  }
  $('cost-start').addEventListener('click', () => {
    if (document.hidden) return;
    if (costPhase === 'idle') {
      costSession = {artifact_type: 'batch_review_cost_observation', schema_version: 1,
        session_id: crypto.randomUUID(), batch_id: envelope.batch_id,
        base_revision: envelope.base_revision, package_sha256: envelope.package_sha256,
        actor_kind: $('cost-actor-kind').value, method: $('cost-method').value,
        started_at_utc: new Date().toISOString(), finished_at_utc: null,
        active_elapsed_ms: 0, paused_elapsed_ms: 0,
        attempt_counts: {review_input_events: 0, queue_button_attempts: 0,
          patch_download_button_attempts: 0, evidence_link_attempts: 0}};
      for (const id of ['cost-actor-kind', 'cost-method']) $(id).disabled = true;
    } else if (costPhase === 'paused') settleCost();
    else return;
    costTick = performance.now();
    costPhase = 'active';
    $('cost-start').disabled = true;
    $('cost-pause').disabled = false;
    $('cost-finish').disabled = false;
    costStatus.textContent = '计时中；角色和比较方法采用开始时声明，不代表资质认证。';
    showCost();
  });
  function pauseCost() {
    if (costPhase !== 'active') return;
    settleCost();
    costPhase = 'paused';
    $('cost-start').disabled = false;
    $('cost-start').textContent = '继续计时';
    $('cost-pause').disabled = true;
    costStatus.textContent = '已暂停；返回后请手动继续。';
    showCost();
  }
  $('cost-pause').addEventListener('click', pauseCost);
  document.addEventListener('visibilitychange', () => { if (document.hidden) pauseCost(); });
  $('cost-finish').addEventListener('click', () => {
    if (!costSession || costPhase === 'finished') return;
    settleCost();
    costPhase = 'finished';
    costSession.finished_at_utc = new Date().toISOString();
    costSession.active_elapsed_ms = Math.round(costSession.active_elapsed_ms);
    costSession.paused_elapsed_ms = Math.round(costSession.paused_elapsed_ms);
    for (const id of ['cost-start', 'cost-pause', 'cost-finish']) $(id).disabled = true;
    $('cost-download').disabled = false;
    costStatus.textContent = '会话已结束；请下载独立计时记录。';
    showCost();
  });
  $('cost-download').addEventListener('click', () => {
    if (costPhase !== 'finished') return;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(costSession, null, 2) + '\n'], {type: 'application/json'}));
    a.download = 'batch-review-cost-' + costSession.session_id + '.json';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  document.addEventListener('input', event => {
    if (event.target.matches('input,select,textarea') && !event.target.closest('#review-cost')) countAttempt('review_input_events');
  });
  document.addEventListener('click', event => {
    if (event.target.closest('a')) countAttempt('evidence_link_attempts');
  });
  for (const [id, name] of [['queue', 'queue_button_attempts'], ['download', 'patch_download_button_attempts']]) {
    $(id).addEventListener('click', () => countAttempt(name));
  }
  setInterval(showCost, 250);
})();
