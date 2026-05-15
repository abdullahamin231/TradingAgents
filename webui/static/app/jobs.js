import { jobsList } from "./dom.js?v=portfolio-tab-5";
import { escapeHtml, statusClass } from "./utils.js?v=portfolio-tab-5";

export function renderJobs(jobs) {
  if (!jobs.length) {
    jobsList.className = "jobs-list empty-state";
    jobsList.textContent = "No jobs yet.";
    return;
  }

  jobsList.className = "jobs-list";
  jobsList.innerHTML = jobs
    .map(
      (job) => `
        <article class="job-entry">
          <div class="job-head">
            <strong>${escapeHtml(job.ticker)} / ${escapeHtml(job.trade_date)}</strong>
            <span class="${statusClass(job.status)}">${escapeHtml(job.status)}</span>
          </div>
          <div class="job-line">Workflow: ${escapeHtml(job.workflow || "analysis_on_demand")} · Job ${escapeHtml(job.job_id.slice(0, 8))}</div>
          <div class="job-line">Provider: ${escapeHtml(job.provider || "opencode")}</div>
          <div class="job-line">Quick: ${escapeHtml(job.quick_model || "default")} · Deep: ${escapeHtml(job.deep_model || "default")}</div>
          ${job.report_path ? `<div class="job-line">Report: <code>${escapeHtml(job.report_path)}</code></div>` : ""}
          <div>${escapeHtml(job.decision || job.error || "Waiting for completion...")}</div>
        </article>
      `
    )
    .join("");
}

export async function fetchJobs() {
  const response = await fetch("/api/jobs");
  const payload = await response.json();
  renderJobs(payload.jobs || []);
}
